"""
MLflow / DagsHub tracking for Prompt Patrol.

Every run goes through start_run(), which stamps the same tag set on every
run in the project. Those tags are what make the report queryable.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import tempfile
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import mlflow
from dotenv import load_dotenv

from config import RunConfig

# MLflow accepts alphanumerics, _ - . / and space in metric names
_BAD_METRIC_CHARS = re.compile(r"[^A-Za-z0-9_\-./ ]")

# set by log_predictions, checked when the run closes
_logged_predictions: set[str] = set()


def setup_mlflow(experiment: str | None = None) -> str:
    """Point MLflow at the team DagsHub repo. Credentials come from .env."""
    load_dotenv()

    repo_owner = os.getenv("DAGSHUB_REPO_OWNER")
    repo_name = os.getenv("DAGSHUB_REPO_NAME")
    if not repo_owner or not repo_name:
        raise RuntimeError("DAGSHUB_REPO_OWNER / DAGSHUB_REPO_NAME missing from .env")

    uri = f"https://dagshub.com/{repo_owner}/{repo_name}.mlflow"
    mlflow.set_tracking_uri(uri)

    if experiment:
        mlflow.set_experiment(experiment)

    return uri


def _git_state() -> dict[str, str]:
    def run(*args: str) -> str:
        try:
            return subprocess.check_output(
                args, stderr=subprocess.DEVNULL, text=True
            ).strip()
        except Exception:
            return "unknown"

    sha = run("git", "rev-parse", "HEAD")
    dirty = run("git", "status", "--porcelain")
    return {
        "git_sha": sha[:12],
        # a dirty tree means the logged code is not the code that ran
        "git_dirty": str(bool(dirty and dirty != "unknown")).lower(),
        "git_branch": run("git", "rev-parse", "--abbrev-ref", "HEAD"),
    }


def standard_tags(cfg: RunConfig) -> dict[str, str]:
    """
    Facts about the execution, not about the config.

    Everything in the config is already logged as a param by flatten(), and
    MLflow filters params as well as it filters tags. Echoing config fields
    into tags as well just creates a second copy that can disagree with the
    first. What belongs here is what a param cannot say: who ran it, what the
    working tree looked like, and whether this is a duplicate of an earlier run.
    """
    return {
        "owner": cfg.owner,          # the DagsHub login is shared; this is not
        "run_role": cfg.run_role,    # lets the report exclude smoke tests
        "config_fingerprint": cfg.fingerprint(),
        **_git_state(),              # git_sha, git_dirty, git_branch
    }


@contextmanager
def start_run(cfg: RunConfig, nested: bool = False,
              extra_tags: dict[str, str] | None = None) -> Iterator[Any]:
    """
    Open a run with the full tag + param set already logged.

        with start_run(cfg) as run:
            ...train...
            log_split_metrics(m, "test")
    """
    setup_mlflow(cfg.experiment)

    with mlflow.start_run(run_name=cfg.run_name, nested=nested) as run:
        mlflow.set_tags(standard_tags(cfg) | (extra_tags or {}))
        if cfg.notes:
            mlflow.set_tag("mlflow.note.content", cfg.notes)

        mlflow.log_params(cfg.flatten())
        log_dict_artifact(cfg.model_dump(), "config.resolved.json")
        log_dict_artifact(_env_state(), "env/environment.json")

        _logged_predictions.clear()
        try:
            yield run
        finally:
            # a run without per-answer predictions cannot be re-analysed later:
            # every new slice or threshold question would need the GPU again
            if cfg.run_role not in ("smoke",) and not _logged_predictions:
                warnings.warn(
                    f"run {run.info.run_id} logged no predictions - call "
                    "log_predictions(df, split) before the run closes",
                    stacklevel=2,
                )
                mlflow.set_tag("predictions_logged", "false")
            else:
                mlflow.set_tag("predictions_logged", ",".join(sorted(_logged_predictions)))


def _env_state() -> dict[str, Any]:
    state: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "mlflow": mlflow.__version__,
    }
    try:  # torch is absent on machines that only read results
        import torch

        state |= {
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
        }
    except Exception:
        pass
    return state


# --------------------------------------------------------------------------
# logging helpers
# --------------------------------------------------------------------------

def log_split_metrics(metrics: dict[str, float], split: str,
                      step: int | None = None) -> None:
    """
    Log a metric bundle under a split prefix: log_split_metrics(m, "test")
    writes test/auroc, test/ece, ... Non-finite values are dropped rather
    than poisoning the comparison table.
    """
    if split not in ("train", "val", "test"):
        raise ValueError(f"split must be train/val/test, got {split!r}")

    clean, dropped = {}, []
    for key, value in metrics.items():
        name = f"{split}/{_BAD_METRIC_CHARS.sub('_', key)}"
        try:
            value = float(value)
        except (TypeError, ValueError):
            dropped.append(key)
            continue
        if value != value or value in (float("inf"), float("-inf")):
            dropped.append(key)
            continue
        clean[name] = value

    if clean:
        mlflow.log_metrics(clean, step=step)
    if dropped:
        mlflow.set_tag(f"{split}_metrics_dropped", ",".join(sorted(dropped))[:480])


def log_model_size(model) -> dict[str, float]:
    """
    Trainable-parameter accounting. This is the number that makes a LoRA vs
    DoRA vs full fine-tune comparison legible - a 0.3% trainable model losing
    2 AUROC points to full FT is a different story from losing 20.
    """
    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)

    sizes = {
        "params_total": float(total),
        "params_trainable": float(trainable),
        "params_trainable_pct": float(100.0 * trainable / total) if total else 0.0,
        # fp32 bytes; what actually ships to the web app for an adapter
        "adapter_mb": float(trainable * 4 / 1024 ** 2),
    }
    mlflow.log_metrics(sizes)
    return sizes


def log_dict_artifact(payload: dict, artifact_path: str) -> None:
    """Write a dict as a JSON artifact at `artifact_path` inside the run."""
    name = Path(artifact_path).name
    subdir = str(Path(artifact_path).parent)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_text(json.dumps(payload, indent=2, default=str))
        mlflow.log_artifact(str(path), None if subdir == "." else subdir)


def log_predictions(df, split: str) -> None:
    """
    Per-answer predictions - the single most valuable artifact of a run.
    With this table any slice, threshold or calibration can be recomputed
    later without a GPU, so a rerun is never needed to answer a new question.

    Expected columns: answer_id, question_id, y_true, y_prob, generator,
    style, n_words.
    """
    required = {"answer_id", "y_true", "y_prob"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"predictions missing columns: {sorted(missing)}")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{split}_predictions.parquet"
        df.to_parquet(path, index=False)
        mlflow.log_artifact(str(path), "predictions")

    _logged_predictions.add(split)


def log_slice_table(rows: list[dict], split: str = "test") -> None:
    """Per-slice reliability rows as CSV, plus the worst slice as a metric."""
    import pandas as pd

    frame = pd.DataFrame(rows)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{split}_slices.csv"
        frame.to_csv(path, index=False)
        mlflow.log_artifact(str(path), "slices")

    # the weakest slice is the honest headline for reliability, not the mean,
    # and it is read at the frozen threshold - the same operating point the
    # instructor gets, not one retuned per slice
    # `unstable` means small-n only. A single-class slice is not unusable, it
    # is undefined for ONE of these rates: an all-negative slice (human) has no
    # TPR but its FPR is the false-accusation rate, the number that matters
    # most here. So drop undefined values per metric, never per slice.
    stable = frame[~frame["unstable"]] if "unstable" in frame else frame
    empty = pd.Series(dtype=float)
    tpr = stable.get("deployed_tpr", empty).dropna()
    fpr = stable.get("deployed_fpr", empty).dropna()

    payload = {}
    if len(tpr):
        payload[f"{split}/slice_worst_deployed_tpr"] = float(tpr.min())
        payload[f"{split}/slice_mean_deployed_tpr"] = float(tpr.mean())
        # so an absent headline is distinguishable from an unlogged one
        payload[f"{split}/n_slices_scored_tpr"] = float(len(tpr))
    if len(fpr):
        payload[f"{split}/slice_worst_deployed_fpr"] = float(fpr.max())
    if payload:
        mlflow.log_metrics(payload)


def log_thresholds(payload: dict) -> None:
    """
    The frozen decision boundary: val-selected threshold, calibrator params,
    abstention band. The web app loads exactly this file, so what is served
    is provably what was evaluated.
    """
    log_dict_artifact(payload, "thresholds.json")


def log_plot(fig, name: str) -> None:
    """Save a matplotlib figure under plots/."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        fig.savefig(path, dpi=140, bbox_inches="tight")
        mlflow.log_artifact(str(path), "plots")
