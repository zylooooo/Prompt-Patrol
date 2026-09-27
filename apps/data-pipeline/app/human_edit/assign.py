"""Pick raw AI answers for the genuine hand edits and write one CSV sheet
per editor, plus a manifest that links every row back to its source.

Every answer goes to exactly one editor, and every editor gets a mix of
generators and quality tiers.
"""

import argparse
import csv
import logging
import random
from pathlib import Path

from harness.generate import load_questions
from human_edit.common import DATA_DIR, DEFAULT_CONFIG, PIPELINE_DIR, load_answers, load_config, write_jsonl

logger = logging.getLogger(__name__)

SHEET_COLUMNS = ["edit_id", "question", "original_answer", "edited_answer", "edit_types", "notes"]


def pick_for_editors(answers, editors, per_editor, seed):
    """Deal answers to editors round-robin across (generator, tier) groups,
    so each editor's rows spread over generators and tiers."""
    if len(set(editors)) != len(editors):
        raise SystemExit(f"duplicate editor names: {editors}")
    needed = len(editors) * per_editor
    rng = random.Random(seed)
    groups = {}
    for record in answers:
        groups.setdefault((record["generator"], record["tier"]), []).append(record)
    queues = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda r: r["answer_id"])
        rng.shuffle(group)
        queues.append(group)
    rng.shuffle(queues)
    # take round-robin across groups so the picked set is balanced
    picked = []
    while len(picked) < needed and any(queues):
        for group_index, queue in enumerate(queues):
            if queue and len(picked) < needed:
                picked.append((group_index, queue.pop()))
    if len(picked) < needed:
        raise SystemExit(f"need {needed} answers for {len(editors)} editors, only {len(picked)} available")
    # then deal group by group, so each group's answers go to different
    # editors instead of the same editor always landing on the same group
    ordered = [record for _, record in sorted(picked, key=lambda p: p[0])]
    return {editor: ordered[i::len(editors)] for i, editor in enumerate(editors)}


def write_sheets(assignments, questions, out_dir):
    """One <editor>.csv per editor plus manifest.jsonl. The edited_answer
    column starts as a copy of the original, editors change it in place."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for editor, records in assignments.items():
        with open(out_dir / f"{editor}.csv", "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
            writer.writeheader()
            for record in records:
                edit_id = f"{record['answer_id']}/edit-genuine"
                writer.writerow({
                    "edit_id": edit_id,
                    "question": questions[record["question_id"]],
                    "original_answer": record["answer"],
                    "edited_answer": record["answer"],
                    "edit_types": "",
                    "notes": "",
                })
                manifest.append({
                    "edit_id": edit_id,
                    "editor": editor,
                    "source_answer_id": record["answer_id"],
                    "question_id": record["question_id"],
                    "generator": record["generator"],
                    "tier": record["tier"],
                    "source_answer": record["answer"],
                })
    write_jsonl(out_dir / "manifest.jsonl", manifest)
    return manifest


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Write hand-edit sheets for the genuine subset.")
    parser.add_argument("--answers", required=True, help="harness answers.jsonl to pick from")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--out", default=DATA_DIR / "sheets", help="folder for the sheets and manifest")
    args = parser.parse_args()

    config = load_config(args.config)
    genuine = config["genuine"]
    answers = load_answers(Path(args.answers))
    questions = load_questions(PIPELINE_DIR / config["questions_file"], config["dataset"])
    question_text = dict(zip(questions["question_id"], questions["question"], strict=True))
    assignments = pick_for_editors(answers, genuine["editors"], genuine["per_editor"], config["seed"])
    manifest = write_sheets(assignments, question_text, Path(args.out))
    logger.info("Wrote %d rows for %d editors to %s", len(manifest), len(assignments), args.out)


if __name__ == "__main__":
    main()
