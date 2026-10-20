"""Build the extended fine-tuning corpus: v0.1 + spliced + paraphrased + human-edited.

Training set  : every human answer in the train partition, plus an equal number of AI answers
                (1:1). Half of the AI answers are raw AI answers; the other half is split evenly
                between spliced, paraphrased and human-edited answers.
Val and test  : every row from all four sets, not downsampled. FPR and TPR do not depend on the
                class mix, and val/test must keep all human answers (corpus build, 3.2.2.7).
                The 10-word minimum is NOT applied here: it is applied at evaluation time
                (n_words is kept), so the data version and the splits stay unchanged.

    python build_extended_corpus.py --dry-run     # print the plan and the checks, write nothing
    python build_extended_corpus.py               # write v0.1-extended-{train,val,test}.parquet + manifest
    python build_extended_corpus.py --force       # overwrite existing outputs

Writes next to the inputs in data/splits/.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SPLITS = Path(__file__).parent / "data" / "splits"
FILES = {
    "base": "v0.1.parquet",
    "spliced": "v0.1-spliced.parquet",
    "paraphrased": "v0.1-paraphrased.parquet",
    "edited": "v0.1-human_edited.parquet",
}
VERSION = "v0.1-extended"
SEED = 42
RAW_SHARE = 0.5  # share of the AI side that is raw AI answers; the rest is split evenly

COLUMNS = ["answer_id", "question_id", "answer", "label", "partition", "dataset", "generator", "tier",
           "n_words", "slice", "core", "source_answer_id", "rewriter"]


# --------------------------------------------------------------------------
# loading and tagging
# --------------------------------------------------------------------------

def load_all() -> dict[str, pd.DataFrame]:
    missing = [f for f in FILES.values() if not (SPLITS / f).exists()]
    if missing:
        raise FileNotFoundError(f"missing in {SPLITS}: {missing} - run `dvc pull` in ml-training/ first")
    return {name: pd.read_parquet(SPLITS / f) for name, f in FILES.items()}


def tag(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One table with a common set of columns. `slice` names match combined_data.py."""
    b, s, p, e = frames["base"], frames["spliced"], frames["paraphrased"], frames["edited"]
    b = b.assign(slice=np.where(b["label"] == 0, "human", "raw-ai"), core=True,
                 source_answer_id=None, rewriter=None)
    # for spliced answers the "source" is the AI donor answer the sentences were taken from
    s = s.assign(slice=s["style"], core=True, source_answer_id=s["ai_answer_id"], rewriter=None)
    p = p.assign(slice=p["style"], core=False, rewriter=p["paraphraser"])
    e = e.assign(slice=e["style"].str.replace("human_edited-", "edited-", regex=False), core=False,
                 rewriter=np.where(e["edit_source"] == "genuine", "human", "deepseek-v4-pro"))
    return pd.concat([x[COLUMNS] for x in (b, s, p, e)], ignore_index=True)


# --------------------------------------------------------------------------
# sampling helpers (all deterministic given the seed)
# --------------------------------------------------------------------------

def allocate(sizes: pd.Series, n: int) -> pd.Series:
    """Split n across groups in proportion to `sizes` (largest remainder), never above a group's size."""
    n = min(int(n), int(sizes.sum()))
    exact = sizes / sizes.sum() * n
    take = np.floor(exact).astype(int)
    for key in (exact - take).sort_values(ascending=False, kind="stable").index[: n - int(take.sum())]:
        take[key] += 1
    take = np.minimum(take, sizes)
    short = n - int(take.sum())
    while short > 0:
        room = (sizes - take)[(sizes - take) > 0]
        if room.empty:
            break
        take[room.index[0]] += 1
        short -= 1
    return take


def sample(pool: pd.DataFrame, n: int, by: list[str], rng: np.random.Generator) -> pd.DataFrame:
    """n rows from `pool`, spread over the strata in `by` in proportion to their size."""
    if n <= 0 or pool.empty:
        return pool.iloc[0:0]
    pool = pool.sort_values("answer_id").assign(_s=lambda d: d[by].astype(str).agg("|".join, axis=1))
    counts = allocate(pool.groupby("_s").size(), n)
    parts = [g.sample(n=int(counts[k]), random_state=int(rng.integers(2**31)))
             for k, g in pool.groupby("_s") if counts[k] > 0]
    return pd.concat(parts).drop(columns="_s")


def split_evenly(total: int, keys: list[str]) -> dict[str, int]:
    base, extra = divmod(total, len(keys))
    return {k: base + (1 if i < extra else 0) for i, k in enumerate(keys)}


# --------------------------------------------------------------------------
# the balanced training set
# --------------------------------------------------------------------------

def build_train(all_rows: pd.DataFrame, rng: np.random.Generator):
    tr = all_rows[all_rows["partition"] == "train"]
    humans = tr[tr["slice"] == "human"]
    n_ai = len(humans)
    n_raw = int(round(n_ai * RAW_SHARE))
    n_each = split_evenly(n_ai - n_raw, ["spliced", "paraphrased", "edited"])

    used: set[str] = set()
    notes = {}

    def fresh(pool):
        return pool[~pool["source_answer_id"].isin(used)] if pool["source_answer_id"].notna().any() else pool

    # 1. spliced: equal across the three bands, spread over generators
    sp = tr[tr["slice"].isin(["spliced-25", "spliced-50", "spliced-75"])]
    picks = []
    for band, k in split_evenly(n_each["spliced"], ["spliced-25", "spliced-50", "spliced-75"]).items():
        picks.append(sample(fresh(sp[sp["slice"] == band]), k, ["generator", "dataset"], rng))
    spliced = pd.concat(picks)
    used |= set(spliced["source_answer_id"])

    # 2. human-edited: every genuine edit in train, the rest simulated
    ed = tr[tr["slice"].isin(["edited-genuine", "edited-simulated"])]
    genuine = ed[ed["slice"] == "edited-genuine"].head(n_each["edited"])
    simulated = sample(fresh(ed[ed["slice"] == "edited-simulated"]), n_each["edited"] - len(genuine),
                       ["generator", "dataset"], rng)
    edited = pd.concat([genuine, simulated])
    used |= set(edited["source_answer_id"])

    # 3. paraphrased: half light, half heavy, one rewrite per source answer
    pa = tr[tr["slice"].isin(["paraphrased-light", "paraphrased-heavy"])]
    picks = []
    for style, k in split_evenly(n_each["paraphrased"], ["paraphrased-light", "paraphrased-heavy"]).items():
        got = sample(fresh(pa[pa["slice"] == style]), k, ["generator", "dataset"], rng)
        used |= set(got["source_answer_id"])
        picks.append(got)
    paraphrased = pd.concat(picks)

    # 4. raw AI: avoid answers already used as a donor or a rewrite source
    raw_pool = tr[tr["slice"] == "raw-ai"]
    clean = raw_pool[~raw_pool["answer_id"].isin(used)]
    fallback = max(0, n_raw - len(clean))
    raw = sample(clean if fallback == 0 else raw_pool, n_raw, ["dataset", "generator"], rng)
    notes["raw_overlap_fallback"] = int(fallback)
    notes["raw_that_are_also_a_source"] = int(raw["answer_id"].isin(used).sum())

    train = pd.concat([humans, raw, spliced, paraphrased, edited]).sort_values("answer_id").reset_index(drop=True)
    return train, notes


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

def check(train, val, test, all_rows, frames):
    ids = pd.concat([train["answer_id"], val["answer_id"], test["answer_id"]])
    assert ids.is_unique, "an answer_id appears in more than one output split"
    assert all_rows["answer_id"].is_unique, "answer_id not unique across the input files"

    q = pd.concat([train, val, test]).groupby("question_id")["partition"].nunique()
    assert (q == 1).all(), f"{int((q > 1).sum())} question(s) span partitions"

    part = frames["base"].set_index("answer_id")["partition"]
    for name in ("paraphrased", "edited"):
        f = frames[name]
        assert (f["source_answer_id"].map(part) == f["partition"]).all(), f"{name}: a rewrite left its source's partition"

    assert (train["label"] == 0).sum() == (train["label"] == 1).sum(), "train is not 1:1"
    core_val, core_test = int(val["core"].sum()), int(test["core"].sum())
    assert (core_val, core_test) == (1519, 2281), f"core val/test are {core_val}/{core_test}, expected 1519/2281"
    assert (train["label"].isin([0, 1])).all() and train["answer"].str.len().gt(0).all()


def summarise(df: pd.DataFrame) -> dict:
    return {"rows": int(len(df)), "human": int((df["label"] == 0).sum()), "ai": int((df["label"] == 1).sum()),
            "per_slice": df["slice"].value_counts().sort_index().to_dict(),
            "per_dataset": df["dataset"].value_counts().sort_index().to_dict(),
            "ai_per_generator": df[df["label"] == 1]["generator"].value_counts().sort_index().to_dict(),
            "min_n_words": int(df["n_words"].min()), "share_under_10_words": round(float((df["n_words"] < 10).mean()), 4)}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the plan and run the checks, write nothing")
    ap.add_argument("--force", action="store_true", help="overwrite existing outputs")
    args = ap.parse_args()

    frames = load_all()
    all_rows = tag(frames)
    rng = np.random.default_rng(SEED)
    train, notes = build_train(all_rows, rng)
    val = all_rows[all_rows["partition"] == "val"].sort_values("answer_id").reset_index(drop=True)
    test = all_rows[all_rows["partition"] == "test"].sort_values("answer_id").reset_index(drop=True)
    check(train, val, test, all_rows, frames)

    manifest = {
        "version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": SEED, "raw_share_of_ai": RAW_SHARE,
        "rule": "train: all human + equal number of AI (50% raw, rest evenly spliced/paraphrased/human-edited), "
                "stratified by dataset/generator; val and test keep every row; 10-word minimum applied at evaluation",
        "inputs": {k: {"file": v, "rows": int(len(frames[k])), "sha256": sha256(SPLITS / v)} for k, v in FILES.items()},
        "train": summarise(train) | notes, "val": summarise(val), "test": summarise(test),
        "core_rows": {"val": int(val["core"].sum()), "test": int(test["core"].sum())},
        "notes": [
            "core=True marks the original combined set (v0.1 + spliced); filtering on it recovers val 1,519 / test 2,281.",
            "spliced rows: source_answer_id is the AI donor answer; paraphrased/edited rows: the AI answer that was rewritten.",
            "rewriter: deepseek-v4-pro for paraphrased and simulated edits, human for genuine edits - needed for "
            "leave-one-generator-out runs that hold out DeepSeek.",
            "human-edited answers all come from Mohler (the genuine edits were made on Mohler answers only).",
        ],
    }

    print(json.dumps({k: manifest[k] for k in ("train", "val", "test", "core_rows")}, indent=2, default=int))
    if args.dry_run:
        print("\n(dry run: nothing written)")
        return

    outs = {s: SPLITS / f"{VERSION}-{s}.parquet" for s in ("train", "val", "test")}
    outs["manifest"] = SPLITS / f"{VERSION}_manifest.json"
    if not args.force and any(p.exists() for p in outs.values()):
        raise SystemExit(f"outputs already exist in {SPLITS}; use --force to overwrite")
    for split, df in (("train", train), ("val", val), ("test", test)):
        df.to_parquet(outs[split], index=False)
    outs["manifest"].write_text(json.dumps(manifest, indent=2, default=int))
    print("\nwrote:", *[str(p.relative_to(Path(__file__).parent)) for p in outs.values()], sep="\n  ")


if __name__ == "__main__":
    main()
