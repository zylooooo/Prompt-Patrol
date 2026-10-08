"""Plots for the MELD LoRA run. Every figure is saved with tracking.log_plot,
so it shows up as an image under the run's Artifacts > plots/ folder."""

import matplotlib

matplotlib.use("Agg")  # no display needed on a training machine
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

COLORS = {"meld_lora": "#1f77b4", "meld_baseline": "#999999"}
CALIBRATION_LABELS = {
    "meld_lora": "MELD LoRA (temperature-calibrated)",
    "meld_baseline": "MELD baseline (uncalibrated)",
}


def _save(fig, name, save):
    if save is None:
        from tracking import log_plot as save
    save(fig, name)
    plt.close(fig)


def plot_training(history, save=None):
    """Loss per epoch (left) and validation AUROC per epoch (right)."""
    h = pd.DataFrame(history)
    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.5))
    a.plot(h["epoch"], h["train_loss"], marker="o", label="train")
    a.plot(h["epoch"], h["val_loss"], marker="o", label="val")
    a.set(xlabel="epoch", ylabel="loss", title="Loss")
    a.legend()
    b.plot(h["epoch"], h["val_auroc"], marker="o", color="#2ca02c")
    b.set(xlabel="epoch", ylabel="AUROC", title="Validation AUROC")
    for ax in (a, b):
        ax.set_xticks(h["epoch"])
    _save(fig, "training_curves.png", save)


def plot_roc(curves, threshold_point=None, target_fpr=0.01, save=None):
    """ROC with a log x-axis so the low false-positive region is readable.
    threshold_point = (fpr, tpr) at the deployed threshold, for the LoRA model."""
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    roc = curves[curves["curve"] == "roc"]
    for name, g in roc.groupby("model"):
        ax.plot(g["x"], g["y"], label=name, color=COLORS.get(name))
    ax.axvline(target_fpr, color="red", linestyle="--", linewidth=1,
               label=f"{target_fpr:.0%} FPR")
    if threshold_point is not None:
        ax.scatter(*threshold_point, color="red", zorder=5, label="deployed threshold")
    # symlog keeps an exact FPR of 0 on the axis and is log-scaled above 0.001
    ax.set(xscale="symlog", xlim=(0, 1), ylim=(0, 1),
           xlabel="false positive rate (log scale above 0.001)",
           ylabel="true positive rate", title="ROC")
    ax.set_xscale("symlog", linthresh=1e-3)
    ax.set_xlim(0, 1)
    ax.legend(loc="lower right")
    _save(fig, "roc.png", save)


def plot_pr(curves, save=None):
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    pr = curves[curves["curve"] == "precision_recall"]
    for name, g in pr.groupby("model"):
        ax.plot(g["x"], g["y"], label=name, color=COLORS.get(name))
    ax.set(xlim=(0, 1), ylim=(0, 1.02), xlabel="recall", ylabel="precision",
           title="Precision-recall")
    ax.legend(loc="lower left")
    _save(fig, "precision_recall.png", save)


def plot_calibration(bins, save=None):
    """Predicted probability vs observed AI rate. Closer to the diagonal is better."""
    fig, ax = plt.subplots(figsize=(5, 4.5))
    ax.plot([0, 1], [0, 1], "k--", linewidth=1, label="perfect")
    for name, g in bins.groupby("model"):
        ax.plot(g["mean_predicted"], g["observed_ai_rate"], marker="o",
                label=CALIBRATION_LABELS.get(name, name), color=COLORS.get(name))
    ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="predicted probability",
           ylabel="observed AI rate",
           title="Calibration (LoRA calibrated; baseline uncalibrated)")
    ax.legend(loc="upper left")
    _save(fig, "calibration.png", save)


def plot_score_hist(labels, probs, threshold, baseline_probs=None, save=None):
    """How well the two groups separate. The threshold belongs to the LoRA model
    only, because the baseline scores are not calibrated the same way."""
    labels = np.asarray(labels)
    panels = [("MELD LoRA (temperature-calibrated)", np.asarray(probs), threshold)]
    if baseline_probs is not None:
        panels.insert(
            0,
            ("MELD baseline (uncalibrated)", np.asarray(baseline_probs, dtype=float), None),
        )
    fig, axes = plt.subplots(1, len(panels), figsize=(5.5 * len(panels), 3.8),
                             sharey=True, squeeze=False)
    bins = np.linspace(0, 1, 41)
    for ax, (title, p, thr) in zip(axes[0], panels):
        ax.hist(p[labels == 0], bins=bins, alpha=0.6, label="human", color="#2ca02c")
        ax.hist(p[labels == 1], bins=bins, alpha=0.6, label="AI", color="#d62728")
        if thr is not None:
            ax.axvline(thr, color="black", linestyle="--", label="threshold")
        ax.set(xlabel="predicted AI probability", title=title)
        ax.legend()
    axes[0][0].set_ylabel("answers")
    _save(fig, "score_distribution.png", save)


def _bars(ax, names, values, color, xlim, xlabel, title):
    """Horizontal bars. Undefined values (NaN) get an N/A label, not a zero bar."""
    values = np.asarray(values, dtype=float)
    ax.barh(names, np.nan_to_num(values, nan=0.0), color=color)
    for i, v in enumerate(values):
        if np.isnan(v):
            ax.text(0.01 * xlim, i, "N/A", va="center", color="gray", style="italic")
    ax.set(xlim=(0, xlim), xlabel=xlabel, title=title)


def plot_slices(slice_frame, save=None):
    """TPR and FPR at the deployed threshold, one bar per slice.
    N/A means the slice has no AI answers (no TPR) or no human answers (no FPR)."""
    f = slice_frame.copy()
    f["name"] = f["slice_by"].astype(str) + ": " + f["slice_value"].astype(str)
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, max(3, 0.35 * len(f))), sharey=True)
    _bars(a, f["name"], f["deployed_tpr"], "#d62728", 1.0,
          "TPR (AI caught)", "Detection rate")
    fpr_max = np.nanmax(f["deployed_fpr"].to_numpy(dtype=float)) if f["deployed_fpr"].notna().any() else 0.05
    _bars(b, f["name"], f["deployed_fpr"], "#1f77b4", max(0.05, fpr_max * 1.2),
          "FPR (humans wrongly flagged)", "False accusation rate")
    _save(fig, "slice_metrics.png", save)


def plot_ppv_prevalence(results, test_prevalence=None, save=None):
    """Projected PPV at deployment prevalences and the test-set prevalence."""
    rows = []
    for key, value in results.items():
        prefix = "deployed_ppv_at_prevalence_"
        if key.startswith(prefix) and np.isfinite(value):
            rows.append((float(key[len(prefix):]), float(value), "deployment"))
    if test_prevalence is not None and np.isfinite(test_prevalence):
        test_ppv = results.get("deployed_precision")
        if test_ppv is not None and np.isfinite(test_ppv):
            rows.append((float(test_prevalence), float(test_ppv), "test set"))
    if not rows:
        return

    rows.sort()
    prevalence = np.asarray([row[0] for row in rows])
    ppv = np.asarray([row[1] for row in rows])
    kind = np.asarray([row[2] for row in rows])
    fig, ax = plt.subplots(figsize=(5.5, 4.0))
    deployment = kind == "deployment"
    if deployment.any():
        ax.plot(prevalence[deployment] * 100, ppv[deployment] * 100,
                marker="o", color="#9467bd", label="projected deployment")
    if (~deployment).any():
        ax.scatter(prevalence[~deployment] * 100, ppv[~deployment] * 100,
                   marker="D", color="#ff7f0e", zorder=4, label="test-set prevalence")
    for x, y, label in zip(prevalence * 100, ppv * 100, kind):
        ax.annotate(f"{y:.1f}%", (x, y), textcoords="offset points",
                    xytext=(0, 7), ha="center")
    ax.set(xlim=(0, max(prevalence) * 100 + 2),
           ylim=(0, 100), xlabel="AI prevalence among answers (%)",
           ylabel="precision among flagged answers (%)",
           title="Projected precision by AI prevalence")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="lower right")
    _save(fig, "ppv_by_prevalence.png", save)