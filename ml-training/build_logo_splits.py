"""Build the E3 leave-one-generator-out splits: one file per AI generator, cut from v0.1.

For each generator G, data/splits/v0.1-logo-<slug>.parquet holds:

    train : every human train answer + the other five generators' train answers
    val   : every human val answer   + the other five generators' val answers
    test  : every human test answer  + G's test answers only

G never appears in train or val, so neither the weights nor the val-fitted threshold
have seen it. Partitions are v0.1's own (question-level), so train/val/test stay
question-disjoint and the human side is identical across all six folds.

Why v0.1 and not v0.1-extended: every paraphrased and simulated-edit row in the
extended corpus was rewritten by deepseek-v4-pro whatever its `generator` says, so a
DeepSeek hold-out cut from it would still train on ~2,600 DeepSeek-written texts.

Why G's val answers are not added to test: load_splits() rejects a question that spans
partitions, and those questions' human answers stay in val. Test therefore has ~86 G
answers per fold, so TPR moves in ~1.2pp steps - report it with a bootstrap CI.

    python build_logo_splits.py --dry-run     # print the folds and run the checks, write nothing
    python build_logo_splits.py               # write v0.1-logo-<slug>.parquet x6 + manifest
    python build_logo_splits.py --force       # overwrite existing outputs

Writes next to the input in data/splits/.
"""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SPLITS = Path(__file__).parent / "data" / "splits"
SOURCE = "v0.1.parquet"
VERSION = "v0.1-logo"
HUMAN = "human"

# slug is what experiments.logo() and the file name use
GENERATORS = {
    "claude-sonnet-5": "claude",
    "deepseek-v4-pro": "deepseek",
    "gemini-3-5": "gemini",
    "gpt-5.5": "gpt",
    "llama3.1-8b": "llama",
    "qwen3-8b": "qwen",
}


def build_fold(df: pd.DataFrame, held_out: str) -> pd.DataFrame:
    human = df["generator"] == HUMAN
    is_g = df["generator"] == held_out
    keep = human | (is_g & (df["partition"] == "test")) | (~is_g & (df["partition"] != "test"))
    return df[keep].sort_values(["partition", "answer_id"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

def normalise(text: pd.Series) -> pd.Series:
    return text.str.lower().map(lambda s: re.sub(r"\W+", " ", s).strip())


def check(fold: pd.DataFrame, df: pd.DataFrame, held_out: str) -> dict:
    tr, va, te = (fold[fold["partition"] == p] for p in ("train", "val", "test"))

    # the point of the fold
    assert held_out not in set(tr["generator"]) | set(va["generator"]), f"{held_out} leaked into train/val"
    assert set(te.loc[te["label"] == 1, "generator"]) == {held_out}, "test AI rows are not all the held-out generator"
    assert set(te["generator"]) == {HUMAN, held_out}

    # the loader's own contract (load_splits in trial-training.py)
    assert fold["answer_id"].is_unique, "answer_id not unique"
    spans = fold.groupby("question_id")["partition"].nunique()
    assert (spans == 1).all(), f"{int((spans > 1).sum())} question(s) span partitions"
    assert set(fold["partition"]) == {"train", "val", "test"}
    assert (fold["label"] == (fold["generator"] != HUMAN).astype(int)).all(), "label disagrees with generator"
    assert fold["answer"].str.strip().str.len().gt(0).all(), "empty answer"

    # nothing moved: every row keeps v0.1's partition, and nothing but G's train/val rows
    # and the other generators' test rows was dropped
    src = df.set_index("answer_id")
    assert (fold["partition"].values == src.loc[fold["answer_id"], "partition"].values).all()
    dropped = df[~df["answer_id"].isin(fold["answer_id"])]
    expected = df[((df["generator"] == held_out) & (df["partition"] != "test"))
                  | ((df["generator"] != held_out) & (df["generator"] != HUMAN) & (df["partition"] == "test"))]
    assert set(dropped["answer_id"]) == set(expected["answer_id"])

    # verbatim (case/punctuation-insensitive) text reuse across the train|val / test boundary
    seen = set(normalise(pd.concat([tr["answer"], va["answer"]])))
    dup = normalise(te["answer"]).isin(seen)
    return {
        "test_texts_also_in_train_or_val": int(dup.sum()),
        "test_ai_texts_also_in_train_or_val": int((dup & (te["label"] == 1)).sum()),
    }


def summarise(part: pd.DataFrame) -> dict:
    return {"rows": int(len(part)), "questions": int(part["question_id"].nunique()),
            "human": int((part["label"] == 0).sum()), "ai": int((part["label"] == 1).sum()),
            "ai_per_generator": part[part["label"] == 1]["generator"].value_counts().sort_index().to_dict(),
            "ai_per_dataset": part[part["label"] == 1]["dataset"].value_counts().sort_index().to_dict()}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the folds and run the checks, write nothing")
    ap.add_argument("--force", action="store_true", help="overwrite existing outputs")
    args = ap.parse_args()

    path = SPLITS / SOURCE
    if not path.exists():
        raise FileNotFoundError(f"missing {path} - run `dvc pull` in ml-training/ first")
    df = pd.read_parquet(path)

    found = set(df["generator"]) - {HUMAN}
    assert found == set(GENERATORS), f"generators in {SOURCE} are {sorted(found)}, expected {sorted(GENERATORS)}"

    folds, report = {}, {}
    for generator, slug in GENERATORS.items():
        fold = build_fold(df, generator)
        reuse = check(fold, df, generator)
        folds[slug] = fold
        report[slug] = {"held_out": generator, "file": f"{VERSION}-{slug}.parquet"} | reuse | {
            p: summarise(fold[fold["partition"] == p]) for p in ("train", "val", "test")}

    # every fold shares the same human rows, so differences between folds are the generator alone
    humans = {slug: frozenset(f.loc[f["label"] == 0, "answer_id"]) for slug, f in folds.items()}
    assert len(set(humans.values())) == 1, "human rows differ between folds"

    manifest = {
        "version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"file": SOURCE, "rows": int(len(df)), "sha256": sha256(path)},
        "rule": "per held-out generator G: train/val = human + other five generators in v0.1's train/val; "
                "test = human test + G's test rows. v0.1 partitions unchanged.",
        "folds": report,
        "notes": [
            "cut from v0.1, not v0.1-extended: the extended corpus's paraphrased and simulated-edit rows were all "
            "rewritten by deepseek-v4-pro, which would leak DeepSeek text into every fold's training data.",
            "G's val-partition answers are dropped rather than moved to test, because their questions' human "
            "answers stay in val and load_splits() rejects a question spanning partitions.",
            "test_texts_also_in_train_or_val counts verbatim matches after lower-casing and stripping punctuation.",
        ],
    }

    rows = [{"fold": s, "held_out": r["held_out"], **{f"{p}_h/ai": f"{r[p]['human']}/{r[p]['ai']}"
             for p in ("train", "val", "test")}, "verbatim_reuse": r["test_texts_also_in_train_or_val"]}
            for s, r in report.items()]
    print(pd.DataFrame(rows).to_string(index=False))
    print("\nall checks passed")
    if args.dry_run:
        print("(dry run: nothing written)")
        return

    outs = {slug: SPLITS / f"{VERSION}-{slug}.parquet" for slug in folds}
    outs["manifest"] = SPLITS / f"{VERSION}_manifest.json"
    if not args.force and any(p.exists() for p in outs.values()):
        raise SystemExit(f"outputs already exist in {SPLITS}; use --force to overwrite")
    for slug, fold in folds.items():
        fold.to_parquet(outs[slug], index=False)
    outs["manifest"].write_text(json.dumps(manifest, indent=2, default=int))
    print("\nwrote:", *[str(p.relative_to(Path(__file__).parent)) for p in outs.values()], sep="\n  ")


if __name__ == "__main__":
    main()
