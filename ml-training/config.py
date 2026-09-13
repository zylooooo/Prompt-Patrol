"""
Config schema for Prompt Patrol experiments.

One RunConfig fully describes a run. Configs are Python objects (see
experiments.py) rather than data files: every field is typed, autocompleted
and refactorable, and a sweep is a loop instead of a pile of near-identical
files.

Defaults live here and only here. An experiment states what it changes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Family = Literal["roberta", "deberta", "radar", "binoculars", "fastdetectgpt", "gptzero"]
# The study's main axis. Also decides whether a PeftConfig is used at all:
# lora/dora build an adapter, full_ft trains everything, zeroshot/api train
# nothing. One field, so it cannot disagree with itself.
TuningMethod = Literal["full_ft", "lora", "dora", "zeroshot", "api"]
RunRole = Literal["train", "eval", "calibrate", "sweep", "smoke"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class ModelConfig(_Strict):
    """What we are running. base_model + revision must pin exactly."""

    family: Family
    base_model: str                      # HF id, or "gptzero" for the API
    tuning_method: TuningMethod
    revision: str                        # pin a commit sha before the final report
    max_length: int = 256                # tokens; short answers rarely exceed this


class DataConfig(_Strict):
    """
    One path to the splits. The version is derived from the filename, so there
    is no second field to fall out of sync with it.

    The file is a single parquet with a `partition` column (train/val/test),
    following apps/data-pipeline/app/splitting.py. Three separate files would
    also need a rule for which one LOGO folds are cut from; one file with a
    partition column is what logo_folds.py already reads.
    """

    splits: str                          # parquet with a `partition` column
    split_strategy: Literal["by_question", "random", "logo"] = "by_question"
    held_out_generator: str = "none"     # set for leave-one-generator-out runs

    @property
    def version(self) -> str:
        """'data/splits/trial-v0.2.parquet' -> 'trial-v0.2'."""
        return self.splits.rstrip("/").rsplit("/", 1)[-1].removesuffix(".parquet")


class PeftConfig(_Strict):
    """
    Adapter hyperparameters. Whether an adapter is built, and whether it is
    LoRA or DoRA, comes from model.tuning_method - not from here.
    """

    r: int = 16
    alpha: int = 32
    dropout: float = 0.05
    target_modules: list[str] = Field(default_factory=lambda: ["query", "value"])
    # the classification head is randomly initialised, so it must train and be
    # saved with the adapter. DeBERTa-v3 also needs "pooler".
    modules_to_save: list[str] = Field(default_factory=lambda: ["classifier"])


class OptimConfig(_Strict):
    """Ignored by zero-shot and API runs."""

    learning_rate: float = 2e-5
    epochs: int = 5
    train_batch_size: int = 16
    eval_batch_size: int = 64
    grad_accum_steps: int = 1
    weight_decay: float = 0.01
    warmup_ratio: float = 0.06
    lr_scheduler: str = "linear"
    max_grad_norm: float = 1.0
    precision: Literal["fp32", "fp16", "bf16"] = "bf16"
    early_stopping_patience: int = 3
    metric_for_best_model: str = "tpr_at_fpr_0.01"   # bare name, as Trainer wants it
    # "balanced" reweights the loss by inverse class frequency. The real
    # marking pile is ~5% AI, so a detector trained on a balanced corpus and
    # deployed on an imbalanced one is a different model than it looks.
    class_weight: Literal["none", "balanced"] = "none"


class CalibrationConfig(_Strict):
    """
    Calibrator and threshold are fitted on val and frozen before test is
    touched. The abstention band is in calibrated probability space.
    """

    method: Literal["none", "platt", "isotonic", "temperature"] = "platt"
    target_fpr: float = 0.01             # the operating point in the report
    # NOTE: these are absolute probabilities, but `threshold` is fitted on val
    # at the target FPR - nothing makes the band bracket it. On the trial run
    # the threshold fitted to 0.3969, putting the whole band above it, so
    # abstention could only withdraw answers already called AI and never guard
    # a borderline human one. Open design call: define the band relative to the
    # fitted threshold instead. This ships to the web app via thresholds.json.
    abstain_low: float = 0.4
    abstain_high: float = 0.6


class RunConfig(_Strict):
    """The whole run. Everything MLflow sees comes from here."""

    experiment: str
    run_name: str
    owner: str                           # SMU id - the DagsHub login is shared,
                                         # so this is the only per-person marker
    run_role: RunRole = "train"
    seed: int = 42
    notes: str = ""

    model: ModelConfig
    data: DataConfig
    peft: PeftConfig = Field(default_factory=PeftConfig)
    optim: OptimConfig = Field(default_factory=OptimConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)

    @model_validator(mode="after")
    def _coherent(self) -> "RunConfig":
        if self.data.split_strategy == "logo" and self.data.held_out_generator == "none":
            raise ValueError("logo split needs data.held_out_generator")
        if self.calibration.abstain_low > self.calibration.abstain_high:
            raise ValueError("calibration.abstain_low above abstain_high")
        return self

    def peft_kwargs(self) -> dict[str, Any]:
        """
        Kwargs for peft.LoraConfig. LoRA and DoRA differ here and nowhere
        else, which is what makes the delta between them attributable.
        """
        if self.model.tuning_method not in ("lora", "dora"):
            raise ValueError(
                f"tuning_method={self.model.tuning_method!r} builds no adapter"
            )
        return {
            "r": self.peft.r,
            "lora_alpha": self.peft.alpha,
            "lora_dropout": self.peft.dropout,
            "target_modules": list(self.peft.target_modules),
            "modules_to_save": list(self.peft.modules_to_save),
            "use_dora": self.model.tuning_method == "dora",
            "task_type": "SEQ_CLS",
        }

    def variant(self, run_name: str, **overrides: Any) -> "RunConfig":
        """
        A revalidated copy with dotted overrides - the sweep helper.

            for r in (8, 16, 32):
                run(cfg.variant(f"lora-r{r}", **{"peft.r": r, "peft.alpha": 2 * r}))
        """
        raw = self.model_dump()
        raw["run_name"] = run_name

        for dotted, value in overrides.items():
            cursor = raw
            *parents, leaf = dotted.split(".")
            for p in parents:
                cursor = cursor[p]
            if leaf not in cursor:
                raise KeyError(f"no such config field: {dotted}")
            cursor[leaf] = value

        return RunConfig(**raw)

    def fingerprint(self) -> str:
        """Stable 12-char hash. Two runs with the same fingerprint are duplicates."""
        payload = self.model_dump(exclude={"run_name", "notes", "owner"})
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    def flatten(self) -> dict[str, str]:
        """Dotted-key params for mlflow.log_params."""
        return _flatten(self.model_dump(exclude={"notes"}))


def _flatten(obj: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, (list, tuple)):
        out[prefix] = ",".join(str(x) for x in obj)
    else:
        out[prefix] = str(obj)
    # MLflow param values are capped; DagsHub is stricter than local MLflow
    return {k: (v[:480] + "...") if len(v) > 490 else v for k, v in out.items()}
