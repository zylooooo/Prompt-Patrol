"""Generation run loop: config in, records out.

Dry-run by default: it prints the call plan and stops. Nothing spends
money without --go.
"""

import argparse
import json
import logging
import random
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

from corpus.clean import clean_text
from harness.clients import build_clients
from harness.prompts import REWRITE_TIERS, SYSTEM, SYSTEM_OVERRIDES, TEMPLATES, TIER_TO_TEMPLATE

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent.parent
PIPELINE_DIR = APP_DIR.parent
CONFIG_DIR = Path(__file__).parent / "configs"
MIN_TARGET_WORDS = 3
# commas, semicolons and angle brackets separate words too, students join
# lists without spaces and write vector<int>
_WORD = re.compile(r"[^\s,;<>]+")
DATASETS = sorted(path.stem for path in CONFIG_DIR.glob("*.yaml"))


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# SPRAG spells its headers differently, these map them to the shared names
COLUMN_ALIASES = {
    "QuestionID": "question_id",
    "QuestionText": "question",
    "StudentAnswer": "student_answer",
}


def load_questions(path, namespace):
    """Return one row per question: question_id, question, and, when the
    corpus has student answers, student_answers. That is every non-blank
    answer to the question as a (source_answer_id, text) pair, shuffled
    in an order fixed by the question id, so every run sees the same
    order. Every tier needs them: the rewrite tier polishes one per call
    (pick_student_answer), the others take one's length
    (pick_target_words).

    Accepts the project's cleaned corpora. Column names are normalised through
    COLUMN_ALIASES, and when no question_id column exists, composite ids
    like E03.Q03.A05 or Q7.A2 collapse to their question prefix. Question
    identity always comes from ids, never the question text, because two
    Mohler texts repeat under different ids."""
    df = pd.read_parquet(path).rename(columns=COLUMN_ALIASES)
    if "question_id" not in df.columns:
        df = df.assign(question_id=df["id"].str.rsplit(".", n=1).str[0])
    df = df.assign(question_id=namespace + "/" + df["question_id"])
    questions = df[["question_id", "question"]].drop_duplicates("question_id").reset_index(drop=True)
    if {"id", "student_answer"} <= set(df.columns):
        written = df[df["student_answer"].fillna("").str.strip() != ""]
        pools = {}
        for question_id, group in written.groupby("question_id"):
            # sorted first, so the order does not depend on the file's row order
            pool = sorted(zip(namespace + "/" + group["id"], group["student_answer"], strict=True))
            random.Random(question_id).shuffle(pool)
            pools[question_id] = pool
        questions = questions.assign(student_answers=[pools.get(q, []) for q in questions["question_id"]])
    return questions


def pick_student_answer(row, position, count, seq):
    """The (source_answer_id, text) one rewrite call polishes. Each
    generator, by its position in the config, and each of its count
    samples takes its own slot in the question's fixed order, so no two
    calls polish the same student while the question has enough answers.
    Past that the slots wrap around and answers are reused."""
    pool = row["student_answers"]
    return pool[(position * count + seq - 1) % len(pool)]


def count_words(text):
    """Words as students write them, so "min(),max(),len()" counts three.
    Callers pass clean_text output, as the corpus builder does for n_words."""
    return len(_WORD.findall(text))


def pick_target_words(row, answer_id):
    """The word count one generated answer is asked for: the length of a
    student answer to the same question after clean_text, drawn with the
    answer id as seed, so <br> tags and list markers never count as
    words. Generated lengths then follow the students' spread above the
    floor instead of each model's habit. Never below MIN_TARGET_WORDS,
    the corpus builder drops shorter answers on both sides."""
    lengths = sorted(count_words(clean_text(text)) for _, text in row["student_answers"])
    return max(MIN_TARGET_WORDS, random.Random(answer_id).choice(lengths))


def existing_answers(path):
    """Records already in answers.jsonl, keyed by answer_id, so a resumed
    run neither pays twice for an answer it holds nor writes a duplicate."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    return {record["answer_id"]: record for record in records}


def run(config, questions, out_dir, go):
    """Generate every configured answer into out_dir: answers.jsonl plus
    run_report.json. Without go, the plan is logged and nothing is called."""
    tiers = config["samples_per_question"]
    # fail at plan time, not mid-run with money already spent
    unknown = sorted(t for t in tiers if t not in TIER_TO_TEMPLATE)
    if unknown:
        raise SystemExit(f"unknown tiers {unknown}, known tiers are {sorted(TIER_TO_TEMPLATE)}")
    generators = [g["name"] for g in config["generators"]]
    if not config.get("course"):
        raise SystemExit("the config needs a course, the student persona names it")
    # every tier uses them, rewrites polish one and the rest take its length
    if "student_answers" not in questions.columns:
        raise SystemExit("the question file needs student answers with ids")
    empty = [q for q, pool in zip(questions["question_id"], questions["student_answers"], strict=True) if not pool]
    if empty:
        raise SystemExit(f"no student answers for {len(empty)} questions, first {empty[:5]}")
    needs_student = sorted(t for t in tiers if t in REWRITE_TIERS)
    if needs_student:
        per_question = max(tiers[t] for t in needs_student) * len(generators)
        short = sum(len(pool) < per_question for pool in questions["student_answers"])
        if short:
            logger.warning(
                "%d questions have fewer student answers than rewrite calls, some are polished more than once", short,
            )
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
    answers_path = out_dir / "answers.jsonl"
    done = existing_answers(answers_path)
    if done:
        # count only answers this plan would make, a folder started with a
        # different config holds answers the plan will not skip
        planned = {
            f"{question_id}/{name}/{tier}/{seq:02d}"
            for question_id in questions["question_id"]
            for tier, count in tiers.items()
            for seq in range(1, count + 1)
            for name in generators
        }
        # answer ids carry no prompt version, so an answer made with other
        # prompts or for another dataset would otherwise be kept as if it
        # were this run's. Every record is checked, not only the planned
        # ones, since the whole folder becomes one corpus source
        namespaces = {question_id.split("/", 1)[0] for question_id in questions["question_id"]}
        stale = sorted(
            answer_id for answer_id, record in done.items()
            if record.get("prompt_template") != TIER_TO_TEMPLATE.get(record.get("tier"))
            or (record.get("tier") not in REWRITE_TIERS and record.get("course") != config["course"])
            or record.get("question_id", "").split("/", 1)[0] not in namespaces
        )
        if stale:
            raise SystemExit(
                f"{len(stale)} answers in {answers_path} came from other prompts or another dataset, "
                f"first {stale[:3]}, start a new run folder"
            )
        skipped = len(planned & done.keys())
        logger.info("%d answers already in %s, %d calls still to make", skipped, answers_path, total - skipped)
        outside = sorted(done.keys() - planned)
        if outside:
            logger.warning("%d answers in the folder are outside this plan, first %s", len(outside), outside[:3])
    if not go:
        logger.info("Dry run only. Re-run with --go to generate.")
        return

    # keys are only needed past the dry-run gate, a plan runs without .env
    load_dotenv(PIPELINE_DIR / ".env")
    clients = build_clients(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "run_report.json"
    earlier = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    # generators left out of this run keep their entries and billed failures
    report = {name: dict(entry) for name, entry in earlier.items() if name not in clients}
    for name in clients:
        records = [record for record in done.values() if record["generator"] == name]
        if earlier.get(name, {}).get("succeeded") == len(records):
            # empty answers bill tokens without leaving a record, so a report
            # that still matches the records carries the folder's full spend
            report[name] = dict(earlier[name])
            continue
        # no report, or a stale one from a killed run, so count the records
        report[name] = {
            "requested": len(records),
            "succeeded": len(records),
            "failed": 0,
            "prompt_tokens": sum(r["usage"]["prompt_tokens"] for r in records),
            "completion_tokens": sum(r["usage"]["completion_tokens"] for r in records),
        }

    calls = [
        (row, tier, seq)
        for _, row in questions.iterrows()
        for tier, count in tiers.items()
        for seq in range(1, count + 1)
    ]
    try:
        with open(answers_path, "a", encoding="utf-8") as out:
            for position, (name, client) in enumerate(clients.items()):
                streak = 0
                for row, tier, seq in calls:
                    answer_id = f"{row['question_id']}/{name}/{tier}/{seq:02d}"
                    if answer_id in done:
                        continue
                    template_name = TIER_TO_TEMPLATE[tier]
                    student_id, student_answer, target_words = None, "", None
                    if tier in REWRITE_TIERS:
                        student_id, student_answer = pick_student_answer(row, position, tiers[tier], seq)
                    else:
                        target_words = pick_target_words(row, answer_id)
                    prompt = TEMPLATES[template_name].format(
                        question=row["question"], student_answer=student_answer, target_words=target_words,
                    )
                    report[name]["requested"] += 1
                    system = SYSTEM_OVERRIDES.get(template_name) or SYSTEM.format(course=config["course"])
                    result = None
                    try:
                        result = client.generate(system, prompt, config["decoding"])
                    except Exception:
                        logger.exception("failed: %s", answer_id)
                    if result is not None and not result.text:
                        # reasoning models can spend the whole token budget
                        # thinking and return nothing, the tokens still bill
                        logger.warning("empty answer: %s", answer_id)
                        report[name]["prompt_tokens"] += result.usage["prompt_tokens"]
                        report[name]["completion_tokens"] += result.usage["completion_tokens"]
                        result = None
                    if result is None:
                        report[name]["failed"] += 1
                        streak += 1
                        if streak >= 3:
                            # a misconfigured generator fails every call the
                            # same way, stop paying to find that out
                            logger.error("%s: three failures in a row, abandoning this generator", name)
                            break
                        continue
                    streak = 0
                    record = {
                        "answer_id": answer_id,
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
                    if tier in REWRITE_TIERS:
                        # id of the student answer the model polished
                        record["source_answer_id"] = student_id
                    else:
                        # with the template, these fix the exact prompt sent
                        record["target_words"] = target_words
                        record["course"] = config["course"]
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    # a killed run keeps every answer it paid for
                    out.flush()
                    report[name]["succeeded"] += 1
                    report[name]["prompt_tokens"] += result.usage["prompt_tokens"]
                    report[name]["completion_tokens"] += result.usage["completion_tokens"]
                logger.info("%s: %s", name, report[name])
    finally:
        # a crash mid-run must not lose the bookkeeping for paid calls
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("Wrote %s", out_dir)


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate raw AI answers per the harness config.")
    # no default, so a run cannot silently use another dataset's config
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset", choices=DATASETS, help="use harness/configs/<dataset>.yaml")
    source.add_argument("--config", help="path to any other harness config")
    parser.add_argument("--questions", type=positive_int, default=None, help="limit to the first N questions (pilot)")
    parser.add_argument("--tag", default="run", help="label for the output folder")
    parser.add_argument("--resume", default=None, help="run id to continue, skips answers it already holds")
    parser.add_argument("--go", action="store_true", help="actually call the APIs; default is a dry-run plan")
    args = parser.parse_args()

    config = load_config(args.config or CONFIG_DIR / f"{args.dataset}.yaml")
    questions = load_questions(PIPELINE_DIR / config["questions_file"], config["dataset"])
    if args.questions is not None:
        questions = questions.head(args.questions)
    run_id = args.resume or f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{config['dataset']}-{args.tag}"
    out_dir = PIPELINE_DIR / "data" / "generated" / run_id
    if args.resume and not out_dir.is_dir():
        # a mistyped id would otherwise start a new, fully paid run
        raise SystemExit(f"no run folder {out_dir} to resume, pass a folder name under data/generated")
    run(config, questions, out_dir, args.go)


if __name__ == "__main__":
    main()
