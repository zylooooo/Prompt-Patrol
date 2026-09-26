"""Read the returned hand-edit sheets back into genuine records.

Rows left identical to the original are dropped and counted. Unknown edit
types, rows from the wrong sheet and ids missing from the manifest stop the
run with a list of what to fix, so bad rows never reach the dataset.
"""

import argparse
import csv
import json
import logging
import re
from pathlib import Path

from human_edit.common import DATA_DIR, DEFAULT_CONFIG, load_config, normalise, read_jsonl, write_jsonl

logger = logging.getLogger(__name__)

SPLIT_TYPES = re.compile(r"[,;/\s]+")


def read_sheet(path):
    # utf-8-sig drops the byte-order mark Excel adds when saving as CSV
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_edit_types(value):
    return [t.strip().lower() for t in SPLIT_TYPES.split(value or "") if t.strip()]


def collect(manifest, sheets, allowed_types):
    """sheets maps editor -> rows. Returns (records, report); raises
    SystemExit listing every row that needs fixing."""
    by_id = {m["edit_id"]: m for m in manifest}
    records, errors, seen = [], [], set()
    unchanged = 0
    for editor, rows in sheets.items():
        for number, row in enumerate(rows, start=2):  # row 1 is the header
            where = f"{editor}.csv row {number}"
            source = by_id.get(row.get("edit_id", ""))
            if source is None:
                errors.append(f"{where}: edit_id not in the manifest")
                continue
            if source["editor"] != editor:
                errors.append(f"{where}: row belongs to {source['editor']}")
                continue
            if source["edit_id"] in seen:
                errors.append(f"{where}: duplicate edit_id")
                continue
            seen.add(source["edit_id"])
            edited = (row.get("edited_answer") or "").strip()
            if not edited or normalise(edited) == normalise(source["source_answer"]):
                unchanged += 1
                continue
            edit_types = parse_edit_types(row.get("edit_types"))
            unknown = sorted(set(edit_types) - set(allowed_types))
            if not edit_types or unknown:
                errors.append(f"{where}: edit_types must be one or more of {allowed_types}, got {row.get('edit_types')!r}")
                continue
            records.append({
                "edit_id": source["edit_id"],
                "source_answer_id": source["source_answer_id"],
                "question_id": source["question_id"],
                "generator": source["generator"],
                "tier": source["tier"],
                "edit_source": "genuine",
                "editor": editor,
                "edit_types": edit_types,
                "notes": (row.get("notes") or "").strip(),
                "source_answer": source["source_answer"],
                "answer": edited,
            })
    if errors:
        raise SystemExit("fix these rows and rerun:\n" + "\n".join(errors))
    returned_editors = set(sheets)
    missing = sorted(
        m["edit_id"] for m in manifest if m["editor"] in returned_editors and m["edit_id"] not in seen
    )
    report = {
        "assigned": len(manifest),
        "editors_returned": sorted(returned_editors),
        "editors_pending": sorted({m["editor"] for m in manifest} - returned_editors),
        "collected": len(records),
        "unchanged_dropped": unchanged,
        "rows_missing_from_returned_sheets": missing,
        "edit_type_counts": {t: sum(t in r["edit_types"] for r in records) for t in allowed_types},
    }
    return sorted(records, key=lambda r: r["edit_id"]), report


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Collect returned hand-edit sheets into genuine records.")
    parser.add_argument("--returned", required=True, help="folder holding the edited <editor>.csv files")
    parser.add_argument("--manifest", default=DATA_DIR / "sheets" / "manifest.jsonl")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--out", default=DATA_DIR / "genuine.jsonl")
    args = parser.parse_args()

    config = load_config(args.config)
    returned = Path(args.returned)
    sheets = {
        editor: read_sheet(returned / f"{editor}.csv")
        for editor in config["genuine"]["editors"]
        if (returned / f"{editor}.csv").exists()
    }
    if not sheets:
        raise SystemExit(f"no <editor>.csv files found in {returned}")
    records, report = collect(read_jsonl(args.manifest), sheets, config["edit_types"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(out, records)
    out.with_name("collect_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("collected %d genuine edits, %d unchanged dropped, pending editors: %s",
                len(records), report["unchanged_dropped"], report["editors_pending"])


if __name__ == "__main__":
    main()
