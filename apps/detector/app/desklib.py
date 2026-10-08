"""The fine-tuned desklib detector: desklib academic + the project's LoRA adapter.

Selected with DETECTOR_BACKEND=desklib (see baseline.py). Mirrors how the model was trained
and evaluated in ml-training/finetune_desklib_lora.py:

  1. the submitted text is cleaned with clean_text, the same cleanup the training corpus had
     (only the copy sent to the model - the submitted answer itself is never changed);
  2. the text is cut at 256 tokens, as in training;
  3. the logit is divided by the temperature fitted on validation and passed through a sigmoid,
     so raw_score is a calibrated probability that the answer is AI-written.

The decision threshold for the 1% false-positive budget (0.9608) lives with the other
thresholds in the API, not here: this service only scores.
"""

import logging
import math
import os
from functools import lru_cache
from pathlib import Path

from clean import clean_text

logger = logging.getLogger(__name__)

DESKLIB_REPO = "desklib/ai-text-detector-academic-v1.01"
ADAPTER_DIR = Path(os.getenv("DESKLIB_ADAPTER_DIR", "/app/model/desklib-lora-adapter"))
# fitted on validation for the final run (lr 2e-4, rank 64, 5 epochs, best epoch restored)
TEMPERATURE = float(os.getenv("DESKLIB_TEMPERATURE", "1.944"))
MAX_TOKENS = 256
MODEL_VERSION = "desklib-academic-lora-v1"


def _model_class():
    """The model card's class, with tie_weights switched off. desklib has no tied weights, and the
    base class's init calls tie_weights, which crashes on newer transformers (see
    ml-training/eval_desklib_zeroshot.py). Defined here so importing this module stays light."""
    import torch
    import torch.nn as nn
    from transformers import AutoConfig, AutoModel, PreTrainedModel

    class DesklibAIDetectionModel(PreTrainedModel):
        config_class = AutoConfig

        def __init__(self, config):
            super().__init__(config)
            self.model = AutoModel.from_config(config)
            self.classifier = nn.Linear(config.hidden_size, 1)
            self.init_weights()

        def tie_weights(self, *args, **kwargs):
            pass

        def forward(self, input_ids, attention_mask=None, labels=None):
            hidden = self.model(input_ids, attention_mask=attention_mask)[0]
            mask = attention_mask.unsqueeze(-1).expand(hidden.size()).float()
            pooled = (hidden * mask).sum(dim=1) / torch.clamp(mask.sum(dim=1), min=1e-9)
            return {"logits": self.classifier(pooled)}

    return DesklibAIDetectionModel


@lru_cache(maxsize=1)
def load():
    """Tokenizer and model, adapter merged in, ready for CPU inference."""
    from huggingface_hub import snapshot_download
    from peft import PeftModel
    from safetensors.torch import load_file
    from transformers import AutoConfig, AutoTokenizer

    if not (ADAPTER_DIR / "adapter_config.json").exists():
        raise FileNotFoundError(f"LoRA adapter not found in {ADAPTER_DIR}")

    logger.info("Loading %s with adapter %s", DESKLIB_REPO, ADAPTER_DIR)
    model_dir = snapshot_download(DESKLIB_REPO)
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = _model_class()(AutoConfig.from_pretrained(model_dir))
    model.load_state_dict(load_file(Path(model_dir) / "model.safetensors"))
    # merging folds the adapter into the weights, so scoring runs the plain model
    model = PeftModel.from_pretrained(model, str(ADAPTER_DIR)).merge_and_unload()
    model.eval()
    return tokenizer, model


def calibrated_probability(logit: float, temperature: float = TEMPERATURE) -> float:
    z = logit / temperature
    # two forms so a very large |z| cannot overflow exp
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def score(text: str) -> tuple[float, bool]:
    """(calibrated probability the answer is AI-written, whether it was cut at MAX_TOKENS)."""
    import torch

    tokenizer, model = load()
    cleaned = clean_text(text)
    truncated = len(tokenizer.encode(cleaned, add_special_tokens=True)) > MAX_TOKENS
    encoded = tokenizer(cleaned, truncation=True, max_length=MAX_TOKENS, return_tensors="pt")
    with torch.no_grad():
        logit = model(input_ids=encoded["input_ids"], attention_mask=encoded["attention_mask"])["logits"]
    return round(calibrated_probability(float(logit[0, 0])), 6), truncated
