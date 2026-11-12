"""desklib + MELD: the fine-tuned desklib detector and the MELD 3-seed soup, their calibrated scores averaged.

Selected with DETECTOR_BACKEND=desklib-meld (see baseline.py); built by Dockerfile.desklib-meld. Mirrors how the
release was scored in ml-training/release_desklib_meld.py (docs/desklib-meld-release.md):
  1. the submitted text is cleaned once with clean_text, and the same cleaned text goes to both models (only the copy
     sent to the models; the submitted answer itself is never changed);
  2. desklib (this bundle's adapter merged in) scores the first 256 tokens and returns a logit; MELD (the soup adapter
     merged into its backbone, the averaged head loaded) reads the whole answer in windows, with MELD's own meld.py
     from the pinned revision, and returns a score. MELD's own "flagged" and threshold are ignored;
  3. each is divided by its own temperature, the two are averaged with weight_meld, and the result goes through a
     sigmoid, so raw_score is a calibrated probability that the answer is AI-written. Averaging the log-odds, not the
     probabilities, is what the threshold was fitted on.
Every number comes from desklib-meld.json in the bundle. The decision threshold (0.945775, fitted on validation at 1%
FPR) is set in the API as DETECTOR_THRESHOLD: this service only scores.
"""

import importlib.util
import json
import logging
import os
import sys
from functools import lru_cache
from pathlib import Path

import desklib
from clean import CLEANING_VERSION, clean_text

logger = logging.getLogger(__name__)

BUNDLE_DIR = Path(os.getenv("DESKLIB_MELD_DIR", "/app/model/desklib-meld"))
SETTINGS_PATH = BUNDLE_DIR / "desklib-meld.json"
MELD_BASE_DIR = Path(os.getenv("MELD_BASE_DIR", "/app/model/meld-base"))
MODEL_VERSION = "desklib-meld-ensemble-v1"
DESKLIB_MAX_TOKENS = 256
_REQUIRED = ("model_version", "calibration_version", "threshold", "weight_meld", "cleaning_version", "desklib", "meld")
_REQUIRED_DESKLIB = ("base_model", "base_revision", "adapter", "temperature", "max_tokens")
_REQUIRED_MELD = ("base_revision", "adapter", "head", "temperature")


@lru_cache(maxsize=1)
def settings() -> dict:
    """The release's desklib-meld.json, checked against what this image runs.

    A mismatch means the threshold in the API was fitted for a different combination, so it fails loudly instead of
    scoring with something nobody calibrated."""
    if not SETTINGS_PATH.exists():
        raise FileNotFoundError(
            f"desklib + MELD settings not found at {SETTINGS_PATH}: fetch the bundle "
            "(ml-training/release_desklib_meld.py --fetch) and rebuild the base image"
        )
    values = json.loads(SETTINGS_PATH.read_text())
    missing = [k for k in _REQUIRED if k not in values]
    missing += [f"desklib.{k}" for k in _REQUIRED_DESKLIB if k not in values.get("desklib", {})]
    missing += [f"meld.{k}" for k in _REQUIRED_MELD if k not in values.get("meld", {})]
    if missing:
        raise ValueError(f"{SETTINGS_PATH.name} is missing {missing}")
    if values["model_version"] != MODEL_VERSION:
        raise ValueError(f"{SETTINGS_PATH.name} is for {values['model_version']}, this code is {MODEL_VERSION}")
    if values["cleaning_version"] != CLEANING_VERSION:
        raise ValueError(f"calibrated on {values['cleaning_version']} text, this code cleans with {CLEANING_VERSION}")
    if values["desklib"]["max_tokens"] != DESKLIB_MAX_TOKENS:
        raise ValueError(
            f"calibrated with desklib cut at {values['desklib']['max_tokens']} tokens, this code cuts at "
            f"{DESKLIB_MAX_TOKENS}"
        )
    return values


def _check_meld_revision(config: dict) -> None:
    """MELD's base model is a plain folder (copied in by prepare_desklib_meld_base.sh), so its REVISION file is the
    only record of which release it is; the bundle's adapter and head only fit the one they were trained on."""
    marker = MELD_BASE_DIR / "REVISION"
    if not marker.exists():
        raise FileNotFoundError(f"no REVISION in {MELD_BASE_DIR}: stage it with scripts/prepare_desklib_meld_base.sh")
    found, wanted = marker.read_text().strip(), config["meld"]["base_revision"]
    if found != wanted:
        raise ValueError(f"{MELD_BASE_DIR} is MELD@{found[:12]}, but the bundle was calibrated on MELD@{wanted[:12]}")


@lru_cache(maxsize=1)
def load_desklib():
    """desklib's tokenizer and model at the pinned base revision, this bundle's adapter merged in."""
    config = settings()["desklib"]
    adapter = BUNDLE_DIR / config["adapter"]
    if not (adapter / "adapter_config.json").exists():
        raise FileNotFoundError(f"desklib LoRA adapter not found in {adapter}")

    import torch
    from huggingface_hub import snapshot_download
    from peft import PeftModel
    from safetensors.torch import load_file
    from transformers import AutoConfig, AutoTokenizer

    torch.set_num_threads(desklib.TORCH_THREADS)
    logger.info(
        "torch threads: intra-op %d, CPUs available %s, CPU model %s",
        torch.get_num_threads(),
        os.cpu_count(),
        desklib._cpu_model(),
    )
    logger.info("Loading %s@%s with adapter %s", config["base_model"], config["base_revision"][:12], adapter)
    model_dir = snapshot_download(config["base_model"], revision=config["base_revision"])
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = desklib._model_class()(AutoConfig.from_pretrained(model_dir))
    model.load_state_dict(load_file(Path(model_dir) / "model.safetensors"))
    model = PeftModel.from_pretrained(model, str(adapter)).merge_and_unload()
    model.float().eval()
    return tokenizer, model


@lru_cache(maxsize=1)
def load_meld():
    """MELD's Scorer from the pinned base revision's own meld.py, the soup adapter merged into its backbone and the
    averaged head loaded, in float32 as MELD's scoring contract requires."""
    config = settings()
    _check_meld_revision(config)
    adapter = BUNDLE_DIR / config["meld"]["adapter"]
    head = BUNDLE_DIR / config["meld"]["head"]
    if not (adapter / "adapter_config.json").exists():
        raise FileNotFoundError(f"MELD soup adapter not found in {adapter}")
    if not head.exists():
        raise FileNotFoundError(f"MELD soup head not found at {head}")

    from peft import PeftModel
    from safetensors.torch import load_file

    spec = importlib.util.spec_from_file_location("meld_base", MELD_BASE_DIR / "meld.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load meld.py from {MELD_BASE_DIR}")
    meld = importlib.util.module_from_spec(spec)
    sys.modules["meld_base"] = meld
    spec.loader.exec_module(meld)

    logger.info("Loading MELD@%s with adapter %s", config["meld"]["base_revision"][:12], adapter)
    scorer = meld.Scorer(model_dir=str(MELD_BASE_DIR), device="cpu")
    model = scorer.model
    model.backbone = PeftModel.from_pretrained(model.backbone, str(adapter)).merge_and_unload()
    result = model.load_state_dict(load_file(head), strict=False)
    # strict=False because the head file holds no backbone weights; anything else not fitting is a wrong head
    if result.unexpected_keys or any(not k.startswith("backbone.") for k in result.missing_keys):
        raise RuntimeError(
            f"MELD head does not fit: unexpected {result.unexpected_keys[:3]}, "
            f"missing {[k for k in result.missing_keys if not k.startswith('backbone.')][:3]}"
        )
    model.float().eval()
    return scorer


def combine(desklib_logit: float, meld_score: float, config: dict) -> float:
    """The calibrated probability: each score over its own temperature, averaged with the MELD weight, then a sigmoid."""
    weight = config["weight_meld"]
    z = (1 - weight) * desklib_logit / config["desklib"]["temperature"] + weight * meld_score / config["meld"][
        "temperature"
    ]
    return desklib.calibrated_probability(z, 1.0)


def score(text: str) -> tuple[float, bool]:
    """(calibrated probability the answer is AI-written, whether either model cut the text).

    desklib reads only the first 256 tokens, so a long answer reports truncated even though MELD read all of it (up
    to its 16,384-token cap), as for the desklib + RADAR ensemble."""
    import torch

    config = settings()
    tokenizer, model = load_desklib()
    scorer = load_meld()
    cleaned = clean_text(text)

    desklib_truncated = len(tokenizer.encode(cleaned, add_special_tokens=True)) > DESKLIB_MAX_TOKENS
    encoded = tokenizer(cleaned, truncation=True, max_length=DESKLIB_MAX_TOKENS, return_tensors="pt")
    with torch.no_grad():
        d_logit = float(model(input_ids=encoded["input_ids"], attention_mask=encoded["attention_mask"])["logits"][0, 0])
    meld_result = scorer.score(cleaned)
    probability = combine(d_logit, float(meld_result["score"]), config)
    return round(probability, 6), desklib_truncated or bool(meld_result["truncated"])
