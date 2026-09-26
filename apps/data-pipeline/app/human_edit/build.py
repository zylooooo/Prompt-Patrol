"""Assemble the human_edited set from genuine and simulated edits.

Every record is labelled human_edited, keeps its source link and carries
edit_source. The edit_source comes from which file a record was read from,
never from the record itself, so a simulated edit can never be passed off
as genuine. Simulated edits that left the answer unchanged are dropped.
"""

import argparse
import json
import logging
from pathlib import Path

from human_edit.common import DATA_DIR, normalise, read_jsonl, word_edit_distance, write_jsonl

logger = logging.getLogger(__name__)


def build(genuine, simulated):
    records, seen_ids, seen_sources = [], set(), {}
    unchanged = 0
    for edit_source, rows in (("genuine", genuine), ("simulated", simulated)):
        for row in rows:
            if row.get("edit_source", edit_source) != edit_source:
                raise SystemExit(f"{row['edit_id']}: found in the {edit_source} file but labelled {row['edit_source']}")
            if row["edit_id"] in seen_ids:
                raise SystemExit(f"duplicate edit_id: {row['edit_id']}")
            earlier = seen_sources.get(row["source_answer_id"])
            if earlier and earlier != edit_source:
                raise SystemExit(f"{row['source_answer_id']} has both a genuine and a simulated edit")
            if normalise(row["answer"]) == normalise(row["source_answer"]):
                unchanged += 1
                continue
            seen_ids.add(row["edit_id"])
            seen_sources[row["source_answer_id"]] = edit_source
            records.append({
                **row,
                "edit_source": edit_source,
                "label": "human_edited",
                "edit_distance": round(word_edit_distance(row["source_answer"], row["answer"]), 4),
            })
    report = {
        "total": len(records),
        "genuine": sum(r["edit_source"] == "genuine" for r in records),
        "simulated": sum(r["edit_source"] == "simulated" for r in records),
        "unchanged_dropped": unchanged,
    }
    return sorted(records, key=lambda r: r["edit_id"]), report


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Build the human_edited set and optionally push it.")
    parser.add_argument("--genuine", default=DATA_DIR / "genuine.jsonl")
    parser.add_argument("--run", required=True, help="simulated run folder holding simulated.jsonl")
    parser.add_argument(
        "--push", default=None,
        help="path_in_repo to push the built file to, for example mohler/human_edited/human_edited.jsonl",
    )
    args = parser.parse_args()

    run_dir = Path(args.run)
    records, report = build(read_jsonl(args.genuine), read_jsonl(run_dir / "simulated.jsonl"))
    out = run_dir / "human_edited.jsonl"
    write_jsonl(out, records)
    if args.push:
        # imported here so building locally needs no HuggingFace token
        from artifact_store import push_artifact

        report["pushed_to"] = args.push
        report["commit_hash"] = push_artifact(out, args.push, f"human_edited set: {report['genuine']} genuine, "
                                                               f"{report['simulated']} simulated")
    (run_dir / "build_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("%s", report)


if __name__ == "__main__":
    main()
