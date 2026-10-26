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


SOURCES_DIR = Path(__file__).parent / "data" / "sources"


def load_questions(frames: dict[str, pd.DataFrame] | None = None, sources_dir: Path = SOURCES_DIR) -> dict[str, str]:
    """
    {question_id: question text} for the extended corpus, read from the cleaned source files because the
    splits only carry the id. Ids look like `engsaf/Q0`, `mohler/E01.Q01` and `sprag/PythonQ057`.

    With `frames` (what load_extended returns) every question id in them must have exactly one non-empty
    text; the error names the ids that do not. Without it, the whole map is returned.
    """
    sources = {}
    for name in ("engsaf", "mohler", "sprag"):
        path = Path(sources_dir) / f"{name}_cleaned.parquet"
        if not path.exists():
            raise FileNotFoundError(f"{path} not found - run `dvc pull` in ml-training/ first")
        sources[name] = pd.read_parquet(path)

    engsaf, mohler, sprag = sources["engsaf"], sources["mohler"], sources["sprag"]
    pairs = pd.concat([
        pd.DataFrame({"question_id": "engsaf/" + engsaf["question_id"].astype(str), "text": engsaf["question"]}),
        # mohler has no question column: the id is the answer id (E01.Q01.A00) without its answer part
        pd.DataFrame({"question_id": "mohler/" + mohler["id"].str.rsplit(".", n=1).str[0], "text": mohler["question"]}),
        pd.DataFrame({"question_id": "sprag/" + sprag["QuestionID"].astype(str), "text": sprag["QuestionText"]}),
    ], ignore_index=True)
    pairs["text"] = pairs["text"].astype("string").str.strip()
    pairs = pairs.dropna(subset=["text"])
    pairs = pairs[pairs["text"] != ""].drop_duplicates()

    if len(clash := pairs.groupby("question_id")["text"].nunique().loc[lambda n: n > 1]):
        raise ValueError(f"{len(clash)} question id(s) have more than one text: {list(clash.index[:5])}")
    questions = dict(zip(pairs["question_id"], pairs["text"]))

    if frames is not None:
        needed = set().union(*(set(f["question_id"]) for f in frames.values()))
        if missing := sorted(needed - set(questions)):
            raise ValueError(f"{len(missing)} question id(s) have no question text: {missing[:5]}")
    return questions


def with_question(frame: pd.DataFrame, questions: dict[str, str], sep: str) -> pd.DataFrame:
    """
    Copy of `frame` whose `answer` column reads "<question> <sep> <answer>": the text a question-aware
    model sees. Every other column is untouched, so `n_words` still counts the answer alone and the
    10-word rule means the same thing as in the answer-only runs.
    """
    if missing := sorted(set(frame["question_id"]) - set(questions)):
        raise ValueError(f"{len(missing)} question id(s) have no question text: {missing[:5]}")
    out = frame.copy()
    out["answer"] = frame["question_id"].map(questions) + f" {sep} " + frame["answer"].astype(str)
    return out


def load_corpus(name: str = "extended") -> dict[str, pd.DataFrame]:
    """`extended` is the corpus we train and evaluate on from now on; `combined` is the earlier
    v0.1 + spliced set, kept so old results can be reproduced."""
    if name == "extended":
        return load_extended()
    if name == "combined":
        return load_combined()
    raise ValueError(f"unknown corpus {name!r}; choose 'extended' or 'combined'")


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
