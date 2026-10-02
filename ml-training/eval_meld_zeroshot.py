"""
Zero-shot MELD evaluation on the real v0.1 corpus.

No training involved - MELD is used exactly as published. This scores val to
fit a decision threshold at the project's FPR budget, freezes it, and scores
test once - the same val-then-freeze-then-test protocol trial-training.py
uses for fine-tuned runs, reusing the same metrics.py functions.

    python eval_meld_zeroshot.py
    python eval_meld_zeroshot.py --target-fpr 0.05

Needs the MELD repo weights (public, ~4.1GB) - downloaded automatically via
huggingface_hub on first run, cached after that.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd

from metrics import evaluate, threshold_at_fpr
from tracking import log_dict_artifact, log_predictions, log_split_metrics, setup_mlflow

MELD_REPO = "anon-review-meld-2026/meld"
SPLITS_PATH = Path(__file__).parent / "data" / "splits" / "v0.1.parquet"
OUT_PATH = Path(__file__).parent / "outputs" / "meld_zeroshot_results.json"
MLFLOW_EXPERIMENT = "zeroshot-baselines"
DATA_MD5 = "851b80f0a9325a11af2126e2cc3b1b25"


def load_meld_scorer(device: str = "cuda"):
    """Download (or reuse the cached) MELD weights and load its own Scorer
    class. MELD ships a standalone meld.py, not a pip package, so it's
    imported directly from the downloaded snapshot rather than installed.
    """
    from huggingface_hub import snapshot_download

    model_dir = snapshot_download(MELD_REPO)

    spec = importlib.util.spec_from_file_location("meld", Path(model_dir) / "meld.py")
    meld = importlib.util.module_from_spec(spec)
    sys.modules["meld"] = meld
    spec.loader.exec_module(meld)

    return meld.Scorer(model_dir=model_dir, device=device)


def score_split(scorer, frame: pd.DataFrame, split_name: str) -> np.ndarray:
    """P(AI) per answer, in the same order as frame. One answer at a time -
    MELD's own Scorer doesn't batch across documents, only across the
    windows of a single long one, which our short answers never need.
    """
    probs = np.empty(len(frame), dtype=float)
    start = time.perf_counter()
    for i, text in enumerate(frame["answer"]):
        try:
            probs[i] = scorer.score(str(text))["p_ai"]
        except ValueError:
            # "no scoreable tokens" - an empty/unusable answer slipped through
            probs[i] = float("nan")
        if (i + 1) % 200 == 0 or i + 1 == len(frame):
            elapsed = time.perf_counter() - start
            print(f"  {split_name}: {i + 1}/{len(frame)} scored ({elapsed:.0f}s)", flush=True)
    return probs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-fpr", type=float, default=0.01,
                        help="FPR budget to fit the threshold at - matches "
                             "metrics.py's fixed project-wide HEADLINE_FPR")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--owner", default="malcolm", help="tag for whose run this is on the shared DagsHub board")
    args = parser.parse_args()

    if not SPLITS_PATH.exists():
        raise SystemExit(f"{SPLITS_PATH} not found - run `dvc pull` in ml-training/ first")

    df = pd.read_parquet(SPLITS_PATH)
    val = df[df["partition"] == "val"].reset_index(drop=True)
    test = df[df["partition"] == "test"].reset_index(drop=True)
    print(f"val: {len(val)} rows ({val['label'].mean():.1%} AI)")
    print(f"test: {len(test)} rows ({test['label'].mean():.1%} AI)")

    print("\nLoading MELD (downloads ~4.1GB on first run, cached after)...")
    scorer = load_meld_scorer(device=args.device)

    setup_mlflow(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name="meld-zeroshot"):
        mlflow.set_tags({"owner": args.owner, "run_role": "eval", "tuning_method": "zeroshot"})
        mlflow.log_params({
            "model": MELD_REPO,
            "target_fpr": args.target_fpr,
            "val_n": len(val),
            "test_n": len(test),
            "data_md5": DATA_MD5,
        })

        print("\nScoring val...")
        val_probs = score_split(scorer, val, "val")
        print("\nScoring test...")
        test_probs = score_split(scorer, test, "test")

        # drop any answer MELD couldn't score at all, from both the probs and labels
        val_ok = ~np.isnan(val_probs)
        test_ok = ~np.isnan(test_probs)
        if (~val_ok).any() or (~test_ok).any():
            print(f"\ndropped unscoreable answers: {(~val_ok).sum()} val, {(~test_ok).sum()} test")

        threshold = threshold_at_fpr(val["label"][val_ok], val_probs[val_ok], args.target_fpr)
        print(f"\nthreshold fit on val at target_fpr={args.target_fpr}: {threshold:.4f}")
        mlflow.log_metric("threshold", threshold)

        results = evaluate(
            test["label"][test_ok], test_probs[test_ok], threshold,
            headline_fpr=args.target_fpr,
        )
        log_split_metrics(results, "test")

        test_predictions = test.loc[test_ok, ["answer_id", "question_id", "label", "generator"]].copy()
        test_predictions = test_predictions.rename(columns={"label": "y_true"})
        test_predictions["y_prob"] = test_probs[test_ok]
        log_predictions(test_predictions, "test")

        print("\n=== MELD zero-shot, test split ===")
        for key in ("auroc", "deployed_tpr", "deployed_fpr", "deployed_precision", "ece", "brier"):
            print(f"  {key}: {results[key]:.4f}")

        payload = {
            "model": "MELD (zero-shot, anon-review-meld-2026/meld)",
            "target_fpr": args.target_fpr,
            "threshold": threshold,
            "val_n": int(val_ok.sum()),
            "test_n": int(test_ok.sum()),
            "results": {k: float(v) for k, v in results.items()},
        }
        log_dict_artifact(payload, "zeroshot_results.json")

        OUT_PATH.parent.mkdir(exist_ok=True)
        OUT_PATH.write_text(json.dumps(payload, indent=2))
        print(f"\nWrote {OUT_PATH}")
        print(f"MLflow run: {mlflow.active_run().info.run_id}")


if __name__ == "__main__":
    main()
