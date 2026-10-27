"""
LoRA fine-tune MELD on the extended corpus (v0.1-extended, see
build_extended_corpus.py). `--data combined` reproduces the earlier v0.1 + spliced runs.

MELD is not a normal sequence-classification checkpoint.  Its backbone emits
token representations, then a custom prototype head reduces token scores with
the top-quantile rule from ``meld.py``.  This script preserves that head and
trains it together with LoRA weights in the ModernBERT backbone.

The evaluation protocol matches the Desklib run:
  1. score the untouched MELD model on val and test;
  2. restore the epoch with the best validation AUROC;
  3. fit temperature and the 1% FPR threshold on val only;
  4. score test once with both values frozen.
Steps 3-4 (and the baseline) use only answers of at least --min-words words
(default 10, the app's own rule). Every val and test row is still scored and
written to outputs/<run>_scores.parquet (scores.py), which harness.py reads.

Examples:
    python finetune_meld_lora.py --epochs 3 --seed 1
    python finetune_meld_lora.py --train-on mohler
    python finetune_meld_lora.py --data combined          # old v0.1 + spliced corpus
    python finetune_meld_lora.py --epochs 1 --max-train-rows 200 --run-name smoke
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
import mlflow
from scipy.optimize import minimize_scalar
from scipy.special import expit
from sklearn.metrics import precision_recall_curve, roc_auc_score, roc_curve

from combined_data import load_corpus, slice_flag_rates
from metrics import calibration_metrics, evaluate, slice_report, threshold_at_fpr
from scores import save_scores, score_rows
from meld_lora_plots import (plot_calibration, plot_pr, plot_roc,
                            plot_ppv_prevalence, plot_score_hist, plot_slices,
                            plot_training)

MELD_REPO = "anon-review-meld-2026/meld"
# the 23 Sep release (config v8) that the sweeps and earlier runs used. ddfc9c78 (27 Oct, v83) is a
# retrained checkpoint with per-generator prototypes; pass --meld-revision main to use the latest
MELD_REVISION = "8990324abd92e1fa17072f6887ea1e5c1cef5abc"
MLFLOW_EXPERIMENT = "E2-finetune"
OUT_DIR = Path(__file__).parent / "outputs"
DATASETS = ("mohler", "sprag", "engsaf")


def load_meld(device: str, revision: str = MELD_REVISION):
    from huggingface_hub import snapshot_download

    model_dir = Path(snapshot_download(MELD_REPO, revision=revision))
    spec = importlib.util.spec_from_file_location("meld_finetune", model_dir / "meld.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load meld.py from {model_dir}")
    meld = importlib.util.module_from_spec(spec)
    sys.modules["meld_finetune"] = meld
    spec.loader.exec_module(meld)
    scorer = meld.Scorer(model_dir=str(model_dir), device=device)
    return meld, scorer, model_dir


def select_splits(frames: dict[str, pd.DataFrame], train_on: list[str] | None):
    if not train_on:
        return tuple(frames[p].reset_index(drop=True) for p in ("train", "val", "test"))
    if bad := set(train_on) - set(DATASETS):
        raise SystemExit(f"unknown dataset(s) {sorted(bad)}; choose from {DATASETS}")
    if set(train_on) == set(DATASETS):
        raise SystemExit("--train-on names every dataset; omit it instead")
    keep = lambda df: df[df["dataset"].isin(train_on)].reset_index(drop=True)
    everything = pd.concat(frames.values(), ignore_index=True)
    held_out = everything[~everything["dataset"].isin(train_on)].reset_index(drop=True)
    return keep(frames["train"]), keep(frames["val"]), held_out


def balance_train(train: pd.DataFrame, seed: int) -> pd.DataFrame:
    n = int(min((train["label"] == 0).sum(), (train["label"] == 1).sum()))
    if n == 0:
        raise ValueError("training data must contain both human and AI answers")
    parts = [g.sample(n, random_state=seed) for _, g in train.groupby("label")]
    return pd.concat(parts).sample(frac=1.0, random_state=seed).reset_index(drop=True)


def add_lora(model, r: int, alpha: int, dropout: float, targets: list[str]):
    from peft import LoraConfig, get_peft_model

    leaves = {name.rsplit(".", 1)[-1] for name, _ in model.backbone.named_modules()}
    missing = sorted(set(targets) - leaves)
    if missing:
        raise ValueError(
            f"LoRA target(s) {missing} not found in MELD backbone; "
            f"available projection names include {sorted(n for n in leaves if 'proj' in n.lower() or n in {'Wqkv', 'Wo'})}"
        )
    model.backbone = get_peft_model(
        model.backbone,
        LoraConfig(r=r, lora_alpha=alpha, lora_dropout=dropout, target_modules=targets),
    )
    # MELD's prototype head is outside the PEFT-wrapped backbone.
    for name, param in model.named_parameters():
        if not name.startswith("backbone.") and not name.startswith("backbone.base_model."):
            param.requires_grad = True
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"trainable params: {trainable:,} of {total:,} ({trainable / total:.2%})")
    # names look like ...layers.0.attn.Wqkv.lora_A.default.weight; report the wrapped module (Wqkv)
    hit = sorted({n.split(".lora_A")[0].rsplit(".", 1)[-1] for n, p in model.backbone.named_parameters()
                  if p.requires_grad and "lora_A" in n})
    print(f"LoRA applied to: {hit}")
    if not hit:
        raise RuntimeError(f"target_modules {targets} matched no LoRA parameters")


def document_windows(meld, tokenizer, text: str, cap: int, window: int):
    text = meld.canonicalize(text)
    ids = tokenizer(text, add_special_tokens=False, truncation=False)["input_ids"][:cap]
    if not ids:
        raise ValueError("no scoreable tokens in input")
    cls = tokenizer.cls_token_id if tokenizer.cls_token_id is not None else tokenizer.bos_token_id
    sep = tokenizer.sep_token_id if tokenizer.sep_token_id is not None else tokenizer.eos_token_id
    pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else 0
    windows = [ids[i:i + window] for i in range(0, len(ids), window)]
    width = max(len(w) for w in windows) + 2
    input_ids = torch.full((len(windows), width), pad, dtype=torch.long)
    attention = torch.zeros((len(windows), width), dtype=torch.long)
    for i, window in enumerate(windows):
        input_ids[i, 0] = cls
        input_ids[i, 1:1 + len(window)] = torch.tensor(window)
        input_ids[i, 1 + len(window)] = sep
        attention[i, :len(window) + 2] = 1
    return input_ids, attention, [len(w) for w in windows]


def top_quantile_mean(values: torch.Tensor, rho: float) -> torch.Tensor:
    k = max(1, math.ceil(values.shape[0] * rho))
    return values.sort(dim=0, descending=True).values[:k].mean(dim=0)


def token_scores(model, input_ids: torch.Tensor, attention_mask: torch.Tensor):
    """Differentiable equivalent of MELD's @torch.no_grad token_scores()."""
    h = model.backbone(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state.float()
    u = model.style_ln(model.style_proj(h))
    tau = model.log_tau.clamp(-4.0, 4.0).exp()
    sqdist = lambda values, prototypes: (
        (values * values).sum(-1, keepdim=True)
        - 2.0 * values @ prototypes.t()
        + (prototypes * prototypes).sum(-1).view(1, 1, -1)
    )
    logit_h = -tau * sqdist(u, model.human_anchors)
    if hasattr(model, "gen_protos"):
        # 27 Oct release onwards: one prototype per generator, a family's logit is its nearest member's
        logit_m = -tau * sqdist(u, model.gen_protos) + model.gen_bias.view(1, 1, -1)
        logit_g = torch.where(model.gen_member, logit_m.unsqueeze(-1),
                              logit_m.new_tensor(float("-inf"))).amax(dim=2)
    else:
        logit_g = -tau * sqdist(u, model.family_protos) + model.family_bias.view(1, 1, -1)
    if model.cfg.get("null_reduction", "lse") == "max":
        human = logit_h.max(dim=-1, keepdim=True).values
    else:
        human = torch.logsumexp(logit_h, dim=-1, keepdim=True)
    s_tok = (logit_g - human).clamp(-30.0, 30.0)
    c_tok = model.cfg["tau_agg"] * torch.logsumexp(s_tok / model.cfg["tau_agg"], dim=-1)
    o_tok = -tau * sqdist(u, model.op_protos) + model.op_bias.view(1, 1, -1)
    return s_tok, c_tok, o_tok


def document_logit(meld, model, tokenizer, text: str, device: torch.device, cap: int,
                   window: int, window_batch: int = 4) -> torch.Tensor:
    ids, attention, lengths = document_windows(meld, tokenizer, text, cap, window)
    cfg = model.cfg
    c_parts, s_parts, o_parts = [], [], []
    for start in range(0, len(lengths), window_batch):
        sl = slice(start, start + window_batch)
        s_tok, c_tok, o_tok = token_scores(model, ids[sl].to(device), attention[sl].to(device))
        for j, length in enumerate(lengths[sl]):
            token_slice = slice(1, 1 + length)
            c_parts.append(c_tok[j, token_slice])
            s_parts.append(s_tok[j, token_slice])
            o_parts.append(o_tok[j, token_slice])
    c_tok = torch.cat(c_parts)
    # The family and operation reductions are auxiliary outputs in MELD.  The
    # shipped document score is the top-quantile family score c_tok.
    _ = top_quantile_mean(torch.cat(s_parts), float(cfg["rho"]))
    _ = top_quantile_mean(torch.cat(o_parts), float(cfg["rho"]))
    return top_quantile_mean(c_tok, float(cfg["rho"]))


def predict_logits(meld, model, tokenizer, texts, device, cap, window, window_batch=4):
    model.eval()
    values = []
    with torch.no_grad():
        for text in texts:
            values.append(float(document_logit(meld, model, tokenizer, str(text), device, cap, window, window_batch)))
    return np.asarray(values, dtype=np.float64)


def fit_temperature(logits, labels):
    y = np.asarray(labels, dtype=float)

    def nll(log_t):
        p = np.clip(expit(logits / np.exp(log_t)), 1e-12, 1 - 1e-12)
        return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))

    return float(np.exp(minimize_scalar(nll, bounds=(-3, 4), method="bounded").x))


def evaluate_protocol(val, test, val_logits, test_logits, target_fpr, calibrate, min_words=0):
    """val fits the temperature and threshold; test is scored once with both frozen.

    Only answers of at least `min_words` words fit either value and enter the metrics (the app
    marks shorter answers uncertain without scoring them). The probabilities returned cover every
    val and test row, so the scores file can still be evaluated on all answers.
    """
    val_logits, test_logits = np.asarray(val_logits), np.asarray(test_logits)
    vmask = (val["n_words"] >= min_words).to_numpy()
    tmask = (test["n_words"] >= min_words).to_numpy()
    val_used, test_used = val[vmask].reset_index(drop=True), test[tmask].reset_index(drop=True)
    temperature = fit_temperature(val_logits[vmask], val_used["label"]) if calibrate else 1.0
    val_prob, test_prob = expit(val_logits / temperature), expit(test_logits / temperature)
    threshold = threshold_at_fpr(val_used["label"], val_prob[vmask], target_fpr)
    results = evaluate(test_used["label"], test_prob[tmask], threshold, headline_fpr=target_fpr,
                       groups=test_used["question_id"].to_numpy())
    slices = {"all": slice_flag_rates(test_used, test_prob[tmask], threshold)}
    for dataset in sorted(test_used["dataset"].unique()):
        mask = (test_used["dataset"] == dataset).to_numpy()
        slices[dataset] = slice_flag_rates(test_used[mask].reset_index(drop=True), test_prob[tmask][mask], threshold)
    raw = calibration_metrics(test_used["label"], expit(test_logits[tmask]))
    return {
        "temperature": temperature, "threshold": threshold, "results": results,
        "slices": slices, "uncalibrated_ece": raw["ece"],
        "uncalibrated_brier": raw["brier"],
        "min_words": min_words, "val_used": len(val_used), "test_used": len(test_used),
    }, val_prob, test_prob


def calibration_bins(labels, probabilities, n_bins=10):
    """Reliability-table rows that can be plotted without rerunning inference."""
    labels = np.asarray(labels, dtype=int)
    probabilities = np.asarray(probabilities, dtype=float)
    rows = []
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    for i in range(n_bins):
        mask = ((probabilities >= edges[i]) & (probabilities < edges[i + 1])
                if i < n_bins - 1 else
                (probabilities >= edges[i]) & (probabilities <= edges[i + 1]))
        if not mask.any():
            continue
        rows.append({
            "bin": i,
            "lower": float(edges[i]),
            "upper": float(edges[i + 1]),
            "n": int(mask.sum()),
            "mean_predicted": float(probabilities[mask].mean()),
            "observed_ai_rate": float(labels[mask].mean()),
        })
    return rows


def curve_rows(labels, probabilities, model_name):
    """Return ROC and precision-recall points in tidy, chart-friendly form."""
    fpr, tpr, roc_thresholds = roc_curve(labels, probabilities)
    precision, recall, pr_thresholds = precision_recall_curve(labels, probabilities)
    rows = [
        {"model": model_name, "curve": "roc", "x": float(x), "y": float(y),
         "threshold": float(t) if np.isfinite(t) else None}
        for x, y, t in zip(fpr, tpr, roc_thresholds)
    ]
    # precision_recall_curve has one extra endpoint without a threshold.
    rows.extend(
        {"model": model_name, "curve": "precision_recall", "x": float(x), "y": float(y),
         "threshold": float(pr_thresholds[i]) if i < len(pr_thresholds) else None}
        for i, (x, y) in enumerate(zip(recall, precision))
    )
    return rows


def log_dataframe_artifact(frame: pd.DataFrame, path: Path, artifact_dir: str):
    frame.to_csv(path, index=False)
    mlflow.log_artifact(str(path), artifact_dir)


def train(model, meld, tokenizer, train, val, args, device, cap, window, log_metric):
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=args.lr, weight_decay=args.weight_decay)
    steps = int(np.ceil(len(train) / args.batch_size)) * args.epochs
    warmup = max(1, int(0.1 * steps))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda s: min((s + 1) / warmup, max(0.0, (steps - s) / max(1, steps - warmup))))
    rng = np.random.default_rng(args.seed)
    best_auc, best_state, best_epoch = -1.0, None, -1
    history = []
    labels = train["label"].to_numpy(dtype=np.float32)
    texts = train["answer"].astype(str).to_numpy()
    for epoch in range(1, args.epochs + 1):
        model.train()
        order = rng.permutation(len(train))
        running = 0.0
        started = time.perf_counter()
        for i in range(0, len(order), args.batch_size):
            idx = order[i:i + args.batch_size]
            logits = torch.stack([document_logit(meld, model, tokenizer, texts[j], device, cap, window)
                                  for j in idx])
            loss = F.binary_cross_entropy_with_logits(logits.float(), torch.from_numpy(labels[idx]).to(device))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            running += loss.item() * len(idx)
        val_logits = predict_logits(meld, model, tokenizer, val["answer"], device, cap, window)
        val_auc = float(roc_auc_score(val["label"], val_logits))
        val_loss = float(F.binary_cross_entropy_with_logits(
            torch.from_numpy(val_logits),
            torch.from_numpy(val["label"].to_numpy(dtype=np.float64)),
        ).item())
        train_loss = running / len(train)
        epoch_seconds = time.perf_counter() - started
        learning_rate = float(optimizer.param_groups[0]["lr"])
        print(f"epoch {epoch}/{args.epochs}: train_loss={train_loss:.4f} "
              f"val_loss={val_loss:.4f} val_auroc={val_auc:.4f} "
              f"({epoch_seconds:.0f}s)", flush=True)
        log_metric("train/loss", train_loss, epoch)
        log_metric("val/loss", val_loss, epoch)
        log_metric("val/auroc", val_auc, epoch)
        log_metric("train/learning_rate", learning_rate, epoch)
        log_metric("train/epoch_seconds", epoch_seconds, epoch)
        history.append({
            "epoch": epoch, "train_loss": train_loss, "val_loss": val_loss,
            "val_auroc": val_auc, "learning_rate": learning_rate,
            "epoch_seconds": epoch_seconds,
        })
        if val_auc > best_auc:
            best_auc, best_epoch = val_auc, epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.named_parameters() if v.requires_grad}
    if best_state is None:
        raise RuntimeError("training produced no validation checkpoint")
    model.load_state_dict(best_state, strict=False)
    print(f"restored epoch {best_epoch} (val_auroc={best_auc:.4f})")
    return best_epoch, best_auc, history


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="extended", choices=["extended", "combined"],
                    help="extended = v0.1-extended (default); combined = the earlier v0.1 + spliced")
    ap.add_argument("--min-words", type=int, default=10,
                    help="only answers of at least this many words fit the temperature and threshold and "
                         "enter the metrics; 0 keeps every answer. All val and test rows are scored and saved")
    ap.add_argument("--train-on", default="")
    ap.add_argument("--no-balance", action="store_true")
    ap.add_argument("--no-calibrate", action="store_true")
    ap.add_argument("--no-baseline", action="store_true")
    ap.add_argument("--target-fpr", type=float, default=0.01)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--targets", default="Wqkv,Wo")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-train-rows", type=int, default=0)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--meld-revision", default=MELD_REVISION,
                    help="MELD checkpoint revision on the HF Hub (default: the 23 Sep release); 'main' is the latest")
    ap.add_argument("--owner", default="malcolm")
    ap.add_argument("--run-name", default="")
    ap.add_argument("--run-role", default="train", choices=["train", "sweep"])
    args = ap.parse_args()

    train_on = [d for d in args.train_on.split(",") if d]
    mode = f"train-{'+'.join(train_on)}" if train_on else "in-distribution"
    # the seed is in the default name: the scores file is named after the run, so repeats must not collide
    run_name = args.run_name or f"meld-lora-{args.data}-{mode}-s{args.seed}"
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    train_frame, val, test = select_splits(load_corpus(args.data), train_on or None)
    if not args.no_balance:
        train_frame = balance_train(train_frame, args.seed)
    if args.max_train_rows:
        train_frame = train_frame.sample(min(args.max_train_rows, len(train_frame)), random_state=args.seed).reset_index(drop=True)
    for name, df in (("train", train_frame), ("val", val), ("test", test)):
        print(f"{name}: {len(df)} rows ({df['label'].mean():.1%} AI) datasets={sorted(df['dataset'].unique())}")
        print("   " + ", ".join(f"{k}={v}" for k, v in df["slice"].value_counts().sort_index().items()))

    meld, scorer, model_dir = load_meld(args.device, args.meld_revision)
    model, tokenizer = scorer.model, scorer.tok
    device = scorer.device
    cap = scorer.cap
    window = scorer.window

    from tracking import log_dict_artifact, log_split_metrics, setup_mlflow

    setup_mlflow(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name=run_name):
        mlflow.set_tags({"owner": args.owner, "run_role": "smoke" if args.max_train_rows else args.run_role,
                         "tuning_method": "lora", "model_family": "meld", "data_mode": mode})
        mlflow.log_params({"base_model": MELD_REPO, "meld_revision": model_dir.name,
                           "data": args.data, "min_words": args.min_words,
                           "train_on": ",".join(train_on) or "all",
                           "balanced": not args.no_balance, "calibrated": not args.no_calibrate,
                           "target_fpr": args.target_fpr, "epochs": args.epochs, "batch_size": args.batch_size,
                           "lr": args.lr, "lora_r": args.r, "lora_alpha": args.alpha, "lora_dropout": args.dropout,
                           "lora_targets": args.targets, "seed": args.seed, "train_n": len(train_frame),
                           "val_n": len(val), "test_n": len(test), "meld_model_dir": str(model_dir)})
        baseline_prob = None
        baseline_val_logits = baseline_logits = None
        base = None
        if not args.no_baseline:
            baseline_val_logits = predict_logits(meld, model, tokenizer, val["answer"], device, cap, window)
            baseline_logits = predict_logits(meld, model, tokenizer, test["answer"], device, cap, window)
            base, _, _ = evaluate_protocol(
                val, test, baseline_val_logits, baseline_logits,
                args.target_fpr, False, args.min_words)
            baseline_prob = expit(baseline_logits)
            log_split_metrics({f"baseline_{k}": v for k, v in base["results"].items()}, "test")

        add_lora(model, args.r, args.alpha, args.dropout, [x for x in args.targets.split(",") if x])
        best_epoch, best_auc, history = train(
            model, meld, tokenizer, train_frame, val, args, device, cap, window,
            lambda key, value, step: mlflow.log_metric(key, value, step=step))
        val_logits = predict_logits(meld, model, tokenizer, val["answer"], device, cap, window)
        test_logits = predict_logits(meld, model, tokenizer, test["answer"], device, cap, window)
        tuned, val_prob, test_prob = evaluate_protocol(val, test, val_logits, test_logits, args.target_fpr,
                                                       not args.no_calibrate, args.min_words)
        print(f"tuned: auroc={tuned['results']['auroc']:.4f} "
              f"deployed_tpr={tuned['results']['deployed_tpr']:.4f} "
              f"deployed_fpr={tuned['results']['deployed_fpr']:.4f} "
              f"(answers of >= {args.min_words} words: val {tuned['val_used']}, test {tuned['test_used']})")
        log_split_metrics(tuned["results"], "test")
        mlflow.log_params({"best_epoch": best_epoch})
        mlflow.log_metrics({"val/best_auroc": best_auc, "temperature": tuned["temperature"],
                            "threshold": tuned["threshold"]})

        OUT_DIR.mkdir(exist_ok=True)
        stem = OUT_DIR / run_name
        predictions = test.assign(logit=test_logits, prob=test_prob)
        predictions["baseline_prob"] = baseline_prob
        predictions = predictions[
            ["answer_id", "dataset", "slice", "label", "question_id", "generator", "n_words",
             "logit", "prob", "baseline_prob"]]
        predictions.to_csv(f"{stem}_test_predictions.csv", index=False)
        # the charts and slice tables use the same answers as the headline metrics
        used = (test["n_words"] >= args.min_words).to_numpy()
        test_used, prob_used = test[used].reset_index(drop=True), test_prob[used]
        baseline_used = baseline_prob[used] if baseline_prob is not None else None
        history_frame = pd.DataFrame(history)
        curve_frame = pd.DataFrame(curve_rows(test_used["label"], prob_used, "meld_lora"))
        if baseline_used is not None:
            curve_frame = pd.concat([
                curve_frame,
                pd.DataFrame(curve_rows(test_used["label"], baseline_used, "meld_baseline")),
            ], ignore_index=True)
        # LoRA uses validation-fitted temperature calibration; the zero-shot
        # baseline remains uncalibrated for this comparison.
        calibration_frame = pd.DataFrame(
            calibration_bins(test_used["label"], prob_used)
        ).assign(model="meld_lora", calibration="temperature")
        if baseline_used is not None:
            calibration_frame = pd.concat([
                calibration_frame,
                pd.DataFrame(calibration_bins(test_used["label"], baseline_used)).assign(
                    model="meld_baseline", calibration="none"
                ),
            ], ignore_index=True)
        predictions_used = predictions[used].reset_index(drop=True)
        slice_frame = pd.DataFrame(
            slice_report(predictions_used, y_true_col="label", y_prob_col="prob",
                         by="dataset", threshold=tuned["threshold"])
            + slice_report(predictions_used, y_true_col="label", y_prob_col="prob",
                           by="slice", threshold=tuned["threshold"])
        )
        for row in slice_frame.to_dict("records"):
            scope = str(row["slice_by"]).replace(" ", "_")
            value = str(row["slice_value"]).replace(" ", "_").replace("/", "_")
            for metric_name in ("deployed_tpr", "deployed_fpr", "auroc", "n"):
                value_to_log = row.get(metric_name)
                if value_to_log is not None and np.isfinite(value_to_log):
                    mlflow.log_metric(f"slice/{scope}/{value}/{metric_name}", float(value_to_log))

        labels = test_used["label"].to_numpy()
        probs = np.asarray(prob_used)
        flagged = probs >= tuned["threshold"]
        deployed_point = (flagged[labels == 0].mean(), flagged[labels == 1].mean())

        plot_training(history)
        plot_roc(curve_frame, deployed_point, args.target_fpr)
        plot_pr(curve_frame)
        plot_calibration(calibration_frame)
        plot_score_hist(labels, probs, tuned["threshold"], baseline_used)
        plot_slices(slice_frame)
        test_prevalence = float(test_used["label"].mean())
        plot_ppv_prevalence(tuned["results"], test_prevalence=test_prevalence)

        log_dataframe_artifact(history_frame, OUT_DIR / f"{run_name}_training_history.csv", "charts")
        log_dataframe_artifact(curve_frame, OUT_DIR / f"{run_name}_curves.csv", "charts")
        log_dataframe_artifact(calibration_frame, OUT_DIR / f"{run_name}_calibration_bins.csv", "charts")
        log_dataframe_artifact(slice_frame, OUT_DIR / f"{run_name}_slice_metrics.csv", "charts")
        ppv_frame = pd.DataFrame([
            {"ai_prevalence": float(key.rsplit("_", 1)[-1]),
             "projected_ppv": float(value), "source": "deployment"}
            for key, value in tuned["results"].items()
            if key.startswith("deployed_ppv_at_prevalence_") and np.isfinite(value)
        ])
        ppv_frame = pd.concat([
            ppv_frame,
            pd.DataFrame([{
                "ai_prevalence": test_prevalence,
                "projected_ppv": float(tuned["results"]["deployed_precision"]),
                "source": "test set",
            }]),
        ], ignore_index=True).sort_values("ai_prevalence")
        log_dataframe_artifact(ppv_frame, OUT_DIR / f"{run_name}_ppv_by_prevalence.csv", "charts")
        payload = {"run": run_name, "mode": mode, "args": vars(args),
                   "n": {"train": len(train_frame), "val": len(val), "test": len(test)},
                   "training_history": history,
                   "tuned": {"best_epoch": best_epoch, "best_val_auroc": best_auc,
                             **{k: v for k, v in tuned.items() if k != "results"},
                             "results": {k: float(v) for k, v in tuned["results"].items()}}}
        if base is not None:
            payload["baseline"] = {k: v for k, v in base.items() if k != "results"} | {
                "results": {k: float(v) for k, v in base["results"].items()}}

        # one row per answer for EVERY val and test row (not filtered by word count), for the
        # untouched and the tuned model; harness.py fits thresholds and evaluates from this file.
        parts = []
        if baseline_logits is not None:
            parts += [score_rows("meld-untouched", "val", val, baseline_val_logits, expit(baseline_val_logits)),
                      score_rows("meld-untouched", "test", test, baseline_logits, baseline_prob)]
        parts += [score_rows("meld-lora", "val", val, val_logits, val_prob),
                  score_rows("meld-lora", "test", test, test_logits, test_prob)]
        scores_path = save_scores(run_name, args.seed, parts)
        if train_on:
            print("note: 'test' here is every row of the held-out datasets, including their train/val partitions, "
                  "so harness.load_run cannot join this file to the corpus val/test files yet")
        Path(f"{stem}_results.json").write_text(json.dumps(payload, indent=2, default=float))
        model.backbone.save_pretrained(f"{stem}_adapter")
        tokenizer.save_pretrained(f"{stem}_adapter")
        torch.save({k: v.cpu() for k, v in model.state_dict().items() if not k.startswith("backbone.")},
                   f"{stem}_head.pt")
        # otherwise the tuned weights live only on the cluster's scratch disk (not backed up, purged
        # after 30 days); with the base checkpoint at meld_revision they can re-score new answers
        mlflow.log_artifacts(f"{stem}_adapter", "model/adapter")
        mlflow.log_artifact(f"{stem}_head.pt", "model")
        mlflow.log_artifact(f"{stem}_test_predictions.csv")
        log_dict_artifact(payload, "meld_lora_results.json")
        print(f"Wrote {stem}_results.json, _test_predictions.csv, chart artifacts, _adapter/, _head.pt "
              f"and {scores_path.name}")


if __name__ == "__main__":
    main()
