"""Plots and chart tables for the MELD and desklib LoRA runs. Every figure is saved with
tracking.log_plot, so it shows up as an image under the run's Artifacts > plots/ folder, and
every chart's data is logged as a CSV under charts/ so it can be redrawn without rerunning."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed on a training machine
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve, roc_curve

# chart model names are <family>_lora and <family>_baseline, e.g. meld_lora, desklib_baseline
COLORS = {"lora": "#1f77b4", "baseline": "#999999"}


def _color(name):
    return COLORS.get(str(name).rsplit("_", 1)[-1])


def _label(name):
    family, _, kind = str(name).rpartition("_")
    family = {"meld": "MELD", "desklib": "desklib"}.get(family, family)
    return {"lora": f"{family} LoRA (temperature-calibrated)",
            "baseline": f"{family} baseline (uncalibrated)"}.get(kind, name)


def _save(fig, name, save):
    if save is None:
        from tracking import log_plot as save
    save(fig, name)
    plt.close(fig)


def plot_training(history, save=None):
    """Loss per epoch (left), validation AUROC per epoch (middle) and, when the run logged them,
    validation partial AUROC and TPR at 1% FPR per epoch (right), which show how noisy the low-FPR
    region is from epoch to epoch."""
    h = pd.DataFrame(history)
    low_fpr = [c for c in ("val_pauroc", "val_tpr_1pct") if c in h]
    fig, axes = plt.subplots(1, 3 if low_fpr else 2, figsize=(13.5 if low_fpr else 9, 3.5))
    a, b = axes[0], axes[1]
    a.plot(h["epoch"], h["train_loss"], marker="o", label="train")
    a.plot(h["epoch"], h["val_loss"], marker="o", label="val")
    a.set(xlabel="epoch", ylabel="loss", title="Loss")
    a.legend()
    b.plot(h["epoch"], h["val_auroc"], marker="o", color="#2ca02c")
    b.set(xlabel="epoch", ylabel="AUROC", title="Validation AUROC")
    if low_fpr:
        c = axes[2]
        names = {"val_pauroc": "partial AUROC at 1% FPR", "val_tpr_1pct": "TPR at exactly 1% FPR"}
        for col, color in zip(low_fpr, ("#9467bd", "#d62728")):
            c.plot(h["epoch"], h[col], marker="o", color=color, label=names[col])
        c.set(xlabel="epoch", ylim=(0, 1), title="Validation, low-FPR region")
        c.legend(loc="lower right")
    for ax in axes:
        ax.set_xticks(h["epoch"])
    _save(fig, "training_curves.png", save)


def plot_roc(curves, threshold_point=None, target_fpr=0.01, save=None):
    """ROC with a log x-axis so the low false-positive region is readable.
    threshold_point = (fpr, tpr) at the deployed threshold, for the LoRA model."""
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    roc = curves[curves["curve"] == "roc"]
    for name, g in roc.groupby("model"):
        ax.plot(g["x"], g["y"], label=name, color=_color(name))
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
        ax.plot(g["x"], g["y"], label=name, color=_color(name))
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
                label=_label(name), color=_color(name))
    ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="predicted probability",
           ylabel="observed AI rate",
           title="Calibration (LoRA calibrated; baseline uncalibrated)")
    ax.legend(loc="upper left")
    _save(fig, "calibration.png", save)


def plot_score_hist(labels, probs, threshold, baseline_probs=None, family="meld", save=None):
    """How well the two groups separate. The threshold belongs to the LoRA model
    only, because the baseline scores are not calibrated the same way."""
    labels = np.asarray(labels)
    panels = [(_label(f"{family}_lora"), np.asarray(probs), threshold)]
    if baseline_probs is not None:
        panels.insert(0, (_label(f"{family}_baseline"), np.asarray(baseline_probs, dtype=float), None))
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


# --------------------------------------------------------------------------
# chart tables, and everything a run logs under charts/ and plots/
# --------------------------------------------------------------------------

def calibration_bins(labels, probabilities, n_bins=10):
    """Reliability-table rows that can be plotted without rerunning inference."""
    labels = np.asarray(labels, dtype=int)
    probabilities = np.asarray(probabilities, dtype=float)
    rows = []
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    for i in range(n_bins):
        mask = ((probabilities >= edges[i]) & (probabilities < edges[i + 1])
                if i < n_bins - 1 else
                (probabilities >= edges[i]) & (probabilities <= edges[i + 1]))
        if not mask.any():
            continue
        rows.append({
            "bin": i,
            "lower": float(edges[i]),
            "upper": float(edges[i + 1]),
            "n": int(mask.sum()),
            "mean_predicted": float(probabilities[mask].mean()),
            "observed_ai_rate": float(labels[mask].mean()),
        })
    return rows


def curve_rows(labels, probabilities, model_name):
    """Return ROC and precision-recall points in tidy, chart-friendly form."""
    fpr, tpr, roc_thresholds = roc_curve(labels, probabilities)
    precision, recall, pr_thresholds = precision_recall_curve(labels, probabilities)
    rows = [
        {"model": model_name, "curve": "roc", "x": float(x), "y": float(y),
         "threshold": float(t) if np.isfinite(t) else None}
        for x, y, t in zip(fpr, tpr, roc_thresholds)
    ]
    # precision_recall_curve has one extra endpoint without a threshold.
    rows.extend(
        {"model": model_name, "curve": "precision_recall", "x": float(x), "y": float(y),
         "threshold": float(pr_thresholds[i]) if i < len(pr_thresholds) else None}
        for i, (x, y) in enumerate(zip(recall, precision))
    )
    return rows


def log_dataframe_artifact(frame: pd.DataFrame, path: Path, artifact_dir: str):
    import mlflow

    frame.to_csv(path, index=False)
    mlflow.log_artifact(str(path), artifact_dir)


def log_lora_charts(run_name, family, test_used, prob_used, baseline_used, history, results, threshold,
                    target_fpr, out_dir):
    """
    Every chart for one tuned run, into the active MLflow run: the figures under plots/, their data as
    CSVs under charts/, and per-slice AUROC, TPR, FPR and n as slice/<by>/<value>/<metric> metrics.

    run_name:       names the CSVs, <out_dir>/<run_name>_<chart>.csv
    family:         meld or desklib; the chart models are <family>_lora and <family>_baseline
    test_used:      test rows the headline metrics use (label, dataset, slice columns), indexed 0..n-1
    prob_used:      the tuned model's calibrated probability for each of those rows
    baseline_used:  the untouched model's probability for the same rows, or None
    history:        one dict per epoch (epoch, train_loss, val_loss, val_auroc, ...); empty skips the
                    training chart, e.g. for a model that was not trained
    results:        metrics.evaluate() output for the tuned model
    threshold:      the frozen threshold fitted on val
    """
    import mlflow

    from metrics import slice_report

    out_dir = Path(out_dir)
    out_dir.mkdir(exist_ok=True)
    tuned_name, baseline_name = f"{family}_lora", f"{family}_baseline"
    labels = test_used["label"].to_numpy()
    probs = np.asarray(prob_used, dtype=float)

    curve_frame = pd.DataFrame(curve_rows(labels, probs, tuned_name))
    calibration_frame = pd.DataFrame(calibration_bins(labels, probs)).assign(
        model=tuned_name, calibration="temperature")
    if baseline_used is not None:
        curve_frame = pd.concat([curve_frame, pd.DataFrame(curve_rows(labels, baseline_used, baseline_name))],
                                ignore_index=True)
        # the tuned model is temperature-calibrated on val; the zero-shot baseline is left uncalibrated
        calibration_frame = pd.concat([calibration_frame, pd.DataFrame(
            calibration_bins(labels, baseline_used)).assign(model=baseline_name, calibration="none")],
            ignore_index=True)
    scored = test_used.assign(prob=probs)
    slice_frame = pd.DataFrame(
        slice_report(scored, y_true_col="label", y_prob_col="prob", by="dataset", threshold=threshold)
        + slice_report(scored, y_true_col="label", y_prob_col="prob", by="slice", threshold=threshold))
    for row in slice_frame.to_dict("records"):
        scope = str(row["slice_by"]).replace(" ", "_")
        value = str(row["slice_value"]).replace(" ", "_").replace("/", "_")
        for metric_name in ("deployed_tpr", "deployed_fpr", "auroc", "n"):
            value_to_log = row.get(metric_name)
            if value_to_log is not None and np.isfinite(value_to_log):
                mlflow.log_metric(f"slice/{scope}/{value}/{metric_name}", float(value_to_log))

    flagged = probs >= threshold
    deployed_point = (flagged[labels == 0].mean(), flagged[labels == 1].mean())
    test_prevalence = float(labels.mean())
    if history:
        plot_training(history)
        log_dataframe_artifact(pd.DataFrame(history), out_dir / f"{run_name}_training_history.csv", "charts")
    plot_roc(curve_frame, deployed_point, target_fpr)
    plot_pr(curve_frame)
    plot_calibration(calibration_frame)
    plot_score_hist(labels, probs, threshold, baseline_used, family=family)
    plot_slices(slice_frame)
    plot_ppv_prevalence(results, test_prevalence=test_prevalence)

    log_dataframe_artifact(curve_frame, out_dir / f"{run_name}_curves.csv", "charts")
    log_dataframe_artifact(calibration_frame, out_dir / f"{run_name}_calibration_bins.csv", "charts")
    log_dataframe_artifact(slice_frame, out_dir / f"{run_name}_slice_metrics.csv", "charts")
    ppv_frame = pd.DataFrame([
        {"ai_prevalence": float(key.rsplit("_", 1)[-1]), "projected_ppv": float(value), "source": "deployment"}
        for key, value in results.items()
        if key.startswith("deployed_ppv_at_prevalence_") and np.isfinite(value)
    ])
    ppv_frame = pd.concat([ppv_frame, pd.DataFrame([{
        "ai_prevalence": test_prevalence, "projected_ppv": float(results["deployed_precision"]),
        "source": "test set",
    }])], ignore_index=True).sort_values("ai_prevalence")
    log_dataframe_artifact(ppv_frame, out_dir / f"{run_name}_ppv_by_prevalence.csv", "charts")
