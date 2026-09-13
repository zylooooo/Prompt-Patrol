"""
Pull runs back out of DagsHub into the tables the report needs.

The point of logging a full config as params is that these functions work
without anyone remembering what a run was called.

    python reporting.py --out reports/
"""

from __future__ import annotations

import argparse
from pathlib import Path

import mlflow
import pandas as pd

from tracking import setup_mlflow

# The columns the comparative evaluation report is built from. Config values
# come from params (the config is the single source of truth for them); only
# facts about the execution come from tags.
HEADLINE_COLUMNS = [
    "params.model.family",
    "params.model.tuning_method",
    "params.data.splits",
    "params.data.held_out_generator",
    "params.seed",
    "tags.owner",
    "metrics.params_trainable_pct",
    "metrics.test/auroc",
    "metrics.test/deployed_tpr",
    "metrics.test/deployed_tpr_ci_low",
    "metrics.test/deployed_tpr_ci_high",
    "metrics.test/deployed_fpr",
    "metrics.test/deployed_fpr_ci_high",
    "metrics.test/oracle_tpr_at_fpr_0.01",
    "metrics.test/ece",
    "metrics.test/brier",
    "metrics.test/abstain_rate",
    "metrics.test/selective_fpr",
    "metrics.train/runtime_s",
]

_RENAME = {
    "tags.mlflow.runName": "run",
    "params.model.family": "detector",
    "params.model.tuning_method": "tuning",
    "params.data.splits": "data",
    "params.data.held_out_generator": "held_out",
    "params.seed": "seed",
    "tags.owner": "owner",
    "metrics.params_trainable_pct": "trainable_%",
    "metrics.test/auroc": "auroc",
    "metrics.test/deployed_tpr": "deployed_tpr",
    "metrics.test/deployed_fpr": "deployed_fpr",
    "metrics.test/oracle_tpr_at_fpr_0.01": "oracle_tpr",
    "metrics.test/ece": "ece",
    "metrics.test/abstain_rate": "abstain",
}


def load_runs(experiment: str, drop_smoke: bool = True) -> pd.DataFrame:
    """
    All finished runs in an experiment as a dataframe. Filtering happens in
    pandas rather than in a server-side filter_string: dotted param names need
    quoting in MLflow's filter grammar and support for it varies by backend.
    """
    setup_mlflow()

    exp = mlflow.get_experiment_by_name(experiment)
    if exp is None:
        raise ValueError(f"no experiment named {experiment!r} on the tracking server")

    runs = mlflow.search_runs(
        experiment_ids=[exp.experiment_id],
        filter_string="attributes.status = 'FINISHED'",
        output_format="pandas",
    )
    # smoke runs are pipeline shakedowns; they are never a result
    if drop_smoke and "tags.run_role" in runs:
        runs = runs[runs["tags.run_role"] != "smoke"]

    return runs.reset_index(drop=True)


def headline_table(experiment: str = "E2-finetune") -> pd.DataFrame:
    """
    The main comparison: one row per detector configuration, sorted by the
    metric the proposal commits to. Runs without a test evaluation drop out.
    """
    runs = load_runs(experiment)
    if runs.empty:
        return runs

    cols = [c for c in HEADLINE_COLUMNS if c in runs.columns]
    table = runs[["tags.mlflow.runName", *cols]].rename(columns=_RENAME)

    table = table.dropna(subset=["auroc"]) if "auroc" in table else table
    sort_key = "deployed_tpr" if "deployed_tpr" in table else "auroc"

    return table.sort_values(sort_key, ascending=False).reset_index(drop=True)


def logo_summary(experiment: str = "E3-reliability") -> pd.DataFrame:
    """
    Leave-one-generator-out. The row that belongs in the report is the WORST
    held-out generator, not the mean - it is the only number that speaks to
    an unseen model, which is the risk the proposal names.
    """
    runs = load_runs(experiment)
    if "params.data.split_strategy" in runs:
        runs = runs[runs["params.data.split_strategy"] == "logo"]
    if runs.empty:
        return runs

    keep = ["params.data.held_out_generator", "params.model.tuning_method",
            "metrics.test/deployed_tpr", "metrics.test/auroc", "metrics.test/fpr"]
    frame = runs[[c for c in keep if c in runs.columns]].rename(columns=_RENAME)

    grouped = frame.groupby("tuning")[["deployed_tpr", "auroc"]]
    summary = grouped.agg(["min", "mean", "std"]).round(4)
    summary.columns = ["_".join(c) for c in summary.columns]

    return summary.reset_index()


def write_report_tables(out_dir: str | Path = "reports") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for name, frame in (
        ("headline_e2.csv", headline_table()),
        ("logo_e3.csv", logo_summary()),
    ):
        if frame is None or frame.empty:
            print(f"skipped {name}: no runs yet")
            continue
        frame.to_csv(out / name, index=False)
        print(f"wrote {out / name} ({len(frame)} rows)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports")
    write_report_tables(parser.parse_args().out)
