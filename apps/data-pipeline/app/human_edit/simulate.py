"""Simulated editing pass: an LLM applies human-like edits at scale.

The prompt is derived from the genuine edits, not guessed: the share of
each edit type and the number of edit types per answer follow what the
editors actually did, and a fixed set of genuine edits is shown as
examples. The derived spec is saved next to the output.

Dry-run by default: it prints the call plan and stops. Nothing spends
money without --go.
"""

import argparse
import json
import logging
import random
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from harness.clients import build_clients
from human_edit.common import (
    DATA_DIR,
    DEFAULT_CONFIG,
    PIPELINE_DIR,
    load_answers,
    load_config,
    read_jsonl,
    stratified_sample,
    tokens,
    word_edit_distance,
)
from human_edit.prompts import EDIT_TYPE_TEXT, EXAMPLE, SYSTEM, TEMPLATE, TEMPLATE_NAME

logger = logging.getLogger(__name__)

MIN_GENUINE = 5


def build_prompt_spec(genuine, edit_types, examples, seed):
    """Everything the prompt takes from the genuine edits: how often each
    edit type was used, how many types editors combined per answer, and
    which genuine edits are shown as examples."""
    if len(genuine) < MIN_GENUINE:
        raise SystemExit(f"need at least {MIN_GENUINE} genuine edits to derive the prompt, got {len(genuine)}")
    type_counts = Counter(t for g in genuine for t in g["edit_types"])
    per_answer = Counter(len(g["edit_types"]) for g in genuine)
    ordered = sorted(genuine, key=lambda g: g["edit_id"])
    shown = random.Random(seed).sample(ordered, min(examples, len(ordered)))
    return {
        "prompt_template": TEMPLATE_NAME,
        "genuine_count": len(genuine),
        # a type no editor used gets weight zero, so the simulation never
        # does something the genuine subset never did
        "type_weights": {t: type_counts.get(t, 0) for t in edit_types},
        # how much of each answer the editors changed; every simulated
        # answer is given one of these as its target size
        "edit_sizes": sorted(round(word_edit_distance(g["source_answer"], g["answer"]), 4) for g in genuine),
        "types_per_answer": {str(k): v for k, v in sorted(per_answer.items())},
        "example_edit_ids": [g["edit_id"] for g in shown],
        "examples": [{"source": g["source_answer"], "edited": g["answer"]} for g in shown],
    }


def draw_edit_types(spec, rng):
    """Draw how many edit types to apply, then which, both following the
    genuine distribution."""
    counts = spec["types_per_answer"]
    how_many = int(rng.choices(list(counts), weights=list(counts.values()))[0])
    pool = {t: w for t, w in spec["type_weights"].items() if w > 0}
    chosen = []
    while pool and len(chosen) < how_many:
        pick = rng.choices(list(pool), weights=list(pool.values()))[0]
        chosen.append(pick)
        del pool[pick]
    return sorted(chosen)


MIN_TARGET = 0.05
MAX_ASKED = 0.9


def draw_target(spec, rng):
    """A target share of words to change, drawn from the genuine edit
    sizes, never below MIN_TARGET so every edit changes something."""
    return max(MIN_TARGET, rng.choice(spec["edit_sizes"]))


def asked_share(target, scale):
    """The share the prompt asks for. The editor model changes less than it
    is asked to, so the target is scaled up by the configured factor, and
    capped so it is never told to rewrite everything."""
    return min(MAX_ASKED, target * scale)


def render_prompt(spec, answer, edit_types, target):
    examples = "\n\n".join(EXAMPLE.format(**e) for e in spec["examples"])
    wanted = "; ".join(EDIT_TYPE_TEXT[t] for t in edit_types)
    n_words = max(1, len(tokens(answer)))
    target_words = max(1, round(target * n_words))
    return TEMPLATE.format(examples=examples, edit_types=wanted, answer=answer, n_words=n_words,
                           target_words=target_words, target_pct=round(target * 100))


def existing_ids(path):
    if not path.exists():
        return set()
    return {r["edit_id"] for r in read_jsonl(path)}


def run(config, answers, genuine, out_dir, go, limit=None):
    """Edit the selected answers into out_dir: simulated.jsonl,
    prompt_spec.json and run_report.json. Without go, the plan is logged
    and nothing is called."""
    simulated = config["simulated"]
    spec = build_prompt_spec(genuine, config["edit_types"], simulated["examples"], config["seed"])
    scale = simulated.get("target_scale", 1.0)
    spec["target_scale"] = scale
    # answers already hand-edited stay out, so one source never carries both
    taken = {g["source_answer_id"] for g in genuine}
    pool = [a for a in answers if a["answer_id"] not in taken]
    selected = stratified_sample(pool, simulated["share"], config["seed"])
    if limit and limit < len(selected):
        # a small trial batch spread over every exam, generator and tier,
        # not the first answers by id, which all come from one exam
        trial = random.Random(config["seed"]).sample(selected, limit)
        selected = sorted(trial, key=lambda a: a["answer_id"])
    editor = simulated["editor"]
    logger.info("Plan: %d of %d answers, one call each to %s", len(selected), len(pool), editor["name"])
    logger.info("Derived edit-type weights %s, types per answer %s", spec["type_weights"], spec["types_per_answer"])
    sizes = spec["edit_sizes"]
    logger.info("Target edit sizes from %d genuine edits, median %.3f, asked at x%s", len(sizes),
                sizes[len(sizes) // 2], scale)
    if not go:
        logger.info("Dry run only. Re-run with --go to edit.")
        return

    load_dotenv(PIPELINE_DIR / ".env")
    client = build_clients({"generators": [editor]})[editor["name"]]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompt_spec.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    out_path = out_dir / "simulated.jsonl"
    done = existing_ids(out_path)
    report = {
        "editor": editor["name"], "requested": 0, "succeeded": 0, "failed": 0,
        "skipped_existing": 0, "prompt_tokens": 0, "completion_tokens": 0,
    }
    rng = random.Random(config["seed"])
    try:
        with open(out_path, "a", encoding="utf-8") as out:
            streak = 0
            for source in selected:
                # draw before the skip check, so a resumed run gives every
                # answer the same edit types as the first attempt did
                edit_types = draw_edit_types(spec, rng)
                target = draw_target(spec, rng)
                edit_id = f"{source['answer_id']}/edit-simulated"
                if edit_id in done:
                    report["skipped_existing"] += 1
                    continue
                report["requested"] += 1
                result = None
                try:
                    result = client.generate(SYSTEM, render_prompt(spec, source["answer"], edit_types, asked_share(target, scale)),
                                             simulated["decoding"])
                except Exception:
                    logger.exception("failed: %s", source["answer_id"])
                if result is not None:
                    report["prompt_tokens"] += result.usage["prompt_tokens"]
                    report["completion_tokens"] += result.usage["completion_tokens"]
                    if not result.text:
                        # empty edits are billed, so they count toward the three-failure stop
                        logger.warning("empty edit: %s", source["answer_id"])
                        result = None
                if result is None:
                    report["failed"] += 1
                    streak += 1
                    if streak >= 3:
                        logger.error("three failures in a row, stopping the run")
                        break
                    continue
                streak = 0
                record = {
                    "edit_id": edit_id,
                    "source_answer_id": source["answer_id"],
                    "question_id": source["question_id"],
                    "generator": source["generator"],
                    "tier": source["tier"],
                    "edit_source": "simulated",
                    "editor": editor["name"],
                    "editor_model_version": result.model_version,
                    "editor_settings": result.params_honoured,
                    "prompt_template": TEMPLATE_NAME,
                    "edit_types": edit_types,
                    "target_edit_distance": target,
                    "asked_share": round(asked_share(target, scale), 4),
                    "example_edit_ids": spec["example_edit_ids"],
                    "usage": result.usage,
                    "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
                    "source_answer": source["answer"],
                    "answer": result.text,
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                report["succeeded"] += 1
    finally:
        (out_dir / "run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("%s", report)
        logger.info("Wrote %s", out_dir)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Apply LLM-simulated student edits to raw AI answers.")
    parser.add_argument("--answers", required=True, help="harness answers.jsonl to edit")
    parser.add_argument("--genuine", default=DATA_DIR / "genuine.jsonl", help="collected genuine edits")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--tag", default="run", help="label for the output folder")
    parser.add_argument("--out", default=None, help="existing run folder to resume into")
    parser.add_argument("--limit", type=int, default=None, help="edit only the first N selected answers, for a trial")
    parser.add_argument("--go", action="store_true", help="actually call the API; default is a dry-run plan")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.out:
        out_dir = Path(args.out)
    else:
        out_dir = DATA_DIR / "simulated" / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + args.tag)
    run(config, load_answers(Path(args.answers)), read_jsonl(args.genuine), out_dir, args.go, args.limit)


if __name__ == "__main__":
    main()
