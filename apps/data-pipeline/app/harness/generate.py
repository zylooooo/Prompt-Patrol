"""Generation run loop: config in, records out.

Dry-run by default: it prints the call plan and stops. Nothing spends
money without --go.
"""

import argparse
import json
import logging
from datetime import datetime, timezone
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


COLUMN_ALIASES = {
    "QuestionID": "question_id",
    "QuestionText": "question",
    "StudentAnswer": "student_answer",
    "Reference Answer": "instructor_answer",
    "reference_answer": "instructor_answer",
}


def load_questions(path, namespace):
    """Return one row per question: question_id, question, instructor_answer.

    Accepts any cleaned corpus. Column names are normalised through
    COLUMN_ALIASES, and when no question_id column exists, composite ids
    like E03.Q03.A05 or Q7.A2 collapse to their question prefix. Question
    identity always comes from ids, never the question text, because two
    Mohler texts repeat under different ids."""
    df = pd.read_parquet(path).rename(columns=COLUMN_ALIASES)
    if "question_id" not in df.columns:
        df = df.assign(question_id=df["id"].str.rsplit(".", n=1).str[0])
    questions = df[["question_id", "question", "instructor_answer"]].drop_duplicates("question_id")
    questions = questions.assign(question_id=namespace + "/" + questions["question_id"])
    return questions.reset_index(drop=True)


def run(config, questions, out_dir, go):
    tiers = config["samples_per_question"]
    generators = [g["name"] for g in config["generators"]]
    total = len(questions) * sum(tiers.values()) * max(len(generators), 1)
    logger.info(
        "Plan: %d questions x %d samples x %d generators = %d calls",
        len(questions), sum(tiers.values()), len(generators), total,
    )
    if not go:
        logger.info("Dry run only. Re-run with --go to generate.")
        return

    load_dotenv(PIPELINE_DIR / ".env")
    clients = build_clients(config)
    tier_templates = {**TIER_TO_TEMPLATE, **config.get("template_overrides", {})}
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        name: {"requested": 0, "succeeded": 0, "failed": 0, "prompt_tokens": 0, "completion_tokens": 0}
        for name in clients
    }

    with open(out_dir / "answers.jsonl", "a", encoding="utf-8") as out:
        for name, client in clients.items():
            for _, row in questions.iterrows():
                for tier, count in tiers.items():
                    template_name = tier_templates[tier]
                    prompt = TEMPLATES[template_name].format(
                        question=row["question"], instructor_answer=row["instructor_answer"]
                    )
                    for seq in range(1, count + 1):
                        report[name]["requested"] += 1
                        try:
                            result = client.generate(SYSTEM, prompt, config["decoding"])
                        except Exception:
                            logger.exception("failed: %s %s %s %02d", name, row["question_id"], tier, seq)
                            report[name]["failed"] += 1
                            continue
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
                            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            "answer": result.text,
                        }
                        out.write(json.dumps(record, ensure_ascii=False) + "\n")
                        report[name]["succeeded"] += 1
                        report[name]["prompt_tokens"] += result.usage["prompt_tokens"]
                        report[name]["completion_tokens"] += result.usage["completion_tokens"]
            logger.info("%s: %s", name, report[name])

    (out_dir / "run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out_dir)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate raw AI answers per the harness config.")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--questions", type=int, default=None, help="limit to the first N questions (pilot)")
    parser.add_argument("--tag", default="run", help="label for the output folder")
    parser.add_argument("--go", action="store_true", help="actually call the APIs; default is a dry-run plan")
    args = parser.parse_args()

    config = load_config(args.config)
    questions = load_questions(PIPELINE_DIR / config["questions_file"], config["dataset"])
    if args.questions:
        questions = questions.head(args.questions)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.tag
    run(config, questions, PIPELINE_DIR / "data" / "generated" / run_id, args.go)


if __name__ == "__main__":
    main()
