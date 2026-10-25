## calibrates the desklib + RADAR combination for the detector: the LIVE desklib (apps/detector) plus a RADAR LoRA adapter.
## picks the RADAR seed and fits the 1% FPR threshold on validation only, then compares with live desklib on test once,
## and writes the files the detector's ensemble backend ships with

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from scipy.special import expit

import harness
import metrics
import radar
from combined_data import load_corpus, slice_flag_rates
from finetune_radar import fit_temperature
from scores import COLUMNS, OUT_DIRECTORY, validate

##  the detector's own code, so desklib is scored exactly as in production (same cleaning, same adapter merge)
DETECTOR_APP = Path(__file__).resolve().parent.parent / "apps" / "detector" / "app"
DETECTOR_MODEL = DETECTOR_APP.parent / "model"
sys.path.insert(0, str(DETECTOR_APP))
##  desklib.py defaults to the container path /app/model/..., so point it at the adapter in the repo
os.environ.setdefault("DESKLIB_ADAPTER_DIR", str(DETECTOR_MODEL / "desklib-lora-adapter"))
import desklib as live_desklib  # noqa: E402
from clean import CLEANING_VERSION, clean_text  # noqa: E402

##  the threshold the API applies to live desklib today (apps/docker-compose.desklib.yml)
LIVE_DESKLIB_THRESHOLD = 0.9608
WEIGHT_RADAR = 0.5
MIN_WORDS = 10
TARGET_FPR = metrics.HEADLINE_FPR
MODEL_VERSION = "desklib-radar-ensemble-v1"

##  makes a half-precision copy of a LoRA adapter (about half the size, so it fits comfortably in git).
##  everything below scores with this copy, so the threshold is fitted on exactly the weights that ship
##
##  src:    adapter folder from the cluster (adapter_config.json + adapter_model.safetensors)
##  dst:    folder to write the fp16 copy to
##  returns dst
def fp16_copy(src: Path, dst: Path) -> Path:
    from safetensors.torch import load_file, save_file

    dst.mkdir(parents=True, exist_ok=True)
    weights = load_file(src / "adapter_model.safetensors")
    save_file({k: v.half() if v.is_floating_point() else v for k, v in weights.items()}, dst / "adapter_model.safetensors")
    shutil.copy(src / "adapter_config.json", dst / "adapter_config.json")
    return dst

##  scores answers with the live desklib: the detector's load() (base + adapter merged), its clean_text and its 256-token cut.
##  batched for speed; desklib averages over real tokens only, so padding doesn't change a score
##
##  texts:  the answers
##  device: where to run it
##  returns raw logits, one per answer, in order
@torch.no_grad()
def desklib_logits(texts: np.ndarray, device: torch.device, batch_size: int = 32) -> np.ndarray:
    tokenizer, model = live_desklib.load()
    model.to(device)
    cleaned = np.asarray([clean_text(str(t)) for t in texts], dtype=object)
    order = np.argsort([len(t) for t in cleaned], kind="stable")
    out = np.empty(len(cleaned))
    for i in range(0, len(cleaned), batch_size):
        idx = order[i:i + batch_size]
        enc = tokenizer(list(cleaned[idx]), padding=True, truncation=True, max_length=live_desklib.MAX_TOKENS,
                        return_tensors="pt").to(device)
        out[idx] = model(input_ids=enc["input_ids"], attention_mask=enc["attention_mask"])["logits"][:, 0].float().cpu().numpy()
    model.to("cpu")
    return out

##  scores answers with RADAR + one LoRA adapter merged in, the same way the detector will: clean_text, then radar.py
##
##  adapter:    the (fp16) adapter folder
##  texts:      the answers
##  device:     where to run it
##  returns raw logits (AI minus human), one per answer, in order
def radar_logits(adapter: Path, texts: np.ndarray, device: torch.device) -> np.ndarray:
    from peft import PeftModel

    model, tokenizer, _ = radar.load_radar("cpu")
    model = PeftModel.from_pretrained(model, str(adapter)).merge_and_unload().to(device).eval()
    cleaned = [clean_text(str(t)) for t in texts]
    logits = radar.predict_logits(model, tokenizer, cleaned, device)
    del model
    return logits

##  the combined score: each model's logit divided by its own temperature (so each is calibrated), then averaged
##
##  z_desklib, z_radar: raw logits
##  t_desklib, t_radar: temperatures
##  returns the combined log-odds; sigmoid of it is the probability the detector returns
def combine(z_desklib, z_radar, t_desklib: float, t_radar: float) -> np.ndarray:
    return (1 - WEIGHT_RADAR) * z_desklib / t_desklib + WEIGHT_RADAR * z_radar / t_radar

##  writes one model's val + test scores as a scores file, so harness.py can run its paired test on the shipped pair
##
##  name:   the model name (and file name)
##  frames: {"val": rows, "test": rows}
##  logit:  {"val": logits, "test": logits}
##  run_id: recorded in the file
##  returns the path
def write_scores(name: str, frames: dict, logit: dict, run_id: str) -> Path:
    parts = [pd.DataFrame({"run_id": run_id, "model": name, "seed": 0, "split": s, "answer_id": frames[s]["answer_id"],
                           "question_id": frames[s]["question_id"], "y_true": frames[s]["label"].astype(np.int64),
                           "logit": logit[s], "y_prob": expit(logit[s])}) for s in ("val", "test")]
    OUT_DIRECTORY.mkdir(exist_ok=True)
    path = OUT_DIRECTORY / f"{name}_scores.parquet"
    validate(pd.concat(parts, ignore_index=True)[COLUMNS]).to_parquet(path, index=False)
    return path

##  the run, in order:
##      1. make fp16 copies of the RADAR adapters, score extended val + test with live desklib and with each RADAR seed
##      2. VALIDATION ONLY: refit each RADAR seed's temperature, combine with desklib, keep the seed whose combination
##         catches the most AI at exactly 1% FPR, and fit the combination's 1% FPR threshold
##      3. TEST, once: live desklib (at today's 0.9608, and at a threshold refit on the same val) vs the combination,
##         per-slice catch rates, and the harness's paired test
##      4. --release: copy the chosen fp16 adapter to apps/detector/model/radar-lora-adapter/ and write ensemble.json there.
##         without --release nothing outside ml-training/outputs/ is touched
##  every step uses answers of at least MIN_WORDS words for fitting and metrics (the app doesn't score shorter ones)
def main() -> None:
    ap = argparse.ArgumentParser(description="Calibrate live desklib + RADAR LoRA for the detector.")
    ap.add_argument("--adapters", default="outputs/radar-lora-extended-s1_adapter,outputs/radar-lora-extended-s2_adapter,"
                                              "outputs/radar-lora-extended-s3_adapter", help="comma-separated RADAR adapter folders")
    ap.add_argument("--device", default=None, help="cuda, mps or cpu (default: best available)")
    ap.add_argument("--release", action="store_true", help="write the chosen adapter and ensemble.json into apps/detector/model/")
    args = ap.parse_args()
    device = torch.device(args.device) if args.device else radar.default_device()

    frames = load_corpus("extended")
    data = {s: frames[s].reset_index(drop=True) for s in ("val", "test")}
    used = {s: (data[s]["n_words"] >= MIN_WORDS).to_numpy() for s in data}
    y = {s: data[s]["label"].to_numpy() for s in data}
    print(f"val {len(data['val'])} / test {len(data['test'])} answers, {used['val'].sum()} / {used['test'].sum()} with >= {MIN_WORDS} words")

    print(f"\nScoring with live desklib ({live_desklib.MODEL_VERSION}, T={live_desklib.TEMPERATURE}) on {device}...")
    zd = {s: desklib_logits(data[s]["answer"].to_numpy(), device) for s in data}
    t_d = live_desklib.TEMPERATURE

    seeds = []
    for src in [Path(a) for a in args.adapters.split(",") if a]:
        fp16 = fp16_copy(src, OUT_DIRECTORY / f"{src.name}_fp16")
        print(f"\nScoring with RADAR + {src.name} (fp16 copy, {(fp16 / 'adapter_model.safetensors').stat().st_size / 1e6:.0f} MB)...")
        zr = {s: radar_logits(fp16, data[s]["answer"].to_numpy(), device) for s in data}
        t_r = fit_temperature(zr["val"][used["val"]], y["val"][used["val"]])
        z = {s: combine(zd[s], zr[s], t_d, t_r) for s in data}
        val_tpr = metrics.oracle_tpr_at_fpr(y["val"][used["val"]], expit(z["val"][used["val"]]), TARGET_FPR)
        print(f"  RADAR temperature {t_r:.3f}, combination catches {val_tpr:.1%} of val AI at exactly 1% FPR")
        seeds.append({"src": src, "fp16": fp16, "zr": zr, "t_r": t_r, "z": z, "val_tpr": val_tpr})

    best = max(seeds, key=lambda s: s["val_tpr"])
    z, zr, t_r = best["z"], best["zr"], best["t_r"]
    threshold = metrics.threshold_at_fpr(y["val"][used["val"]], expit(z["val"][used["val"]]), TARGET_FPR)
    desklib_val_threshold = metrics.threshold_at_fpr(y["val"][used["val"]], expit(zd["val"][used["val"]] / t_d), TARGET_FPR)
    print(f"\nchosen on validation: {best['src'].name}, combination threshold {threshold:.4f} "
          f"(live desklib refit on the same val: {desklib_val_threshold:.4f}, live today: {LIVE_DESKLIB_THRESHOLD})")

    test = data["test"][used["test"]].reset_index(drop=True)
    yt, groups = y["test"][used["test"]], test["question_id"].to_numpy()
    p_live = expit(zd["test"][used["test"]] / t_d)
    p_ens = expit(z["test"][used["test"]])
    rows = {
        "desklib live (threshold 0.9608, as deployed)": (p_live, LIVE_DESKLIB_THRESHOLD),
        "desklib live (threshold refit on extended val)": (p_live, desklib_val_threshold),
        "desklib + RADAR (threshold fit on val)": (p_ens, threshold),
    }
    print(f"\n=== TEST, answers of >= {MIN_WORDS} words ({len(test)}), thresholds frozen before test ===")
    report = {}
    for name, (p, thr) in rows.items():
        r = metrics.evaluate(yt, p, thr, headline_fpr=TARGET_FPR, groups=groups)
        report[name] = r
        print(f"  {name:<48} AI caught {r['deployed_tpr']:.1%} [{r['deployed_tpr_ci_low']:.1%}, {r['deployed_tpr_ci_high']:.1%}]  "
              f"humans flagged {r['deployed_fpr']:.2%}  AUROC {r['auroc']:.3f}  AI caught at exactly 1% FPR {r['oracle_tpr_at_fpr_0.01']:.1%}")

    print("\n  per answer type, AI caught at each model's frozen threshold (human = wrongly flagged):")
    slices = {name: {s["slice"]: s for s in slice_flag_rates(test, p, thr)} for name, (p, thr) in rows.items()}
    for sl in sorted(slices[next(iter(slices))]):
        cells = "  ".join(f"{slices[name][sl]['flag_rate']:6.1%}" for name in rows)
        print(f"    {sl:<20} n={slices[next(iter(slices))][sl]['n']:<5} {cells}")
    print("    (columns: desklib live at 0.9608 | desklib live refit | desklib + RADAR)")

    run_id = f"calibration-{date.today().isoformat()}"
    files = [write_scores("desklib-live", data, {s: zd[s] / t_d for s in data}, run_id),
             write_scores("desklib-radar-ensemble", data, z, run_id)]
    df = harness.load_runs(files)
    print("\n=== harness paired test: combination minus live desklib (both thresholds fit on val; whole questions resampled) ===")
    for metric in ("deployed_tpr", "oracle_tpr_at_fpr_0.01", "auroc"):
        r = harness.compare_pair(df, "desklib-radar-ensemble", "desklib-live", metric=metric, min_words=MIN_WORDS)
        print(f"  {metric:<24} {r['diff']:+.4f}  [{r['ci_low']:+.4f}, {r['ci_high']:+.4f}]  "
              f"{'REAL GAP' if r['gap_is_clear'] else 'could be noise'}")

    flagged_only_by_ens = (yt == 1) & (p_ens >= threshold) & (p_live < LIVE_DESKLIB_THRESHOLD)
    false_alarms_ens = (yt == 0) & (p_ens >= threshold)
    demo = test.assign(desklib_live=p_live, ensemble=p_ens)[flagged_only_by_ens | false_alarms_ens]
    demo = demo.assign(case=np.where(demo["label"] == 1, "AI caught only by the combination", "human wrongly flagged by the combination"))
    demo_path = OUT_DIRECTORY / "ensemble_demo_examples.csv"
    demo[["case", "slice", "dataset", "answer_id", "desklib_live", "ensemble", "answer"]].sort_values(["case", "slice"]).to_csv(demo_path, index=False)
    print(f"\n{flagged_only_by_ens.sum()} test AI answers caught only by the combination, {false_alarms_ens.sum()} humans it wrongly flags "
          f"-> {demo_path}")

    settings = {
        "model_version": MODEL_VERSION,
        "calibration_version": f"desklib{t_d:g}-radar{t_r:.3f}-thr{threshold:.4f}-v1",
        "threshold": round(float(threshold), 6),
        "target_fpr": TARGET_FPR,
        "min_words": MIN_WORDS,
        "weight_radar": WEIGHT_RADAR,
        "desklib_model_version": live_desklib.MODEL_VERSION,
        "desklib_temperature": t_d,
        "radar_model": radar.MODEL_ID,
        "radar_revision": radar.REVISION,
        "radar_adapter": best["src"].name,
        "radar_temperature": round(float(t_r), 6),
        "cleaning_version": CLEANING_VERSION,
        "max_tokens": live_desklib.MAX_TOKENS,
        "calibrated_on": "v0.1-extended val (answers >= 10 words)",
        "calibrated": date.today().isoformat(),
    }
    (OUT_DIRECTORY / "ensemble.json").write_text(json.dumps(settings, indent=2))
    print(f"\nsettings -> {OUT_DIRECTORY / 'ensemble.json'}")
    print(f"API settings for docker-compose.ensemble.yml: DETECTOR_MODEL_VERSION={MODEL_VERSION}  "
          f"DETECTOR_THRESHOLD={settings['threshold']}  DETECTOR_CALIBRATION_VERSION={settings['calibration_version']}")

    if args.release:
        target = DETECTOR_MODEL / "radar-lora-adapter"
        target.mkdir(parents=True, exist_ok=True)
        for f in ("adapter_config.json", "adapter_model.safetensors"):
            shutil.copy(best["fp16"] / f, target / f)
        (DETECTOR_MODEL / "ensemble.json").write_text(json.dumps(settings, indent=2))
        print(f"RELEASED: {target}/ and {DETECTOR_MODEL / 'ensemble.json'}")


if __name__ == "__main__":
    main()
