"""Build the spliced corpus: config in, labelled documents out.

Pairs eligible human answers with AI answers to the same question and
writes one JSON record per document, carrying both source answer ids.
Deterministic for a fixed config and seed. The record shape is
documented in docs/spliced-schema.md.
"""

import argparse
import json
import logging
from pathlib import Path

import pandas as pd
import yaml

from splicer.segment import segment
from splicer.splice import is_eligible, make_rng, splice_pair

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent.parent
PIPELINE_DIR = APP_DIR.parent
DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


COLUMN_ALIASES = {"QuestionID": "question_id", "StudentAnswer": "student_answer"}


def load_human_answers(path, min_sentences, namespace):
    """Segment every human answer and keep the eligible ones, grouped by question."""
    df = pd.read_parquet(path).rename(columns=COLUMN_ALIASES)
    if "question_id" not in df.columns:
        df = df.assign(question_id=df["id"].str.rsplit(".", n=1).str[0])
    df = df.assign(question_id=namespace + "/" + df["question_id"])
    grouped = {}
    dropped = 0
    for _, row in df.iterrows():
        sentences = segment(row["student_answer"])
        if not is_eligible(sentences, min_sentences):
            dropped += 1
            continue
        grouped.setdefault(row["question_id"], []).append(
            {"question_id": row["question_id"], "answer_id": namespace + "/" + row["id"], "sentences": sentences}
        )
    logger.info("human answers: %d eligible, %d excluded", sum(len(v) for v in grouped.values()), dropped)
    return grouped


def load_ai_answers(path):
    """Segment the harness output, grouped by question. No prose gate here.
    The AI side only donates sentences and splice_pair rejects short donors."""
    grouped = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            sentences = segment(record["answer"])
            if sentences:
                grouped.setdefault(record["question_id"], []).append(
                    {
                        "answer_id": record["answer_id"],
                        "sentences": sentences,
                        "source_answer_id": record.get("source_answer_id"),
                    }
                )
    return grouped


def build_corpus(humans, ais, config, rng):
    """The assembly itself, pure enough to test without files."""
    records = []
    # set order varies with hash randomisation, sorting keeps runs deterministic
    questions = sorted(set(humans) & set(ais))
    if not questions:
        logger.warning("no overlapping questions between the corpora, check the dataset namespaces")
    for fraction in config["target_fractions"]:
        # each fraction draws from the full pool, the same pair can recur
        # across fractions
        pairs = [(h, a) for q in questions for h in humans[q] for a in ais[q]]
        rng.shuffle(pairs)
        count = 0
        for human, ai in pairs:
            if count >= config["docs_per_fraction"]:
                break
            if ai.get("source_answer_id") == human["answer_id"]:
                # never pair an answer with its own rewrite
                continue
            result = splice_pair(human["sentences"], ai["sentences"], fraction, rng)
            if result is None:
                continue
            labelled, actual = result
            records.append({
                "doc_id": f"spliced/{config['dataset']}/f{round(fraction * 100):02d}/{count:04d}",
                "question_id": human["question_id"],
                "human_answer_id": human["answer_id"],
                "ai_answer_id": ai["answer_id"],
                "target_ai_fraction": fraction,
                "ai_fraction": round(actual, 4),
                "sentences": labelled,
            })
            count += 1
        logger.info("fraction %.2f: built %d documents", fraction, count)
    return records


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Build the spliced corpus from one harness run.")
    parser.add_argument("--ai-answers", default=None, help="answers.jsonl to splice, overrides the config value")
    args = parser.parse_args()
    config = yaml.safe_load(open(DEFAULT_CONFIG, encoding="utf-8"))
    ai_path = PIPELINE_DIR / (args.ai_answers or config["ai_answers"])
    if not ai_path.exists():
        raise SystemExit(
            f"no AI answers at {ai_path}, point ai_answers in app/splicer/config.yaml "
            "or --ai-answers at a run folder's answers.jsonl"
        )
    humans = load_human_answers(PIPELINE_DIR / config["human_corpus"], config["min_sentences"], config["dataset"])
    ais = load_ai_answers(ai_path)
    records = build_corpus(humans, ais, config, make_rng(config["seed"]))
    out_dir = PIPELINE_DIR / config["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"spliced_{config['dataset']}.jsonl"
    with open(out_path, "w", encoding="utf-8") as out:
        for record in records:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("wrote %d documents to %s", len(records), out_path)


if __name__ == "__main__":
    main()
