## combines two fine-tuned models into one detector by averaging their calibrated scores, e.g. desklib + RADAR
## writes the combination as normal scores files, so harness.py evaluates and compares it like any other model

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit, logit

import harness
import metrics
from scores import COLUMNS, OUT_DIRECTORY, load_scores, validate

##  the defaults: RADAR's best (full fine-tune, 8 epochs) and desklib's best (Malcolm's confirm run), seeds 1 2 3 of each
DEFAULT_A = "radar-full-e8-extended"
DEFAULT_B = "desklib-lora-confirm-qkvf-r64-e8"

##  weights tried by --weight val. the weight is the share given to model B (desklib); A gets the rest
WEIGHT_GRID = (0.3, 0.4, 0.5, 0.6, 0.7)

##  finds the scores file of one run: outputs/<run>_scores.parquet if it's there, otherwise downloads it from the
##  run's predictions/ folder on DagsHub (into a temporary folder, the repo is not touched)
##  raises SystemExit if the run or its scores file can't be found
##
##  run_name:   the MLflow run name, e.g. radar-full-e8-extended-s1
##  returns the path of the scores file
def find_scores(run_name: str) -> Path:
    local = OUT_DIRECTORY / f"{run_name}_scores.parquet"
    if local.exists():
        return local

    import mlflow
    from tracking import setup_mlflow

    setup_mlflow()
    runs = mlflow.search_runs(search_all_experiments=True, filter_string=f"tags.mlflow.runName = '{run_name}'",
                              output_format="list")
    runs = [r for r in runs if r.info.status == "FINISHED"]
    if not runs:
        raise SystemExit(f"no finished run named {run_name} on DagsHub")

    artifact = f"predictions/{run_name}_scores.parquet"
    path = mlflow.artifacts.download_artifacts(run_id=runs[0].info.run_id, artifact_path=artifact,
                                               dst_path=tempfile.mkdtemp(prefix="ensemble-"))
    return Path(path)

##  the tuned model's rows from one scores file (the -untouched rows are dropped)
##  raises SystemExit if the file holds more or fewer than one tuned model
##
##  path:   a scores file
##  returns (model name, rows with split, answer_id, question_id, y_true, y_prob, run_id)
def tuned_rows(path: Path) -> tuple[str, pd.DataFrame]:
    scores = load_scores(path)
    tuned = sorted(m for m in scores["model"].unique() if not m.endswith("-untouched"))
    if len(tuned) != 1:
        raise SystemExit(f"{path.name}: expected one tuned model, found {tuned}")
    rows = scores[scores["model"] == tuned[0]]
    return tuned[0], rows[["split", "answer_id", "question_id", "y_true", "y_prob", "run_id"]].reset_index(drop=True)

##  joins model A's and model B's rows for one seed on (split, answer_id), checking they cover the same answers with the
##  same labels, and turns each calibrated probability back into a log-odds score (the scale the two are averaged on)
##  raises SystemExit if the two files don't cover exactly the same answers
##
##  a, b:   rows from tuned_rows() for model A and model B
##  returns one row per answer with columns z_a and z_b (log-odds) plus split, answer_id, question_id, y_true
def pair_rows(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    merged = a.merge(b, on=["split", "answer_id"], suffixes=("_a", "_b"), validate="one_to_one")
    if len(merged) != len(a) or len(merged) != len(b):
        raise SystemExit(f"the two scores files don't cover the same answers ({len(a)} vs {len(b)} rows, {len(merged)} shared)")
    if (merged["y_true_a"] != merged["y_true_b"]).any():
        raise SystemExit("the two scores files disagree on labels")

    eps = 1e-7
    return pd.DataFrame({
        "split": merged["split"],
        "answer_id": merged["answer_id"],
        "question_id": merged["question_id_a"],
        "y_true": merged["y_true_a"],
        "z_a": logit(np.clip(merged["y_prob_a"], eps, 1 - eps)),
        "z_b": logit(np.clip(merged["y_prob_b"], eps, 1 - eps)),
    })

##  picks the weight on VALIDATION only: the grid weight whose combination catches the most AI at exactly 1% FPR on val,
##  averaged over the seed pairs. never looks at test, so the test numbers stay honest
##
##  pairs:      one pair_rows() frame per seed
##  n_words:    {answer_id: word count}, to keep the same >= min_words answers the threshold is fitted on
##  min_words:  shortest answer used
##  returns the chosen weight for model B
def choose_weight(pairs: list[pd.DataFrame], n_words: pd.Series, min_words: int) -> float:
    def val_tpr(pair, w):
        v = pair[(pair["split"] == "val") & (pair["answer_id"].map(n_words) >= min_words)]
        return metrics.oracle_tpr_at_fpr(v["y_true"], expit((1 - w) * v["z_a"] + w * v["z_b"]), metrics.HEADLINE_FPR)

    scores = {w: float(np.mean([val_tpr(p, w) for p in pairs])) for w in WEIGHT_GRID}
    print("val AI caught at exactly 1% FPR by weight on B: " + "  ".join(f"{w}={s:.3f}" for w, s in scores.items()))
    return max(scores, key=scores.get)

##  writes one seed's combination as a scores file (val and test rows, every answer, like any model's)
##  logit = the weighted average log-odds, y_prob = sigmoid(logit). no extra temperature: both inputs are already calibrated
##
##  pair:       pair_rows() frame for this seed
##  weight:     share given to model B
##  model:      the `model` column, e.g. ensemble-radar-desklib
##  run_name:   names the file outputs/<run_name>_scores.parquet
##  seed:       the seed of the two runs combined
##  run_id:     recorded in the file, built from the two source run ids so the combination is traceable
##  returns the path written
def write_combination(pair: pd.DataFrame, weight: float, model: str, run_name: str, seed: int, run_id: str) -> Path:
    z = (1 - weight) * pair["z_a"] + weight * pair["z_b"]
    out = pd.DataFrame({
        "run_id": run_id, "model": model, "seed": seed, "split": pair["split"], "answer_id": pair["answer_id"],
        "question_id": pair["question_id"], "y_true": pair["y_true"].astype(np.int64), "logit": z, "y_prob": expit(z),
    })[COLUMNS]
    OUT_DIRECTORY.mkdir(exist_ok=True)
    path = OUT_DIRECTORY / f"{run_name}_scores.parquet"
    validate(out).to_parquet(path, index=False)
    return path

##  the run, in order:
##      1. find the scores files of model A and model B for each seed (local outputs/ first, then DagsHub)
##      2. pair them answer by answer, check they match
##      3. pick the weight (a number, or --weight val to choose it on validation only)
##      4. write one combination scores file per seed: outputs/ensemble-<a>+<b>-s<seed>_scores.parquet
##      5. evaluate with harness.py: per-seed metrics, mean over seeds, and the paired test against model B on its own
##  nothing is logged to DagsHub. the combination files are ordinary scores files, so they can be shared or uploaded later
def main() -> None:
    ap = argparse.ArgumentParser(description="Average two fine-tuned models' calibrated scores and evaluate the result.")
    ap.add_argument("--a", default=DEFAULT_A, help="run name of model A without -s<seed> (default: RADAR's best)")
    ap.add_argument("--b", default=DEFAULT_B, help="run name of model B without -s<seed> (default: desklib's best)")
    ap.add_argument("--seeds", default="1,2,3", help="seeds to pair: run A -s1 with run B -s1, and so on")
    ap.add_argument("--weight", default="0.5", help='share given to B (0-1), or "val" to choose it on validation only')
    ap.add_argument("--model-name", default="ensemble-radar-desklib", help="the `model` column the harness groups by")
    ap.add_argument("--min-words", type=int, default=harness.MIN_WORDS)
    args = ap.parse_args()
    seeds = [int(s) for s in args.seeds.split(",") if s]

    n_words = harness.load_meta().drop_duplicates("answer_id").set_index("answer_id")["n_words"]
    pairs, sources = [], []
    for seed in seeds:
        path_a, path_b = find_scores(f"{args.a}-s{seed}"), find_scores(f"{args.b}-s{seed}")
        (model_a, a), (model_b, b) = tuned_rows(path_a), tuned_rows(path_b)
        pairs.append(pair_rows(a, b))
        sources.append((path_a, path_b, f"{a['run_id'].iloc[0]}+{b['run_id'].iloc[0]}"))
        print(f"seed {seed}: {model_a} ({path_a.name}) + {model_b} ({path_b.name}), {len(pairs[-1])} answers")

    weight = choose_weight(pairs, n_words, args.min_words) if args.weight == "val" else float(args.weight)
    if not 0 <= weight <= 1:
        raise SystemExit("--weight must be between 0 and 1, or val")
    print(f"weight: {1 - weight:.2f} x {model_a} + {weight:.2f} x {model_b}")

    written = []
    for seed, pair, (_, _, run_id) in zip(seeds, pairs, sources):
        run_name = f"{args.model_name}-s{seed}"
        written.append(write_combination(pair, weight, args.model_name, run_name, seed, run_id))
        print(f"wrote {written[-1]}")

    df = harness.load_runs(written + [p for _, p, _ in sources] + [p for p, _, _ in sources])
    table = harness.compare_models(df, models=[args.model_name, model_a, model_b], min_words=(args.min_words,))
    summary = harness.aggregate_seeds(table)
    pd.set_option("display.width", 250)
    cols = ["model", "n_runs"] + [f"{m}_{s}" for m in harness.SEED_SUMMARY_METRICS for s in ("mean", "std")
                                  if f"{m}_{s}" in summary.columns]
    print(f"\n=== test split, answers of >= {args.min_words} words, mean and spread over seeds ===")
    print(summary[cols].round(3).to_string(index=False))

    print(f"\n=== paired test: {args.model_name} minus each model on its own (95% interval, whole questions resampled) ===")
    for other in (model_b, model_a):
        for metric in ("oracle_tpr_at_fpr_0.01", "deployed_tpr", "auroc"):
            r = harness.compare_pair(df, args.model_name, other, metric=metric, min_words=args.min_words)
            print(f"  vs {other:<26} {metric:<24} {r['diff']:+.4f}  [{r['ci_low']:+.4f}, {r['ci_high']:+.4f}]  "
                  f"better in {r['share_a_better']:.0%} of draws  {'REAL GAP' if r['gap_is_clear'] else 'could be noise'}")


if __name__ == "__main__":
    main()
