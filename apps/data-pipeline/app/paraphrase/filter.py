"""Score paraphrase candidates and split kept from excluded.

Two checks per candidate:
- similarity: cosine similarity of source and paraphrase embeddings.
  Below similarity_floor the meaning did not survive.
- surface_change: share of the word sequence that changed, 0 for an
  identical answer, 1 for nothing in common. Below min_surface_change
  the rewrite is too trivial to count as a paraphrase.

With both thresholds null (the pilot) everything is scored and kept, and
--spot-check writes a sample to read by hand before choosing them.
"""

import argparse
import csv
import difflib
import json
import logging
import math
import random
import re
import statistics
from pathlib import Path

import openai
from dotenv import load_dotenv

from harness.clients import _retry
from paraphrase.generate import DEFAULT_CONFIG, PIPELINE_DIR, load_config

logger = logging.getLogger(__name__)

WORD = re.compile(r"\w+")
EMBED_BATCH = 100


def surface_change(source, paraphrase):
    """Word-level change between two texts, case-insensitive, 0 to 1."""
    a, b = WORD.findall(source.lower()), WORD.findall(paraphrase.lower())
    if not a and not b:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def cosine(u, v):
    dot = sum(x * y for x, y in zip(u, v, strict=True))
    norm = math.sqrt(sum(x * x for x in u)) * math.sqrt(sum(y * y for y in v))
    return dot / norm if norm else 0.0


class OpenAIEmbedder:
    def __init__(self, model):
        self.model = model
        self._client = openai.OpenAI()  # reads OPENAI_API_KEY

    def embed(self, texts):
        def is_retryable(exc):
            return isinstance(exc, (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError))

        vectors = []
        for start in range(0, len(texts), EMBED_BATCH):
            batch = texts[start:start + EMBED_BATCH]
            resp = _retry(lambda: self._client.embeddings.create(model=self.model, input=batch), is_retryable)
            vectors.extend(item.embedding for item in sorted(resp.data, key=lambda d: d.index))
        return vectors


def load_candidates(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def score(candidates, embedder):
    """Attach similarity and surface_change to every candidate."""
    texts = sorted({c["source_answer"] for c in candidates} | {c["answer"] for c in candidates})
    vectors = dict(zip(texts, embedder.embed(texts), strict=True)) if texts else {}
    return [
        {
            **c,
            "similarity": round(cosine(vectors[c["source_answer"]], vectors[c["answer"]]), 4),
            "surface_change": round(surface_change(c["source_answer"], c["answer"]), 4),
        }
        for c in candidates
    ]


def exclusion_reason(candidate, filters):
    """None when the candidate passes, otherwise why it was excluded."""
    floor = filters.get("similarity_floor")
    if floor is not None and candidate["similarity"] < floor:
        return "meaning_lost"
    min_change = filters.get("min_surface_change")
    if isinstance(min_change, dict):
        min_change = min_change.get(candidate["strength"])
    if min_change is not None and candidate["surface_change"] < min_change:
        return "trivial_rewrite"
    return None


def summarise(values):
    if not values:
        return None
    return {"min": min(values), "median": round(statistics.median(values), 4), "max": max(values)}


def write_spot_check(path, scored, size, seed):
    """A random sample to read by hand. The two blank columns are for the
    reader's verdicts, which decide the thresholds."""
    sample = random.Random(seed).sample(scored, min(size, len(scored)))
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "paraphrase_id", "strength", "similarity", "surface_change",
            "source_answer", "paraphrase", "meaning_kept", "actually_changed",
        ])
        for c in sorted(sample, key=lambda c: c["paraphrase_id"]):
            writer.writerow([
                c["paraphrase_id"], c["strength"], c["similarity"], c["surface_change"],
                c["source_answer"], c["answer"], "", "",
            ])


def run_filter(config, candidates, embedder, out_dir, spot_check=0):
    """Write paraphrased.jsonl (kept), excluded.jsonl and filter_report.json
    into out_dir, plus spot_check.csv when spot_check is above zero."""
    filters = config["filters"]
    scored = score(candidates, embedder)
    kept, excluded = [], []
    for c in scored:
        reason = exclusion_reason(c, filters)
        if reason:
            excluded.append({**c, "exclusion_reason": reason})
        else:
            kept.append({**c, "label": "paraphrased"})

    with open(out_dir / "paraphrased.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in kept)
    with open(out_dir / "excluded.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in excluded)

    strengths = sorted({c["strength"] for c in scored})
    report = {
        "candidates": len(scored),
        "kept": len(kept),
        "excluded": len(excluded),
        "excluded_by_reason": {
            reason: sum(1 for r in excluded if r["exclusion_reason"] == reason)
            for reason in ("meaning_lost", "trivial_rewrite")
        },
        "kept_by_strength": {s: sum(1 for r in kept if r["strength"] == s) for s in strengths},
        "filters": filters,
        "scores_by_strength": {
            s: {
                "similarity": summarise([c["similarity"] for c in scored if c["strength"] == s]),
                "surface_change": summarise([c["surface_change"] for c in scored if c["strength"] == s]),
            }
            for s in strengths
        },
    }
    (out_dir / "filter_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if spot_check:
        write_spot_check(out_dir / "spot_check.csv", scored, spot_check, config["seed"])
    logger.info("kept %d of %d, excluded %s", len(kept), len(scored), report["excluded_by_reason"])
    return report


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Score and filter paraphrase candidates.")
    parser.add_argument("--run", required=True, help="paraphrase run folder holding candidates.jsonl")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--spot-check", type=int, default=0, help="also write N random samples to spot_check.csv")
    args = parser.parse_args()

    config = load_config(args.config)
    out_dir = Path(args.run)
    candidates = load_candidates(out_dir / "candidates.jsonl")
    load_dotenv(PIPELINE_DIR / ".env")
    embedder = OpenAIEmbedder(config["filters"]["embedding_model"])
    run_filter(config, candidates, embedder, out_dir, args.spot_check)


if __name__ == "__main__":
    main()
