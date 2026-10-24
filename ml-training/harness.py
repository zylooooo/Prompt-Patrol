"""Turn saved per-answer scores into the metrics we compare models and runs on.

Reads per-answer scores files (see scores.py), joins n_words, slice, dataset and generator from
the extended corpus by answer_id, and evaluates with the project protocol:

  1. keep the rows with n_words >= min_words, in BOTH validation and test (the app never
     scores shorter answers, so the threshold is fitted on the answers it will be used on),
  2. fit the 1% FPR threshold on the validation scores and freeze it,
  3. score the test split once, with confidence intervals that resample whole questions.

The scores file itself is never filtered: save every val and test row, filter here. Metric
functions live in metrics.py; this module only wires them together. It never retrains anything.

Names
  run     one training + scoring: one scores file, one MLflow run_id, one seed
  seed    the training seed of that run (the `seed` column). NOT the bootstrap_seed argument,
          which only makes the confidence intervals reproducible
  model   the setting being compared, the `model` column: <family>-<method>[-variant], e.g.
          desklib-untouched, desklib-lora, desklib-dora, desklib-lora-question. A model has one
          run per seed.

    import harness
    df = harness.load_runs(["outputs/desklib-lora-s1_scores.parquet",
                            "outputs/desklib-lora-s2_scores.parquet",
                            "outputs/meld-lora-s1_scores.parquet"])
    table = harness.compare_models(df)          # one row per run and filter (all / >= 10 words)
    summary = harness.aggregate_seeds(table)    # one row per model: mean and spread over seeds
    harness.compare_pair(df, "desklib-lora", "desklib-dora")   # is the gap real?
    harness.write_results("results", runs=table, seeds_summary=summary)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import metrics
from scores import load_scores

SPLITS_DIR = Path(__file__).parent / "data" / "splits"
CORPUS = "v0.1-extended"
MIN_WORDS = 10
MIN_SEEDS = 3  # fewer runs of a model than this is flagged in compare_pair
META_COLUMNS = ["answer_id", "partition", "label", "n_words", "slice", "dataset", "generator", "core"]

HEADLINE_COLUMNS = [
    "run_id", "seed", "model", "min_words", "n_test", "share_test_excluded", "threshold",
    "deployed_tpr", "deployed_tpr_ci_low", "deployed_tpr_ci_high",
    "deployed_fpr", "deployed_fpr_ci_low", "deployed_fpr_ci_high",
    # TPR if the threshold were set on test to hit exactly 1% FPR: an equal-FPR number for
    # comparing models whose frozen thresholds landed at different FPRs. Optimistic as a promise.
    "oracle_tpr_at_fpr_0.01", "oracle_tpr_at_fpr_0.01_ci_low", "oracle_tpr_at_fpr_0.01_ci_high",
    "auroc", "auroc_ci_low", "auroc_ci_high", "ece", "brier", "precision",
]
SEED_SUMMARY_METRICS = ("deployed_tpr", "deployed_fpr", "oracle_tpr_at_fpr_0.01", "auroc", "ece", "brier")

# metrics comparable between two models with compare_pair: name -> fn(y_true, y_prob, threshold)
PAIR_METRICS = {
    "deployed_tpr": lambda y, p, t: metrics.operating_point_metrics(y, p, t)["recall"],
    "deployed_fpr": lambda y, p, t: metrics.operating_point_metrics(y, p, t)["fpr"],
    "oracle_tpr_at_fpr_0.01": lambda y, p, t: metrics.oracle_tpr_at_fpr(y, p, metrics.HEADLINE_FPR),
    "auroc": lambda y, p, t: float(metrics.roc_auc_score(y, p)),
}


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def load_meta(corpus: str = CORPUS, splits_dir: Path | str = SPLITS_DIR) -> pd.DataFrame:
    """Validation and test rows of the corpus, with the columns the scores file leaves out."""
    parts = [pd.read_parquet(Path(splits_dir) / f"{corpus}-{split}.parquet", columns=META_COLUMNS)
             for split in ("val", "test")]
    meta = pd.concat(parts, ignore_index=True)
    if not meta["answer_id"].is_unique:
        raise ValueError(f"{corpus}: answer_id is not unique across val and test")
    return meta


def attach_meta(scores: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Join corpus columns onto a scores table by answer_id, checking that the two agree."""
    merged = scores.merge(meta, on="answer_id", how="left", validate="many_to_one")

    unmatched = merged["partition"].isna()
    if unmatched.any():
        sample = merged.loc[unmatched, "answer_id"].head(3).tolist()
        raise ValueError(f"{int(unmatched.sum())} scores rows are not in the corpus val/test files, e.g. {sample}")
    if (merged["split"] != merged["partition"]).any():
        raise ValueError("split in the scores file disagrees with the corpus partition")
    if (merged["y_true"] != merged["label"]).any():
        raise ValueError("y_true in the scores file disagrees with the corpus label")
    return merged.drop(columns=["partition", "label"])


def load_run(path: Path | str, corpus: str = CORPUS, splits_dir: Path | str = SPLITS_DIR) -> pd.DataFrame:
    """One scores file, validated by scores.py, with the corpus columns attached."""
    return attach_meta(load_scores(path), load_meta(corpus, splits_dir))


def load_runs(paths, corpus: str = CORPUS, splits_dir: Path | str = SPLITS_DIR) -> pd.DataFrame:
    """Several scores files (runs, seeds, models) in one table, ready for compare_models."""
    meta = load_meta(corpus, splits_dir)
    df = pd.concat([attach_meta(load_scores(p), meta) for p in paths], ignore_index=True)
    if df.duplicated(["run_id", "model", "split", "answer_id"]).any():
        raise ValueError("the same run_id and model appear twice (a file loaded twice, or two files from one run)")
    return df


# --------------------------------------------------------------------------
# selecting rows
# --------------------------------------------------------------------------

def _select(df: pd.DataFrame, model: str, run_id: str | None = None) -> pd.DataFrame:
    """The rows of ONE run of a model. Refuses to pool several runs (seeds) silently."""
    d = df[df["model"] == model]
    if d.empty:
        raise ValueError(f"no rows for model {model!r}")
    if run_id is None:
        ids = sorted(d["run_id"].unique())
        if len(ids) > 1:
            raise ValueError(f"{model!r} appears in more than one run ({ids}); pass run_id=... "
                             f"or use compare_models, which evaluates each run")
        return d
    d = d[d["run_id"] == run_id]
    if d.empty:
        raise ValueError(f"no rows for model {model!r} in run {run_id!r}")
    return d


def _rows(d: pd.DataFrame, split: str, min_words: int | None) -> pd.DataFrame:
    rows = d[d["split"] == split]
    return rows[rows["n_words"] >= min_words] if min_words else rows


def _frozen_threshold(d: pd.DataFrame, min_words: int | None, fpr: float = metrics.HEADLINE_FPR) -> float:
    val = _rows(d, "val", min_words)
    return metrics.threshold_at_fpr(val["y_true"], val["y_prob"], fpr)


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------

def evaluate_model(df: pd.DataFrame, model: str, min_words: int | None = MIN_WORDS, run_id: str | None = None,
                   target_fprs=metrics.TARGET_FPRS, bootstrap_n: int = metrics.BOOTSTRAP_N,
                   bootstrap_seed: int = 42) -> dict:
    """The full metric set for one run of a model: threshold fitted on val, frozen, scored once on test.

    `min_words=None` keeps every answer. Alongside the metrics it returns how many answers the
    filter removed, and how many human validation answers each threshold rests on (a threshold
    at FPR f lets through only n_human * f of them, so very strict levels rest on very few).
    `bootstrap_seed` only makes the confidence intervals reproducible; it is not the training seed.
    """
    d = _select(df, model, run_id)
    val = _rows(d, "val", min_words)
    test = _rows(d, "test", min_words)
    n_human_val = int((val["y_true"] == 0).sum())
    if test.empty or n_human_val == 0:
        raise ValueError(f"{model}: need human validation rows and test rows (min_words={min_words})")

    threshold = metrics.threshold_at_fpr(val["y_true"], val["y_prob"], metrics.HEADLINE_FPR)
    out = metrics.evaluate(
        test["y_true"], test["y_prob"], threshold,
        target_fprs=target_fprs, bootstrap_n=bootstrap_n, seed=bootstrap_seed,
        groups=test["question_id"].to_numpy(),
    )

    n_test_all = int((d["split"] == "test").sum())
    out |= {
        "run_id": d["run_id"].iloc[0],
        "seed": int(d["seed"].iloc[0]),
        "model": model,
        "min_words": min_words or 0,
        "n_val": len(val),
        "n_human_val": n_human_val,
        "n_test": len(test),
        "n_test_questions": int(test["question_id"].nunique()),
        "share_test_excluded": 1.0 - len(test) / n_test_all,
    }
    for fpr in target_fprs:
        out[f"threshold_at_fpr_{fpr:g}"] = metrics.threshold_at_fpr(val["y_true"], val["y_prob"], fpr)
        out[f"val_human_errors_allowed_{fpr:g}"] = n_human_val * fpr
    return out


def validation_table(df: pd.DataFrame, min_words: int | None = MIN_WORDS, models=None,
                     fpr: float = metrics.HEADLINE_FPR) -> pd.DataFrame:
    """One row per run, from the VALIDATION rows only: for choosing a setting without touching test.

    `val_auroc` is threshold-free. `val_tpr` / `val_fpr` are at the threshold fitted on these same
    val rows at `fpr`, so val_tpr is in-sample (a ranking aid, not a result to report). Rank a
    sweep by val_auroc and use val_tpr as a check, since the goal is TPR at a low FPR.
    """
    runs = df[["model", "run_id", "seed"]].drop_duplicates().sort_values(["model", "seed", "run_id"])
    if models is not None:
        runs = runs[runs["model"].isin(list(models))]
    rows = []
    for r in runs.itertuples(index=False):
        d = _select(df, r.model, r.run_id)
        val = _rows(d, "val", min_words)
        op = metrics.operating_point_metrics(val["y_true"], val["y_prob"], _frozen_threshold(d, min_words, fpr))
        rows.append({"model": r.model, "run_id": r.run_id, "seed": r.seed, "min_words": min_words or 0,
                     "n_val": len(val), "val_auroc": metrics.ranking_metrics(val["y_true"], val["y_prob"])["auroc"],
                     "val_tpr": op["recall"], "val_fpr": op["fpr"]})
    return pd.DataFrame(rows)


def compare_models(df: pd.DataFrame, models=None, min_words=(None, MIN_WORDS), **kwargs) -> pd.DataFrame:
    """One row per run and filter, for the comparison table. Each run has its own frozen threshold."""
    runs = df[["model", "run_id", "seed"]].drop_duplicates().sort_values(["model", "seed", "run_id"])
    if models is not None:
        runs = runs[runs["model"].isin(list(models))]
    rows = [evaluate_model(df, r.model, mw, run_id=r.run_id, **kwargs)
            for r in runs.itertuples(index=False) for mw in min_words]
    return pd.DataFrame(rows)[HEADLINE_COLUMNS]


def aggregate_seeds(table: pd.DataFrame, columns=SEED_SUMMARY_METRICS) -> pd.DataFrame:
    """One row per model and filter: how many runs, and the mean and spread of each metric over them.

    Report this, not a single run: the spread is how much the result moves by luck alone. The std
    is NaN when a model has only one run.
    """
    spec = {"n_runs": ("run_id", "nunique")}
    for col in columns:
        spec[f"{col}_mean"] = (col, "mean")
        spec[f"{col}_std"] = (col, "std")
    spec["deployed_tpr_min"] = ("deployed_tpr", "min")
    spec["deployed_tpr_max"] = ("deployed_tpr", "max")
    return table.groupby(["model", "min_words"]).agg(**spec).reset_index()


def compare_pair(df: pd.DataFrame, model_a: str, model_b: str, min_words: int | None = MIN_WORDS,
                 metric: str = "deployed_tpr", bootstrap_n: int = metrics.BOOTSTRAP_N,
                 bootstrap_seed: int = 42) -> dict:
    """Is model A really different from model B on `metric`? Difference A - B with a CI.

    Every run of each model is used, so the two models may have different numbers of runs and
    different seed numbers (5 runs of one against 3 of the other is fine). Both models are
    resampled on the same questions in every bootstrap draw, and the metric is averaged over each
    model's own runs before the difference is taken. If the interval contains 0, the gap is not
    distinguishable from noise. The interval covers which questions were drawn, not training
    luck: check the gap against the seed spread in aggregate_seeds too. To compare many models,
    compare each one against a single reference model.
    """
    if metric not in PAIR_METRICS:
        raise ValueError(f"metric must be one of {sorted(PAIR_METRICS)}")

    run_ids = {}
    for model in (model_a, model_b):
        run_ids[model] = list(df.loc[df["model"] == model, "run_id"].drop_duplicates())
        if not run_ids[model]:
            raise ValueError(f"no runs of {model!r} in the scores")

    y_true = groups = None
    probs = {"a": [], "b": []}
    thresholds = {"a": [], "b": []}
    for side, model in (("a", model_a), ("b", model_b)):
        for run_id in run_ids[model]:
            d = _select(df, model, run_id)
            test = _rows(d, "test", min_words).sort_values("answer_id").reset_index(drop=True)
            if y_true is None:
                y_true, groups, ids = test["y_true"].to_numpy(), test["question_id"].to_numpy(), test["answer_id"]
            elif not test["answer_id"].equals(ids):
                raise ValueError("the models were not scored on the same test answers")
            probs[side].append(test["y_prob"].to_numpy())
            thresholds[side].append(_frozen_threshold(d, min_words))

    out = metrics.paired_bootstrap_diff(
        y_true, probs["a"], probs["b"], thresholds["a"], thresholds["b"], groups, PAIR_METRICS[metric],
        n=bootstrap_n, seed=bootstrap_seed,
    )
    n_a, n_b = len(run_ids[model_a]), len(run_ids[model_b])
    return out | {
        "model_a": model_a, "model_b": model_b, "metric": metric, "min_words": min_words or 0,
        "n_runs_a": n_a, "n_runs_b": n_b, "low_seed_count": min(n_a, n_b) < MIN_SEEDS,
        "gap_is_clear": bool(out["ci_low"] > 0 or out["ci_high"] < 0),
    }


def slice_table(df: pd.DataFrame, model: str, by: str = "slice", min_words: int | None = MIN_WORDS,
                run_id: str | None = None) -> pd.DataFrame:
    """Per-group results on test (for example by slice, dataset or generator), frozen val threshold."""
    d = _select(df, model, run_id)
    return pd.DataFrame(metrics.slice_report(_rows(d, "test", min_words), by=by,
                                             threshold=_frozen_threshold(d, min_words)))


def slice_summary(df: pd.DataFrame, model: str, by: str = "slice", min_words: int | None = MIN_WORDS) -> pd.DataFrame:
    """Per-group rate averaged over ALL runs of a model, however many there are.

    One row per group: `rate` is the TPR for groups of AI answers and the FPR for the human group
    (`rate_type` says which), with the mean, std, min and max over the runs. Each run uses its own
    frozen threshold. The std is NaN when there is only one run, and `unstable` is True if any run
    saw a group too small to trust.
    """
    run_ids = list(df.loc[df["model"] == model, "run_id"].drop_duplicates())
    if not run_ids:
        raise ValueError(f"no runs of {model!r} in the scores")
    tables = []
    for run_id in run_ids:
        t = slice_table(df, model, by=by, min_words=min_words, run_id=run_id)
        is_ai = t["deployed_tpr"].notna()
        tables.append(pd.DataFrame({
            "slice_value": t["slice_value"], "n": t["n"], "unstable": t["unstable"],
            "rate_type": np.where(is_ai, "TPR", "FPR"),
            "rate": np.where(is_ai, t["deployed_tpr"], t["deployed_fpr"]),
        }))
    out = pd.concat(tables).groupby("slice_value").agg(
        rate_type=("rate_type", "first"), n=("n", "first"), n_runs=("rate", "size"),
        rate_mean=("rate", "mean"), rate_std=("rate", "std"),
        rate_min=("rate", "min"), rate_max=("rate", "max"), unstable=("unstable", "any"),
    ).reset_index()
    return out[["slice_value", "rate_type", "n", "n_runs", "rate_mean", "rate_std", "rate_min", "rate_max", "unstable"]]


def risk_coverage(df: pd.DataFrame, model: str, min_words: int | None = MIN_WORDS, split: str = "val",
                  widths=metrics.BAND_WIDTHS, run_id: str | None = None) -> pd.DataFrame:
    """Risk-coverage table for the uncertain band. Choose the band on val (the default), not on test."""
    d = _select(df, model, run_id)
    rows = _rows(d, split, min_words)
    return pd.DataFrame(metrics.risk_coverage_curve(rows["y_true"], rows["y_prob"],
                                                    _frozen_threshold(d, min_words), widths))


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------

def write_results(out_dir: Path | str, **tables: pd.DataFrame) -> dict[str, Path]:
    """Write each table as <name>.csv in out_dir and return the paths, so a comparison can be shared."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, table in tables.items():
        paths[name] = out / f"{name}.csv"
        table.to_csv(paths[name], index=False)
    return paths
