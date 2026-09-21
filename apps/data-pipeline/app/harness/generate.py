"""Generation run loop: config in, records out.

Dry-run by default: it prints the call plan and stops. Nothing spends
money without --go.
"""

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

from harness.clients import build_clients
from harness.prompts import SYSTEM, TEMPLATES, TIER_TO_TEMPLATE

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent.parent
PIPELINE_DIR = APP_DIR.parent
DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# SPRAG and EngSAF spell their headers differently, both collapse to one schema
COLUMN_ALIASES = {
    "QuestionID": "question_id",
    "QuestionText": "question",
    "StudentAnswer": "student_answer",
    "Reference Answer": "instructor_answer",
    "reference_answer": "instructor_answer",
}


def load_questions(path, namespace):
    """Return one row per question: question_id, question,
    instructor_answer, and the corpus's first student answer per
    question with its source_answer_id, which the rewrite template
    paraphrases.

    Accepts the project's cleaned corpora. Column names are normalised through
    COLUMN_ALIASES, and when no question_id column exists, composite ids
    like E03.Q03.A05 or Q7.A2 collapse to their question prefix. Question
    identity always comes from ids, never the question text, because two
    Mohler texts repeat under different ids."""
    df = pd.read_parquet(path).rename(columns=COLUMN_ALIASES)
    if "question_id" not in df.columns:
        df = df.assign(question_id=df["id"].str.rsplit(".", n=1).str[0])
    columns = ["question_id", "question", "instructor_answer"]
    if "student_answer" in df.columns:
        columns.append("student_answer")
        if "id" in df.columns:
            df = df.assign(source_answer_id=namespace + "/" + df["id"])
            columns.append("source_answer_id")
    questions = df[columns].drop_duplicates("question_id")
    questions = questions.assign(question_id=namespace + "/" + questions["question_id"])
    return questions.reset_index(drop=True)


def run(config, questions, out_dir, go):
    """Generate every configured answer into out_dir: answers.jsonl plus
    run_report.json. Without go, the plan is logged and nothing is called."""
    tiers = config["samples_per_question"]
    tier_templates = {**TIER_TO_TEMPLATE, **config.get("template_overrides", {})}
    # fail at plan time, not mid-run with money already spent
    missing = sorted(t for t in tiers if t not in tier_templates)
    unknown = sorted(set(tier_templates.values()) - set(TEMPLATES))
    if missing or unknown:
        raise SystemExit(f"bad tier config, tiers without a template: {missing}, unknown templates: {unknown}")
    needs_student = sorted(t for t in tiers if "{student_answer}" in TEMPLATES[tier_templates[t]])
    if needs_student and "student_answer" not in questions.columns:
        raise SystemExit(f"tiers {needs_student} use templates that need a student_answer column in the question file")
    generators = [g["name"] for g in config["generators"]]
    duplicates = sorted({name for name in generators if generators.count(name) > 1})
    if duplicates:
        raise SystemExit(f"duplicate generator names: {duplicates}")
    no_extra_body = sorted(
        g["name"] for g in config["generators"]
        if g.get("extra_body") and g["provider"] not in ("openai", "deepseek", "ollama")
    )
    if no_extra_body:
        raise SystemExit(f"extra_body is not wired for these generators' providers: {no_extra_body}")
    total = len(questions) * sum(tiers.values()) * len(generators)
    logger.info(
        "Plan: %d questions x %d samples x %d generators = %d calls",
        len(questions), sum(tiers.values()), len(generators), total,
    )
    if not go:
        logger.info("Dry run only. Re-run with --go to generate.")
        return

    # keys are only needed past the dry-run gate, a plan runs without .env
    load_dotenv(PIPELINE_DIR / ".env")
    clients = build_clients(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        name: {"requested": 0, "succeeded": 0, "failed": 0, "prompt_tokens": 0, "completion_tokens": 0}
        for name in clients
    }

    calls = [
        (row, tier, seq)
        for _, row in questions.iterrows()
        for tier, count in tiers.items()
        for seq in range(1, count + 1)
    ]
    try:
        # append, a rerun into an existing folder must not erase paid answers
        with open(out_dir / "answers.jsonl", "a", encoding="utf-8") as out:
            for name, client in clients.items():
                streak = 0
                for row, tier, seq in calls:
                    template_name = tier_templates[tier]
                    prompt = TEMPLATES[template_name].format(
                        question=row["question"], instructor_answer=row["instructor_answer"],
                        student_answer=row.get("student_answer", ""),
                    )
                    report[name]["requested"] += 1
                    try:
                        result = client.generate(SYSTEM, prompt, config["decoding"])
                    except Exception:
                        logger.exception("failed: %s %s %s %02d", name, row["question_id"], tier, seq)
                        report[name]["failed"] += 1
                        streak += 1
                        if streak >= 3:
                            # a dead endpoint fails every call, stop paying the retry tax
                            logger.error("%s: three failures in a row, abandoning this generator", name)
                            break
                        continue
                    streak = 0
                    if not result.text:
                        # reasoning models can spend the whole token budget
                        # thinking and return nothing
                        logger.warning("empty answer: %s %s %s %02d", name, row["question_id"], tier, seq)
                        report[name]["failed"] += 1
                        report[name]["prompt_tokens"] += result.usage["prompt_tokens"]
                        report[name]["completion_tokens"] += result.usage["completion_tokens"]
                        continue
                    record = {
                        "answer_id": f"{row['question_id']}/{name}/{tier}/{seq:02d}",
                        "question_id": row["question_id"],
                        "generator": name,
                        "model_version": result.model_version,
                        "prompt_template": template_name,
                        "tier": tier,
                        "params_honoured": result.params_honoured,
                        "usage": result.usage,
                        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
                        "answer": result.text,
                    }
                    if "{student_answer}" in TEMPLATES[template_name]:
                        # the human answer this record paraphrases, the
                        # splicer refuses to pair the two
                        record["source_answer_id"] = row.get("source_answer_id")
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    report[name]["succeeded"] += 1
                    report[name]["prompt_tokens"] += result.usage["prompt_tokens"]
                    report[name]["completion_tokens"] += result.usage["completion_tokens"]
                logger.info("%s: %s", name, report[name])
    finally:
        # a crash mid-run must not lose the bookkeeping for paid calls
        (out_dir / "run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("Wrote %s", out_dir)


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate raw AI answers per the harness config.")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--questions", type=positive_int, default=None, help="limit to the first N questions (pilot)")
    parser.add_argument("--tag", default="run", help="label for the output folder")
    parser.add_argument("--go", action="store_true", help="actually call the APIs; default is a dry-run plan")
    args = parser.parse_args()

    config = load_config(args.config)
    questions = load_questions(PIPELINE_DIR / config["questions_file"], config["dataset"])
    if args.questions is not None:
        questions = questions.head(args.questions)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + args.tag
    run(config, questions, PIPELINE_DIR / "data" / "generated" / run_id, args.go)


if __name__ == "__main__":
    main()
