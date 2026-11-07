
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
from combined_data import DATA_DIR, load_corpus, slice_flag_rates
from metrics import evaluate, threshold_at_fpr
from scores import OUT_DIRECTORY, save_scores, score_rows
from tracking import _git_state, log_dict_artifact, log_split_metrics, setup_mlflow

##  same experiment and run-name pattern as the desklib and MELD zero-shot runs, so they sit side by side on DagsHub.
##  the run is named radar-zeroshot-<data>, e.g. radar-zeroshot-extended
MLFLOW_EXPERIMENT = "zeroshot-baselines"
MODEL_NAME = "radar-untouched"

##  zero-shot has no randomness (no training, no sampling), so the scores file records seed 0
SEED = 0

##  only used with --data combined (the old v0.1 + spliced corpus): reworded AI answers, all label 1, scored as extra test sets.
##  only their test rows are used, and they are kept out of the main metrics and the scores file.
##  the extended corpus (the default) already holds them inside val and test as slices, so there they're in the normal metrics
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

##  the run, in order (the same protocol as desklib's zero-shot and the harness):
##      1. load val and test (--data, extended by default; for combined also the robustness test sets)
##      2. score every row with untouched RADAR
##      3. using only answers of at least --min-words words (the app doesn't score shorter ones):
##         fit the 1% FPR threshold on val, then score test once with it frozen, with confidence intervals by whole question
##      4. log metrics and per-slice flag rates to MLflow, and save the scores file with EVERY val and test row for the harness
##  --offline logs to a temporary local folder instead of DagsHub, for testing the script without adding a run to the shared board
def main() -> None:
    ap = argparse.ArgumentParser(description="Zero-shot RADAR (PP-547).")
    ap.add_argument("--data", default="extended", choices=["extended", "combined"],
                    help="extended = v0.1-extended, the team's corpus (default); combined = the old v0.1 + spliced")
    ap.add_argument("--min-words", type=int, default=10,
                    help="only answers of at least this many words fit the threshold and enter the metrics; 0 keeps every answer")
    ap.add_argument("--target-fpr", type=float, default=0.01, help="false-positive budget the threshold is fitted at, on val")
    ap.add_argument("--device", default=None, help="cuda, mps or cpu (default: best available)")
    ap.add_argument("--owner", default="faheem", help="whose run this is on the shared DagsHub board")
    ap.add_argument("--offline", action="store_true", help="log to a temporary local folder, not DagsHub")
    args = ap.parse_args()

    run_name = f"radar-zeroshot-{args.data}"
    frames = load_corpus(args.data)
    val, test = frames["val"], frames["test"]
    robustness = load_robustness_sets() if args.data == "combined" else {}
    vmask = (val["n_words"] >= args.min_words).to_numpy()
    tmask = (test["n_words"] >= args.min_words).to_numpy()
    val_used, test_used = val[vmask].reset_index(drop=True), test[tmask].reset_index(drop=True)
    print(f"val: {len(val)} rows ({val['label'].mean():.1%} AI), test: {len(test)} rows ({test['label'].mean():.1%} AI)")
    print(f"answers of >= {args.min_words} words used for the threshold and metrics: val {len(val_used)}, test {len(test_used)}")
    if robustness:
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

    with mlflow.start_run(run_name=run_name):
        mlflow.set_tags({"owner": args.owner, "run_role": "eval", "tuning_method": "zeroshot",
                         "model_family": "radar", **_git_state()})
        mlflow.log_params({
            "model": f"{radar.MODEL_ID}@{radar.REVISION[:12]}",
            "data": args.data,
            "min_words": args.min_words,
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

        threshold = threshold_at_fpr(val_used["label"], val_prob[vmask], args.target_fpr)
        mlflow.log_metric("threshold", threshold)
        print(f"\nthreshold fitted on val at {args.target_fpr:.0%} FPR: {threshold:.4f}")

        results = evaluate(test_used["label"], test_prob[tmask], threshold, headline_fpr=args.target_fpr,
                           groups=test_used["question_id"].to_numpy())
        log_split_metrics(results, "test")
        mlflow.log_metric("val/auroc", float(roc_auc_score(val_used["label"], val_logits[vmask])))

        print("\n=== RADAR zero-shot, test split ===")
        for key in ("auroc", "deployed_tpr", "deployed_fpr", "deployed_precision", "ece", "brier"):
            print(f"  {key}: {results[key]:.4f}")

        slices = slice_flag_rates(test_used, test_prob[tmask], threshold)
        print("\n  per slice (flag rate at the frozen threshold; human = FPR, rest = TPR):")
        for row in slices:
            print(f"    {row['slice']:<18} n={row['n']:<5} {row['kind']}={row['flag_rate']:.3f}")
            mlflow.log_metric(f"test/slice_{row['slice'].replace('-', '_')}_flag_rate", row["flag_rate"])

        robust = {}
        if robustness:
            used_logits = {k: v[(robustness[k]["n_words"] >= args.min_words).to_numpy()] for k, v in set_logits.items()}
            robust = robustness_metrics(test_logits[tmask & (test["label"].to_numpy() == 0)], used_logits, threshold)
            print("\n  robustness (reworded AI answers vs the test human answers):")
            for name, row in robust.items():
                print(f"    {name:<13} n={row['n']:<5} flag_rate={row['flag_rate']:.3f}  auroc={row['auroc']:.3f}")
                mlflow.log_metrics({f"test/robust_{name}_flag_rate": row["flag_rate"], f"test/robust_{name}_auroc": row["auroc"]})

        save_scores(run_name, SEED, [
            score_rows(MODEL_NAME, "val", val, val_logits, val_prob),
            score_rows(MODEL_NAME, "test", test, test_logits, test_prob),
        ])

        payload = {
            "model": f"{radar.MODEL_ID}@{radar.REVISION}",
            "data": args.data,
            "min_words": args.min_words,
            "target_fpr": args.target_fpr,
            "threshold": threshold,
            "val_n": len(val),
            "test_n": len(test),
            "val_used": len(val_used),
            "test_used": len(test_used),
            "results": {k: float(v) for k, v in results.items()},
            "slices": slices,
            "robustness": robust,
        }
        log_dict_artifact(payload, "zeroshot_results.json")
        out_path = OUT_DIRECTORY / f"{run_name}_results.json"
        out_path.write_text(json.dumps(payload, indent=2))
        print(f"\nWrote {out_path}")
        print(f"MLflow run: {mlflow.active_run().info.run_id}")

if __name__ == "__main__":
    main()
