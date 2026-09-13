"""
Fine-tune a baseline detector, end to end.

The script is generic on purpose: it takes a RunConfig and executes it. Every
choice that could differ between runs lives in the config, so running
ROBERTA_DORA or ROBERTA_FULL instead is a one-line change at the bottom and
nothing else - which is what keeps the delta between them attributable to the
tuning method rather than to a script edit.

    python trial-training.py
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from torch.utils.data import Dataset
import mlflow
import numpy as np
import torch
from peft import LoraConfig, get_peft_model
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    EarlyStoppingCallback,
    Trainer,
    TrainingArguments,
    set_seed,
)

from config import RunConfig
from metrics import (
    LENGTH_BINS,
    POSITIVE_LABEL,
    SLICE_BY,
    evaluate,
    operating_point_metrics,
    ranking_metrics,
    slice_report,
    threshold_at_fpr,
)
from tracking import (
    log_model_size,
    log_predictions,
    log_slice_table,
    log_split_metrics,
    log_thresholds,
    start_run,
)

PARTITIONS = ("train", "val", "test")


# --------------------------------------------------------------------------
# base model identity
# --------------------------------------------------------------------------

def resolve_base_model_sha(cfg: RunConfig) -> str:
    """
    Ask the Hub what cfg.model.revision actually resolves to.

    Passing revision= to from_pretrained already pins the checkout. What this
    adds is a record: when the revision is a sha it confirms the repo still
    serves that commit, and when someone writes revision="main" it captures
    what main was at run time, which is the only way that run stays
    reproducible after the branch moves.

    Network failure is not fatal - a run that cannot reach the Hub can still
    train from cache; it just cannot prove which commit it used.
    """
    try:
        from huggingface_hub import HfApi

        sha = HfApi().model_info(cfg.model.base_model, revision=cfg.model.revision).sha
    except Exception as exc:                       # offline, rate-limited, gated
        return f"unresolved: {type(exc).__name__}"

    pinned = cfg.model.revision
    if len(pinned) == 40 and sha != pinned:
        raise RuntimeError(
            f"{cfg.model.base_model} revision {pinned} resolved to {sha}"
        )
    return sha


def load_tokenizer(cfg: RunConfig):
    return AutoTokenizer.from_pretrained(
        cfg.model.base_model, revision=cfg.model.revision
    )


# --------------------------------------------------------------------------
# splits
# --------------------------------------------------------------------------

def load_splits(cfg: RunConfig) -> dict[str, pd.DataFrame]:
    """
    Read the DVC-tracked split file and hand back one frame per partition.

    Every check below raises rather than warns, because each of these faults
    produces a plausible-looking number instead of a crash. A run that fails
    loudly here costs ten minutes; one that succeeds quietly costs a result
    nobody can defend.
    """
    path = Path(cfg.data.splits)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run `dvc pull` first")

    df = pd.read_parquet(path)

    required = {"answer", "label", "partition", "question_id", "answer_id",
                "generator", "n_words"}
    if missing := required - set(df.columns):
        raise ValueError(f"{path} missing columns: {sorted(missing)}")

    # A question with its human answers in train and its AI answer in test
    # lets the detector score the topic rather than the authorship, and every
    # metric downstream comes out too good.
    spans = df.groupby("question_id")["partition"].nunique()
    if len(leaked := spans[spans > 1]):
        raise ValueError(f"{len(leaked)} question(s) span partitions: "
                         f"{list(leaked.index[:5])}")

    # predictions are joined back on answer_id; duplicates silently fan out
    if not df["answer_id"].is_unique:
        raise ValueError("answer_id is not unique")

    frames = {p: g.reset_index(drop=True) for p, g in df.groupby("partition")}
    if set(frames) != set(PARTITIONS):
        raise ValueError(f"expected {PARTITIONS}, found {sorted(frames)}")

    return frames


class AnswerDataset(Dataset):
    """
    The answer text only. The question is deliberately withheld.

    Every question in this corpus has exactly one AI answer, so a model that
    can see the question can score well by memorising which questions it has
    met rather than by detecting machine text. Pair encoding is the right
    final design - the deployed app always holds the question, and
    question/answer coherence is real signal - but it needs a corpus with
    several AI answers per question before that shortcut closes.
    """

    def __init__(self, frame: pd.DataFrame, tokenizer, max_length: int):
        # no padding here: DataCollatorWithPadding pads per batch, so a batch
        # of 10-word answers is not blown up to max_length
        self.encodings = tokenizer(
            frame["answer"].tolist(), truncation=True, max_length=max_length
        )
        self.labels = frame["label"].tolist()

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, i: int) -> dict:
        return {k: v[i] for k, v in self.encodings.items()} | {"labels": self.labels[i]}


def truncation_report(frames: dict[str, pd.DataFrame], tokenizer,
                      max_length: int) -> dict[str, dict[str, float]]:
    """
    Evidence for the max_length in the config. Truncating an answer removes
    exactly the tail a detector might be reading, so this belongs in the run
    record rather than in a comment.
    """
    out = {}
    for part, frame in frames.items():
        lengths = [len(ids) for ids in
                   tokenizer(frame["answer"].tolist())["input_ids"]]
        out[part] = {
            "tokens_p50": float(pd.Series(lengths).median()),
            "tokens_max": float(max(lengths)),
            "truncated_pct": float(
                100.0 * sum(n > max_length for n in lengths) / len(lengths)
            ),
        }
    return out


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------

def build_model(cfg: RunConfig):
    """
    The base checkpoint, plus an adapter if the tuning method calls for one.

    Which of LoRA / DoRA / full fine-tune happens is read from
    cfg.model.tuning_method and nowhere else, and the adapter kwargs come from
    cfg.peft_kwargs(). LoRA and DoRA therefore differ by exactly one boolean,
    which is what makes the gap between them attributable to the method rather
    than to anything this function did differently.
    """
    if cfg.model.tuning_method in ("zeroshot", "api"):
        raise ValueError(
            f"tuning_method={cfg.model.tuning_method!r} trains nothing - "
            "run it through the evaluation path, not this script"
        )

    # seeded here specifically: the classification head is randomly
    # initialised and so is LoRA's A matrix, so this call is the difference
    # between seed=42 being reproducible and being decorative
    set_seed(cfg.seed)

    model = AutoModelForSequenceClassification.from_pretrained(
        cfg.model.base_model,
        revision=cfg.model.revision,
        num_labels=2,
        # saved into the checkpoint, so the web app cannot mix up which column
        # is P(AI). 1 = ai_generated is fixed project-wide by metrics.py.
        id2label={0: "human", 1: POSITIVE_LABEL},
        label2id={"human": 0, POSITIVE_LABEL: 1},
    )

    if cfg.model.tuning_method in ("lora", "dora"):
        model = get_peft_model(model, LoraConfig(**cfg.peft_kwargs()))

    return model


def param_counts(model) -> dict[str, float]:
    """Local mirror of tracking.log_model_size, without needing a live run."""
    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    return {
        "params_total": total,
        "params_trainable": trainable,
        "params_trainable_pct": 100.0 * trainable / total if total else 0.0,
        "adapter_mb": trainable * 4 / 1024 ** 2,
    }


# --------------------------------------------------------------------------
# training
# --------------------------------------------------------------------------

def probs_from_logits(logits) -> np.ndarray:
    """
    P(AI) for every row. Column 1 is the AI class by construction - build_model
    pins id2label - so this is the one place the label convention turns into a
    number, and everything downstream reads a probability.
    """
    logits = torch.as_tensor(logits, dtype=torch.float32)
    return torch.softmax(logits, dim=-1)[:, 1].numpy()


def compute_metrics(eval_pred) -> dict[str, float]:
    """
    Per-epoch validation metrics. Threshold-free on purpose: the deployed
    threshold is fitted once on the finished model, not re-chosen every epoch.
    Names are bare so optim.metric_for_best_model can name one directly.
    """
    y_prob = probs_from_logits(eval_pred.predictions)
    y_true = np.asarray(eval_pred.label_ids).ravel()
    return ranking_metrics(y_true, y_prob)


class WeightedTrainer(Trainer):
    """
    Trainer with inverse-frequency class weights, used when
    optim.class_weight == "balanced".

    It exists for the real corpus, which is far more skewed than this trial.
    Note the tradeoff it makes: reweighting improves recall on the rare class
    but distorts the output probabilities, so the calibrator downstream has
    more work to do and ECE is expected to be worse than an unweighted run.
    """

    def __init__(self, *args, class_weights: torch.Tensor | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_weights = class_weights

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        loss = torch.nn.functional.cross_entropy(
            outputs.logits,
            labels,
            weight=self.class_weights.to(outputs.logits.device)
            if self.class_weights is not None
            else None,
        )
        return (loss, outputs) if return_outputs else loss


def class_weights_for(cfg: RunConfig, frame) -> torch.Tensor | None:
    """Inverse class frequency, normalised to mean 1 so the LR stays comparable."""
    if cfg.optim.class_weight == "none":
        return None
    counts = np.bincount(frame["label"].to_numpy(), minlength=2).astype(float)
    weights = len(frame) / (2.0 * np.maximum(counts, 1.0))
    return torch.tensor(weights / weights.mean(), dtype=torch.float32)


def training_arguments(cfg: RunConfig, output_dir: Path,
                       n_train: int) -> TrainingArguments:
    """
    Every field traceable to the config - nothing tuned inline.

    transformers 5 dropped warmup_ratio in favour of warmup_steps, so the
    ratio is converted here rather than in the config. The config keeps the
    ratio because that is the quantity that stays meaningful when the corpus
    or the batch size changes; a step count would not.
    """
    steps_per_epoch = math.ceil(
        n_train / (cfg.optim.train_batch_size * cfg.optim.grad_accum_steps)
    )
    total_steps = steps_per_epoch * cfg.optim.epochs

    return TrainingArguments(
        output_dir=str(output_dir),
        seed=cfg.seed,
        data_seed=cfg.seed,                     # pins batch order too

        learning_rate=cfg.optim.learning_rate,
        num_train_epochs=cfg.optim.epochs,
        per_device_train_batch_size=cfg.optim.train_batch_size,
        per_device_eval_batch_size=cfg.optim.eval_batch_size,
        gradient_accumulation_steps=cfg.optim.grad_accum_steps,
        weight_decay=cfg.optim.weight_decay,
        warmup_steps=round(cfg.optim.warmup_ratio * total_steps),
        lr_scheduler_type=cfg.optim.lr_scheduler,
        max_grad_norm=cfg.optim.max_grad_norm,
        fp16=cfg.optim.precision == "fp16",
        bf16=cfg.optim.precision == "bf16",

        # evaluate and checkpoint on the same cadence, because early stopping
        # and load_best_model_at_end both compare across saved checkpoints
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model=cfg.optim.metric_for_best_model,
        greater_is_better=True,
        save_total_limit=1,                     # full_ft checkpoints are ~500 MB

        logging_strategy="epoch",
        report_to=[],                           # tracking.py owns MLflow, not
                                                # the Trainer's own integration
        dataloader_num_workers=0,               # MPS deadlocks with workers > 0
        disable_tqdm=False,
    )


def build_trainer(cfg: RunConfig, model, tokenizer, datasets, frames,
                  output_dir: Path) -> Trainer:
    weights = class_weights_for(cfg, frames["train"])
    kind = WeightedTrainer if weights is not None else Trainer
    extra = {"class_weights": weights} if weights is not None else {}

    return kind(
        model=model,
        args=training_arguments(cfg, output_dir, len(frames["train"])),
        train_dataset=datasets["train"],
        eval_dataset=datasets["val"],
        processing_class=tokenizer,
        # pads to the longest answer in each batch rather than to max_length,
        # which on a corpus with a median of 19 tokens is most of the compute
        data_collator=DataCollatorWithPadding(tokenizer),
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(cfg.optim.early_stopping_patience)],
        **extra,
    )


# --------------------------------------------------------------------------
# calibration and the frozen operating point
#
# Everything below is fitted on VALIDATION and then frozen. Test is scored
# once, with these numbers already fixed. Refitting either the calibrator or
# the threshold on test would inflate the result and is not defensible in the
# report - evaluate() reports the oracle alongside so the gap is visible.
# --------------------------------------------------------------------------

_EPS = 1e-6


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), _EPS, 1 - _EPS)
    return np.log(p / (1 - p))


@dataclass
class Calibrator:
    """
    A fitted probability map, plus plain-JSON parameters.

    The parameters are stored as floats and lists rather than as a pickled
    sklearn object on purpose: thresholds.json has to be readable by the web
    app, which is TypeScript and cannot unpickle anything. Anything that
    cannot be expressed here cannot be deployed.
    """

    method: str
    params: dict

    def transform(self, y_prob) -> np.ndarray:
        y_prob = np.asarray(y_prob, dtype=float)
        if self.method == "none":
            return y_prob
        if self.method == "platt":
            a, b = self.params["a"], self.params["b"]
            return 1.0 / (1.0 + np.exp(-(a * _logit(y_prob) + b)))
        if self.method == "temperature":
            return 1.0 / (1.0 + np.exp(-_logit(y_prob) / self.params["temperature"]))
        if self.method == "isotonic":
            return np.interp(
                y_prob, self.params["x"], self.params["y"],
                left=self.params["y"][0], right=self.params["y"][-1],
            )
        raise ValueError(f"unknown calibration method {self.method!r}")


def fit_calibrator(cfg: RunConfig, y_true, y_prob) -> Calibrator:
    """
    Fit on validation only.

    A detector can rank well and still be badly calibrated - "87% confident"
    has to mean "wrong 13 times in 100" before the number can be shown to an
    instructor. Note the trial's val split has 68 rows, which is thin for
    fitting anything; ECE on a split this small is indicative, not measured.
    """
    method = cfg.calibration.method
    y_true = np.asarray(y_true).astype(int)
    y_prob = np.asarray(y_prob, dtype=float)

    if method == "none":
        return Calibrator("none", {})

    if method == "platt":
        from sklearn.linear_model import LogisticRegression

        # C is huge so this is effectively unregularised - the classic Platt
        # map, a 2-parameter logistic fitted on the log-odds of the score
        lr = LogisticRegression(C=1e10).fit(_logit(y_prob).reshape(-1, 1), y_true)
        return Calibrator("platt", {"a": float(lr.coef_[0][0]),
                                    "b": float(lr.intercept_[0])})

    if method == "isotonic":
        from sklearn.isotonic import IsotonicRegression

        iso = IsotonicRegression(out_of_bounds="clip").fit(y_prob, y_true)
        # stored as breakpoints so the map is a plain lookup downstream
        return Calibrator("isotonic", {"x": [float(v) for v in iso.X_thresholds_],
                                       "y": [float(v) for v in iso.y_thresholds_]})

    if method == "temperature":
        from scipy.optimize import minimize_scalar

        z = _logit(y_prob)

        def nll(t: float) -> float:
            p = np.clip(1.0 / (1.0 + np.exp(-z / t)), _EPS, 1 - _EPS)
            return float(-np.mean(y_true * np.log(p) + (1 - y_true) * np.log(1 - p)))

        best = minimize_scalar(nll, bounds=(0.05, 20.0), method="bounded")
        return Calibrator("temperature", {"temperature": float(best.x)})

    raise ValueError(f"unknown calibration method {method!r}")


def freeze_operating_point(cfg: RunConfig, calibrator: Calibrator,
                           y_true, y_prob_cal) -> dict:
    """
    The decision boundary the report and the web app both use.

    The headline threshold sits at cfg.calibration.target_fpr. A second one at
    5% is recorded alongside because on a validation split with 51 negatives a
    1% budget permits 0.51 false positives - that is, zero - so the headline
    threshold can land above every score and flag nothing. That outcome is
    correct for the budget rather than a bug, but a run whose only operating
    point is degenerate tells you nothing about whether the pipeline works.
    """
    headline = threshold_at_fpr(y_true, y_prob_cal, cfg.calibration.target_fpr)
    secondary = threshold_at_fpr(y_true, y_prob_cal, 0.05)

    n_neg = int((np.asarray(y_true) == 0).sum())
    return {
        "threshold": float(headline),
        "target_fpr": float(cfg.calibration.target_fpr),
        "threshold_at_fpr_0.05": float(secondary),
        "calibration_method": calibrator.method,
        "calibration_params": calibrator.params,
        "abstain_low": float(cfg.calibration.abstain_low),
        "abstain_high": float(cfg.calibration.abstain_high),
        "fitted_on": "val",
        "val_negatives": n_neg,
        # < 1 means the budget cannot be spent on a single false positive, so
        # the headline threshold is expected to flag nothing
        "val_false_positive_budget": round(n_neg * cfg.calibration.target_fpr, 3),
    }


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def predict_probs(trainer: Trainer, dataset) -> tuple[np.ndarray, np.ndarray]:
    out = trainer.predict(dataset)
    return probs_from_logits(out.predictions), np.asarray(out.label_ids).ravel()


def predictions_frame(frame: pd.DataFrame, y_prob_raw, y_prob_cal) -> pd.DataFrame:
    """
    The per-answer table, and the most valuable artifact a run produces: with
    it, any later question about a different threshold, a different slice or a
    different calibrator is answered from a parquet file instead of from a GPU.

    Both scores are kept. y_prob is calibrated - it is what the app shows and
    what every metric is computed on - while y_prob_raw is the model output,
    which is what a different calibrator would have to be refitted against.
    """
    out = frame[["answer_id", "question_id", "generator", "n_words"]].copy()
    out["y_true"] = frame["label"].to_numpy()
    out["y_prob"] = np.asarray(y_prob_cal, dtype=float)
    out["y_prob_raw"] = np.asarray(y_prob_raw, dtype=float)
    # bins come from metrics.LENGTH_BINS rather than from here, so every run
    # slices length the same way and the rows stay comparable
    out["length_bin"] = pd.cut(
        frame["n_words"], bins=list(LENGTH_BINS), include_lowest=True
    ).astype(str)
    return out


def save_model(cfg: RunConfig, trainer: Trainer, tokenizer, out_dir: Path) -> None:
    """
    Adapters are logged; full fine-tunes are not.

    A LoRA adapter plus its head is a few MB, so keeping one per run costs
    nothing and means the web app can load the exact weights that produced the
    logged numbers. A full fine-tune is ~500 MB, and a sweep of them would
    make the shared DagsHub repo unusable for everyone. Those runs are
    reproducible from the config and the git sha instead.
    """
    if cfg.model.tuning_method not in ("lora", "dora"):
        mlflow.set_tag("model_artifact", "skipped: full fine-tune is ~500MB/run")
        return

    adapter_dir = out_dir / "adapter"
    trainer.model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)
    mlflow.log_artifacts(str(adapter_dir), "model")


def run(cfg: RunConfig, output_root: Path = Path("outputs")) -> dict:
    """
    Execute one RunConfig end to end and log everything the report needs.

    The order is the protocol: train, fit the calibrator and threshold on
    validation, freeze them, and only then score test. Test is read once,
    after the decision boundary is already fixed.
    """
    out_dir = output_root / cfg.run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    with start_run(cfg):
        mlflow.set_tag("base_model_sha", resolve_base_model_sha(cfg))

        tokenizer = load_tokenizer(cfg)
        frames = load_splits(cfg)
        datasets = {p: AnswerDataset(frames[p], tokenizer, cfg.model.max_length)
                    for p in PARTITIONS}

        for split, stats in truncation_report(
            frames, tokenizer, cfg.model.max_length
        ).items():
            log_split_metrics(stats, split)

        model = build_model(cfg)
        log_model_size(model)

        trainer = build_trainer(cfg, model, tokenizer, datasets, frames, out_dir)
        started = time.perf_counter()
        trainer.train()
        log_split_metrics({"runtime_s": time.perf_counter() - started}, "train")

        # ---- validation: fit the calibrator and the threshold, then freeze --
        val_raw, y_val = predict_probs(trainer, datasets["val"])
        calibrator = fit_calibrator(cfg, y_val, val_raw)
        val_cal = calibrator.transform(val_raw)

        operating_point = freeze_operating_point(cfg, calibrator, y_val, val_cal)
        log_thresholds(operating_point)

        band = (cfg.calibration.abstain_low, cfg.calibration.abstain_high)
        log_split_metrics(
            evaluate(y_val, val_cal, operating_point["threshold"],
                     abstain_low=band[0], abstain_high=band[1]), "val")
        log_predictions(predictions_frame(frames["val"], val_raw, val_cal), "val")

        # ---- test: read once, with the boundary already fixed --------------
        test_raw, y_test = predict_probs(trainer, datasets["test"])
        test_cal = calibrator.transform(test_raw)

        test_metrics = evaluate(y_test, test_cal, operating_point["threshold"],
                                abstain_low=band[0], abstain_high=band[1])

        # the secondary frozen point. On a val split whose 1% budget rounds to
        # zero false positives the headline threshold flags nothing, so this is
        # the only non-degenerate operating point on a corpus this small.
        secondary = operating_point_metrics(
            y_test, test_cal, operating_point["threshold_at_fpr_0.05"])
        test_metrics |= {
            "deployed_tpr_at_fpr_0.05": secondary["recall"],
            "deployed_fpr_at_fpr_0.05": secondary["fpr"],
            "deployed_precision_at_fpr_0.05": secondary["precision"],
        }
        log_split_metrics(test_metrics, "test")

        predictions = predictions_frame(frames["test"], test_raw, test_cal)
        log_predictions(predictions, "test")

        # `style` is in metrics.SLICE_BY but absent from this corpus, so the
        # loop takes whichever slice columns actually exist
        slices = [
            row
            for by in SLICE_BY if by in predictions.columns
            for row in slice_report(predictions, by=by,
                                    threshold=operating_point["threshold"])
        ]
        log_slice_table(slices, "test")

        save_model(cfg, trainer, tokenizer, out_dir)

        return {"test": test_metrics, "operating_point": operating_point}


# --------------------------------------------------------------------------

def inspect(cfg: RunConfig) -> None:
    """Dry check of the data and model wiring - no training, no MLflow."""
    print(f"{cfg.run_name}  fp={cfg.fingerprint()}  data={cfg.data.version}")
    print("base model sha:", resolve_base_model_sha(cfg))

    tokenizer = load_tokenizer(cfg)
    frames = load_splits(cfg)

    for part in PARTITIONS:
        f = frames[part]
        print(f"{part:6} {len(f):4} rows  {f['question_id'].nunique():3} questions  "
              f"{int(f['label'].sum()):3} AI ({f['label'].mean():.0%})")

    print(f"\ntruncation @ max_length = {cfg.model.max_length}")
    for split, stats in truncation_report(frames, tokenizer,
                                          cfg.model.max_length).items():
        print(f"  {split:6} p50 {stats['tokens_p50']:5.0f}  "
              f"max {stats['tokens_max']:5.0f}  "
              f"truncated {stats['truncated_pct']:.1f}%")

    model = build_model(cfg)
    counts = param_counts(model)
    print(f"\n{cfg.model.tuning_method} on {cfg.model.base_model}")
    print(f"  trainable {counts['params_trainable']:,} / "
          f"{counts['params_total']:,} ({counts['params_trainable_pct']:.3f}%)"
          f"  ~{counts['adapter_mb']:.1f} MB")
    lora = [n for n, q in model.named_parameters() if q.requires_grad and "lora_" in n]
    if lora:
        targets = sorted({re.search(r"\.(\w+)\.lora_[AB]", n).group(1) for n in lora})
        layers = len({re.search(r"layer\.(\d+)", n).group(1) for n in lora})
        print(f"  adapter on {targets} across {layers} layers: "
              f"{sum(q.numel() for n, q in model.named_parameters() if 'lora_' in n and q.requires_grad):,} params")
    print(f"  head (random init, trained via modules_to_save): "
          f"{sum(q.numel() for n, q in model.named_parameters() if q.requires_grad and 'lora_' not in n):,} params")

    decoded = tokenizer.decode(AnswerDataset(frames["train"], tokenizer,
                                             cfg.model.max_length)[0]["input_ids"])
    print(f"\nfirst train example (answer only, no question):\n  {decoded}")


if __name__ == "__main__":
    import argparse

    import experiments

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", default="TRIAL",
                        help="name of a RunConfig in experiments.py")
    parser.add_argument("--inspect", action="store_true",
                        help="check data and model wiring without training")
    args = parser.parse_args()

    cfg = getattr(experiments, args.config, None)
    if not isinstance(cfg, RunConfig):
        raise SystemExit(
            f"{args.config!r} is not a RunConfig in experiments.py. "
            f"Available: {sorted(k for k, v in vars(experiments).items() if isinstance(v, RunConfig))}"
        )

    if args.inspect:
        inspect(cfg)
    else:
        result = run(cfg)
        print("\ntest:", {k: round(v, 4) for k, v in result["test"].items()
                          if k in ("auroc", "deployed_tpr", "deployed_fpr",
                                   "deployed_tpr_at_fpr_0.05", "ece", "brier")})
