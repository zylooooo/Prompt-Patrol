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
    matthews_corrcoef,
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

    thr = float(thresholds[valid[np.argmax(tpr[valid])]]) if len(valid) else np.inf

    # Two ways to end up with no usable threshold: a slice with no negatives
    # at all (roc_curve returns nan FPR, valid is empty - happens in
    # leave-one-generator-out), or landing on the artificial +inf threshold
    # roc_curve prepends, meaning no real threshold meets the budget. Either
    # way the only in-budget policy is to flag nothing, so sit just above the
    # top score - returning 1.0 would still flag answers scored exactly 1.0.
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

    recall = float(recall_score(y_true, y_pred, zero_division=0))
    tnr = float(tn / n_neg) if n_neg else float("nan")

    return {
        "threshold": float(threshold),
        "accuracy": float((tp + tn) / max(len(y_true), 1)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": recall,
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        # the realised FPR on this split: proves the frozen threshold held
        "fpr": float(fp / n_neg) if n_neg else float("nan"),
        "tnr": tnr,
        # the missed-AI rate. Redundant with recall, logged anyway because
        # "we miss 65% of AI answers" is how the limitation should be stated
        # to the sponsor, and it reads differently from "TPR 0.35"
        "fnr": float(fn / n_pos) if n_pos else float("nan"),
        # robust to class imbalance, but note that at a fixed 1% FPR the TNR
        # term is pinned near 0.99, so this is close to a rescaled recall
        "balanced_accuracy": float((recall + tnr) / 2) if n_neg else float("nan"),
        # the single-number summary a reviewer asks for when given only F1
        "mcc": float(matthews_corrcoef(y_true, y_pred)),
        "tp": float(tp), "fp": float(fp), "tn": float(tn), "fn": float(fn),
        "n": float(len(y_true)),
        "n_positive": float(n_pos),
        # what fraction of THIS split is AI. Precision is only interpretable
        # against it - see deployed_ppv_at_prevalence_* in evaluate()
        "prevalence": float(n_pos / len(y_true)) if len(y_true) else float("nan"),
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

def bootstrap_cis(y_true, y_prob, fns, n=1000, alpha=0.05, seed=42):
    """
    Stratified bootstrap CIs for several metrics in ONE resampling pass.

    `fns` maps a metric name to fn(y_true, y_prob) -> float. Sharing the
    resamples across metrics is both cheaper and more honest: the intervals
    are then correlated the same way the point estimates are.

    With ~2.3k answers the test split is small enough that any headline
    number quoted without an interval reads as overclaiming.
    """
    y_true, y_prob = _as_arrays(y_true, y_prob)
    rng = np.random.default_rng(seed)
    pos, neg = np.where(y_true == 1)[0], np.where(y_true == 0)[0]

    samples = {name: [] for name in fns}
    for _ in range(n):
        idx = np.concatenate([
            rng.choice(pos, size=len(pos), replace=True),
            rng.choice(neg, size=len(neg), replace=True),
        ])
        yt, yp = y_true[idx], y_prob[idx]
        for name, fn in fns.items():
            try:
                samples[name].append(fn(yt, yp))
            except ValueError:
                continue

    out = {}
    for name, draws in samples.items():
        if not draws:
            out[name] = (float("nan"), float("nan"))
            continue
        out[name] = (
            float(np.percentile(draws, 100 * alpha / 2)),
            float(np.percentile(draws, 100 * (1 - alpha / 2))),
        )
    return out

# --------------------------------------------------------------------------
# the standard bundle
# --------------------------------------------------------------------------

def evaluate(
    y_true,
    y_prob,
    threshold,
    target_fprs=(0.001, 0.01, 0.05),
    headline_fpr=0.01,
    deployment_prevalence=(0.05, 0.10, 0.20),
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

    # The pair the report leads with. deployed_* is what an instructor
    # actually gets: the frozen val threshold applied here. deployed_fpr is
    # the promise being kept or broken - if it drifts above target_fpr, the
    # 1% false-accusation budget did not survive the val -> test transfer,
    # and that gap is itself a finding.
    out["deployed_tpr"] = out["recall"]
    out["deployed_fpr"] = out["fpr"]
    out["deployed_precision"] = out["precision"]

    # Precision measured on a ~50/50 corpus badly overstates what an
    # instructor sees, because real classes are nowhere near balanced. These
    # project the SAME deployed TPR/FPR onto plausible real AI rates:
    #   PPV = TPR*pi / (TPR*pi + FPR*(1-pi))
    # At 1% FPR and 5% prevalence, a flag can still be wrong half the time.
    # This is the number that speaks to wrongful accusation, not `precision`.
    for pi in deployment_prevalence:
        hits = out["deployed_tpr"] * pi
        false_alarms = out["deployed_fpr"] * (1 - pi)
        denom = hits + false_alarms
        out[f"deployed_ppv_at_prevalence_{pi:g}"] = (
            float(hits / denom) if denom > 0 else float("nan")
        )

    for fpr in target_fprs:
        # oracle: best case if the threshold were retuned on this very split.
        # Upper bound only - the gap to deployed_tpr is the cost of not
        # getting to see the test labels.
        out[f"oracle_tpr_at_fpr_{fpr:g}"] = oracle_tpr_at_fpr(y_true, y_prob, fpr)

    if bootstrap_n:
        cis = bootstrap_cis(
            y_true, y_prob,
            {
                "deployed_tpr": lambda t, p: operating_point_metrics(t, p, threshold)["recall"],
                "deployed_fpr": lambda t, p: operating_point_metrics(t, p, threshold)["fpr"],
                f"oracle_tpr_at_fpr_{headline_fpr:g}":
                    lambda t, p: oracle_tpr_at_fpr(t, p, headline_fpr),
                "auroc": lambda t, p: float(roc_auc_score(t, p)),
            },
            n=bootstrap_n, seed=seed,
        )
        for name, (lo, hi) in cis.items():
            out[f"{name}_ci_low"], out[f"{name}_ci_high"] = lo, hi

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
            row["oracle_tpr_at_fpr_0.01"] = oracle_tpr_at_fpr(y_true, y_prob, 0.01)

        row["deployed_tpr"] = row["recall"]
        row["deployed_fpr"] = row["fpr"]

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
