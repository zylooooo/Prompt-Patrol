"""desklib pieces that desklib_meld.py builds on: the model class, the calibrated probability and the torch
thread count. desklib + MELD (desklib_meld.py) is the served model; desklib on its own is not served any more.
"""

import math
import os

# torch picks its own default from the CPU topology (often physical cores only), and the PP-533
# load test saw the detector use half its 2 vCPU. One thread per CPU this process may run on is
# safe because baseline._lock lets only one forward pass run at a time.
# process_cpu_count ignores a cgroup CPU quota (docker --cpus), so set this to match one locally.
TORCH_THREADS = int(os.getenv("DETECTOR_TORCH_THREADS") or os.process_cpu_count() or 1)


def _cpu_model() -> str:
    """The host CPU, logged at startup: Fargate doesn't promise a CPU generation, and PP-533 saw the
    same code score ~35% faster after a redeploy. A load-test comparison is only fair on one model."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            return next((line.split(":", 1)[1].strip() for line in f if line.startswith("model name")), "unknown")
    except OSError:
        return "unknown"


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

        def forward(self, input_ids, attention_mask, labels=None):
            hidden = self.model(input_ids, attention_mask=attention_mask)[0]
            mask = attention_mask.unsqueeze(-1).expand(hidden.size()).float()
            pooled = (hidden * mask).sum(dim=1) / torch.clamp(mask.sum(dim=1), min=1e-9)
            return {"logits": self.classifier(pooled)}

    return DesklibAIDetectionModel


def calibrated_probability(logit: float, temperature: float) -> float:
    z = logit / temperature
    # two forms so a very large |z| cannot overflow exp
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)
