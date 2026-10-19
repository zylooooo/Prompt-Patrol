
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.metrics import roc_auc_score

import radar
from combined_data import DATA_DIR, load_combined, slice_flag_rates
from metrics import evaluate, threshold_at_fpr
from scores import OUT_DIRECTORY, save_scores, score_rows
from tracking import _git_state, log_dict_artifact, log_split_metrics, setup_mlflow

##  same experiment and run-name pattern as the desklib and MELD zero-shot runs, so they sit side by side on DagsHub
MLFLOW_EXPERIMENT = "zeroshot-baselines"
RUN_NAME = "radar-zeroshot-combined"
MODEL_NAME = "radar-untouched"

##  zero-shot has no randomness (no training, no sampling), so the scores file records seed 0
SEED = 0

##  reworded AI answers, all label 1, scored as extra test sets to see whether RADAR still catches AI text after rewording.
##  only their test rows are used, and they are kept out of the main metrics and the scores file, so the headline numbers stay comparable with desklib's and MELD's
ROBUSTNESS_SETS = {
    "paraphrased": DATA_DIR / "v0.1-paraphrased.parquet",
    "human_edited": DATA_DIR / "v0.1-human_edited.parquet",
}

##  loads the test rows of each robustness set
##  raises FileNotFoundError if a file is missing (run `dvc pull` in ml-training/ first)
def load_robustness_sets() -> dict[str, pd.DataFrame]:
    sets = {}
    for name, path in ROBUSTNESS_SETS.items():
        if not path.exists():
            raise FileNotFoundError(f"{path} not found - run `dvc pull` in ml-training/ first")
        frame = pd.read_parquet(path)
        sets[name] = frame[frame["partition"] == "test"].reset_index(drop=True)
    return sets

##  how RADAR does on each robustness set, at the threshold frozen on val
##      - flag_rate:    share of the reworded AI answers flagged as AI (higher is better)
##      - auroc:        how well it separates them from the human answers in the main test split
##
##  human_logits:   logits of the human answers in the main test split
##  set_logits:     {set name: logits of that set's answers}
##  threshold:      the probability threshold fitted on val
def robustness_metrics(human_logits: np.ndarray, set_logits: dict[str, np.ndarray], threshold: float) -> dict[str, dict]:
    out = {}
    for name, logits in set_logits.items():
        y = np.r_[np.zeros(len(human_logits)), np.ones(len(logits))]
        out[name] = {
            "n": len(logits),
            "flag_rate": float((expit(logits) >= threshold).mean()),
            "auroc": float(roc_auc_score(y, np.r_[human_logits, logits])),
        }
    return out

##  scores one set of answers and prints how long it took
##
##  name:   label for the printout (val/test/paraphrased, etc)
##  frame:  the rows to score, uses the answer column
def score(model, tokenizer, device, name: str, frame: pd.DataFrame) -> np.ndarray:
    start = time.perf_counter()
    logits = radar.predict_logits(model, tokenizer, frame["answer"].to_numpy(), device)
    print(f"  {name}: {len(frame)} answers scored in {time.perf_counter() - start:.0f}s", flush=True)
    return logits

##  the run, in order:
##      1. load val and test (v0.1 + spliced, same rows as desklib and MELD) and the robustness test sets
##      2. score everything with untouched RADAR
##      3. fit the 1% FPR threshold on val, then score test once with it frozen
##      4. log metrics, per-slice flag rates and robustness numbers to MLflow, and save the scores file for the harness
##  --offline logs to a temporary local folder instead of DagsHub, for testing the script without adding a run to the shared board
def main() -> None:
    ap = argparse.ArgumentParser(description="Zero-shot RADAR on the combined corpus (PP-547).")
    ap.add_argument("--target-fpr", type=float, default=0.01, help="false-positive budget the threshold is fitted at, on val")
    ap.add_argument("--device", default=None, help="cuda, mps or cpu (default: best available)")
    ap.add_argument("--owner", default="faheem", help="whose run this is on the shared DagsHub board")
    ap.add_argument("--offline", action="store_true", help="log to a temporary local folder, not DagsHub")
    args = ap.parse_args()

    frames = load_combined()
    val, test = frames["val"], frames["test"]
    robustness = load_robustness_sets()
    print(f"val: {len(val)} rows ({val['label'].mean():.1%} AI), test: {len(test)} rows ({test['label'].mean():.1%} AI)")
    print("robustness test sets: " + ", ".join(f"{k}={len(v)}" for k, v in robustness.items()))

    print("\nLoading RADAR (downloads ~1.4GB on the first run, cached after)...")
    model, tokenizer, device = radar.load_radar(args.device)

    if args.offline:
        tmp = Path(tempfile.mkdtemp(prefix="radar-offline-"))
        mlflow.set_tracking_uri(f"sqlite:///{tmp / 'mlflow.db'}")
        mlflow.create_experiment(MLFLOW_EXPERIMENT, artifact_location=(tmp / "artifacts").as_uri())
        mlflow.set_experiment(MLFLOW_EXPERIMENT)
        print(f"OFFLINE: logging to {mlflow.get_tracking_uri()}, nothing goes to DagsHub")
    else:
        setup_mlflow(MLFLOW_EXPERIMENT)

    with mlflow.start_run(run_name=RUN_NAME):
        mlflow.set_tags({"owner": args.owner, "run_role": "eval", "tuning_method": "zeroshot",
                         "model_family": "radar", **_git_state()})
        mlflow.log_params({
            "model": f"{radar.MODEL_ID}@{radar.REVISION[:12]}",
            "data": "v0.1+spliced",
            "target_fpr": args.target_fpr,
            "max_len": radar.MAX_LEN,
            "val_n": len(val),
            "test_n": len(test),
            **{f"{k}_test_n": len(v) for k, v in robustness.items()},
        })

        print(f"\nScoring on {device}...")
        val_logits = score(model, tokenizer, device, "val", val)
        test_logits = score(model, tokenizer, device, "test", test)
        set_logits = {name: score(model, tokenizer, device, name, frame) for name, frame in robustness.items()}
        val_prob, test_prob = expit(val_logits), expit(test_logits)

        threshold = threshold_at_fpr(val["label"], val_prob, args.target_fpr)
        mlflow.log_metric("threshold", threshold)
        print(f"\nthreshold fitted on val at {args.target_fpr:.0%} FPR: {threshold:.4f}")

        results = evaluate(test["label"], test_prob, threshold, headline_fpr=args.target_fpr)
        log_split_metrics(results, "test")
        mlflow.log_metric("val/auroc", float(roc_auc_score(val["label"], val_logits)))

        print("\n=== RADAR zero-shot, test split ===")
        for key in ("auroc", "deployed_tpr", "deployed_fpr", "deployed_precision", "ece", "brier"):
            print(f"  {key}: {results[key]:.4f}")

        slices = slice_flag_rates(test, test_prob, threshold)
        print("\n  per slice (flag rate at the frozen threshold; human = FPR, rest = TPR):")
        for row in slices:
            print(f"    {row['slice']:<11} n={row['n']:<5} {row['kind']}={row['flag_rate']:.3f}")
            mlflow.log_metric(f"test/slice_{row['slice'].replace('-', '_')}_flag_rate", row["flag_rate"])

        robust = robustness_metrics(test_logits[test["label"].to_numpy() == 0], set_logits, threshold)
        print("\n  robustness (reworded AI answers vs the test human answers):")
        for name, row in robust.items():
            print(f"    {name:<13} n={row['n']:<5} flag_rate={row['flag_rate']:.3f}  auroc={row['auroc']:.3f}")
            mlflow.log_metrics({f"test/robust_{name}_flag_rate": row["flag_rate"], f"test/robust_{name}_auroc": row["auroc"]})

        save_scores(RUN_NAME, SEED, [
            score_rows(MODEL_NAME, "val", val, val_logits, val_prob),
            score_rows(MODEL_NAME, "test", test, test_logits, test_prob),
        ])

        payload = {
            "model": f"{radar.MODEL_ID}@{radar.REVISION}",
            "data": "v0.1+spliced",
            "target_fpr": args.target_fpr,
            "threshold": threshold,
            "val_n": len(val),
            "test_n": len(test),
            "results": {k: float(v) for k, v in results.items()},
            "slices": slices,
            "robustness": robust,
        }
        log_dict_artifact(payload, "zeroshot_results.json")
        out_path = OUT_DIRECTORY / f"{RUN_NAME}_results.json"
        out_path.write_text(json.dumps(payload, indent=2))
        print(f"\nWrote {out_path}")
        print(f"MLflow run: {mlflow.active_run().info.run_id}")

if __name__ == "__main__":
    main()
