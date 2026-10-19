## per-answer scores file that the shared evaluation harness reads from every run

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.special import expit

OUT_DIRECTORY = Path(__file__).parent / "outputs"
COLUMNS = ["run_id", "model", "seed", "split", "answer_id", "question_id", "y_true", "logit", "y_prob"]
SPLITS = ("val", "test")

##  builds the scores-file rows for one model on one split - one row per answer
##  a fine-tuning run calls this 4 times (untouched validation, untouched test, tuned validation and tuned test)
##  it passes the results to save_scored().
##
##  model:  the name written to the file (radar-untouched/radar-lora, etc)
##  split:  the split name (val/test)
##  frame:  the split's rows from load_combined(). uses its answer_id, question_id and label columns
##  label:  the true label for reach row (1 = AI, 0 = human)
##  logits: the model's raw output for each row, before temperature scaling
##  y_prob: the probability that the threshold is applied to -> sigmoid(logit) for untouched model, sigmoid(logit/T) for the tuned model
def score_rows(model: str, split: str, frame: pd.DataFrame, logits, y_prob) -> pd.DataFrame:
    logits, y_prob = np.asasrray(logits, dtype=np.float64), np.asarray(y_prob, dtype=np.float64)
    if not lens(frame) == len(logits) == len(y_prob):
        raise ValueError(f"{model}/{split}: {len(frame)} rows but {len(logits)} logits and {len(y_prob)} probs")

    return pd.DataFrame({
        "model": model,
        "split": split,
        "answer_id": frame["answer_id"].to_numpy(),
        "question_id": frame["question_id"].to_numpy(),
        "y_true": frame["label"].to_numpy(dtype=np.int64),
        "logit": logits,
        "y_prob": y_prob,
    })

##  checks a whole scores file and raises ValueError on the first issue found.
##  runs in 2 places: 
##      - save_scores() before writing, so that a bad file is never saved
##      - load_scores() after reading, so that the harness never computes metrics from a bad file
##  it returns the same unchange DataFrame when every check passes
##  the checks:
##      - all nine columns in COLUMNS are present
##      - every row's split is 'val' or 'test' and 'train' rows are refused
##      - each model has both val and test rows, since the harness fits the treshold on val and measures on test. 
##        it is checked per model, so that a file holding radar-untouched and radar-lora needs all 4 combinations
##      - no answer_id appears twice for the same model and split
##      - y_true is only 0 (human) or 1 (AI)
##      - logit and y_prob are between 0 and 1
##      - for any model named "*-untouched", y_prob = sigmoid(logit). 
##        the untouched model is never calibrated, so a mismatch would indicate that the temperature scaling was applied by mistake
def validate(scores: pd.DataFrame) -> pd.DataFrame:
    if missing := set(COLUMNS) - set(scores.columns):
        raise ValueError(f"scores missing columns: {sorted(missing)}")

    if bad := set(scores["split"]) - set(SPLITS):
        raise ValueError(f"only val and test rows belong in a scores file, got {sorted(bad)}")

    for model, group in scores.groupby("model"):
        if have := set(group["split"]) ^ set(SPLITS):
            raise ValueError(f"{model}: needs both val and test splits, mismatched on {sorted(have)}")
        if dupes := int(group.duplicated(["split", "answer_id"]).sum()):
            raise ValueError(f"{model}: {dupes} answer_id values repeat within a split")

    if not scores["y_true"].isin([0, 1]).all():
        raise ValueError("y_true must be 0 (human) or 1 (AI)")

    if not np.isfinite(scores[["logit", "y_prob"]].to_numpy()).all():
        raise ValueError("logit and y_prob must be finite")

    if not scores["y_prob"].between(0, 1).all():
        raise ValueError("y_prob must be a probability in [0, 1]")

    untouched = scores["model"].str.endswith("-untouched")

    if untouched.any() and not np.allclose(scores.loc[untouched, "y_prob"], expit(scores.loc[untouched, "logit"]), atol=1e-6):
        raise ValueError("an -untouched model's y_prob must be sigmoid(logit), before any temperature scaling")
    return scores

##  combines a run's score rows into one file, checks it, saves it, and uploads it to MLflow
##  call it once at the end of a run, inside `with mlflow.start_run(***)` block.
##
##  run_name:   names the file: 'outputs/<run_name>_scores.parquet'. 
##  seed:       the run's random seed (written on every row)
##  parts:      the DataFrames from score_rows(): 4 for the fine-tuning run (untouched and tuned, val and test), 2 for a zero-shot run
##  run_id:     leave empty inside an MLflow run and the active run's id is used. 
##  out_dir:    folder to write to
def save_scores(run_name: str, seed: int, parts: Iterable[pd.DataFrame], run_id: str | None = None, out_dir: Path = OUT_DIRECTORY) -> Path:
    import mlflow

    active = mlflow.active_run()
    run_id = run_id or (active.info.run_id if active else None)

    if run_id is None:
        raise RuntimeError("no run_id given and no active MLflow run")

    scores = pd.concat(list(parts), ignore_index=True)
    scores.insert(0, "seed", int(seed))
    scores.insert(0, "run_id", run_id)
    scores = validate(scores[COLUMNS])

    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"{run_name}_scores.parquet"
    scores.to_parquet(path, index=False)

    if active:
        mlflow.log_artifact(str(path), "predictions")
    print(f"Wrote {path} ({len(scores)} rows: {scores.groupby(['model', 'split']).size().to_dict()})")
    return path

def load_scores(path: str | Path) -> pd.DataFrame:
    return validate(pd.read_parquet(path))
