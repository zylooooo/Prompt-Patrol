"""
Zero-shot desklib (academic variant) evaluation on the extended corpus (v0.1-extended).

Same protocol as eval_meld_zeroshot.py - no training, scores val to fit a
decision threshold at the project's FPR budget, freezes it, scores test once.
Uses the academic-tuned checkpoint rather than desklib's general-purpose one,
since it's fine-tuned on academic writing - a closer domain match to short
exam answers than a RAID-leaderboard-general model.

Only answers of at least --min-words words (default 10, the app's rule) fit the
threshold and enter the metrics; every val and test row is scored and saved to
outputs/<run>_scores.parquet (scores.py) so harness.py can evaluate either way.
Scoring is deterministic, so there is no seed (the file records seed 0).

    python eval_desklib_zeroshot.py                  # extended corpus
    python eval_desklib_zeroshot.py --data combined  # the earlier v0.1 + spliced set
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from scipy.special import expit
from transformers import AutoConfig, AutoModel, AutoTokenizer, PreTrainedModel

from combined_data import load_combined, load_corpus, slice_flag_rates
from metrics import evaluate, threshold_at_fpr
from scores import save_scores, score_rows
from tracking import log_dict_artifact, log_split_metrics, setup_mlflow

DESKLIB_REPO = "desklib/ai-text-detector-academic-v1.01"
MAX_LEN = 768  # desklib's own documented max_len
OUT_PATH = Path(__file__).parent / "outputs" / "desklib_zeroshot_results.json"
MLFLOW_EXPERIMENT = "zeroshot-baselines"


class DesklibAIDetectionModel(PreTrainedModel):
    """Copied from the model card (desklib ships no importable module, just
    this class definition), with one change: tie_weights() is overridden as
    a no-op. This architecture has no tied weights at all - no LM head, just
    a classifier on pooled output - but current transformers' base
    PreTrainedModel.init_weights() unconditionally calls tie_weights(), which
    reads a self.all_tied_weights_keys property this bare custom subclass
    never gets, crashing with an AttributeError before load_state_dict ever
    runs. Since there is nothing to tie here, skipping it is correct, not a
    workaround.
    Mean-pooled DeBERTa representation, one logit, sigmoid -> P(AI)."""

    config_class = AutoConfig

    def __init__(self, config):
        super().__init__(config)
        self.model = AutoModel.from_config(config)
        self.classifier = nn.Linear(config.hidden_size, 1)
        self.init_weights()

    def tie_weights(self, *args, **kwargs):
        pass

    def forward(self, input_ids, attention_mask=None, labels=None):
        outputs = self.model(input_ids, attention_mask=attention_mask)
        last_hidden_state = outputs[0]
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
        sum_embeddings = torch.sum(last_hidden_state * input_mask_expanded, dim=1)
        sum_mask = torch.clamp(input_mask_expanded.sum(dim=1), min=1e-9)
        pooled_output = sum_embeddings / sum_mask
        logits = self.classifier(pooled_output)
        return {"logits": logits}


class Scorer:
    """Mirrors MELD's Scorer shape - one text in, P(AI) out - so both
    eval scripts read the same way, even though desklib needs no custom
    loading beyond the class above."""

    def __init__(self, device: str = "cuda"):
        # DesklibAIDetectionModel.from_pretrained() breaks on current
        # transformers (AttributeError: no attribute 'all_tied_weights_keys'
        # - a newer internal weight-tying path this older custom class
        # doesn't support). Load it the way MELD's own code does instead:
        # build the model from config, then load the real weights directly
        # from the safetensors file, skipping from_pretrained() entirely.
        from huggingface_hub import snapshot_download
        from safetensors.torch import load_file

        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        model_dir = snapshot_download(DESKLIB_REPO)

        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        config = AutoConfig.from_pretrained(model_dir)
        self.model = DesklibAIDetectionModel(config)
        self.model.load_state_dict(load_file(Path(model_dir) / "model.safetensors"))
        self.model.to(self.device)
        self.model.eval()

    @torch.no_grad()
    def score_logit(self, text: str) -> float:
        """The raw model output, before the sigmoid (the scores file stores it)."""
        encoded = self.tokenizer(
            text, padding="max_length", truncation=True, max_length=MAX_LEN, return_tensors="pt"
        )
        input_ids = encoded["input_ids"].to(self.device)
        attention_mask = encoded["attention_mask"].to(self.device)
        logits = self.model(input_ids=input_ids, attention_mask=attention_mask)["logits"]
        return logits.item()

    def score(self, text: str) -> float:
        return float(torch.sigmoid(torch.tensor(self.score_logit(text))))


def score_split(scorer: Scorer, frame: pd.DataFrame, split_name: str) -> np.ndarray:
    """Raw logits, one per row; probabilities are expit(logits)."""
    logits = np.empty(len(frame), dtype=float)
    start = time.perf_counter()
    for i, text in enumerate(frame["answer"]):
        logits[i] = scorer.score_logit(str(text))
        if (i + 1) % 200 == 0 or i + 1 == len(frame):
            elapsed = time.perf_counter() - start
            print(f"  {split_name}: {i + 1}/{len(frame)} scored ({elapsed:.0f}s)", flush=True)
    return logits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-fpr", type=float, default=0.01,
                        help="FPR budget to fit the threshold at - matches "
                             "metrics.py's fixed project-wide HEADLINE_FPR")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--owner", default="malcolm", help="tag for whose run this is on the shared DagsHub board")
    parser.add_argument("--data", default="extended", choices=["extended", "combined"],
                        help="corpus to score: extended = v0.1-extended (default); combined = v0.1 + spliced")
    parser.add_argument("--min-words", type=int, default=10,
                        help="only answers of at least this many words fit the threshold and enter the metrics "
                             "(the app does not score shorter ones); 0 keeps every answer. "
                             "All val and test rows are scored and saved either way")
    parser.add_argument("--no-spliced", action="store_true",
                        help="score the raw v0.1 corpus only (the original baseline), "
                             "without the spliced answers (implies --data combined)")
    args = parser.parse_args()

    if args.no_spliced:
        args.data = "combined"
        frames = load_combined(include_spliced=False)
    else:
        frames = load_corpus(args.data)
    val, test = frames["val"], frames["test"]
    data_version = {"extended": "v0.1-extended", "combined": "v0.1+spliced"}[args.data]
    if args.no_spliced:
        data_version = "v0.1"
    run_suffix = "" if args.no_spliced else f"-{args.data}"
    print(f"data: {data_version}")
    print(f"val: {len(val)} rows ({val['label'].mean():.1%} AI)")
    print(f"test: {len(test)} rows ({test['label'].mean():.1%} AI)")
    vmask = (val["n_words"] >= args.min_words).to_numpy()
    tmask = (test["n_words"] >= args.min_words).to_numpy()
    val_used, test_used = val[vmask].reset_index(drop=True), test[tmask].reset_index(drop=True)
    print(f"answers of >= {args.min_words} words used for the threshold and metrics: "
          f"val {len(val_used)}, test {len(test_used)}")

    print("\nLoading desklib academic (downloads ~1.7GB on first run, cached after)...")
    scorer = Scorer(device=args.device)

    setup_mlflow(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name=f"desklib-academic-zeroshot{run_suffix}"):
        mlflow.set_tags({"owner": args.owner, "run_role": "eval", "tuning_method": "zeroshot"})
        mlflow.log_params({
            "model": DESKLIB_REPO,
            "target_fpr": args.target_fpr,
            "data": data_version,
            "min_words": args.min_words,
            "val_n": len(val),
            "test_n": len(test),
        })

        print("\nScoring val...")
        val_logits = score_split(scorer, val, "val")
        print("\nScoring test...")
        test_logits = score_split(scorer, test, "test")
        val_probs, test_probs = expit(val_logits), expit(test_logits)  # untouched: no temperature

        # one row per answer for EVERY val and test row (not filtered by word count); harness.py reads it
        scores_path = save_scores(f"desklib-academic-zeroshot{run_suffix}", 0, [
            score_rows("desklib-untouched", "val", val, val_logits, val_probs),
            score_rows("desklib-untouched", "test", test, test_logits, test_probs),
        ])

        threshold = threshold_at_fpr(val_used["label"], val_probs[vmask], args.target_fpr)
        print(f"\nthreshold fit on val at target_fpr={args.target_fpr}: {threshold:.4f}")
        mlflow.log_metric("threshold", threshold)

        results = evaluate(test_used["label"], test_probs[tmask], threshold, headline_fpr=args.target_fpr,
                           groups=test_used["question_id"].to_numpy())
        log_split_metrics(results, "test")

        print(f"\n=== desklib (academic) zero-shot, test split (answers of >= {args.min_words} words) ===")
        for key in ("auroc", "deployed_tpr", "deployed_fpr", "deployed_precision", "ece", "brier"):
            print(f"  {key}: {results[key]:.4f}")

        slices = slice_flag_rates(test_used, test_probs[tmask], threshold)
        print("\n  per slice (flag rate at the frozen threshold; human = FPR, rest = TPR):")
        for row in slices:
            print(f"    {row['slice']:<11} n={row['n']:<5} {row['kind']}={row['flag_rate']:.3f}")
            mlflow.log_metric(f"test/slice_{row['slice'].replace('-', '_')}_flag_rate", row["flag_rate"])

        payload = {
            "model": f"desklib academic (zero-shot, {DESKLIB_REPO})",
            "data": data_version,
            "min_words": args.min_words,
            "target_fpr": args.target_fpr,
            "threshold": threshold,
            "val_n": len(val),
            "test_n": len(test),
            "val_used": len(val_used),
            "test_used": len(test_used),
            "scores_file": scores_path.name,
            "results": {k: float(v) for k, v in results.items()},
            "slices": slices,
        }
        log_dict_artifact(payload, "zeroshot_results.json")

        out_path = OUT_PATH.with_name(f"{OUT_PATH.stem}{run_suffix.replace('-', '_')}.json")
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2))
        print(f"\nWrote {out_path}")
        print(f"MLflow run: {mlflow.active_run().info.run_id}")


if __name__ == "__main__":
    main()
