"""Build a fine-tuning corpus version from files already on disk.

Cleaned student answers are labelled human (0) and raw harness answers
ai (1), both passed through corpus.clean.clean_text. Every dataset is split by question on its own, so each one
appears in train, val and test, and every answer follows its question
into one partition. The output is the single parquet with a partition
column that ml-training's load_splits() reads, plus a manifest recording
the sources, counts and the partition of every question.

Nothing is called and nothing is paid for.
"""

import argparse
import hashlib
import json
import logging
import random
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from config import SPLIT_RATIOS, SPLIT_SEED
from corpus.clean import CLEANING_VERSION, clean_text
from harness.generate import COLUMN_ALIASES, count_words
from harness.prompts import is_rewrite

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent.parent
PIPELINE_DIR = APP_DIR.parent
DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"

HUMAN, AI = 0, 1
MIN_WORDS = 3
PARTITIONS = ("train", "val", "test")
# the load_splits() contract first, then two columns kept for slicing results
COLUMNS = ["answer", "label", "partition", "question_id", "answer_id", "generator", "n_words", "dataset", "tier"]


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalise(text):
    """Case and whitespace folded, so two ids asking the same question match."""
    return " ".join(str(text).lower().split())


def load_human(path, dataset):
    """Every student answer that is not blank after clean_text, labelled
    human. Ids are namespaced the way the harness namespaces them, so both
    sides meet on question_id."""
    df = pd.read_parquet(path).rename(columns=COLUMN_ALIASES)
    if "question_id" not in df.columns:
        df = df.assign(question_id=df["id"].str.rsplit(".", n=1).str[0])
    # a missing text would normalise to "nan" and merge unrelated questions
    blank = df["question"].fillna("").str.strip() == ""
    if blank.any():
        raise SystemExit(f"{dataset} has questions without text, first {sorted(set(df.loc[blank, 'question_id']))[:3]}")
    df = df.assign(student_answer=df["student_answer"].fillna("").map(clean_text))
    df = df[df["student_answer"] != ""]
    return pd.DataFrame({
        "answer": df["student_answer"],
        "label": HUMAN,
        "question_id": dataset + "/" + df["question_id"],
        "answer_id": dataset + "/" + df["id"],
        "generator": "human",
        "dataset": dataset,
        "tier": None,
        "question_text": df["question"].map(normalise),
    }).reset_index(drop=True)


def load_ai(path, dataset, question_texts):
    """Raw harness answers, labelled ai, how many rewrite-tier records were
    skipped, and the prompt template behind each tier. An answer to a
    question outside this dataset stops the build, since it means the
    wrong run folder is configured, and so does a tier made with more
    than one template or course, since a resume should never mix them."""
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    kept = [r for r in records if not is_rewrite(r)]
    foreign = sorted({r["question_id"] for r in kept} - set(question_texts))
    if foreign:
        raise SystemExit(f"{path} answers questions outside {dataset}, first {foreign[:3]}")
    prompts = {}
    for r in kept:
        prompts.setdefault(r["tier"], set()).add((r.get("prompt_template"), r.get("course")))
    mixed = sorted(tier for tier, versions in prompts.items() if len(versions) > 1)
    if mixed:
        raise SystemExit(f"{path} mixes prompt versions within tiers {mixed}, build from a run made with one version")
    templates = {tier: next(iter(versions))[0] for tier, versions in sorted(prompts.items())}
    logger.info("%s: %d ai answers, %d rewrite-tier records skipped", dataset, len(kept), len(records) - len(kept))
    return pd.DataFrame({
        "answer": [clean_text(r["answer"]) for r in kept],
        "label": AI,
        "question_id": [r["question_id"] for r in kept],
        "answer_id": [r["answer_id"] for r in kept],
        "generator": [r["generator"] for r in kept],
        "dataset": dataset,
        "tier": [r["tier"] for r in kept],
        "question_text": [question_texts[r["question_id"]] for r in kept],
    }), len(records) - len(kept), templates


def question_groups(question_texts, twins=()):
    """Group key per question_id. Ids that share a question text, or that
    are listed as twins because they ask the same thing in other words,
    are joined, and each group is named by its smallest text, so the key
    does not depend on dict order."""
    unknown = sorted({q for pair in twins for q in pair} - set(question_texts))
    if unknown:
        raise SystemExit(f"same_question lists ids that are not in the corpus, first {unknown[:3]}")
    parent = {q: q for q in question_texts}

    def root(q):
        while parent[q] != q:
            q = parent[q]
        return q

    by_text = {}
    for question_id, text in question_texts.items():
        by_text.setdefault(text, []).append(question_id)
    for members in [*by_text.values(), *twins]:
        for other in members[1:]:
            parent[root(other)] = root(members[0])
    names = {}
    for question_id, text in question_texts.items():
        names.setdefault(root(question_id), []).append(text)
    return {question_id: min(names[root(question_id)]) for question_id in question_texts}


def assign_partitions(question_texts, dataset, seed, ratios, twins=()):
    """Map each question_id to train, val or test. A question group (see
    question_groups) lands together. Groups are sorted, then shuffled with
    a seed per dataset, so every build gives the same split."""
    keys = question_groups(question_texts, twins)
    groups = sorted(set(keys.values()))
    if len(groups) < len(PARTITIONS):
        raise SystemExit(f"{dataset} has {len(groups)} distinct questions, too few to split three ways")
    random.Random(f"{seed}/{dataset}").shuffle(groups)
    n_test = max(1, round(len(groups) * ratios["test"]))
    n_val = max(1, round(len(groups) * ratios["val"]))
    partition = {group: "test" for group in groups[:n_test]}
    partition |= {group: "val" for group in groups[n_test:n_test + n_val]}
    partition |= {group: "train" for group in groups[n_test + n_val:]}
    return {question_id: partition[key] for question_id, key in keys.items()}


def cap_train_humans(corpus, seed):
    """In train, keep as many human answers per question as the question
    has ai answers, picked at random with a seed. Otherwise a dataset
    with many answers per question, like EngSAF, is mostly human and the
    model can learn the dataset instead of the writing. Val and test keep
    every human answer, since they set and measure the false-positive
    rate. Returns the capped corpus and how many answers were dropped."""
    ai_counts = corpus[corpus["label"] == AI].groupby("question_id").size()
    train_humans = corpus[(corpus["label"] == HUMAN) & (corpus["partition"] == "train")]
    dropped, without_ai = set(), 0
    for question_id, group in train_humans.groupby("question_id"):
        ids = sorted(group["answer_id"])
        limit = int(ai_counts.get(question_id, 0))
        without_ai += limit == 0
        if len(ids) > limit:
            kept = set(random.Random(f"{seed}/{question_id}").sample(ids, limit))
            dropped |= set(ids) - kept
    if without_ai:
        logger.warning("%d train questions have no ai answers, so none of their human answers are kept", without_ai)
    return corpus[~corpus["answer_id"].isin(dropped)].reset_index(drop=True), len(dropped)


def check(corpus):
    """Stop the build on anything load_splits() would reject or that would
    make the evaluation unfair."""
    problems = []
    for key in ("question_id", "question_text", "question_group"):
        spans = corpus.groupby(key)["partition"].nunique()
        if (spans > 1).any():
            problems.append(f"{key} in more than one partition: {list(spans[spans > 1].index[:3])}")
    if (corpus["answer"] == "").any():
        problems.append(f"empty answers: {list(corpus['answer_id'][corpus['answer'] == ''][:3])}")
    if not corpus["answer_id"].is_unique:
        problems.append(f"duplicate answer_id: {list(corpus['answer_id'][corpus['answer_id'].duplicated()][:3])}")
    # per dataset, so a pilot run for one dataset cannot pass as complete
    for partition in PARTITIONS:
        part = corpus[corpus["partition"] == partition]
        for dataset in sorted(set(corpus["dataset"])):
            labels = set(part.loc[part["dataset"] == dataset, "label"])
            if not labels:
                problems.append(f"{partition} has no answers from {dataset}")
            elif labels != {HUMAN, AI}:
                problems.append(f"{partition} {dataset} does not have both human and ai answers")
    if problems:
        raise SystemExit("corpus check failed:\n  " + "\n  ".join(problems))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def shown(path):
    """Path relative to the pipeline folder when it lies inside it, so a
    manifest built from pipeline paths carries no home directory."""
    path = Path(path)
    return path.relative_to(PIPELINE_DIR).as_posix() if path.is_relative_to(PIPELINE_DIR) else path.as_posix()


def build(sources, seed=SPLIT_SEED, ratios=SPLIT_RATIOS, same_question=None):
    """sources maps dataset to (cleaned human corpus, harness answers.jsonl),
    same_question maps dataset to twin id pairs. Returns the corpus, in
    load_splits() shape, and its manifest."""
    same_question = same_question or {}
    frames, question_partitions, groups, twins_used, uncovered, rewrites = [], {}, {}, {}, {}, 0
    prompt_templates = {}
    for dataset, (human_path, ai_path) in sources.items():
        humans = load_human(human_path, dataset)
        question_texts = dict(zip(humans["question_id"], humans["question_text"], strict=True))
        ais, skipped, prompt_templates[dataset] = load_ai(ai_path, dataset, question_texts)
        rewrites += skipped
        twins = [[f"{dataset}/{q}" for q in pair] for pair in same_question.get(dataset, [])]
        twins_used[dataset] = twins
        groups |= question_groups(question_texts, twins)
        question_partitions |= assign_partitions(question_texts, dataset, seed, ratios, twins)
        uncovered[dataset] = sorted(set(question_texts) - set(ais["question_id"]))
        if uncovered[dataset]:
            logger.warning("%s: %d questions have no ai answers, first %s",
                           dataset, len(uncovered[dataset]), uncovered[dataset][:3])
        frames += [humans, ais]
    corpus = pd.concat(frames, ignore_index=True)
    corpus["partition"] = corpus["question_id"].map(question_partitions)
    corpus["question_group"] = corpus["question_id"].map(groups)
    corpus["n_words"] = corpus["answer"].map(count_words)
    # the harness never asks for fewer than 3 words, so shorter answers
    # exist only on the human side and would give the label away
    short = corpus["n_words"] < MIN_WORDS
    too_short = {
        "human": int((short & (corpus["label"] == HUMAN)).sum()),
        "ai": int((short & (corpus["label"] == AI)).sum()),
    }
    corpus = corpus[~short].reset_index(drop=True)
    corpus, dropped = cap_train_humans(corpus, seed)
    check(corpus)

    # fixed row order, so the same inputs give the same rows in the same order
    corpus["order"] = corpus["partition"].map({p: i for i, p in enumerate(PARTITIONS)})
    corpus = corpus.sort_values(["order", "dataset", "question_id", "label", "answer_id"]).reset_index(drop=True)
    counts = corpus.groupby(["partition", "dataset", "label"]).size()
    manifest = {
        "seed": seed,
        "split_ratios": ratios,
        "sources": {
            dataset: {
                "human_corpus": {"path": shown(human_path), "sha256": sha256(human_path)},
                "ai_answers": {"path": shown(ai_path), "sha256": sha256(ai_path)},
            }
            for dataset, (human_path, ai_path) in sources.items()
        },
        "rows": {
            partition: {
                dataset: {"human": int(counts.get((partition, dataset, HUMAN), 0)),
                          "ai": int(counts.get((partition, dataset, AI), 0))}
                for dataset in sources
            }
            for partition in PARTITIONS
        },
        "generators": sorted(set(corpus["generator"]) - {"human"}),
        # the detector must clean submitted text the same way
        "text_cleaning": CLEANING_VERSION,
        "answers_under_min_words_dropped": too_short,
        "train_human_answers_dropped_by_cap": dropped,
        "rewrite_records_skipped": rewrites,
        "prompt_templates": prompt_templates,
        "questions_without_ai_answers": uncovered,
        "same_question": twins_used,
        # kept so the splicer can splice test questions only
        "question_partitions": dict(sorted(question_partitions.items())),
    }
    return corpus[COLUMNS], manifest


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Build a fine-tuning corpus version from cleaned and generated data.")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--datasets", nargs="+", help="build from these datasets only, default all in the config")
    args = parser.parse_args()

    config = load_config(args.config)
    names = args.datasets or list(config["datasets"])
    # a misspelt key would silently drop every twin for that dataset
    stray = sorted(set(config.get("same_question") or {}) - set(config["datasets"]))
    if stray:
        raise SystemExit(f"same_question names datasets the config does not have: {stray}")
    unknown = sorted(set(names) - set(config["datasets"]))
    if unknown:
        raise SystemExit(f"unknown datasets {unknown}, the config has {sorted(config['datasets'])}")
    sources = {}
    for name in names:
        paths = config["datasets"][name]
        human_path, ai_path = PIPELINE_DIR / paths["human_corpus"], PIPELINE_DIR / paths["ai_answers"]
        for path in (human_path, ai_path):
            if not path.exists():
                raise SystemExit(f"no file at {path}, set the {name} paths in {shown(Path(args.config))}")
        sources[name] = (human_path, ai_path)

    corpus, manifest = build(sources, same_question=config.get("same_question"))
    out_dir = PIPELINE_DIR / config["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    version = config["version"]
    if set(names) != set(config["datasets"]):
        # a partial build must never replace the full corpus of the same version
        version = f"{version}-only-{'-'.join(sorted(names))}"
    corpus.to_parquet(out_dir / f"{version}.parquet", index=False)
    manifest = {"version": version, "built_at": datetime.now(UTC).isoformat(timespec="seconds"), **manifest}
    (out_dir / f"{version}_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for partition, datasets in manifest["rows"].items():
        logger.info("%s: %s", partition, datasets)
    logger.info("Wrote %s", out_dir / f"{version}.parquet")


if __name__ == "__main__":
    main()
