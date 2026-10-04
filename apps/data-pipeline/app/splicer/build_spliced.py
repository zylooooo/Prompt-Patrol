"""Build spliced answers from a built corpus version.

A spliced answer is a student answer with some of its sentences
replaced, in place, by the first sentences of an AI answer to the same
question. Each configured partition is spliced only from its own rows, so
no sentence the detector trained on reaches a spliced answer. Spliced
answers are grouped into bands by the share of their words that are AI,
and every band holds the same number per model. Output is a parquet in
the corpus column shape plus a manifest, written next to the corpus. The
columns are documented in docs/spliced-schema.md.
"""

import argparse
import json
import logging
import random
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import spacy
import yaml

from corpus.build import sha256, shown
from corpus.clean import clean_text
from harness.generate import count_words
from splicer.segment import MODEL, segment
from splicer.select import select
from splicer.splice import ai_share, band_candidates, is_eligible

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent.parent
PIPELINE_DIR = APP_DIR.parent
DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"

HUMAN, AI = 0, 1
POSITION_CAP = 200
# the corpus columns first, then the spliced extras
COLUMNS = ["answer", "label", "partition", "question_id", "answer_id", "generator", "n_words", "dataset", "tier",
           "style", "ai_fraction", "human_answer_id", "ai_answer_id", "n_sentences", "ai_positions"]


def load_corpus(path):
    """The corpus parquet and the manifest written beside it."""
    path = Path(path)
    manifest_path = path.with_name(f"{path.stem}_manifest.json")
    for required in (path, manifest_path):
        if not required.exists():
            raise SystemExit(f"no file at {required}, build the corpus version first")
    return pd.read_parquet(path), json.loads(manifest_path.read_text(encoding="utf-8"))


def check_config(config, corpus):
    """Stop on settings the build cannot honour, before any splicing.
    Returns the bands, the models and the count per model."""
    missing = sorted(set(config["partitions"]) - set(corpus["partition"]))
    if missing:
        raise SystemExit(f"the corpus has no {missing} partition")
    bands = {int(band): (float(low), float(high)) for band, (low, high) in config["bands"].items()}
    ranges = sorted(bands.values())
    if any(not 0 <= low < high <= 1 for low, high in ranges):
        raise SystemExit(f"band ranges must lie inside 0 to 1 with low below high, got {bands}")
    if any(later[0] <= earlier[1] for earlier, later in zip(ranges, ranges[1:])):
        raise SystemExit(f"band ranges overlap, got {bands}")
    models = sorted(set(corpus["generator"]) - {"human"})
    per_model, extra = divmod(config["answers_per_band"], len(models))
    if extra or not per_model:
        raise SystemExit(f"answers_per_band {config['answers_per_band']} does not divide across {len(models)} models")
    return bands, models, per_model


def band_pool(part, sentences, bands, seed, min_sentences):
    """Every in-band splice for one partition and dataset, by band, with
    how many bases and donors it drew on."""
    humans = part[part["label"] == HUMAN].sort_values("answer_id")
    ais = part[part["label"] == AI].sort_values("answer_id")
    donors = {question_id: list(group.itertuples()) for question_id, group in ais.groupby("question_id")}
    pool, eligible = {band: [] for band in bands}, 0
    for base in humans.itertuples():
        if not is_eligible(sentences[base.answer_id], min_sentences):
            continue
        eligible += 1
        for donor in donors.get(base.question_id, []):
            reached = band_candidates(base.answer_id, sentences[base.answer_id], donor.answer_id,
                                      sentences[donor.answer_id], bands, seed, POSITION_CAP)
            for band, (_, labelled, _) in reached.items():
                pool[band].append({"model": donor.generator, "base_id": base.answer_id, "donor_id": donor.answer_id,
                                   "question_id": base.question_id, "tier": donor.tier, "labelled": labelled})
    return pool, eligible, len(ais)


def check(spliced, corpus, manifest, config, bands):
    """Stop the build on anything that would make the spliced answers
    unfair or unlike the corpus text."""
    problems = []
    partition_of = spliced["question_id"].map(manifest["question_partitions"])
    leaked = spliced[~partition_of.isin(config["partitions"]) | (partition_of != spliced["partition"])]
    if len(leaked):
        problems.append(f"questions outside the configured partitions: {list(leaked['question_id'][:3])}")
    question_of = dict(zip(corpus["answer_id"], corpus["question_id"], strict=True))
    crossed = spliced[(spliced["human_answer_id"].map(question_of) != spliced["question_id"])
                      | (spliced["ai_answer_id"].map(question_of) != spliced["question_id"])]
    if len(crossed):
        problems.append(f"base and donor answer different questions: {list(crossed['answer_id'][:3])}")
    band = spliced["style"].str.removeprefix("spliced-").astype(int)
    outside = spliced[(spliced["ai_fraction"] < band.map(lambda b: bands[b][0]))
                      | (spliced["ai_fraction"] > band.map(lambda b: bands[b][1]))]
    if len(outside):
        problems.append(f"ai shares outside their band: {list(outside['answer_id'][:3])}")
    uses = spliced.groupby(["partition", "dataset", "style", "human_answer_id"]).size()
    if (uses > config["max_base_uses"]).any():
        problems.append(f"bases used more than {config['max_base_uses']} times in a band: "
                        f"{list(uses[uses > config['max_base_uses']].index[:3])}")
    if spliced.duplicated(["partition", "dataset", "style", "human_answer_id", "ai_answer_id"]).any():
        problems.append("a base and donor pair repeats within a band")
    if not spliced["answer_id"].is_unique or spliced["answer_id"].isin(corpus["answer_id"]).any():
        problems.append("spliced ids repeat or collide with corpus ids")
    unclean = spliced[spliced["answer"].map(clean_text) != spliced["answer"]]
    if len(unclean):
        problems.append(f"answers that change under clean_text: {list(unclean['answer_id'][:3])}")
    if problems:
        raise SystemExit("spliced answers check failed:\n  " + "\n  ".join(problems))


def segmenter_versions():
    """The spaCy and segmentation model versions, read without loading the model."""
    return {"spacy": spacy.__version__, "model": MODEL, "model_version": spacy.util.get_package_version(MODEL)}


def build(corpus, manifest, config):
    """The spliced answers, in the corpus column shape, and the statistics
    for their manifest."""
    bands, models, per_model = check_config(config, corpus)
    seed = config["seed"]
    rows = corpus[corpus["partition"].isin(config["partitions"])]
    sentences = {answer_id: segment(text) for answer_id, text in zip(rows["answer_id"], rows["answer"], strict=True)}
    records, eligible, candidates = [], {}, {}
    for partition in config["partitions"]:
        for dataset in sorted(set(rows["dataset"])):
            part = rows[(rows["partition"] == partition) & (rows["dataset"] == dataset)]
            pool, bases, donors = band_pool(part, sentences, bands, seed, config["min_sentences"])
            eligible.setdefault(partition, {})[dataset] = {"bases": bases, "donors": donors}
            candidates.setdefault(partition, {})[dataset] = {str(b): len(pool[b]) for b in sorted(bands)}
            for band in sorted(bands):
                draw = random.Random(f"{seed}/select/{partition}/{dataset}/{band}")
                chosen, counts = select(pool[band], models, per_model, config["max_base_uses"], draw)
                short = {model: n for model, n in counts.items() if n < per_model}
                if short:
                    raise SystemExit(f"{partition} {dataset} band {band} cannot reach {per_model} per model, "
                                     f"found {short}")
                chosen.sort(key=lambda c: (c["model"], c["base_id"], c["donor_id"]))
                for number, c in enumerate(chosen):
                    text = " ".join(s["text"] for s in c["labelled"])
                    records.append({
                        "answer": text, "label": AI, "partition": partition, "question_id": c["question_id"],
                        "answer_id": f"spliced/{partition}/{dataset}/b{band}/{number:04d}",
                        "generator": c["model"], "n_words": count_words(text), "dataset": dataset,
                        "tier": c["tier"], "style": f"spliced-{band}", "ai_fraction": round(ai_share(c["labelled"]), 4),
                        "human_answer_id": c["base_id"], "ai_answer_id": c["donor_id"],
                        "n_sentences": len(c["labelled"]),
                        "ai_positions": [i for i, s in enumerate(c["labelled"]) if s["label"] == "ai"],
                    })
    spliced = pd.DataFrame(records, columns=COLUMNS)
    check(spliced, corpus, manifest, config, bands)

    row_counts, shares = {}, {}
    per_model_count = spliced.groupby(["partition", "dataset", "style", "generator"]).size()
    for (partition, dataset, style, model), n in per_model_count.items():
        by_band = row_counts.setdefault(partition, {}).setdefault(dataset, {})
        by_band.setdefault(style.removeprefix("spliced-"), {})[model] = int(n)
    mean_share = spliced.groupby(["partition", "dataset", "style"])["ai_fraction"].mean()
    for (partition, dataset, style), mean in mean_share.items():
        shares.setdefault(partition, {}).setdefault(dataset, {})[style.removeprefix("spliced-")] = round(float(mean), 4)
    stats = {
        "text_cleaning": manifest["text_cleaning"],
        "segmenter": segmenter_versions(),
        "seed": seed,
        "partitions": list(config["partitions"]),
        "bands": {str(b): list(r) for b, r in sorted(bands.items())},
        "answers_per_band": config["answers_per_band"],
        "answers_per_model": per_model,
        "max_base_uses": config["max_base_uses"],
        "min_sentences": config["min_sentences"],
        "eligible": eligible,
        "candidates": candidates,
        "rows": row_counts,
        "mean_ai_fraction": shares,
        "most_base_uses": int(spliced.groupby(["partition", "dataset", "style", "human_answer_id"]).size().max()),
        "answers_per_question": {q: int(n) for q, n in spliced.groupby("question_id").size().items()},
    }
    return spliced, stats


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Build spliced answers from a built corpus version.")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--corpus", help="corpus parquet relative to apps/data-pipeline, overrides the config value")
    args = parser.parse_args()
    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    corpus_path = PIPELINE_DIR / (args.corpus or config["corpus"])
    corpus, manifest = load_corpus(corpus_path)
    spliced, stats = build(corpus, manifest, config)

    version = f"{manifest['version']}-spliced"
    out_path = corpus_path.with_name(f"{version}.parquet")
    manifest_path = corpus_path.with_name(f"{version}_manifest.json")
    full = {"version": version, "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source": {"path": shown(corpus_path), "sha256": sha256(corpus_path)}, **stats}
    # write under temporary names first, so a failed write never leaves a half-written file
    parquet_tmp = out_path.with_name(out_path.name + ".tmp")
    manifest_tmp = manifest_path.with_name(manifest_path.name + ".tmp")
    spliced.to_parquet(parquet_tmp, index=False)
    manifest_tmp.write_text(json.dumps(full, indent=2), encoding="utf-8")
    parquet_tmp.replace(out_path)
    manifest_tmp.replace(manifest_path)
    logger.info("wrote %d spliced answers to %s", len(spliced), out_path)


if __name__ == "__main__":
    main()
