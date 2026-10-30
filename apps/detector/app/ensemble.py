"""desklib + RADAR: the live desklib detector and RADAR with the project's LoRA adapter, their scores averaged.

Selected with DETECTOR_BACKEND=ensemble (see baseline.py). Mirrors how the combination was calibrated in
ml-training/calibrate_ensemble.py:
  1. the submitted text is cleaned once with clean_text, as for desklib (only the copy sent to the models);
  2. desklib (desklib.py, adapter merged) and RADAR (adapter merged) each score the cleaned text, cut at 256 tokens;
  3. each logit is divided by its own temperature, the two are averaged with the weight in ensemble.json, and the
     result goes through a sigmoid, so raw_score is a calibrated probability that the answer is AI-written.
The decision threshold (fitted on validation at 1% FPR) is in ensemble.json and set in the API as DETECTOR_THRESHOLD:
this service only scores.

RADAR (TrustSafeAI/RADAR-Vicuna-7B) is licensed for non-commercial use only.
"""

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import desklib
from clean import clean_text

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path(os.getenv("ENSEMBLE_SETTINGS", "/app/model/ensemble.json"))
RADAR_ADAPTER_DIR = Path(os.getenv("RADAR_ADAPTER_DIR", "/app/model/radar-lora-adapter"))
MAX_TOKENS = 256
MODEL_VERSION = "desklib-radar-ensemble-v1"
# RADAR has two outputs, [AI, human] (the authors' own example reads index 0 as AI-generated)
AI, HUMAN = 0, 1
_REQUIRED = (
    "model_version",
    "weight_radar",
    "desklib_temperature",
    "desklib_model_version",
    "radar_model",
    "radar_revision",
    "radar_temperature",
    "max_tokens",
)


@lru_cache(maxsize=1)
def settings() -> dict:
    """The calibration written by ml-training/calibrate_ensemble.py, checked against what this image runs.

    A mismatch means the threshold in the API was fitted for different models, so it fails loudly instead of
    scoring with a combination nobody calibrated."""
    if not SETTINGS_PATH.exists():
        raise FileNotFoundError(f"ensemble settings not found at {SETTINGS_PATH}")
    values = json.loads(SETTINGS_PATH.read_text())
    if missing := [k for k in _REQUIRED if k not in values]:
        raise ValueError(f"{SETTINGS_PATH.name} is missing {missing}")
    if values["model_version"] != MODEL_VERSION:
        raise ValueError(f"{SETTINGS_PATH.name} is for {values['model_version']}, this code is {MODEL_VERSION}")
    if values["desklib_model_version"] != desklib.MODEL_VERSION or values["desklib_temperature"] != desklib.TEMPERATURE:
        raise ValueError(
            f"calibrated for desklib {values['desklib_model_version']} at T={values['desklib_temperature']}, "
            f"but this image runs {desklib.MODEL_VERSION} at T={desklib.TEMPERATURE}: rerun calibrate_ensemble.py"
        )
    if values["max_tokens"] != MAX_TOKENS:
        raise ValueError(f"calibrated with a {values['max_tokens']}-token cut, this code cuts at {MAX_TOKENS}")
    return values


@lru_cache(maxsize=1)
def load_radar():
    """RADAR's tokenizer and model at the pinned revision, adapter merged in, ready for CPU inference."""
    if not (RADAR_ADAPTER_DIR / "adapter_config.json").exists():
        raise FileNotFoundError(f"RADAR LoRA adapter not found in {RADAR_ADAPTER_DIR}")

    from peft import PeftModel
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    config = settings()
    logger.info(
        "Loading %s@%s with adapter %s", config["radar_model"], config["radar_revision"][:12], RADAR_ADAPTER_DIR
    )
    tokenizer = AutoTokenizer.from_pretrained(config["radar_model"], revision=config["radar_revision"])
    model, info = AutoModelForSequenceClassification.from_pretrained(
        config["radar_model"], revision=config["radar_revision"], output_loading_info=True
    )
    # a weight that fails to load is replaced with random numbers and only logs a warning
    if failed := {k: sorted(v) for k, v in info.items() if v}:
        raise RuntimeError(f"RADAR weights did not load cleanly: {failed}")
    model = PeftModel.from_pretrained(model, str(RADAR_ADAPTER_DIR)).merge_and_unload()
    model.eval()
    return tokenizer, model


def combine(desklib_logit: float, radar_logit: float, config: dict) -> float:
    """The calibrated probability: each logit over its own temperature, averaged with the RADAR weight, then a sigmoid."""
    weight = config["weight_radar"]
    z = (1 - weight) * desklib_logit / config["desklib_temperature"] + weight * radar_logit / config[
        "radar_temperature"
    ]
    return desklib.calibrated_probability(z, 1.0)


def score(text: str) -> tuple[float, bool]:
    """(calibrated probability the answer is AI-written, whether either model cut it at MAX_TOKENS)."""
    import torch

    config = settings()
    d_tokenizer, d_model = desklib.load()
    r_tokenizer, r_model = load_radar()
    cleaned = clean_text(text)

    truncated = any(
        len(tok.encode(cleaned, add_special_tokens=True)) > MAX_TOKENS for tok in (d_tokenizer, r_tokenizer)
    )
    d_enc = d_tokenizer(cleaned, truncation=True, max_length=MAX_TOKENS, return_tensors="pt")
    r_enc = r_tokenizer(cleaned, truncation=True, max_length=MAX_TOKENS, return_tensors="pt")
    with torch.no_grad():
        d_logit = float(d_model(input_ids=d_enc["input_ids"], attention_mask=d_enc["attention_mask"])["logits"][0, 0])
        r_out = r_model(input_ids=r_enc["input_ids"], attention_mask=r_enc["attention_mask"]).logits.float()
    r_logit = float(r_out[0, AI] - r_out[0, HUMAN])
    return round(combine(d_logit, r_logit, config), 6), truncated
