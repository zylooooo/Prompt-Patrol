"""
Official Prompt Patrol metrics.

Every detector, fine-tuned or zero-shot, is scored through evaluate() so the
comparison table is apples-to-apples. Metric names here are the contract:
they are what lands in MLflow and what the report reads back.

Protocol note: the headline number is TPR at a FIXED low FPR, and the
threshold that fixes it MUST be chosen on validation, then frozen and applied
to test. Choosing it on test inflates the number and is not defensible in the
report. evaluate() reports both so the gap is visible.
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)

# label convention, fixed project-wide: 1 = AI-generated, 0 = human.
# a "false positive" is therefore a human answer flagged as AI - the error
# that wrongly accuses a student, and the one we hold to a fixed budget.
POSITIVE_LABEL = "ai_generated"


def _as_arrays(y_true, y_prob):
    y_true = np.asarray(y_true).astype(int).ravel()
    y_prob = np.asarray(y_prob).astype(float).ravel()
    if y_true.shape != y_prob.shape:
        raise ValueError(f"shape mismatch: {y_true.shape} vs {y_prob.shape}")
    return y_true, y_prob


# --------------------------------------------------------------------------
# operating point selection (fit on val, freeze, apply to test)
# --------------------------------------------------------------------------

def threshold_at_fpr(y_true, y_prob, target_fpr=0.01):
    """
    Lowest threshold whose FPR still sits at or under the budget.
    Fit this on validation and carry it to test unchanged.
    """
    y_true, y_prob = _as_arrays(y_true, y_prob)
    fpr, tpr, thresholds = roc_curve(y_true, y_prob)

    valid = np.where(fpr <= target_fpr)[0]

    if len(valid) == 0:
        return float(np.nextafter(np.max(y_prob), np.inf))

    # among thresholds inside the budget, take the one with the best TPR
    best = valid[np.argmax(tpr[valid])]
    thr = float(thresholds[best])

    # roc_curve prepends an artificial +inf threshold. Landing on it means no
    # real threshold meets the budget, so the only in-budget policy is to flag
    # nothing - return just above the top score rather than 1.0, which would
    # still flag every answer scored exactly 1.0 and blow the budget.
    if not np.isfinite(thr):
        return float(np.nextafter(float(np.max(y_prob)), np.inf))

    return thr


def oracle_tpr_at_fpr(y_true, y_prob, target_fpr=0.01):
    """
    Best TPR achievable on THIS split at the FPR budget. Optimistic, because
    the threshold is picked with the labels in hand - report it only as the
    oracle upper bound next to the frozen-threshold number.
    """
    y_true, y_prob = _as_arrays(y_true, y_prob)
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    valid = np.where(fpr <= target_fpr)[0]
    return float(np.max(tpr[valid])) if len(valid) else 0.0


def find_best_f1_threshold(y_true, y_prob):
    """Validation-only threshold search. Kept for the F1-tuned baseline."""
    y_true, y_prob = _as_arrays(y_true, y_prob)

    best_f1, best_threshold = 0.0, 0.5
    for t in np.linspace(0.05, 0.95, 181):
        f1 = f1_score(y_true, (y_prob >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1, best_threshold = f1, float(t)

    return best_threshold


# --------------------------------------------------------------------------
# metric families
# --------------------------------------------------------------------------

def ranking_metrics(y_true, y_prob):
    """Threshold-free. Comparable across detectors with different score scales."""
    y_true, y_prob = _as_arrays(y_true, y_prob)
    if len(np.unique(y_true)) < 2:
        return {"auroc": float("nan"), "auprc": float("nan")}
    return {
        "auroc": float(roc_auc_score(y_true, y_prob)),
        "auprc": float(average_precision_score(y_true, y_prob)),
    }


def operating_point_metrics(y_true, y_prob, threshold):
    """Everything at the deployed threshold, plus raw counts."""
    y_true, y_prob = _as_arrays(y_true, y_prob)
    y_pred = (y_prob >= threshold).astype(int)

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    n_neg, n_pos = tn + fp, tp + fn

    return {
        "threshold": float(threshold),
        "accuracy": float((tp + tn) / max(len(y_true), 1)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        # the realised FPR on this split: proves the frozen threshold held
        "fpr": float(fp / n_neg) if n_neg else float("nan"),
        "tnr": float(tn / n_neg) if n_neg else float("nan"),
        "tp": float(tp), "fp": float(fp), "tn": float(tn), "fn": float(fn),
        "n": float(len(y_true)),
        "n_positive": float(n_pos),
    }


def expected_calibration_error(y_true, y_prob, n_bins=10):
    """
    ECE over equal-width bins of predicted P(AI). Confidence in a bin is
    compared against the observed AI rate in that bin.
    """
    y_true, y_prob = _as_arrays(y_true, y_prob)
    edges = np.linspace(0.0, 1.0, n_bins + 1)

    ece, mce = 0.0, 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        # final bin closes on the right so p == 1.0 is not silently dropped
        mask = (y_prob >= lo) & (y_prob < hi) if i < n_bins - 1 else (y_prob >= lo) & (y_prob <= hi)
        if not mask.any():
            continue

        gap = abs(float(np.mean(y_true[mask])) - float(np.mean(y_prob[mask])))
        ece += (mask.sum() / len(y_true)) * gap
        mce = max(mce, gap)

    return float(ece), float(mce)


def calibration_metrics(y_true, y_prob, n_bins=10):
    """Does a stated confidence mean what it says? Lower is better throughout."""
    y_true, y_prob = _as_arrays(y_true, y_prob)
    ece, mce = expected_calibration_error(y_true, y_prob, n_bins)

    eps = 1e-7
    return {
        "ece": ece,
        "mce": mce,
        "brier": float(brier_score_loss(y_true, y_prob)),
        "nll": float(log_loss(y_true, np.clip(y_prob, eps, 1 - eps), labels=[0, 1])),
    }


def abstention_metrics(y_true, y_prob, threshold, abstain_low, abstain_high):
    """
    The "uncertain" band the app shows instead of guessing. Selective metrics
    are computed only over answers the tool actually commits to, so a low
    selective FPR is only meaningful when read next to coverage.
    """
    y_true, y_prob = _as_arrays(y_true, y_prob)
    abstain = (y_prob >= abstain_low) & (y_prob <= abstain_high)
    covered = ~abstain

    out = {
        "abstain_low": float(abstain_low),
        "abstain_high": float(abstain_high),
        "abstain_rate": float(abstain.mean()),
        "coverage": float(covered.mean()),
    }
    if covered.sum() == 0:
        return out | {"selective_accuracy": float("nan"), "selective_fpr": float("nan")}

    sub = operating_point_metrics(y_true[covered], y_prob[covered], threshold)
    return out | {
        "selective_accuracy": sub["accuracy"],
        "selective_fpr": sub["fpr"],
        "selective_recall": sub["recall"],
    }


# --------------------------------------------------------------------------
# uncertainty
# --------------------------------------------------------------------------

def bootstrap_ci(y_true, y_prob, fn, n=1000, alpha=0.05, seed=42):
    """
    Stratified bootstrap CI for any metric fn(y_true, y_prob) -> float.
    With ~2.3k answers the test split is small enough that a headline number
    without an interval will read as overclaiming.
    """
    y_true, y_prob = _as_arrays(y_true, y_prob)
    rng = np.random.default_rng(seed)
    pos, neg = np.where(y_true == 1)[0], np.where(y_true == 0)[0]

    samples = []
    for _ in range(n):
        idx = np.concatenate([
            rng.choice(pos, size=len(pos), replace=True),
            rng.choice(neg, size=len(neg), replace=True),
        ])
        try:
            samples.append(fn(y_true[idx], y_prob[idx]))
        except ValueError:
            continue

    if not samples:
        return float("nan"), float("nan")

    return (
        float(np.percentile(samples, 100 * alpha / 2)),
        float(np.percentile(samples, 100 * (1 - alpha / 2))),
    )


# --------------------------------------------------------------------------
# the standard bundle
# --------------------------------------------------------------------------

def evaluate(
    y_true,
    y_prob,
    threshold,
    target_fprs=(0.001, 0.01, 0.05),
    abstain_low=None,
    abstain_high=None,
    bootstrap_n=1000,
    seed=42,
):
    """
    The full metric set for one split. `threshold` must come from validation.
    Returns a flat dict of MLflow-safe metric names.
    """
    y_true, y_prob = _as_arrays(y_true, y_prob)

    out = ranking_metrics(y_true, y_prob)
    out |= operating_point_metrics(y_true, y_prob, threshold)
    out |= calibration_metrics(y_true, y_prob)

    for fpr in target_fprs:
        # oracle: best case if the threshold were tuned on this very split
        out[f"tpr_at_fpr_{fpr:g}_oracle"] = oracle_tpr_at_fpr(y_true, y_prob, fpr)

    # headline: the frozen threshold, so tpr_at_fpr_0.01 pairs with `fpr` above
    out["tpr_at_fixed_threshold"] = out["recall"]

    if bootstrap_n:
        lo, hi = bootstrap_ci(
            y_true, y_prob,
            lambda t, p: oracle_tpr_at_fpr(t, p, 0.01),
            n=bootstrap_n, seed=seed,
        )
        out["tpr_at_fpr_0.01_ci_low"] = lo
        out["tpr_at_fpr_0.01_ci_high"] = hi

        lo, hi = bootstrap_ci(
            y_true, y_prob,
            lambda t, p: float(roc_auc_score(t, p)),
            n=bootstrap_n, seed=seed,
        )
        out["auroc_ci_low"], out["auroc_ci_high"] = lo, hi

    if abstain_low is not None and abstain_high is not None:
        out |= abstention_metrics(y_true, y_prob, threshold, abstain_low, abstain_high)

    return out


def slice_report(df, y_true_col="y_true", y_prob_col="y_prob",
                 by="generator", threshold=0.5, min_n=50):
    """
    Per-slice metrics for the E3 reliability map. `df` is the predictions
    table; `by` is a column such as generator, style or length_bin.
    Returns a list of dicts, one row per slice value.
    """
    rows = []
    for value, group in df.groupby(by, dropna=False):
        y_true = group[y_true_col].to_numpy()
        y_prob = group[y_prob_col].to_numpy()

        row = {"slice_by": by, "slice_value": str(value), "n": len(group),
               "unstable": len(group) < min_n}

        if len(np.unique(y_true)) < 2:
            # a single-class slice (common in leave-one-generator-out) can
            # still report error rate, but not AUROC
            row |= operating_point_metrics(y_true, y_prob, threshold)
        else:
            row |= ranking_metrics(y_true, y_prob)
            row |= operating_point_metrics(y_true, y_prob, threshold)
            row["tpr_at_fpr_0.01_oracle"] = oracle_tpr_at_fpr(y_true, y_prob, 0.01)

        rows.append(row)

    return rows


# backwards-compatible aliases used by the first DagsHub trial runs
compute_tpr_at_fpr = oracle_tpr_at_fpr
compute_ece = lambda y_true, y_prob, n_bins=10: expected_calibration_error(
    y_true, y_prob, n_bins
)[0]


def compute_metrics(y_true, y_prob, threshold=0.5):
    """Legacy entry point. Prefer evaluate() - it adds CIs and abstention."""
    return evaluate(y_true, y_prob, threshold, bootstrap_n=0)
