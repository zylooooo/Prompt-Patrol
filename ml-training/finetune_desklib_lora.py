"""
LoRA fine-tune of desklib (academic) on the combined v0.1 + spliced corpus.

Protocol (same as the zero-shot baselines, plus training):
  1. Score val and test with the UNTOUCHED model -> baseline row, on the same
     rows as the tuned model so the before/after table is apples to apples.
  2. Balance train to an even number of AI and human answers, train a LoRA
     adapter + the classifier head, keep the epoch with the best val AUROC.
  3. Temperature-scale the logits on val (calibration), fit the 1% FPR
     threshold on val, FREEZE both, score test once.

Two data modes:
  default            train on every dataset's train partition, test on the test
                     partition (in-distribution: same datasets, unseen questions).
  --train-on mohler  train/val on that dataset only; test on EVERY row of the
                     other datasets (the model has never seen those datasets,
                     so all of their partitions are legitimate test data).

    python finetune_desklib_lora.py
    python finetune_desklib_lora.py --train-on mohler
    python finetune_desklib_lora.py --epochs 1 --max-train-rows 200 --run-name smoke   # pipeline check
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from scipy.optimize import minimize_scalar
from scipy.special import expit
from sklearn.metrics import roc_auc_score

from combined_data import load_combined, slice_flag_rates
from metrics import calibration_metrics, evaluate, threshold_at_fpr

MLFLOW_EXPERIMENT = "E2-finetune"
OUT_DIR = Path(__file__).parent / "outputs"
DATASETS = ("mohler", "sprag", "engsaf")
# answers are ~15-20 words; the zero-shot scripts pad to desklib's 768, which
# mean-pooling ignores, so a short dynamic length gives the same scores faster
MAX_LEN = 256


# --------------------------------------------------------------------------
# data selection
# --------------------------------------------------------------------------

def select_splits(frames: dict[str, pd.DataFrame], train_on: list[str] | None):
    """
    Returns (train, val, test) frames, each indexed 0..n-1.

    train_on None  -> all datasets; test = the test partition.
    train_on [..]  -> train/val limited to those datasets; test = every row of
                      the remaining datasets, whatever its partition.
    """
    if not train_on:
        return (frames["train"].reset_index(drop=True),
                frames["val"].reset_index(drop=True),
                frames["test"].reset_index(drop=True))

    if bad := set(train_on) - set(DATASETS):
        raise SystemExit(f"unknown dataset(s) {sorted(bad)}; choose from {DATASETS}")
    if set(train_on) == set(DATASETS):
        raise SystemExit("--train-on names every dataset, so nothing is held out; omit it instead")

    keep = lambda df: df[df["dataset"].isin(train_on)].reset_index(drop=True)
    everything = pd.concat(frames.values(), ignore_index=True)
    held_out = everything[~everything["dataset"].isin(train_on)].reset_index(drop=True)
    return keep(frames["train"]), keep(frames["val"]), held_out


def balance_train(train: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Even AI and human counts, by randomly dropping rows from the larger class.
    The raw/spliced/generator mix of the AI rows is preserved in expectation."""
    n = int(min((train["label"] == 0).sum(), (train["label"] == 1).sum()))
    parts = [g.sample(n, random_state=seed) for _, g in train.groupby("label")]
    return pd.concat(parts).sample(frac=1.0, random_state=seed).reset_index(drop=True)


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------

def build_lora_model(scorer, r: int, alpha: int, dropout: float, targets: list[str]):
    from peft import LoraConfig, get_peft_model

    # LoRA on the DeBERTa attention projections; the 1-logit classifier head is
    # trained in full (and saved with the adapter) because it was fit for the
    # original task and should be free to adapt.
    cfg = LoraConfig(r=r, lora_alpha=alpha, lora_dropout=dropout,
                     target_modules=targets, modules_to_save=["classifier"])
    model = get_peft_model(scorer.model, cfg)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"trainable params: {trainable:,} of {total:,} ({trainable / total:.2%})")
    hit = sorted({n.split(".lora_A")[0].split(".")[-1] for n, p in model.named_parameters()
                  if p.requires_grad and ".lora_A" in n})
    print(f"LoRA applied to: {hit}")
    if not hit:
        raise SystemExit(f"target_modules {targets} matched nothing - check the DeBERTa module names")
    return model


def encode(tokenizer, texts, device):
    enc = tokenizer(list(texts), padding=True, truncation=True, max_length=MAX_LEN, return_tensors="pt")
    return enc["input_ids"].to(device), enc["attention_mask"].to(device)


@torch.no_grad()
def predict_logits(model, tokenizer, texts, device, batch_size=64) -> np.ndarray:
    """Raw logits (pre-sigmoid). Sorted by length so batches pad little; order restored."""
    model.eval()
    texts = np.asarray([str(t) for t in texts], dtype=object)
    order = np.argsort([len(t) for t in texts])
    out = np.empty(len(texts), dtype=np.float64)
    for i in range(0, len(texts), batch_size):
        idx = order[i:i + batch_size]
        ids, mask = encode(tokenizer, texts[idx], device)
        with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            logits = model(input_ids=ids, attention_mask=mask)["logits"]
        out[idx] = logits.float().squeeze(-1).cpu().numpy()
    return out


def train_lora(model, tokenizer, train: pd.DataFrame, val: pd.DataFrame, args, device, log_metric):
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=args.weight_decay)
    total_steps = int(np.ceil(len(train) / args.batch_size)) * args.epochs
    warmup = max(1, int(0.1 * total_steps))
    # linear warmup over the first 10% of steps, then linear decay to zero
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min((s + 1) / warmup, max(0.0, (total_steps - s) / max(1, total_steps - warmup))))

    texts = train["answer"].astype(str).to_numpy()
    labels = train["label"].to_numpy(dtype=np.float32)
    rng = np.random.default_rng(args.seed)

    best_auc, best_state, best_epoch = -1.0, None, -1
    for epoch in range(1, args.epochs + 1):
        model.train()
        perm = rng.permutation(len(train))
        t0, running = time.perf_counter(), 0.0
        for i in range(0, len(perm), args.batch_size):
            idx = perm[i:i + args.batch_size]
            ids, mask = encode(tokenizer, texts[idx], device)
            y = torch.from_numpy(labels[idx]).to(device)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(input_ids=ids, attention_mask=mask)["logits"].squeeze(-1)
            loss = F.binary_cross_entropy_with_logits(logits.float(), y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            sched.step()
            opt.zero_grad(set_to_none=True)
            running += loss.item() * len(idx)
        train_loss = running / len(train)

        val_logits = predict_logits(model, tokenizer, val["answer"], device)
        val_auc = float(roc_auc_score(val["label"], val_logits))
        val_loss = float(F.binary_cross_entropy_with_logits(
            torch.from_numpy(val_logits), torch.from_numpy(val["label"].to_numpy(dtype=np.float64))).item())
        print(f"epoch {epoch}/{args.epochs}: train_loss={train_loss:.4f} val_loss={val_loss:.4f} "
              f"val_auroc={val_auc:.4f} ({time.perf_counter() - t0:.0f}s)", flush=True)
        log_metric("train/loss", train_loss, epoch)
        log_metric("val/loss", val_loss, epoch)
        log_metric("val/auroc", val_auc, epoch)

        if val_auc > best_auc:
            best_auc, best_epoch = val_auc, epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.named_parameters() if v.requires_grad}

    # strict=False because best_state holds only the trainable tensors; but a key
    # that matches nothing would silently skip the restore, so fail on that
    result = model.load_state_dict(best_state, strict=False)
    if result.unexpected_keys:
        raise RuntimeError(f"best-epoch restore matched no parameters for: {result.unexpected_keys[:3]}")
    print(f"restored epoch {best_epoch} (val_auroc={best_auc:.4f})")
    return best_epoch, best_auc


# --------------------------------------------------------------------------
# calibration + scoring protocol
# --------------------------------------------------------------------------

def fit_temperature(val_logits: np.ndarray, val_labels: np.ndarray) -> float:
    """Single temperature T minimising the val NLL of sigmoid(logit / T)."""
    y = np.asarray(val_labels, dtype=float)

    def nll(log_t):
        p = np.clip(expit(val_logits / np.exp(log_t)), 1e-12, 1 - 1e-12)
        return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))

    return float(np.exp(minimize_scalar(nll, bounds=(-3, 4), method="bounded").x))


def evaluate_protocol(val: pd.DataFrame, test: pd.DataFrame, val_logits, test_logits,
                      calibrate: bool, target_fpr: float):
    """val picks T and the threshold; test is scored once with both frozen."""
    T = fit_temperature(val_logits, val["label"].to_numpy()) if calibrate else 1.0
    val_p, test_p = expit(val_logits / T), expit(test_logits / T)
    for name, p in (("val", val_p), ("test", test_p)):
        if sat := int((p >= 1 - 1e-12).sum()):
            print(f"WARNING: {sat} {name} probabilities saturate at 1.0 (ties near the threshold), T={T:.2f}")
    thr = threshold_at_fpr(val["label"], val_p, target_fpr)
    results = evaluate(test["label"], test_p, thr, headline_fpr=target_fpr)

    slices = {"all": slice_flag_rates(test, test_p, thr)}
    for d in sorted(test["dataset"].unique()):
        m = (test["dataset"] == d).to_numpy()
        slices[d] = slice_flag_rates(test[m].reset_index(drop=True), test_p[m], thr)
    raw = calibration_metrics(test["label"], expit(test_logits))
    return {"temperature": T, "threshold": thr, "results": results, "slices": slices,
            "uncalibrated_ece": raw["ece"], "uncalibrated_brier": raw["brier"]}, test_p


def print_report(title: str, out: dict) -> None:
    r = out["results"]
    print(f"\n=== {title} ===  T={out['temperature']:.3f} threshold={out['threshold']:.4f}")
    for key in ("auroc", "deployed_tpr", "deployed_fpr", "deployed_precision", "ece", "brier"):
        print(f"  {key}: {r[key]:.4f}")
    for scope, rows in out["slices"].items():
        print(f"  [{scope}]")
        for row in rows:
            print(f"    {row['slice']:<11} n={row['n']:<5} {row['kind']}={row['flag_rate']:.3f}")


def jsonable(out: dict) -> dict:
    return {k: v for k, v in out.items() if k != "results"} | {
        "results": {k: float(v) for k, v in out["results"].items()}}


# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train-on", default="", help="comma-separated datasets to train on (default: all)")
    ap.add_argument("--no-balance", action="store_true", help="skip the even AI/human downsampling of train")
    ap.add_argument("--no-calibrate", action="store_true")
    ap.add_argument("--no-baseline", action="store_true", help="skip scoring the untouched model first")
    ap.add_argument("--target-fpr", type=float, default=0.01)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--targets", default="query_proj,value_proj")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-train-rows", type=int, default=0, help="debug: cap the train rows")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--owner", default="malcolm")
    ap.add_argument("--run-name", default="")
    args = ap.parse_args()

    train_on = [d for d in args.train_on.split(",") if d]
    mode = f"train-{'+'.join(train_on)}" if train_on else "in-distribution"
    run_name = args.run_name or f"desklib-lora-{mode}"

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    train, val, test = select_splits(load_combined(), train_on or None)
    if not args.no_balance:
        before = train["label"].value_counts().to_dict()
        train = balance_train(train, args.seed)
        print(f"balanced train: {before} -> {train['label'].value_counts().to_dict()}")
    if args.max_train_rows:
        train = train.sample(min(args.max_train_rows, len(train)), random_state=args.seed).reset_index(drop=True)
    for name, df in (("train", train), ("val", val), ("test", test)):
        print(f"{name}: {len(df)} rows ({df['label'].mean():.1%} AI) datasets={sorted(df['dataset'].unique())}")
        print("   " + ", ".join(f"{k}={v}" for k, v in df["slice"].value_counts().sort_index().items()))

    import mlflow
    from eval_desklib_zeroshot import Scorer
    from tracking import log_dict_artifact, log_split_metrics, setup_mlflow

    scorer = Scorer(device=args.device)
    device, tokenizer = scorer.device, scorer.tokenizer

    setup_mlflow(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name=run_name):
        # reporting.py drops run_role="smoke" from every table, so a pipeline check
        # (capped train rows) can never be mistaken for a result
        mlflow.set_tags({"owner": args.owner, "run_role": "smoke" if args.max_train_rows else "train",
                         "tuning_method": "lora",
                         "model_family": "deberta", "data_mode": mode})
        mlflow.log_params({
            "base_model": "desklib/ai-text-detector-academic-v1.01", "data": "v0.1+spliced",
            "train_on": ",".join(train_on) or "all", "balanced": not args.no_balance,
            "calibrated": not args.no_calibrate, "target_fpr": args.target_fpr,
            "epochs": args.epochs, "batch_size": args.batch_size, "lr": args.lr,
            "lora_r": args.r, "lora_alpha": args.alpha, "lora_dropout": args.dropout,
            "lora_targets": args.targets, "max_len": MAX_LEN, "seed": args.seed,
            "train_n": len(train), "val_n": len(val), "test_n": len(test),
        })
        payload = {"run": run_name, "mode": mode, "args": vars(args),
                   "n": {"train": len(train), "val": len(val), "test": len(test)}}

        if not args.no_baseline:
            print("\nScoring untouched model (baseline)...")
            base, _ = evaluate_protocol(
                val, test,
                predict_logits(scorer.model, tokenizer, val["answer"], device),
                predict_logits(scorer.model, tokenizer, test["answer"], device),
                calibrate=False, target_fpr=args.target_fpr)
            print_report("BASELINE (zero-shot, same rows)", base)
            log_split_metrics({f"baseline_{k}": v for k, v in base["results"].items()}, "test")
            payload["baseline"] = jsonable(base)

        model = build_lora_model(scorer, args.r, args.alpha, args.dropout, args.targets.split(","))
        model.to(device)
        print("\nTraining...")
        best_epoch, best_auc = train_lora(model, tokenizer, train, val, args, device,
                                          lambda k, v, s: mlflow.log_metric(k, v, step=s))
        mlflow.log_params({"best_epoch": best_epoch})

        val_logits = predict_logits(model, tokenizer, val["answer"], device)
        test_logits = predict_logits(model, tokenizer, test["answer"], device)
        tuned, test_p = evaluate_protocol(val, test, val_logits, test_logits,
                                          calibrate=not args.no_calibrate, target_fpr=args.target_fpr)
        print_report("TUNED (LoRA)", tuned)
        log_split_metrics(tuned["results"], "test")
        mlflow.log_metrics({"temperature": tuned["temperature"], "threshold": tuned["threshold"],
                            "test/uncalibrated_ece": tuned["uncalibrated_ece"],
                            "test/uncalibrated_brier": tuned["uncalibrated_brier"]})
        for scope, rows in tuned["slices"].items():
            for row in rows:
                mlflow.log_metric(f"test/{scope}_{row['slice'].replace('-', '_')}_flag_rate", row["flag_rate"])
        payload["tuned"] = jsonable(tuned) | {"best_epoch": best_epoch, "best_val_auroc": best_auc}

        OUT_DIR.mkdir(exist_ok=True)
        stem = OUT_DIR / f"desklib_lora_{mode}"
        test.assign(logit=test_logits, prob=test_p)[
            ["answer_id", "dataset", "slice", "label", "question_id", "generator", "n_words", "logit", "prob"]
        ].to_csv(f"{stem}_test_predictions.csv", index=False)
        Path(f"{stem}_results.json").write_text(json.dumps(payload, indent=2, default=float))
        model.save_pretrained(f"{stem}_adapter")
        mlflow.log_artifact(f"{stem}_test_predictions.csv")
        log_dict_artifact(payload, "lora_results.json")
        print(f"\nWrote {stem}_results.json, _test_predictions.csv, _adapter/")
        print(f"MLflow run: {mlflow.active_run().info.run_id}")


if __name__ == "__main__":
    main()
