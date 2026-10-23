## fine-tunes RADAR on the combined corpus with LoRA, DoRA or a full fine-tune (PP-548)

from __future__ import annotations

import argparse
import json
import random
import re
import tempfile
import time
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from scipy.optimize import minimize_scalar
from scipy.special import expit
from sklearn.metrics import roc_auc_score

import radar
from combined_data import DATA_DIR, KEEP, load_combined, slice_flag_rates
from metrics import calibration_metrics, evaluate, threshold_at_fpr
from scores import OUT_DIRECTORY, save_scores, score_rows
from tracking import _git_state, log_dict_artifact, log_split_metrics, setup_mlflow

MLFLOW_EXPERIMENT = "E2-finetune"
DATASETS = ("mohler", "sprag", "engsaf")
METHODS = ("lora", "dora", "full")

##  two epochs whose val partial AUROC differ by no more than this count as tied, see train_model()
PAUROC_TIE = 0.002

##  reworded AI answers (all label 1). their train rows are added to training with --extended,
##  their test rows are always scored as separate robustness numbers, never mixed into the headline metrics
EXTENDED_SETS = {
    "paraphrased": DATA_DIR / "v0.1-paraphrased.parquet",
    "human_edited": DATA_DIR / "v0.1-human_edited.parquet",
}

##  LoRA/DoRA go on every linear layer inside the 24 encoder layers (attention query/key/value/output and the feed-forward layers).
##  written as a pattern so that classifier.dense is NOT matched: the classifier head is trained in full instead (modules_to_save)
ALL_LINEAR = r"roberta\.encoder\.layer\.\d+\.(attention\.self\.(query|key|value)|attention\.output\.dense|intermediate\.dense|output\.dense)"

##  makes a run repeatable: same seed -> same shuffling, same dropout, same starting adapter weights
##
##  seed:   the random seed
def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

##  picks the train, val and test rows
##      - train_on empty:   every dataset; test = the test partition (in-distribution: same datasets, unseen questions)
##      - train_on given:   train/val use only those datasets; test = every row of the other datasets (never seen at all)
##  with extended, the train rows of the paraphrased and human-edited sets (same datasets) are added to train only,
##  so val and test stay exactly the rows desklib and MELD were scored on
##
##  train_on:   dataset names to train on (mohler/sprag/engsaf), empty for all
##  extended:   add the reworded AI answers to training
def select_data(train_on: list[str], extended: bool):
    if bad := set(train_on) - set(DATASETS):
        raise SystemExit(f"unknown dataset(s) {sorted(bad)}; choose from {DATASETS}")

    if set(train_on) == set(DATASETS):
        raise SystemExit("--train-on names every dataset, so nothing is held out; leave it out instead")

    frames = load_combined()
    in_train_sets = (lambda df: df["dataset"].isin(train_on)) if train_on else (lambda df: pd.Series(True, index=df.index))

    if train_on:
        everything = pd.concat(frames.values(), ignore_index=True)
        train, val = frames["train"][in_train_sets(frames["train"])], frames["val"][in_train_sets(frames["val"])]
        test = everything[~in_train_sets(everything)]
    else:
        train, val, test = frames["train"], frames["val"], frames["test"]

    robustness, extra_train = {}, []
    for name, path in EXTENDED_SETS.items():
        if not path.exists():
            raise FileNotFoundError(f"{path} not found - run `dvc pull` in ml-training/ first")
        rows = pd.read_parquet(path).assign(slice=name, ai_fraction=1.0)[KEEP + ["slice", "ai_fraction"]]
        held_out = rows[~in_train_sets(rows)] if train_on else rows[rows["partition"] == "test"]
        if len(held_out):
            robustness[name] = held_out.reset_index(drop=True)
        if extended:
            extra_train.append(rows[(rows["partition"] == "train") & in_train_sets(rows)])

    train = pd.concat([train, *extra_train], ignore_index=True)
    return train.reset_index(drop=True), val.reset_index(drop=True), test.reset_index(drop=True), robustness

##  desklib's way of balancing (--balance): randomly drops rows from the larger class until AI and human counts are equal.
##  the mix of raw, spliced and generator rows inside each class is kept in expectation.
##  only for the like-for-like desklib-recipe run, the default keeps every row and weights the loss instead
##
##  train:  training rows
##  seed:   which rows are dropped
##  returns the balanced, shuffled rows
def balance_train(train: pd.DataFrame, seed: int) -> pd.DataFrame:
    n = int(train["label"].value_counts().min())
    parts = [g.sample(n, random_state=seed) for _, g in train.groupby("label")]
    return pd.concat(parts).sample(frac=1.0, random_state=seed).reset_index(drop=True)

##  puts LoRA or DoRA adapters on RADAR, or leaves every weight trainable for a full fine-tune
##  the classifier head is always fully trainable, since untouched RADAR's head ranks our answers backwards
##
##  model:      untouched RADAR
##  method:     lora/dora/full
##  r:          adapter rank (how much each adapter can learn), ignored for full
##  alpha:      adapter scaling, usually 2 x r, ignored for full
##  dropout:    adapter dropout, ignored for full
##  targets:    "all" for every encoder linear layer, or a comma list such as "query,value"
def prepare_model(model, method: str, r: int, alpha: int, dropout: float, targets: str):
    if method == "full":
        for p in model.parameters():
            p.requires_grad = True
        return model

    from peft import LoraConfig, get_peft_model

    target_modules = ALL_LINEAR if targets == "all" else targets.split(",")
    cfg = LoraConfig(r=r, lora_alpha=alpha, lora_dropout=dropout, target_modules=target_modules,
                     modules_to_save=["classifier"], use_dora=method == "dora")
    model = get_peft_model(model, cfg)

    hit = sorted({re.sub(r"\.\d+\.", ".N.", n.split(".lora_A")[0]) for n, p in model.named_parameters() if ".lora_A" in n})
    if not hit:
        raise SystemExit(f"--targets {targets!r} matched no layers")
    print(f"adapters on {len(hit)} layer types: {[h.split('layer.N.')[-1] for h in hit]}")
    return model

##  the optimiser's parameter groups
##  LoRA/DoRA: one learning rate for every trainable weight.
##  full: layer-wise learning-rate decay -> each layer down from the top gets layer_decay x the rate of the layer above,
##  so the lower layers (general language knowledge from RADAR's training) change least, and the classifier changes most.
##  biases and LayerNorm weights get no weight decay, the usual practice for transformers
##
##  model:          the prepared model
##  method:         lora/dora/full
##  lr:             learning rate (for full: the classifier's rate, the top of the decay)
##  weight_decay:   AdamW weight decay
##  layer_decay:    per-layer factor for full, e.g. 0.9
def param_groups(model, method: str, lr: float, weight_decay: float, layer_decay: float) -> list[dict]:
    if method != "full":
        return [{"params": [p for p in model.parameters() if p.requires_grad], "lr": lr, "weight_decay": weight_decay}]

    top = model.config.num_hidden_layers + 1
    groups: dict[tuple, dict] = {}
    for name, p in model.named_parameters():
        if name.startswith("roberta.embeddings"):
            depth = 0
        elif m := re.search(r"encoder\.layer\.(\d+)\.", name):
            depth = int(m.group(1)) + 1
        else:
            depth = top
        no_decay = name.endswith("bias") or "LayerNorm" in name
        group = groups.setdefault((depth, no_decay), {"params": [], "lr": lr * layer_decay ** (top - depth),
                                                      "weight_decay": 0.0 if no_decay else weight_decay})
        group["params"].append(p)
    return list(groups.values())

##  partial AUROC up to 1% FPR (sklearn's standardised version: 0.5 = random, 1.0 = perfect)
##  scores only the low-false-positive region the project cares about, so it picks the best epoch for the 1% FPR threshold,
##  and it is steadier than TPR at 1% FPR itself on ~880 validation human answers
##
##  y:      true labels (1 = AI)
##  logits: model scores
def pauroc(y, logits, max_fpr: float = 0.01) -> float:
    return float(roc_auc_score(y, logits, max_fpr=max_fpr))

##  trains the model, scoring val after every epoch, and puts back the weights from the epoch with the best val partial AUROC.
##  epochs whose partial AUROC is within PAUROC_TIE of the best count as tied, and the tie goes to the higher plain val AUROC,
##  so the choice isn't made by noise when partial AUROC barely moves (it sits near its 0.5 floor early in training)
##  loss: binary cross-entropy on radar_logit(), with AI answers weighted by (human count / AI count),
##  so both classes count equally without throwing away any rows (desklib balanced by dropping AI rows instead, see --balance)
##  lr schedule: linear warm-up over the first 10% of steps, then linear decay to zero
##
##  model:      the prepared model
##  tokenizer:  RADAR's tokenizer
##  train:      training rows (answer, label)
##  val:        validation rows (answer, label)
##  args:       the command-line settings
##  device:     where the model is
##  log_metric: function(name, value, step) that records a metric
def train_model(model, tokenizer, train: pd.DataFrame, val: pd.DataFrame, args, device, log_metric):
    groups = param_groups(model, args.method, args.lr, args.weight_decay, args.layer_decay)
    params = [p for g in groups for p in g["params"]]
    opt = torch.optim.AdamW(groups)
    steps = int(np.ceil(len(train) / args.batch_size)) * args.epochs
    warmup = max(1, int(0.1 * steps))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min((s + 1) / warmup, max(0.0, (steps - s) / max(1, steps - warmup))))

    texts = train["answer"].astype(str).to_numpy()
    labels = train["label"].to_numpy(dtype=np.float32)
    n_ai, n_human = int(labels.sum()), int(len(labels) - labels.sum())
    pos_weight = torch.tensor(n_human / n_ai if args.class_weights else 1.0, device=device)
    print(f"train: {n_human} human, {n_ai} AI -> AI loss weight {pos_weight.item():.3f}")

    rng = np.random.default_rng(args.seed)
    best_score, best_auroc, best_epoch, best_state, history = -1.0, -1.0, -1, None, []
    for epoch in range(1, args.epochs + 1):
        model.train()
        start, running = time.perf_counter(), 0.0
        order = rng.permutation(len(texts))
        for i in range(0, len(texts), args.batch_size):
            idx = order[i:i + args.batch_size]
            ids, mask = radar.encode(tokenizer, texts[idx], device)
            y = torch.from_numpy(labels[idx]).to(device)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = radar.radar_logit(model, ids, mask)
            loss = F.binary_cross_entropy_with_logits(logits.float(), y, pos_weight=pos_weight)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            sched.step()
            opt.zero_grad(set_to_none=True)
            running += loss.item() * len(idx)

        val_logits = radar.predict_logits(model, tokenizer, val["answer"], device)
        y_val = val["label"].to_numpy()
        row = {
            "epoch": epoch,
            "train_loss": running / len(texts),
            "val_loss": float(F.binary_cross_entropy_with_logits(torch.from_numpy(val_logits), torch.from_numpy(y_val.astype(np.float64)))),
            "val_auroc": float(roc_auc_score(y_val, val_logits)),
            "val_pauroc": pauroc(y_val, val_logits),
            "lr": sched.get_last_lr()[-1],
            "seconds": time.perf_counter() - start,
        }
        history.append(row)
        print(f"epoch {epoch}/{args.epochs}: train_loss={row['train_loss']:.4f} val_loss={row['val_loss']:.4f} "
              f"val_auroc={row['val_auroc']:.4f} val_pauroc@1%={row['val_pauroc']:.4f} ({row['seconds']:.0f}s)", flush=True)
        for key in ("train_loss", "val_loss", "val_auroc", "val_pauroc", "lr", "seconds"):
            log_metric(key.replace("_", "/", 1) if key.startswith(("train_", "val_")) else f"train/{key}", row[key], epoch)

        clearly_better = row["val_pauroc"] > best_score + PAUROC_TIE
        tied_but_better = abs(row["val_pauroc"] - best_score) <= PAUROC_TIE and row["val_auroc"] > best_auroc
        if clearly_better or tied_but_better:
            best_score, best_auroc, best_epoch = row["val_pauroc"], row["val_auroc"], epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.named_parameters() if v.requires_grad}

    result = model.load_state_dict(best_state, strict=False)
    if result.unexpected_keys:
        raise RuntimeError(f"best-epoch restore matched no parameters for: {result.unexpected_keys[:3]}")
    print(f"restored epoch {best_epoch} (val partial AUROC {best_score:.4f}, val AUROC {best_auroc:.4f})")
    return best_epoch, best_score, history

##  one temperature T that makes sigmoid(logit / T) best match the val labels (lowest log loss).
##  only rescales the scores, so the ranking (AUROC) doesn't change, but the probabilities become honest
##
##  val_logits: tuned model's val logits
##  val_labels: val labels
def fit_temperature(val_logits: np.ndarray, val_labels: np.ndarray) -> float:
    y = np.asarray(val_labels, dtype=float)

    def nll(log_t):
        p = np.clip(expit(val_logits / np.exp(log_t)), 1e-12, 1 - 1e-12)
        return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))

    return float(np.exp(minimize_scalar(nll, bounds=(-3, 4), method="bounded").x))

##  the evaluation protocol: everything is chosen on val, frozen, then test is scored once
##      1. temperature T fitted on val (skipped for the untouched model, which stays as published)
##      2. the 1% FPR threshold fitted on val's (calibrated) probabilities
##      3. test metrics, per-slice flag rates and robustness numbers, all at that frozen threshold
##
##  val, test:          the rows
##  val_logits, test_logits, robust_logits: the model's logits for each, robust_logits = {set name: logits}
##  calibrate:          fit a temperature (tuned model) or not (untouched model)
##  target_fpr:         the false-positive budget
def evaluate_protocol(val, test, val_logits, test_logits, robust_logits: dict, calibrate: bool, target_fpr: float):
    T = fit_temperature(val_logits, val["label"].to_numpy()) if calibrate else 1.0
    val_p, test_p = expit(val_logits / T), expit(test_logits / T)
    threshold = threshold_at_fpr(val["label"], val_p, target_fpr)
    human = test_logits[test["label"].to_numpy() == 0]
    robust = {}
    for name, logits in robust_logits.items():
        y = np.r_[np.zeros(len(human)), np.ones(len(logits))]
        robust[name] = {"n": len(logits), "flag_rate": float((expit(logits / T) >= threshold).mean()),
                        "auroc": float(roc_auc_score(y, np.r_[human, logits]))}
    out = {
        "temperature": T,
        "threshold": threshold,
        "results": evaluate(test["label"], test_p, threshold, headline_fpr=target_fpr),
        "test_pauroc": pauroc(test["label"], test_logits, target_fpr),
        "uncalibrated_ece": calibration_metrics(test["label"], expit(test_logits))["ece"],
        "slices": slice_flag_rates(test, test_p, threshold),
        "robustness": robust,
    }
    return out, val_p, test_p

##  prints the headline numbers of one evaluated model
##
##  title:  heading for the printout
##  out:    result of evaluate_protocol()
def print_report(title: str, out: dict) -> None:
    r = out["results"]
    print(f"\n=== {title} ===  (T={out['temperature']:.3f}, threshold={out['threshold']:.4f})")
    print(f"  auroc {r['auroc']:.4f}  pauroc@1% {out['test_pauroc']:.4f}  deployed_tpr {r['deployed_tpr']:.4f}  "
          f"deployed_fpr {r['deployed_fpr']:.4f}  ece {r['ece']:.4f}")
    print("  " + "  ".join(f"{s['slice']}={s['flag_rate']:.3f}" for s in out["slices"]))
    print("  robustness: " + "  ".join(f"{k} flag={v['flag_rate']:.3f} auroc={v['auroc']:.3f}" for k, v in out["robustness"].items()))

##  logs one evaluated model to MLflow: test metrics, partial AUROC, slice flag rates and robustness, under a name prefix
##
##  prefix: "" for the tuned model, "baseline_" for the untouched one
##  out:    result of evaluate_protocol()
def log_evaluation(prefix: str, out: dict) -> None:
    log_split_metrics({f"{prefix}{k}": v for k, v in out["results"].items()}, "test")
    mlflow.log_metric(f"test/{prefix}pauroc_1pct", out["test_pauroc"])
    for row in out["slices"]:
        mlflow.log_metric(f"test/{prefix}slice_{row['slice'].replace('-', '_')}_flag_rate", row["flag_rate"])
    for name, row in out["robustness"].items():
        mlflow.log_metrics({f"test/{prefix}robust_{name}_flag_rate": row["flag_rate"], f"test/{prefix}robust_{name}_auroc": row["auroc"]})

##  the run, in order:
##      1. pick the data (and the extended rows with --extended, balanced by dropping rows with --balance), load untouched RADAR
##      2. score val, test and the robustness sets with the UNTOUCHED model first -> baseline on exactly the same rows
##      3. add adapters (lora/dora) or unfreeze everything (full), train, keep the best epoch by val partial AUROC
##      4. score everything with the tuned model, calibrate on val, fix the threshold on val, score test once
##      5. log to MLflow, save the scores file for the harness, the thresholds, and the adapter (lora/dora only)
##  --offline logs to a temporary local folder instead of DagsHub, for testing without adding a run to the shared board
##  --max-train-rows marks the run as run_role=smoke, which the report tables drop
def main() -> None:
    ap = argparse.ArgumentParser(description="Fine-tune RADAR with LoRA, DoRA or a full fine-tune (PP-548).")
    ap.add_argument("--method", choices=METHODS, default="lora")
    ap.add_argument("--train-on", default="", help="comma-separated datasets to train on (default: all)")
    ap.add_argument("--extended", action="store_true", help="add the paraphrased and human-edited train rows")
    ap.add_argument("--balance", action="store_true", help="desklib's recipe: drop rows until AI and human counts match")
    ap.add_argument("--no-class-weights", dest="class_weights", action="store_false", help="plain loss, no class weighting")
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=None, help="default: 2e-4 for lora/dora, 2e-5 for full")
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--layer-decay", type=float, default=0.9, help="full only: learning-rate factor per layer going down")
    ap.add_argument("--r", type=int, default=32)
    ap.add_argument("--alpha", type=int, default=None, help="default: 2 x r")
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--targets", default="all", help='"all" encoder linear layers, or a comma list such as "query,value"')
    ap.add_argument("--target-fpr", type=float, default=0.01)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-train-rows", type=int, default=0, help="smoke test: cap the train rows (tags the run as smoke)")
    ap.add_argument("--device", default=None, help="cuda, mps or cpu (default: best available)")
    ap.add_argument("--owner", default="faheem")
    ap.add_argument("--run-name", default="")
    ap.add_argument("--run-role", default="train", choices=["train", "sweep"], help="sweep runs are left out of headline tables")
    ap.add_argument("--offline", action="store_true", help="log to a temporary local folder, not DagsHub")
    args = ap.parse_args()
    args.lr = args.lr or (2e-5 if args.method == "full" else 2e-4)
    args.alpha = args.alpha or 2 * args.r

    set_seed(args.seed)
    train_on = [d for d in args.train_on.split(",") if d]
    mode = f"train-{'+'.join(train_on)}" if train_on else "in-distribution"
    tuned_name = f"radar-{args.method}{'-ext' if args.extended else ''}"
    run_name = args.run_name or f"{tuned_name}-{mode}"

    train, val, test, robustness = select_data(train_on, args.extended)
    if args.balance:
        before = train["label"].value_counts().to_dict()
        train = balance_train(train, args.seed)
        print(f"balanced train: {before} -> {train['label'].value_counts().to_dict()}")
    if args.max_train_rows:
        train = train.sample(min(args.max_train_rows, len(train)), random_state=args.seed).reset_index(drop=True)
    for name, df in (("train", train), ("val", val), ("test", test)):
        print(f"{name}: {len(df)} rows ({df['label'].mean():.1%} AI) datasets={sorted(df['dataset'].unique())}")
    print("robustness: " + ", ".join(f"{k}={len(v)}" for k, v in robustness.items()))

    model, tokenizer, device = radar.load_radar(args.device)

    if args.offline:
        tmp = Path(tempfile.mkdtemp(prefix="radar-offline-"))
        mlflow.set_tracking_uri(f"sqlite:///{tmp / 'mlflow.db'}")
        mlflow.create_experiment(MLFLOW_EXPERIMENT, artifact_location=(tmp / "artifacts").as_uri())
        mlflow.set_experiment(MLFLOW_EXPERIMENT)
        print(f"OFFLINE: logging to {mlflow.get_tracking_uri()}, nothing goes to DagsHub")
    else:
        setup_mlflow(MLFLOW_EXPERIMENT)

    with mlflow.start_run(run_name=run_name):
        mlflow.set_tags({"owner": args.owner, "run_role": "smoke" if args.max_train_rows else args.run_role,
                         "tuning_method": args.method, "model_family": "radar", "data_mode": mode, **_git_state()})
        mlflow.log_params({
            "base_model": f"{radar.MODEL_ID}@{radar.REVISION[:12]}",
            "data": "v0.1+spliced" + ("+paraphrased+human_edited(train)" if args.extended else ""),
            "train_on": ",".join(train_on) or "all", "balanced": args.balance, "class_weights": args.class_weights,
            "target_fpr": args.target_fpr,
            "method": args.method, "epochs": args.epochs, "batch_size": args.batch_size, "lr": args.lr,
            "weight_decay": args.weight_decay, "layer_decay": args.layer_decay if args.method == "full" else None,
            "lora_r": args.r if args.method != "full" else None, "lora_alpha": args.alpha if args.method != "full" else None,
            "lora_dropout": args.dropout if args.method != "full" else None,
            "lora_targets": args.targets if args.method != "full" else None,
            "max_len": radar.MAX_LEN, "seed": args.seed, "train_n": len(train), "val_n": len(val), "test_n": len(test),
        })

        def score_all(m):
            return (radar.predict_logits(m, tokenizer, val["answer"], device),
                    radar.predict_logits(m, tokenizer, test["answer"], device),
                    {k: radar.predict_logits(m, tokenizer, v["answer"], device) for k, v in robustness.items()})

        print("\nScoring the untouched model (baseline, same rows)...")
        base_val, base_test, base_robust = score_all(model)
        base, base_val_p, base_test_p = evaluate_protocol(val, test, base_val, base_test, base_robust, False, args.target_fpr)
        print_report("BASELINE (untouched RADAR)", base)
        log_evaluation("baseline_", base)

        model = prepare_model(model, args.method, args.r, args.alpha, args.dropout, args.targets).to(device)
        trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
        total = sum(p.numel() for p in model.parameters())
        print(f"trainable params: {trainable:,} of {total:,} ({trainable / total:.2%})")
        mlflow.log_params({"trainable_params": trainable})

        print("\nTraining...")
        best_epoch, best_pauroc, history = train_model(model, tokenizer, train, val, args, device,
                                                       lambda k, v, s: mlflow.log_metric(k, v, step=s))
        mlflow.log_params({"best_epoch": best_epoch})
        mlflow.log_metric("val/best_pauroc", best_pauroc)

        val_logits, test_logits, robust_logits = score_all(model)
        tuned, val_p, test_p = evaluate_protocol(val, test, val_logits, test_logits, robust_logits, True, args.target_fpr)
        print_report(f"TUNED ({tuned_name})", tuned)
        log_evaluation("", tuned)
        mlflow.log_metrics({"temperature": tuned["temperature"], "threshold": tuned["threshold"],
                            "test/uncalibrated_ece": tuned["uncalibrated_ece"]})

        save_scores(run_name, args.seed, [
            score_rows("radar-untouched", "val", val, base_val, base_val_p),
            score_rows("radar-untouched", "test", test, base_test, base_test_p),
            score_rows(tuned_name, "val", val, val_logits, val_p),
            score_rows(tuned_name, "test", test, test_logits, test_p),
        ])

        thresholds = {"model": tuned_name, "base_model": radar.MODEL_ID, "revision": radar.REVISION,
                      "temperature": tuned["temperature"], "threshold": tuned["threshold"], "target_fpr": args.target_fpr,
                      "max_len": radar.MAX_LEN, "best_epoch": best_epoch}
        log_dict_artifact(thresholds, "thresholds.json")
        payload = {"run": run_name, "args": vars(args), "history": history, "thresholds": thresholds,
                   "n": {"train": len(train), "val": len(val), "test": len(test)},
                   "baseline": {k: v for k, v in base.items()}, "tuned": {k: v for k, v in tuned.items()}}
        log_dict_artifact(payload, "radar_results.json")

        stem = OUT_DIRECTORY / run_name
        Path(f"{stem}_results.json").write_text(json.dumps(payload, indent=2, default=float))
        if args.method != "full":
            model.save_pretrained(f"{stem}_adapter")
            print(f"\nWrote {stem}_adapter/")
        print(f"Wrote {stem}_results.json")
        print(f"MLflow run: {mlflow.active_run().info.run_id}")


if __name__ == "__main__":
    main()
