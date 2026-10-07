"""Attach paraphrased or human_edited answers to a built corpus version.

The paraphrase and human-edit passes read a harness run, so their output
holds answers whose source never made it into the corpus (thinned by keep,
cut by the floor or the train cap). This keeps only records whose
source_answer_id is an AI answer in the corpus version, gives each the
partition, question_id, dataset and tier of that source, so a rewrite of a
test answer is a test row, and cleans the text with the same clean_text the
corpus used. Output is a parquet in the corpus column shape plus a manifest,
written next to the corpus as <version>-<style>.parquet, the same way the
splicer writes <version>-spliced.parquet.

From inside app/:

    python -m corpus.attach_styles --style paraphrased \
        --corpus ../ml-training/data/splits/v0.1.parquet \
        --source ../data/paraphrased/<run>/paraphrased.jsonl --source ...
"""

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from corpus.build import MIN_WORDS, sha256, shown
from corpus.clean import CLEANING_VERSION, clean_text
from harness.generate import count_words

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent.parent
PIPELINE_DIR = APP_DIR.parent

AI = 1
CORPUS_COLUMNS = ["answer", "label", "partition", "question_id", "answer_id", "generator", "n_words", "dataset",
                  "tier"]
# per style: the record field used as answer_id, how the style column is
# named from a record, and the record fields kept as extra columns
STYLES = {
    "paraphrased": {
        "id": "paraphrase_id",
        "style": lambda r: f"paraphrased-{r['strength']}",
        "extras": ["strength", "similarity", "surface_change", "paraphraser"],
    },
    "human_edited": {
        "id": "edit_id",
        "style": lambda r: f"human_edited-{r['edit_source']}",
        "extras": ["edit_source", "edit_types", "edit_distance"],
    },
}


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_corpus(path):
    """The corpus parquet and the manifest written beside it."""
    path = Path(path)
    manifest_path = path.with_name(f"{path.stem}_manifest.json")
    for required in (path, manifest_path):
        if not required.exists():
            raise SystemExit(f"no file at {required}, pull or build the corpus version first")
    return pd.read_parquet(path), json.loads(manifest_path.read_text(encoding="utf-8"))


def attach(records, corpus, style):
    """Records matched to their corpus source. Returns (rows, stats)."""
    spec = STYLES[style]
    sources = corpus[corpus["label"] == AI].set_index("answer_id")
    rows, seen = [], set()
    not_in_corpus = short = 0
    for record in records:
        answer_id = record[spec["id"]]
        if answer_id in seen:
            raise SystemExit(f"duplicate {spec['id']}: {answer_id}")
        seen.add(answer_id)
        source_id = record["source_answer_id"]
        if source_id not in sources.index:
            not_in_corpus += 1
            continue
        source = sources.loc[source_id]
        if record.get("question_id", source["question_id"]) != source["question_id"]:
            raise SystemExit(f"{answer_id}: question_id {record['question_id']} but its source is "
                             f"{source['question_id']}")
        text = clean_text(record["answer"])
        n_words = count_words(text)
        if n_words < MIN_WORDS:
            short += 1
            continue
        rows.append({
            "answer": text, "label": AI, "partition": source["partition"], "question_id": source["question_id"],
            "answer_id": answer_id, "generator": source["generator"], "n_words": n_words,
            "dataset": source["dataset"], "tier": source["tier"], "style": spec["style"](record),
            "source_answer_id": source_id, **{k: record.get(k) for k in spec["extras"]},
        })
    columns = CORPUS_COLUMNS + ["style", "source_answer_id"] + spec["extras"]
    frame = pd.DataFrame(rows, columns=columns)
    stats = {
        "records_read": len(records),
        "dropped_source_not_in_corpus": not_in_corpus,
        "dropped_below_floor": short,
        "rows": len(frame),
        "rows_by": {
            p: {d: {s: int(n) for s, n in g2.groupby("style").size().items()}
                for d, g2 in g1.groupby("dataset")}
            for p, g1 in frame.groupby("partition")
        },
        "sources_covered": int(frame["source_answer_id"].nunique()),
    }
    return frame, stats


def check(frame, manifest):
    """The same partition rule the corpus holds: every row sits in its
    question's partition."""
    expected = frame["question_id"].map(manifest["question_partitions"])
    wrong = frame[expected != frame["partition"]]
    if len(wrong):
        raise SystemExit(f"rows outside their question's partition: {list(wrong['answer_id'][:3])}")
    if frame["answer"].str.strip().eq("").any():
        raise SystemExit("empty answer after cleaning")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Attach paraphrased or human_edited answers to a corpus version.")
    parser.add_argument("--style", required=True, choices=sorted(STYLES))
    parser.add_argument("--corpus", required=True, help="corpus parquet, a manifest must sit beside it")
    parser.add_argument("--source", required=True, action="append",
                        help="paraphrased.jsonl or human_edited.jsonl, repeat for each run")
    args = parser.parse_args()

    corpus_path = Path(args.corpus).resolve()
    corpus, manifest = load_corpus(corpus_path)
    records = [r for path in args.source for r in read_jsonl(path)]
    frame, stats = attach(records, corpus, args.style)
    check(frame, manifest)

    version = f"{manifest['version']}-{args.style}"
    out_path = corpus_path.with_name(f"{version}.parquet")
    manifest_path = corpus_path.with_name(f"{version}_manifest.json")
    full = {
        "version": version,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus": {"path": shown(corpus_path), "sha256": sha256(corpus_path)},
        "sources": [{"path": shown(Path(p).resolve()), "sha256": sha256(p)} for p in args.source],
        "text_cleaning": CLEANING_VERSION,
        "min_words": MIN_WORDS,
        **stats,
    }
    # temporary names first, so a failed write never leaves a half-written file
    parquet_tmp = out_path.with_name(out_path.name + ".tmp")
    manifest_tmp = manifest_path.with_name(manifest_path.name + ".tmp")
    frame.to_parquet(parquet_tmp, index=False)
    manifest_tmp.write_text(json.dumps(full, indent=2), encoding="utf-8")
    parquet_tmp.replace(out_path)
    manifest_tmp.replace(manifest_path)
    logger.info("wrote %d %s rows to %s (%d sources not in the corpus, %d below the floor)", len(frame),
                args.style, out_path, stats["dropped_source_not_in_corpus"], stats["dropped_below_floor"])


if __name__ == "__main__":
    main()
