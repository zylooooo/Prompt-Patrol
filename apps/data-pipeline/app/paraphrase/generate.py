"""Paraphrase run loop: raw AI answers in, reworded candidates out.

Dry-run by default: it prints the call plan and stops. Nothing spends
money without --go. Scoring and filtering is a separate step
(paraphrase.filter), so thresholds can be retuned without paying for
the rewrites again.
"""

import argparse
import json
import logging
import random
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from harness.clients import build_clients
from paraphrase.prompts import STRENGTH_TO_TEMPLATE, SYSTEM, TEMPLATES

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent.parent
PIPELINE_DIR = APP_DIR.parent
DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_answers(path):
    """Harness records with a non-empty answer, in file order."""
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    return [r for r in records if r.get("answer", "").strip()]


def select_answers(answers, share, seed):
    """Pick a fixed share of answers from every (generator, tier) group, so
    the pass covers all generators and quality tiers. The same share and
    seed always pick the same answers."""
    if not 0 < share <= 1:
        raise SystemExit(f"share must be in (0, 1], got {share}")
    groups = {}
    for record in answers:
        groups.setdefault((record["generator"], record["tier"]), []).append(record)
    rng = random.Random(seed)
    picked = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda r: r["answer_id"])
        count = min(len(group), max(1, round(len(group) * share)))
        picked.extend(rng.sample(group, count))
    return sorted(picked, key=lambda r: r["answer_id"])


def existing_ids(path):
    """Paraphrase ids already written, so a rerun into the same folder skips
    paid work instead of repeating it."""
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        return {json.loads(line)["paraphrase_id"] for line in f if line.strip()}


def build_record(source, strength, template_name, paraphraser_name, result):
    record = {
        "paraphrase_id": f"{source['answer_id']}/para-{strength}",
        "source_answer_id": source["answer_id"],
        "question_id": source["question_id"],
        # generator stays the source's, so leave-one-generator-out folds
        # still hold out every answer a generator wrote, reworded or not
        "generator": source["generator"],
        "tier": source["tier"],
        "strength": strength,
        "paraphraser": paraphraser_name,
        "paraphraser_model_version": result.model_version,
        "paraphraser_settings": result.params_honoured,
        "prompt_template": template_name,
        "usage": result.usage,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_answer": source["answer"],
        "answer": result.text,
    }
    if source.get("source_answer_id"):
        # the source was itself a rewrite of a real student answer
        record["human_source_answer_id"] = source["source_answer_id"]
    return record


def run(config, answers, out_dir, go):
    """Paraphrase the selected answers into out_dir: candidates.jsonl plus
    run_report.json. Without go, the plan is logged and nothing is called."""
    strengths = config["strengths"]
    unknown = sorted(s for s in strengths if s not in STRENGTH_TO_TEMPLATE)
    if unknown:
        raise SystemExit(f"unknown strengths, no template for: {unknown}")
    paraphraser = config["paraphraser"]
    selected = select_answers(answers, config["share"], config["seed"])
    total = len(selected) * len(strengths)
    logger.info(
        "Plan: %d of %d answers x %d strengths = %d calls to %s",
        len(selected), len(answers), len(strengths), total, paraphraser["name"],
    )
    if not go:
        logger.info("Dry run only. Re-run with --go to paraphrase.")
        return

    # keys are only needed past the dry-run gate
    load_dotenv(PIPELINE_DIR / ".env")
    client = build_clients({"generators": [paraphraser]})[paraphraser["name"]]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "candidates.jsonl"
    done = existing_ids(out_path)
    report = {
        "paraphraser": paraphraser["name"], "requested": 0, "succeeded": 0, "failed": 0,
        "skipped_existing": 0, "prompt_tokens": 0, "completion_tokens": 0,
    }
    calls = [(source, strength) for source in selected for strength in strengths]
    try:
        # append, a rerun into an existing folder must not erase paid rewrites
        with open(out_path, "a", encoding="utf-8") as out:
            streak = 0
            for source, strength in calls:
                if f"{source['answer_id']}/para-{strength}" in done:
                    report["skipped_existing"] += 1
                    continue
                template_name = STRENGTH_TO_TEMPLATE[strength]
                prompt = TEMPLATES[template_name].format(answer=source["answer"])
                report["requested"] += 1
                try:
                    result = client.generate(SYSTEM, prompt, config["decoding"])
                except Exception:
                    logger.exception("failed: %s %s", source["answer_id"], strength)
                    report["failed"] += 1
                    streak += 1
                    if streak >= 3:
                        logger.error("three failures in a row, stopping the run")
                        break
                    continue
                streak = 0
                report["prompt_tokens"] += result.usage["prompt_tokens"]
                report["completion_tokens"] += result.usage["completion_tokens"]
                if not result.text:
                    logger.warning("empty paraphrase: %s %s", source["answer_id"], strength)
                    report["failed"] += 1
                    continue
                record = build_record(source, strength, template_name, paraphraser["name"], result)
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                report["succeeded"] += 1
    finally:
        # a crash mid-run must not lose the bookkeeping for paid calls
        (out_dir / "run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("%s", report)
        logger.info("Wrote %s", out_dir)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Paraphrase raw AI answers per the paraphrase config.")
    parser.add_argument("--answers", required=True, help="harness answers.jsonl to paraphrase")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--tag", default="run", help="label for the output folder")
    parser.add_argument("--out", default=None, help="existing run folder to resume into")
    parser.add_argument("--go", action="store_true", help="actually call the API; default is a dry-run plan")
    args = parser.parse_args()

    config = load_config(args.config)
    answers = load_answers(Path(args.answers))
    if args.out:
        out_dir = Path(args.out)
    else:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + args.tag
        out_dir = PIPELINE_DIR / "data" / "paraphrased" / run_id
    run(config, answers, out_dir, args.go)


if __name__ == "__main__":
    main()
