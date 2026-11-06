"""
Combined corpus loader: v0.1 raw answers + spliced answers, one table.

load_splits() in trial-training.py reads only the corpus version, and the
spliced file holds label-1 rows only, so neither alone is the training or
evaluation set we want. This appends the spliced rows to their own
partition and tags every row with a `slice` so results can be reported
per slice:

    human        student answers (label 0) - the FPR comes from these
    raw-ai       fully AI answers from the corpus (label 1)
    spliced-25   student answers with ~25% of the words replaced by AI
    spliced-50   ... ~50%
    spliced-75   ... ~75%

    from combined_data import load_combined
    frames = load_combined()          # {"train": df, "val": df, "test": df}

Both files are DVC-tracked; run `dvc pull` in ml-training/ first.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data" / "splits"
CORPUS_PATH = DATA_DIR / "v0.1.parquet"
SPLICED_PATH = DATA_DIR / "v0.1-spliced.parquet"
PARTITIONS = ("train", "val", "test")

# columns both files share (the load_splits() contract plus dataset/tier)
KEEP = ["answer", "label", "partition", "question_id", "answer_id",
        "generator", "n_words", "dataset", "tier"]
SPLICED_BANDS = ("spliced-25", "spliced-50", "spliced-75")


def load_combined(
    corpus_path: Path = CORPUS_PATH,
    spliced_path: Path = SPLICED_PATH,
    include_spliced: bool = True,
) -> dict[str, pd.DataFrame]:
    for p in (corpus_path, spliced_path) if include_spliced else (corpus_path,):
        if not Path(p).exists():
            raise FileNotFoundError(f"{p} not found - run `dvc pull` in ml-training/ first")

    corpus = pd.read_parquet(corpus_path)
    corpus = corpus.assign(
        slice=corpus["label"].map({0: "human", 1: "raw-ai"}),
        ai_fraction=corpus["label"].astype(float),
    )[KEEP + ["slice", "ai_fraction"]]

    parts = [corpus]
    if include_spliced:
        spliced = pd.read_parquet(spliced_path)
        if bad := set(spliced["style"]) - set(SPLICED_BANDS):
            raise ValueError(f"unexpected spliced styles: {sorted(bad)}")
        if (spliced["label"] != 1).any():
            raise ValueError("spliced file should be label 1 only")
        spliced = spliced.assign(slice=spliced["style"])[KEEP + ["slice", "ai_fraction"]]
        parts.append(spliced)

    df = pd.concat(parts, ignore_index=True)

    if not df["answer_id"].is_unique:
        raise ValueError("answer_id is not unique after combining")

    # a question in two partitions lets the model learn topic, not authorship
    spans = df.groupby("question_id")["partition"].nunique()
    if len(leaked := spans[spans > 1]):
        raise ValueError(f"{len(leaked)} question(s) span partitions: {list(leaked.index[:5])}")

    frames = {p: g.reset_index(drop=True) for p, g in df.groupby("partition")}
    if set(frames) != set(PARTITIONS):
        raise ValueError(f"expected {PARTITIONS}, found {sorted(frames)}")
    return frames


EXTENDED = "v0.1-extended"


def load_extended(corpus: str = EXTENDED, data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    """
    The extended corpus written by build_extended_corpus.py: v0.1 + spliced + paraphrased +
    human-edited answers. Same shape as load_combined(): {"train": df, "val": df, "test": df}.

    train is balanced 1:1 (all human answers plus an equal number of AI answers); val and test hold
    every row. Every row has a `slice` (human, raw-ai, spliced-25/50/75, paraphrased-light/heavy,
    edited-genuine/simulated) and `core`, which is True for the original combined set, so
    `frames["test"][frames["test"]["core"]]` is the old 2,281-answer test set.
    """
    frames = {}
    for part in PARTITIONS:
        path = Path(data_dir) / f"{corpus}-{part}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"{path} not found - run `dvc pull` in ml-training/ first")
        frame = pd.read_parquet(path).reset_index(drop=True)
        if (frame["partition"] != part).any():
            raise ValueError(f"{path.name} holds rows from another partition")
        frames[part] = frame

    everything = pd.concat(frames.values(), ignore_index=True)
    if not everything["answer_id"].is_unique:
        raise ValueError("answer_id is not unique across train, val and test")
    spans = everything.groupby("question_id")["partition"].nunique()
    if len(leaked := spans[spans > 1]):
        raise ValueError(f"{len(leaked)} question(s) span partitions: {list(leaked.index[:5])}")
    return frames


def load_corpus(name: str = "extended") -> dict[str, pd.DataFrame]:
    """`extended` is the corpus we train and evaluate on from now on; `combined` is the earlier
    v0.1 + spliced set, kept so old results can be reproduced."""
    if name == "extended":
        return load_extended()
    if name == "combined":
        return load_combined()
    raise ValueError(f"unknown corpus {name!r}; choose 'extended' or 'combined'")


def parse_weights(spec: str) -> list[tuple[list[tuple[str, str]], float]]:
    """
    Parses a --weights spec into rules. Rules are comma-separated; each is conditions joined by &,
    a colon, then the weight. A condition is column=value, and the value may use * and ? wildcards:

        "slice=spliced-*:2,slice=paraphrased-heavy:2,dataset=mohler&slice=human:2"

    returns [([(column, pattern), ...], weight), ...]; an empty spec gives no rules
    """
    rules = []
    for item in (s.strip() for s in spec.split(",")):
        if not item:
            continue
        conditions, sep, weight = item.rpartition(":")
        if not sep or not conditions:
            raise ValueError(f"weight rule {item!r} needs the form column=value[&column=value]:weight")
        parsed = []
        for condition in conditions.split("&"):
            column, eq, pattern = condition.partition("=")
            if not eq or not column or not pattern:
                raise ValueError(f"condition {condition!r} in {item!r} needs the form column=value")
            parsed.append((column.strip(), pattern.strip()))
        if (w := float(weight)) <= 0:
            raise ValueError(f"weight in {item!r} must be positive")
        rules.append((parsed, w))
    return rules


def row_weights(frame: pd.DataFrame, spec: str) -> np.ndarray:
    """
    Per-row loss weights for training, from a --weights spec (see parse_weights). A row matching
    several rules gets the product of their weights. Each label's weights are then rescaled to
    average 1, so the classes stay balanced and the loss keeps its scale: upweighting spliced AI
    answers takes weight from the other AI answers, never from the human ones.

    raises ValueError on an unknown column or a rule that matches no row (almost always a typo,
    which would otherwise train silently with no weighting)
    returns one weight per row of `frame`, in order
    """
    from fnmatch import fnmatchcase

    weights = np.ones(len(frame))
    for conditions, weight in parse_weights(spec):
        mask = np.ones(len(frame), dtype=bool)
        for column, pattern in conditions:
            if column not in frame.columns:
                raise ValueError(f"weight rule names column {column!r}, which the training data does not have")
            mask &= frame[column].astype(str).map(lambda v: fnmatchcase(v, pattern)).to_numpy()
        if not mask.any():
            raise ValueError(f"weight rule {conditions} matches no training row")
        weights[mask] *= weight
    labels = frame["label"].to_numpy()
    for label in np.unique(labels):
        weights[labels == label] /= weights[labels == label].mean()
    return weights


def slice_flag_rates(frame: pd.DataFrame, probs, threshold: float) -> list[dict]:
    """
    Share of each slice flagged as AI at the frozen threshold. For `human`
    that is the false-positive rate; for every AI slice it is the TPR.
    Rows with a NaN score (answers a model could not score) are skipped.
    """
    probs = np.asarray(probs, dtype=float)
    keep = ~np.isnan(probs)
    frame, probs = frame[keep], probs[keep]
    rows = []
    for sl, group in frame.groupby("slice"):
        flagged = probs[frame.index.get_indexer(group.index)] >= threshold
        rows.append({"slice": sl, "n": len(group), "flag_rate": float(flagged.mean()),
                     "kind": "FPR" if sl == "human" else "TPR"})
    return sorted(rows, key=lambda r: (r["slice"] != "human", r["slice"]))


def describe(frames: dict[str, pd.DataFrame]) -> None:
    for name in PARTITIONS:
        f = frames[name]
        print(f"{name}: {len(f)} rows")
        for sl, n in f["slice"].value_counts().sort_index().items():
            print(f"    {sl:<11} {n}")


if __name__ == "__main__":
    describe(load_combined())
