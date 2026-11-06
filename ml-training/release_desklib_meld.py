"""
Builds the deployable desklib + MELD detector chosen in E7 (docs/desklib-meld-experiment-results.md), with every
file the detector needs and the numbers to check it against. Trains nothing.

E7's choice, on val: the desklib reference rerun (desklib-lora-qkvf-r64-e8-extended, 3 seeds) + the MELD 3-seed
soup (meld-lora-soup-all-s1 = meld-lora-extended-s1/s2/s3 averaged), 50/50 on calibrated log-odds.

In order:
  1. downloads the 3 desklib seed adapters and the 3 MELD members' adapters and heads from DagsHub;
  2. stores the soup as ONE LoRA adapter: the members' A matrices stacked, and their B matrices stacked with each
     scaled by scale/n, so its update is exactly the average of the members' updates (rank 16 x 3 = 48), plus
     the averaged prototype head. CHECK 1: its update equals the averaged one;
  3. keeps every adapter in half precision (what ships) and scores val + test through the deployment path in
     float32: the detector's clean_text, then desklib cut at 256 tokens, and MELD's own Scorer.score.
     CHECK 2: the shipped soup reproduces meld-lora-soup-all-s1's saved val scores;
  4. VALIDATION ONLY: fits each model's temperature, keeps the desklib seed whose pair has the highest val AUROC
     (E7's rule), fits the 1% FPR threshold, and tabulates abstention bands for the API;
  5. TEST, once: the pair at the frozen threshold, per dataset and slice, against live desklib (today's default);
  6. writes the bundle to outputs/release/<MODEL_VERSION>/ and logs it to DagsHub as one run (RUN_NAME).

Then, on any machine with DagsHub credentials, --fetch copies the logged bundle into apps/detector/model/desklib-meld/
(no GPU, no data needed). --release does the same copy straight from this run's outputs.

    python release_desklib_meld.py --smoke 120          # pipeline check on 120 val + 120 test answers, logs nothing
    python release_desklib_meld.py                      # the real run (GPU), logs the bundle to DagsHub
    python release_desklib_meld.py --fetch              # later, locally: bundle -> apps/detector/model/desklib-meld/
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import torch
from scipy.special import expit
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

import harness
import metrics
from calibrate_ensemble import DETECTOR_MODEL, LIVE_DESKLIB_THRESHOLD, desklib_logits, fp16_copy, live_desklib, write_scores
from clean import CLEANING_VERSION, clean_text
from combined_data import load_corpus, slice_flag_rates
from ensemble_scores import find_scores
from finetune_meld_lora import MELD_REPO, MLFLOW_EXPERIMENT, fit_temperature, load_meld
from scores import OUT_DIRECTORY, load_scores
from soup_meld_lora import average_heads, lora_deltas, member_files

DESKLIB_BASE = "desklib-lora-qkvf-r64-e8-extended"
DESKLIB_SEEDS = (1, 2, 3)
MELD_MEMBERS = ("meld-lora-extended-s1", "meld-lora-extended-s2", "meld-lora-extended-s3")
SOUP_RUN = "meld-lora-soup-all-s1"      # the soup E7 evaluated; its saved scores are CHECK 2's reference
WEIGHT_MELD = 0.5
MIN_WORDS = 10
TARGET_FPR = metrics.HEADLINE_FPR

MODEL_VERSION = "desklib-meld-ensemble-v1"
DESKLIB_VERSION = "desklib-academic-lora-v2"   # v1 is the live adapter in apps/detector/model/desklib-lora-adapter
MELD_VERSION = "meld-soup3-v1"
RUN_NAME = f"release-{MODEL_VERSION}"
DETECTOR_TARGET = DETECTOR_MODEL / "desklib-meld"

##  the API's abstention bands to tabulate on val (apps/api checks_service.py: uncertain if |p - threshold| <= band)
BANDS = (0.0, 0.005, 0.01, 0.02, 0.05, 0.08)
CHECK1_MAX_REL = 1e-4        # stacked adapter vs averaged updates, float32: should be ~1e-7
CHECK2_MIN_SPEARMAN = 0.9995 # fp16 shipped soup vs the soup run's float32 scores
CHECK2_MAX_ABS = 0.25        # in logits; MELD's document scores span roughly -20..20
N_GOLDEN_RANDOM, N_GOLDEN_NEAR = 16, 6


# --------------------------------------------------------------------------
# the soup as one adapter
# --------------------------------------------------------------------------

##  the members' LoRA adapters stacked into one, whose update is exactly their average:
##      mean_i(s_i * B_i @ A_i) = [B_1 s_1/n, ..., B_n s_n/n] @ [A_1; ...; A_n]
##  with rank = sum of ranks and lora_alpha = rank (scale 1, the scales are folded into B)
##
##  adapters:   member adapter folders (adapter_config.json + adapter_model.safetensors), same targets
##  dst:        folder to write the stacked adapter to
##  dtype:      the dtype to store it in (float16 ships; float32 is exact, for CHECK 1)
##  returns dst
def stacked_soup_adapter(adapters: list[Path], dst: Path, dtype: torch.dtype = torch.float16) -> Path:
    from safetensors.torch import load_file, save_file

    configs = [json.loads((Path(a) / "adapter_config.json").read_text()) for a in adapters]
    targets = [sorted([c["target_modules"]] if isinstance(c["target_modules"], str) else c["target_modules"])
               for c in configs]
    for c, t in zip(configs, targets):
        if c.get("use_rslora") or c.get("use_dora") or c.get("rank_pattern") or c.get("alpha_pattern"):
            raise SystemExit("a member uses rsLoRA, DoRA or per-layer ranks; stacking assumes plain LoRA")
        if t != targets[0]:
            raise SystemExit(f"members wrap different modules: {targets[0]} vs {t}")
    weights = [load_file(Path(a) / "adapter_model.safetensors") for a in adapters]
    if any(set(w) != set(weights[0]) for w in weights):
        raise SystemExit("members' adapters hold different tensors")
    extra = sorted(k for k in weights[0] if ".lora_A." not in k and ".lora_B." not in k)
    if extra:
        raise SystemExit(f"adapter holds tensors other than LoRA A/B (e.g. {extra[:2]}); the head is averaged separately")

    n = len(adapters)
    out = {}
    for key in sorted(weights[0]):
        if ".lora_A." in key:   # (r, in): stack along the rank
            out[key] = torch.cat([w[key].float() for w in weights], dim=0)
        else:                   # (out, r): stack along the rank, each scaled by its own alpha/r and 1/n
            out[key] = torch.cat([w[key].float() * (c["lora_alpha"] / c["r"]) / n for w, c in zip(weights, configs)],
                                 dim=1)
    rank = sum(c["r"] for c in configs)
    config = dict(configs[0], r=rank, lora_alpha=rank, lora_dropout=0.0, inference_mode=True)
    dst.mkdir(parents=True, exist_ok=True)
    save_file({k: v.to(dtype).contiguous() for k, v in out.items()}, dst / "adapter_model.safetensors")
    (dst / "adapter_config.json").write_text(json.dumps(config, indent=2))
    return dst


##  CHECK 1: the stacked adapter's update against the average of the members' updates, layer by layer
##  returns the largest |difference| relative to the largest |averaged update| in that layer
def check_stacked(model, members: list[Path], stacked: Path) -> float:
    summed: dict[str, torch.Tensor] = {}
    for adapter in members:
        for name, delta in lora_deltas(model, adapter).items():
            summed[name] = summed[name] + delta if name in summed else delta
    got = lora_deltas(model, stacked)
    if sorted(got) != sorted(summed):
        raise SystemExit("the stacked adapter wraps different layers from its members")
    worst = 0.0
    for name, total in summed.items():
        want = total / len(members)
        worst = max(worst, float((got[name] - want).abs().max() / want.abs().max().clamp_min(1e-12)))
    return worst


# --------------------------------------------------------------------------
# DagsHub
# --------------------------------------------------------------------------

def latest_run(run_name: str):
    runs = mlflow.search_runs(search_all_experiments=True, filter_string=f"tags.mlflow.runName = '{run_name}'",
                              order_by=["attributes.start_time DESC"], output_format="list")
    runs = [r for r in runs if r.info.status == "FINISHED"]
    if not runs:
        raise SystemExit(f"no finished run named {run_name} on DagsHub")
    return runs[0]


##  one desklib seed's adapter: outputs/<run>_adapter if present, otherwise the run's model/adapter artifact
##  returns (adapter folder, run id)
def desklib_adapter(run_name: str) -> tuple[Path, str]:
    run = latest_run(run_name)
    local = OUT_DIRECTORY / f"{run_name}_adapter"
    if (local / "adapter_config.json").exists():
        return local, run.info.run_id
    folder = Path(mlflow.artifacts.download_artifacts(run_id=run.info.run_id, artifact_path="model/adapter",
                                                      dst_path=tempfile.mkdtemp(prefix="release-desklib-")))
    if not (folder / "adapter_config.json").exists():
        raise SystemExit(f"{run_name} has no model/adapter artifact (was it run without --log-adapter?)")
    return folder, run.info.run_id


##  saved logits of one run's tuned model on val, by answer_id (for the reproduction checks)
def saved_val_logits(run_name: str) -> pd.Series:
    saved = load_scores(find_scores(run_name))
    saved = saved[(saved["split"] == "val") & ~saved["model"].str.endswith("-untouched")]
    return saved.set_index("answer_id")["logit"]


##  agreement of fresh scores with a run's saved ones, on the answers clean_text leaves unchanged
def agreement(fresh: np.ndarray, frame: pd.DataFrame, saved: pd.Series) -> dict:
    same = np.array([clean_text(str(t)) == str(t) for t in frame["answer"]])
    ref = saved.reindex(frame["answer_id"]).to_numpy()
    keep = same & ~np.isnan(ref)
    gap = np.abs(fresh[keep] - ref[keep])
    return {"n": int(keep.sum()), "n_changed_by_clean_text": int((~same).sum()),
            "spearman": float(spearmanr(fresh[keep], ref[keep]).statistic),
            "max_abs": float(gap.max()), "mean_abs": float(gap.mean())}


# --------------------------------------------------------------------------
# MELD on the deployment path
# --------------------------------------------------------------------------

##  MELD at its pinned revision with the shipped (fp16) soup adapter merged in and the averaged head loaded,
##  run in float32 - what the detector would load
def load_soup_scorer(device: str, revision: str, adapter: Path, head: Path):
    from peft import PeftModel
    from safetensors.torch import load_file

    meld, scorer, model_dir = load_meld(device, revision)
    model = scorer.model
    model.backbone = PeftModel.from_pretrained(model.backbone, str(adapter)).merge_and_unload()
    result = model.load_state_dict(load_file(head), strict=False)
    if result.unexpected_keys or any(not k.startswith("backbone.") for k in result.missing_keys):
        raise RuntimeError(f"head does not fit MELD: unexpected {result.unexpected_keys[:3]}, "
                           f"missing {[k for k in result.missing_keys if not k.startswith('backbone.')][:3]}")
    model.float().eval()
    return scorer, model_dir


##  document scores (logits) with MELD's own Scorer.score, after the detector's clean_text.
##  Scorer.score canonicalises the text itself; its "flagged" and threshold are MELD's own and are ignored
def meld_scores(scorer, texts) -> np.ndarray:
    return np.asarray([scorer.score(clean_text(str(t)))["score"] for t in texts], dtype=np.float64)


def move_scorer(scorer, device: str) -> None:
    scorer.model.to(device)
    scorer.device = torch.device(device)


##  desklib logits with a given adapter, through the detector's own load() (adapter merged, clean_text, 256 tokens)
def desklib_scores(adapter: Path, texts, device) -> np.ndarray:
    live_desklib.ADAPTER_DIR = Path(adapter)
    live_desklib.load.cache_clear()
    try:
        return desklib_logits(np.asarray(texts, dtype=object), torch.device(device))
    finally:
        live_desklib.load.cache_clear()


# --------------------------------------------------------------------------
# decisions on val
# --------------------------------------------------------------------------

def combine(zd, zm, t_d: float, t_m: float) -> np.ndarray:
    return (1 - WEIGHT_MELD) * np.asarray(zd) / t_d + WEIGHT_MELD * np.asarray(zm) / t_m


##  the API's verdicts on val at each abstention band: share of each class flagged as AI, and uncertain
def band_table(y: np.ndarray, p: np.ndarray, threshold: float) -> list[dict]:
    rows = []
    for band in BANDS:
        uncertain = np.abs(p - threshold) <= band
        flagged = (p > threshold) & ~uncertain
        rows.append({"band": band,
                     "humans_flagged": float(flagged[y == 0].mean()), "humans_uncertain": float(uncertain[y == 0].mean()),
                     "ai_flagged": float(flagged[y == 1].mean()), "ai_uncertain": float(uncertain[y == 1].mean())})
    return rows


def dataset_fpr(frame: pd.DataFrame, p: np.ndarray, threshold: float) -> dict:
    human = (frame["label"] == 0).to_numpy()
    return {d: {"n_human": int((human & (frame["dataset"] == d).to_numpy()).sum()),
                "wrongly_flagged": float((p[human & (frame["dataset"] == d).to_numpy()] >= threshold).mean())}
            for d in sorted(frame["dataset"].unique())}


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip() + \
            ("" if subprocess.call(["git", "diff", "--quiet"]) == 0 else "-dirty")
    except Exception:
        return "unknown"


# --------------------------------------------------------------------------
# fetch: bundle from DagsHub into the detector
# --------------------------------------------------------------------------

##  run_id: a specific release run (what the handoff doc pins); default the newest finished RUN_NAME
def fetch(run_id: str | None = None) -> None:
    from tracking import setup_mlflow

    setup_mlflow()
    run = mlflow.get_run(run_id) if run_id else latest_run(RUN_NAME)
    if run.info.run_name != RUN_NAME or run.info.status != "FINISHED":
        raise SystemExit(f"run {run.info.run_id} is {run.info.run_name} ({run.info.status}), not a finished {RUN_NAME}")
    folder = Path(mlflow.artifacts.download_artifacts(run_id=run.info.run_id, artifact_path=f"release/{MODEL_VERSION}",
                                                      dst_path=tempfile.mkdtemp(prefix="release-fetch-")))
    install(folder)
    print(f"fetched {RUN_NAME} ({run.info.run_id}) -> {DETECTOR_TARGET}")


def install(bundle: Path) -> None:
    if DETECTOR_TARGET.exists():
        shutil.rmtree(DETECTOR_TARGET)
    shutil.copytree(bundle, DETECTOR_TARGET)


# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--owner", default="tori")
    ap.add_argument("--smoke", type=int, default=0,
                    help="score only N val and N test answers, log nothing, skip the gates' verdicts: a pipeline check")
    ap.add_argument("--offline", action="store_true", help="do not log the release run to DagsHub")
    ap.add_argument("--release", action="store_true", help="also copy the bundle into apps/detector/model/desklib-meld/")
    ap.add_argument("--fetch", action="store_true",
                    help="only download the logged bundle from DagsHub into apps/detector/model/desklib-meld/")
    ap.add_argument("--run-id", default=None,
                    help="with --fetch: the release run to download (default: the newest one)")
    args = ap.parse_args()
    if args.fetch:
        return fetch(args.run_id)
    from safetensors.torch import save_file
    from tracking import log_split_metrics, setup_mlflow

    smoke = args.smoke > 0
    bundle = OUT_DIRECTORY / "release" / (MODEL_VERSION + ("-smoke" if smoke else ""))
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix="release-work-"))
    report: dict = {"model_version": MODEL_VERSION, "git_commit": git_commit(), "smoke": args.smoke}

    # ---- data
    frames = load_corpus("extended")
    data = {s: frames[s].reset_index(drop=True) for s in ("val", "test")}
    if smoke:
        data = {s: d.sample(n=min(args.smoke, len(d)), random_state=0).reset_index(drop=True) for s, d in data.items()}
    used = {s: (data[s]["n_words"] >= MIN_WORDS).to_numpy() for s in data}
    y = {s: data[s]["label"].to_numpy() for s in data}
    texts = {s: data[s]["answer"].to_numpy() for s in data}
    print(f"val {len(data['val'])} / test {len(data['test'])} answers, "
          f"{used['val'].sum()} / {used['test'].sum()} with >= {MIN_WORDS} words")

    # ---- 1. members from DagsHub
    setup_mlflow()
    desklib_src = {k: desklib_adapter(f"{DESKLIB_BASE}-s{k}") for k in DESKLIB_SEEDS}
    meld_files = [member_files(m) for m in MELD_MEMBERS]
    revisions = {f[2] for f in meld_files}
    if len(revisions) != 1:
        raise SystemExit(f"MELD members were trained on different releases {sorted(revisions)}")
    revision = revisions.pop()
    report["sources"] = {"desklib": {f"{DESKLIB_BASE}-s{k}": rid for k, (_, rid) in desklib_src.items()},
                         "meld": {m: f[3] for m, f in zip(MELD_MEMBERS, meld_files)}, "meld_revision": revision}

    # ---- 2. the soup as one adapter + averaged head
    member_adapters = [f[0] for f in meld_files]
    exact = stacked_soup_adapter(member_adapters, work / "meld-soup-fp32", torch.float32)
    shipped_meld = stacked_soup_adapter(member_adapters, bundle / "meld-soup-adapter", torch.float16)
    head = average_heads([torch.load(f[1], map_location="cpu") for f in meld_files])
    save_file({k: v.contiguous() for k, v in head.items()}, bundle / "meld-soup-head.safetensors")

    _, plain, _ = load_meld(args.device, revision)
    report["check1_max_rel_error"] = check_stacked(plain.model, member_adapters, exact)
    del plain
    torch.cuda.empty_cache() if torch.cuda.is_available() else None
    print(f"CHECK 1: stacked soup adapter vs averaged member updates, max relative error "
          f"{report['check1_max_rel_error']:.2e} (limit {CHECK1_MAX_REL:g})")

    # ---- 3. score on the deployment path
    print(f"\nscoring with the shipped MELD soup on {args.device}...")
    scorer, meld_dir = load_soup_scorer(args.device, revision, shipped_meld, bundle / "meld-soup-head.safetensors")
    zm = {s: meld_scores(scorer, texts[s]) for s in data}
    report["check2"] = agreement(zm["val"], data["val"], saved_val_logits(SOUP_RUN))
    print(f"CHECK 2: shipped soup vs {SOUP_RUN}'s saved val scores: {report['check2']}")
    move_scorer(scorer, "cpu")

    zd, desklib_fp16 = {}, {}
    for k, (src, _) in desklib_src.items():
        desklib_fp16[k] = fp16_copy(src, work / f"desklib-s{k}-fp16")
        print(f"scoring with desklib seed {k} (fp16 adapter)...")
        zd[k] = {s: desklib_scores(desklib_fp16[k], texts[s], args.device) for s in data}
    report["check3_desklib_vs_training"] = {
        k: agreement(zd[k]["val"], data["val"], saved_val_logits(f"{DESKLIB_BASE}-s{k}")) for k in DESKLIB_SEEDS}
    print("CHECK 3 (information only, training scored in bf16): "
          + ", ".join(f"s{k} spearman {v['spearman']:.4f}" for k, v in report["check3_desklib_vs_training"].items()))
    print("scoring with live desklib (today's default stack)...")
    z_live = {s: desklib_scores(DETECTOR_MODEL / "desklib-lora-adapter", texts[s], args.device) / live_desklib.TEMPERATURE
              for s in data}

    # ---- 4. validation only
    yv, mv = y["val"][used["val"]], used["val"]
    t_m = fit_temperature(zm["val"][mv], yv)
    candidates = []
    for k in DESKLIB_SEEDS:
        t_d = fit_temperature(zd[k]["val"][mv], yv)
        zv = combine(zd[k]["val"], zm["val"], t_d, t_m)[mv]
        candidates.append({"seed": k, "desklib_temperature": t_d, "val_auroc": float(roc_auc_score(yv, zv)),
                           "val_tpr_at_1pct": metrics.oracle_tpr_at_fpr(yv, expit(zv), TARGET_FPR)})
    best = max(candidates, key=lambda c: (c["val_auroc"], c["val_tpr_at_1pct"]))
    k, t_d = best["seed"], best["desklib_temperature"]
    z = {s: combine(zd[k][s], zm[s], t_d, t_m) for s in data}
    p = {s: expit(z[s]) for s in data}
    threshold = metrics.threshold_at_fpr(yv, p["val"][mv], TARGET_FPR)
    val_used = data["val"][mv].reset_index(drop=True)
    strict = max(metrics.threshold_at_fpr(yv[(val_used["dataset"] == d).to_numpy()],
                                          p["val"][mv][(val_used["dataset"] == d).to_numpy()], TARGET_FPR)
                 for d in val_used["dataset"].unique())
    report["val"] = {
        "meld_temperature": t_m, "candidates": candidates, "chosen_desklib_seed": k, "threshold": threshold,
        "per_dataset_wrongly_flagged": dataset_fpr(val_used, p["val"][mv], threshold),
        "strict_threshold_every_dataset_within_1pct": strict,
        "strict_ai_caught": float((p["val"][mv][yv == 1] >= strict).mean()),
        "abstention_bands_api_rule": band_table(yv, p["val"][mv], threshold),
    }
    print(f"\nVAL: desklib seed {k} (pair val AUROC {best['val_auroc']:.4f}), T_desklib {t_d:.3f}, T_meld {t_m:.3f}, "
          f"threshold {threshold:.6f}")
    for c in candidates:
        print(f"  seed {c['seed']}: val AUROC {c['val_auroc']:.4f}, AI caught at exactly 1% FPR {c['val_tpr_at_1pct']:.1%}")
    print("  abstention bands (val, API rule):")
    for r in report["val"]["abstention_bands_api_rule"]:
        print(f"    +-{r['band']:<6} humans flagged {r['humans_flagged']:.2%}  uncertain {r['humans_uncertain']:.2%} | "
              f"AI flagged {r['ai_flagged']:.1%}  uncertain {r['ai_uncertain']:.1%}")

    # ---- 5. test, once
    mt = used["test"]
    test_used = data["test"][mt].reset_index(drop=True)
    yt, groups = y["test"][mt], test_used["question_id"].to_numpy()
    p_live = expit(z_live["test"][mt])
    live_refit = metrics.threshold_at_fpr(yv, expit(z_live["val"][mv]), TARGET_FPR)
    rows = {"desklib + MELD soup (threshold fit on val)": (p["test"][mt], threshold),
            "desklib live (0.9608, as deployed)": (p_live, LIVE_DESKLIB_THRESHOLD),
            "desklib live (threshold refit on val)": (p_live, live_refit)}
    report["test"] = {}
    print(f"\n=== TEST, answers of >= {MIN_WORDS} words ({len(test_used)}), thresholds frozen before test ===")
    for name, (pt, thr) in rows.items():
        r = metrics.evaluate(yt, pt, thr, headline_fpr=TARGET_FPR, groups=groups, bootstrap_n=0 if smoke else 1000)
        report["test"][name] = {key: float(v) for key, v in r.items()}
        print(f"  {name:<44} AI caught {r['deployed_tpr']:.1%}  humans flagged {r['deployed_fpr']:.2%}  "
              f"AUROC {r['auroc']:.4f}  AI caught at exactly 1% FPR {r['oracle_tpr_at_fpr_0.01']:.1%}")
    report["test_per_dataset_wrongly_flagged"] = dataset_fpr(test_used, p["test"][mt], threshold)
    report["test_slices"] = slice_flag_rates(test_used, p["test"][mt], threshold)
    print(f"  wrongly flagged per dataset: {report['test_per_dataset_wrongly_flagged']}")

    run_id = f"{RUN_NAME}-{date.today().isoformat()}"
    files = [write_scores("desklib-live", data, z_live, run_id), write_scores(MODEL_VERSION, data, z, run_id)]
    if not smoke:
        df = harness.load_runs(files)
        report["paired_vs_live_desklib"] = {}
        for metric in ("deployed_tpr", "oracle_tpr_at_fpr_0.01", "auroc"):
            r = harness.compare_pair(df, MODEL_VERSION, "desklib-live", metric=metric, min_words=MIN_WORDS)
            report["paired_vs_live_desklib"][metric] = {key: float(v) if isinstance(v, (int, float, np.floating)) else v
                                                        for key, v in r.items()}
            print(f"  paired, {metric:<24} {r['diff']:+.4f}  [{r['ci_low']:+.4f}, {r['ci_high']:+.4f}]")

    # ---- golden vectors: val answers scored on CPU, float32, as the detector will
    rng = np.random.default_rng(0)
    pool = np.flatnonzero(mv)
    near = pool[np.argsort(np.abs(p["val"][pool] - threshold))[:N_GOLDEN_NEAR]]
    rest = np.setdiff1d(pool, near)
    pick = np.concatenate([rng.choice(rest[y["val"][rest] == c], N_GOLDEN_RANDOM // 2, replace=False) for c in (0, 1)]
                          + [near, [pool[np.argmax(data["val"]["n_words"].to_numpy()[pool])]]])
    pick = list(dict.fromkeys(int(i) for i in pick))
    gold_texts = texts["val"][pick]
    gold_zm = meld_scores(scorer, gold_texts)
    gold_zd = desklib_scores(desklib_fp16[k], gold_texts, "cpu")
    gold_p = expit(combine(gold_zd, gold_zm, t_d, t_m))
    report["golden_cpu_vs_gpu_max_abs_prob"] = float(np.abs(gold_p - p["val"][pick]).max())
    golden = [{"answer_id": str(data["val"]["answer_id"][i]), "label": int(y["val"][i]), "text": str(texts["val"][i]),
               "desklib_logit": float(a), "meld_score": float(b), "probability": float(c),
               "above_threshold": bool(c > threshold)}
              for i, a, b, c in zip(pick, gold_zd, gold_zm, gold_p)]

    # ---- 6. the bundle
    shutil.copytree(desklib_fp16[k], bundle / "desklib-lora-adapter")
    from huggingface_hub import snapshot_download
    desklib_revision = Path(snapshot_download(live_desklib.DESKLIB_REPO)).name
    settings = {
        "model_version": MODEL_VERSION,
        "calibration_version": f"desklib{t_d:.3f}-meld{t_m:.3f}-thr{threshold:.4f}-v1",
        "threshold": round(float(threshold), 6),
        "target_fpr": TARGET_FPR,
        "min_words": MIN_WORDS,
        "combine": "z = (1 - weight_meld) * desklib_logit / desklib.temperature + weight_meld * meld_score / "
                   "meld.temperature; probability = sigmoid(z); AI if probability > threshold",
        "weight_meld": WEIGHT_MELD,
        "cleaning_version": CLEANING_VERSION,
        "desklib": {"model_version": DESKLIB_VERSION, "base_model": live_desklib.DESKLIB_REPO,
                    "base_revision": desklib_revision, "adapter": "desklib-lora-adapter",
                    "temperature": round(float(t_d), 6), "max_tokens": live_desklib.MAX_TOKENS,
                    "scoring": "apps/detector/app/desklib.py: clean_text, cut at max_tokens, adapter merged, "
                               "mean-pooled logit",
                    "source_run": f"{DESKLIB_BASE}-s{k}", "source_run_id": desklib_src[k][1]},
        "meld": {"model_version": MELD_VERSION, "base_model": MELD_REPO, "base_revision": revision,
                 "adapter": "meld-soup-adapter", "head": "meld-soup-head.safetensors",
                 "temperature": round(float(t_m), 6), "window_tokens": scorer.window, "cap_tokens": scorer.cap,
                 "rho": scorer.rho,
                 "scoring": "meld.py from the base revision: Scorer(model_dir); merge the adapter into "
                            "scorer.model.backbone; load the head into scorer.model (strict=False); "
                            "score = scorer.score(clean_text(text))['score']. Ignore its 'flagged' and threshold",
                 "soup_of": list(MELD_MEMBERS), "soup_member_run_ids": [f[3] for f in meld_files],
                 "soup_recipe": "members' LoRA updates averaged exactly (stacked rank-48 adapter), heads averaged"},
        "calibrated_on": "v0.1-extended val (answers >= 10 words)" + (f" SMOKE SUBSAMPLE {args.smoke}" if smoke else ""),
        "calibrated": date.today().isoformat(),
        "git_commit": report["git_commit"],
    }
    (bundle / "desklib-meld.json").write_text(json.dumps(settings, indent=2))
    (bundle / "golden.json").write_text(json.dumps({"tolerance_probability": 2e-3, "threshold": settings["threshold"],
                                                    "answers": golden}, indent=2))

    gates = {"check1": report["check1_max_rel_error"] <= CHECK1_MAX_REL,
             "check2": report["check2"]["spearman"] >= CHECK2_MIN_SPEARMAN and report["check2"]["max_abs"] <= CHECK2_MAX_ABS}
    report["gates"] = gates
    (bundle / "report.json").write_text(json.dumps(report, indent=2, default=float))
    print(f"\nbundle -> {bundle}  ({sum(f.stat().st_size for f in bundle.rglob('*') if f.is_file()) / 1e6:.0f} MB)")
    print(f"gates: {gates}")
    print(f"API settings: DETECTOR_MODEL_VERSION={MODEL_VERSION} DETECTOR_THRESHOLD={settings['threshold']} "
          f"DETECTOR_CALIBRATION_VERSION={settings['calibration_version']}")

    if smoke:
        print("SMOKE run: nothing logged; numbers come from a subsample and mean nothing")
        return
    if not all(gates.values()):
        raise SystemExit("a check failed: the bundle is in outputs/ for inspection, but is NOT logged or released")

    if not args.offline:
        mlflow.set_experiment(MLFLOW_EXPERIMENT)
        with mlflow.start_run(run_name=RUN_NAME):
            mlflow.set_tags({"owner": args.owner, "run_role": "release", "model_family": "desklib+meld",
                             "data_mode": "in-distribution"})
            mlflow.log_params({"model_version": MODEL_VERSION, "desklib_source": f"{DESKLIB_BASE}-s{k}",
                               "meld_soup_of": ",".join(MELD_MEMBERS), "meld_revision": revision,
                               "weight_meld": WEIGHT_MELD, "min_words": MIN_WORDS, "target_fpr": TARGET_FPR,
                               "git_commit": report["git_commit"]})
            mlflow.log_metrics({"threshold": threshold, "desklib_temperature": t_d, "meld_temperature": t_m,
                                "val_auroc": best["val_auroc"], "check2_spearman": report["check2"]["spearman"]})
            log_split_metrics(report["test"]["desklib + MELD soup (threshold fit on val)"], "test")
            mlflow.log_artifacts(str(bundle), f"release/{MODEL_VERSION}")
            for f in files:
                mlflow.log_artifact(str(f), "predictions")
            print(f"logged {RUN_NAME}: {mlflow.active_run().info.run_id}")
    if args.release:
        install(bundle)
        print(f"RELEASED -> {DETECTOR_TARGET}")


if __name__ == "__main__":
    main()
