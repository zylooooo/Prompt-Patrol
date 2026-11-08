"""
Benchmarks our desklib and MELD detectors on RAID (Dugan et al., ACL 2024, https://github.com/liamdugan/raid),
a large out-of-domain test: news, Reddit, recipes, poetry, abstracts, reviews, books and Wikipedia, from 11
generators, with and without 11 adversarial attacks. Trains nothing.

Four subcommands, run in this order:

  sample    once: a fixed, labelled sample of RAID's train split, for choosing what to submit         (CPU)
  score     one component's raw logits on `train-sample` or `test`, in resumable chunks       (GPU, DagsHub)
  evaluate  RAID's own metric on the labelled sample, for every candidate side by side         (CPU, offline)
  submit    the leaderboard files (predictions.json + metadata.json) for one candidate on test (CPU, offline)

    python eval_raid.py sample
    python eval_raid.py score --component meld-v0.1-extended --split train-sample --smoke 64
    python eval_raid.py score --component meld-v0.1-extended --split train-sample
    python eval_raid.py evaluate --candidates desklib-v0.1 desklib-v0.1-extended ensemble-v0.1-extended
    python eval_raid.py score --component desklib-v0.1-extended --split test
    python eval_raid.py submit --candidate desklib-v0.1-extended --name Prompt-Patrol-desklib --contact "<email>"

A COMPONENT is one model that `score` loads, written as kind:run (or a name from PRESETS):
  desklib:<run>      one desklib LoRA run's adapter, scored through the detector's own path (clean_text, 256 tokens)
  meld:<run>         one MELD LoRA run's adapter and head, scored with MELD's own Scorer.score after clean_text
  meld-soup:<run>    a soup run, rebuilt exactly from its members (its soup_members param) as release_desklib_meld.py does
A CANDIDATE is what `evaluate` and `submit` rate: a component, or `<desklib component>+<meld component>`, the
shipped recipe, (1 - w) * desklib_z + w * meld_z on calibrated log-odds, with w = --weight-meld (0.5 ships).

WHAT IS SUBMITTED: calibrated log-odds, z = logit / T, with T the run's validation temperature (logged to DagsHub
when it trained). RAID sets its own threshold for each domain from human-written, unattacked texts, at 5% and 1%
FPR, so our thresholds and the API's abstention band play no part. Log-odds, not probabilities: sigmoid rounds
confident texts to exactly 1.0, which ties their scores, and RAID's threshold search (a mean-initialised walk in
steps of 0.5) suits a scale of roughly -20..20.

The test labels are hidden. Only the leaderboard bot scores test, when you open the pull request, and it posts the
results publicly on that PR. `evaluate` is the private way to compare candidates; it never touches test.

Needs raid-bench WITHOUT its dependencies (it pins numpy 1.26 and pandas 2.2, which would break this venv; its code
runs fine on ours):  pip install --no-deps raid-bench==0.2.0
RAID's CSVs download to $RAID_CACHE_DIR (default ~/.cache/raid; train.csv is many GB, so point it at scratch on the
cluster).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "outputs" / "raid"
SAMPLE_PATH = OUT / "data" / "train-sample.parquet"
SPLITS = ("train-sample", "test")
CHUNK_ROWS = 2000

# columns of RAID's train.csv that the evaluation reads; test.csv is read for id and generation only
LABEL_COLUMNS = ["id", "model", "decoding", "repetition_penalty", "attack", "domain"]
CELL = ["domain", "model", "attack"]
TARGET_FPRS = (0.05, 0.01)  # what the leaderboard bot reports (leaderboard/hydrate.py)

# leaderboard/hydrate.py builds SubmissionMetadata(**metadata.json): any other key fails the submission
METADATA_REQUIRED = ("date_released", "detector_name", "contact_info")
METADATA_OPTIONAL = ("website", "paper_link", "huggingface_link", "github_link", "additional_metadata")
SUBMISSION_NAME = re.compile(r"[\w.\-]+")

# v0.1 = the E3 `control` fold of cluster/logo.sh (raw v0.1 answers, every generator); v0.1-extended = the E2/E7
# runs that the release was built from. desklib is seed 1 here; the release picked its seed on val
# (outputs/release/<version>/report.json, val.chosen_desklib_seed), so change -s1 to match it if you want the shipped one.
PRESETS = {
    "desklib-v0.1": "desklib:desklib-lora-logo-control-s1",
    "desklib-v0.1-extended": "desklib:desklib-lora-qkvf-r64-e8-extended-s1",
    "meld-v0.1": "meld-soup:meld-lora-soup-logo-control-s1",
    "meld-v0.1-extended": "meld-soup:meld-lora-soup-all-s1",
    "ensemble-v0.1": "desklib-v0.1+meld-v0.1",
    "ensemble-v0.1-extended": "desklib-v0.1-extended+meld-v0.1-extended",
}
KINDS = ("desklib", "meld", "meld-soup")


# --------------------------------------------------------------------------
# names
# --------------------------------------------------------------------------

##  a candidate's components, presets expanded: "desklib-v0.1" -> ["desklib:desklib-lora-logo-control-s1"]
def components_of(candidate: str) -> list[str]:
    candidate = PRESETS.get(candidate, candidate)
    parts = [PRESETS.get(p, p) for p in candidate.split("+")]
    if any("+" in p for p in parts):
        return components_of("+".join(parts))
    for p in parts:
        kind, _, run = p.partition(":")
        if kind not in KINDS or not run:
            raise SystemExit(f"{p!r} is not a component: write desklib:<run>, meld:<run> or meld-soup:<run> "
                             f"(or one of {', '.join(PRESETS)})")
    if len(parts) == 2 and not (parts[0].startswith("desklib:") and parts[1].startswith("meld")):
        raise SystemExit(f"a pair is <desklib component>+<meld component>, got {candidate!r}")
    if len(parts) > 2:
        raise SystemExit(f"a candidate is one component or a desklib+meld pair, got {len(parts)} parts")
    return parts


##  a filesystem-safe folder name for a component
def tag(component: str) -> str:
    return component.replace(":", "__")


def scores_dir(component: str, split: str) -> Path:
    return OUT / "scores" / tag(component) / split


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

def raid_csv(name: str) -> Path:
    try:
        from raid.utils import RAID_CACHE_DIR, RAID_DATA_URL_BASE, download_file
    except ImportError:
        raise SystemExit("raid-bench is not installed: pip install --no-deps raid-bench==0.2.0") from None
    return download_file(f"{RAID_DATA_URL_BASE}/{name}", RAID_CACHE_DIR / name)


##  a deterministic pseudo-random key in [0, 1) per id, so the sample doesn't depend on file order or a seed
def hash_keys(ids) -> np.ndarray:
    return np.array([int.from_bytes(hashlib.sha256(str(i).encode()).digest()[:8], "big") / 2**64 for i in ids])


##  keeps, in each (domain, generator, attack) cell, the rows with the lowest hash keys: n per machine cell,
##  n_human per human cell. Human cells get more because RAID's thresholds come from the human rows alone
def top_per_cell(frame: pd.DataFrame, n: int, n_human: int) -> pd.DataFrame:
    frame = frame.sort_values("_key", kind="stable")
    rank = frame.groupby(CELL, dropna=False, sort=False).cumcount().to_numpy()
    limit = np.where(frame["model"].eq("human").to_numpy(), n_human, n)
    return frame[rank < limit]


##  the labelled sample, streamed from train.csv so the whole file never sits in memory
def build_sample(csv: Path, n: int, n_human: int, chunksize: int = 200_000) -> pd.DataFrame:
    kept = None
    for chunk in pd.read_csv(csv, usecols=LABEL_COLUMNS + ["generation"], chunksize=chunksize):
        chunk["_key"] = hash_keys(chunk["id"])
        kept = top_per_cell(chunk if kept is None else pd.concat([kept, chunk], ignore_index=True), n, n_human)
    if kept is None:
        raise SystemExit(f"{csv} is empty")
    return kept.drop(columns="_key").sort_values("id").reset_index(drop=True)


##  one split's rows, sorted by id: id + generation, and the labels for train-sample
def load_split(split: str) -> pd.DataFrame:
    if split == "train-sample":
        if not SAMPLE_PATH.exists():
            raise SystemExit(f"{SAMPLE_PATH} is missing: run `python eval_raid.py sample` first")
        frame = pd.read_parquet(SAMPLE_PATH)
    elif split == "test":
        frame = pd.read_csv(raid_csv("test.csv"), usecols=["id", "generation"])
    else:
        raise SystemExit(f"split must be one of {SPLITS}")
    frame["generation"] = frame["generation"].fillna("").astype(str)
    return frame.sort_values("id").reset_index(drop=True)


def ids_fingerprint(ids) -> str:
    return hashlib.sha256("\n".join(map(str, ids)).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# components on the GPU
# --------------------------------------------------------------------------

##  loads one component. returns (texts -> raw logits, info for meta.json: run ids and the validation temperature)
def load_component(component: str, device: str):
    import os

    import torch
    from safetensors.torch import save_file

    # apps/detector/app/desklib.py calls os.process_cpu_count() at import, which is Python 3.13+ (the detector's
    # image); ml-training and the cluster run 3.11. The value only sets torch's CPU threads, so cpu_count will do
    if not hasattr(os, "process_cpu_count"):
        os.process_cpu_count = os.cpu_count
    import release_desklib_meld as release
    from soup_meld_lora import average_heads, member_files
    from tracking import setup_mlflow

    setup_mlflow()
    kind, _, name = component.partition(":")
    run = release.latest_run(name)
    temperature = run.data.metrics.get("temperature")
    if not temperature:
        raise SystemExit(f"{name} logged no temperature metric, so its scores can't be put on log-odds")
    info = {"component": component, "run": name, "run_id": run.info.run_id, "temperature": float(temperature),
            "run_data": run.data.params.get("data")}
    work = Path(tempfile.mkdtemp(prefix="raid-"))

    if kind == "desklib":
        adapter, _ = release.desklib_adapter(name)
        release.live_desklib.ADAPTER_DIR = Path(adapter)
        release.live_desklib.load.cache_clear()
        info["scoring"] = "apps/detector/app/desklib.py: clean_text, 256 tokens, adapter merged, float32"
        return (lambda texts: release.desklib_logits(np.asarray(texts, dtype=object), torch.device(device))), info

    if kind == "meld":
        members = [name]
    else:
        members = [m for m in run.data.params.get("soup_members", "").split(",") if m]
        if not members:
            raise SystemExit(f"{name} logged no soup_members param; is it a soup run?")
    files = [member_files(m) for m in members]
    revisions = {f[2] for f in files}
    if len(revisions) != 1:
        raise SystemExit(f"{name}: members were trained on different MELD releases {sorted(revisions)}")
    if kind == "meld":
        adapter = files[0][0]
        head = torch.load(files[0][1], map_location="cpu")
    else:
        adapter = release.stacked_soup_adapter([f[0] for f in files], work / "soup-adapter", torch.float32)
        head = average_heads([torch.load(f[1], map_location="cpu") for f in files])
    save_file({k: v.contiguous() for k, v in head.items()}, work / "head.safetensors")
    scorer, _ = release.load_soup_scorer(device, revisions.pop(), adapter, work / "head.safetensors")
    info.update(members=members, member_run_ids=[f[3] for f in files], meld_revision=files[0][2],
                scoring="MELD Scorer.score(clean_text(text)), adapter merged, float32")
    return (lambda texts: release.meld_scores(scorer, texts)), info


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip() + \
            ("" if subprocess.call(["git", "diff", "--quiet"]) == 0 else "-dirty")
    except Exception:
        return "unknown"


##  scores every chunk of a split that has no file yet, so a job killed by its time limit resumes where it stopped.
##  chunk k holds rows [k * chunk_rows, (k + 1) * chunk_rows) of the split sorted by id
def score_chunks(frame: pd.DataFrame, fn, out: Path, info: dict, chunk_rows: int = CHUNK_ROWS) -> int:
    out.mkdir(parents=True, exist_ok=True)
    meta_path = out / "meta.json"
    meta = {**info, "n_rows": len(frame), "chunk_rows": chunk_rows, "ids_fingerprint": ids_fingerprint(frame["id"])}
    if meta_path.exists():
        old = json.loads(meta_path.read_text())
        for key in ("n_rows", "chunk_rows", "ids_fingerprint", "run_id"):
            if old.get(key) != meta[key]:
                raise SystemExit(f"{out} holds scores for a different {key} ({old.get(key)} vs {meta[key]}); "
                                 "move it away to rescore")
    meta_path.write_text(json.dumps(meta, indent=2))

    n_chunks = math.ceil(len(frame) / chunk_rows)
    todo = [k for k in range(n_chunks) if not (out / f"chunk-{k:05d}.parquet").exists()]
    print(f"{info['component']} on {out.name}: {n_chunks - len(todo)}/{n_chunks} chunks already done")
    start, done_rows = time.time(), 0
    for k in todo:
        rows = frame.iloc[k * chunk_rows:(k + 1) * chunk_rows]
        logits = np.asarray(fn(rows["generation"].tolist()), dtype=np.float64)
        if len(logits) != len(rows) or not np.isfinite(logits).all():
            raise SystemExit(f"chunk {k}: {len(logits)} scores for {len(rows)} rows, or a non-finite score")
        tmp = out / f"chunk-{k:05d}.parquet.tmp"
        pd.DataFrame({"id": rows["id"].to_numpy(), "logit": logits}).to_parquet(tmp, index=False)
        tmp.rename(out / f"chunk-{k:05d}.parquet")  # atomic, so a half-written chunk never counts as done
        done_rows += len(rows)
        rate = done_rows / (time.time() - start)
        left = sum(min(chunk_rows, len(frame) - j * chunk_rows) for j in todo[todo.index(k) + 1:])
        print(f"  chunk {k + 1}/{n_chunks}  {rate:.1f} texts/s  ~{left / rate / 3600:.1f} h left", flush=True)
    return len(todo)


# --------------------------------------------------------------------------
# scores -> candidates
# --------------------------------------------------------------------------

##  a component's logits on a split, by id, with its meta.json. refuses an unfinished one
def load_logits(component: str, split: str) -> tuple[pd.Series, dict]:
    out = scores_dir(component, split)
    if not (out / "meta.json").exists():
        raise SystemExit(f"{component} has no scores on {split}: run `python eval_raid.py score --component "
                         f"{component} --split {split}`")
    meta = json.loads((out / "meta.json").read_text())
    n_chunks = math.ceil(meta["n_rows"] / meta["chunk_rows"])
    missing = [k for k in range(n_chunks) if not (out / f"chunk-{k:05d}.parquet").exists()]
    if missing:
        raise SystemExit(f"{component} on {split} is unfinished: {len(missing)}/{n_chunks} chunks missing "
                         f"(first: {missing[0]}); resubmit its score job")
    scores = pd.concat([pd.read_parquet(out / f"chunk-{k:05d}.parquet") for k in range(n_chunks)], ignore_index=True)
    if len(scores) != meta["n_rows"] or scores["id"].duplicated().any():
        raise SystemExit(f"{component} on {split}: {len(scores)} scores for {meta['n_rows']} rows, or duplicate ids")
    return scores.set_index("id")["logit"], meta


##  calibrated log-odds of one component, or of a desklib+meld pair: (1 - w) * z_desklib + w * z_meld
def combine(logits: list[pd.Series], temperatures: list[float], weight_meld: float) -> pd.Series:
    z = [lg / t for lg, t in zip(logits, temperatures)]
    if len(z) == 1:
        return z[0]
    if not z[0].index.equals(z[1].index):
        z[1] = z[1].reindex(z[0].index)
        if z[1].isna().any():
            raise SystemExit("the pair's two components scored different texts")
    return (1 - weight_meld) * z[0] + weight_meld * z[1]


def candidate_scores(candidate: str, split: str, weight_meld: float) -> tuple[pd.Series, list[dict]]:
    loaded = [load_logits(c, split) for c in components_of(candidate)]
    return combine([lg for lg, _ in loaded], [m["temperature"] for _, m in loaded], weight_meld), [m for _, m in loaded]


def as_results(z: pd.Series) -> list[dict]:
    """RAID's prediction format, as raid.run_detection returns it: [{"id": ..., "score": ...}, ...]"""
    return [{"id": str(i), "score": float(s)} for i, s in z.items()]


# --------------------------------------------------------------------------
# evaluate (labelled sample only)
# --------------------------------------------------------------------------

def _is_all(record: dict, keys) -> bool:
    return all(record[k] == "all" for k in keys)


##  the headline rows of raid.run_evaluation's output: overall, overall unattacked, each domain, each attack.
##  accuracy is the share of AI texts caught at the domain thresholds (TPR); None where RAID couldn't hit the FPR
def summarise(evaluation: dict) -> pd.DataFrame:
    rows = []
    for r in evaluation["scores"]:
        if not _is_all(r, ("model", "decoding", "repetition_penalty")):
            continue
        if r["domain"] == "all" and r["attack"] == "all":
            view = "overall"
        elif r["domain"] == "all" and r["attack"] == "none":
            view = "overall, no attacks"
        elif r["attack"] == "all" and r["domain"] != "all":
            view = f"domain: {r['domain']}"
        elif r["domain"] == "all":
            view = f"attack: {r['attack']}"
        else:
            continue
        acc = {f: (r["accuracy"].get(str(f)) or {}).get("accuracy") for f in TARGET_FPRS}
        rows.append({"view": view, **{f"tpr@{f:g}": acc[f] for f in TARGET_FPRS}, "auroc": r["auroc"]})
    return pd.DataFrame(rows)


##  domains where RAID's threshold search missed the target FPR by more than its epsilon (their accuracy is None)
def missed_fprs(evaluation: dict, epsilon: float = 0.0005) -> dict:
    return {f: {d: v for d, v in by_domain.items() if v - float(f) > epsilon}
            for f, by_domain in evaluation["fpr"].items() if isinstance(by_domain, dict)}


def evaluate(candidates: list[str], weight_meld: float) -> pd.DataFrame:
    from raid import run_evaluation

    labels = pd.read_parquet(SAMPLE_PATH, columns=LABEL_COLUMNS)
    (OUT / "eval").mkdir(parents=True, exist_ok=True)
    tables = []
    for cand in candidates:
        z, metas = candidate_scores(cand, "train-sample", weight_meld)
        evaluation = run_evaluation(as_results(z), labels, target_fpr=TARGET_FPRS)
        table = summarise(evaluation).assign(candidate=cand)
        tables.append(table)
        missed = {f: d for f, d in missed_fprs(evaluation).items() if d}
        (OUT / "eval" / f"{tag(cand)}.json").write_text(json.dumps(
            {"candidate": cand, "components": metas, "weight_meld": weight_meld, "missed_fpr": missed,
             "evaluation": evaluation}, indent=2, default=float))
        if missed:
            print(f"  {cand}: RAID's threshold missed the target FPR in {missed}; those domains report no accuracy")
    out = pd.concat(tables, ignore_index=True)
    out.to_csv(OUT / "eval" / "summary.csv", index=False)
    return out


# --------------------------------------------------------------------------
# submit (test)
# --------------------------------------------------------------------------

def check_metadata(metadata: dict) -> None:
    missing = [k for k in METADATA_REQUIRED if not metadata.get(k)]
    unknown = sorted(set(metadata) - set(METADATA_REQUIRED) - set(METADATA_OPTIONAL))
    if missing or unknown:
        raise SystemExit(f"metadata.json: missing {missing}, keys the leaderboard rejects {unknown}")


##  checks predictions cover every test id exactly once with a finite score; the bot gives a submission with
##  missing texts no overall score, so it would not appear on the main leaderboard
def check_predictions(z: pd.Series, test_ids) -> None:
    if z.index.duplicated().any():
        raise SystemExit("duplicate ids in the predictions")
    if not np.isfinite(z.to_numpy()).all():
        raise SystemExit("a prediction is not a finite number")
    missing, extra = set(map(str, test_ids)) - set(map(str, z.index)), set(map(str, z.index)) - set(map(str, test_ids))
    if missing or extra:
        raise SystemExit(f"predictions don't match the test set: {len(missing)} test ids missing, {len(extra)} extra")


def submit(args) -> Path:
    if not SUBMISSION_NAME.fullmatch(args.name):
        raise SystemExit("--name may hold only letters, digits, dots, dashes and underscores (the bot's rule)")
    z, metas = candidate_scores(args.candidate, "test", args.weight_meld)
    check_predictions(z, pd.read_csv(raid_csv("test.csv"), usecols=["id"])["id"])
    metadata = {
        "date_released": args.date or date.today().isoformat(),
        "detector_name": args.detector_name or args.name,
        "contact_info": args.contact,
        **{k: v for k, v in (("website", args.website), ("paper_link", args.paper_link),
                             ("huggingface_link", args.huggingface_link), ("github_link", args.github_link)) if v},
        "additional_metadata": {
            "candidate": args.candidate, "weight_meld": args.weight_meld if len(metas) == 2 else None,
            "components": [{k: m.get(k) for k in ("component", "run_id", "temperature", "run_data", "members",
                                                   "meld_revision", "scoring")} for m in metas],
            "score": "calibrated log-odds (logit / validation temperature); higher = more likely machine-generated",
            "trained_on_raid": False,
            "git_commit": git_commit(),
        },
    }
    check_metadata(metadata)
    folder = OUT / "submissions" / args.name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2))
    with open(folder / "predictions.json", "w") as f:
        json.dump(as_results(z), f)
    return folder


# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sample", help="build the labelled train sample (once)")
    s.add_argument("--per-cell", type=int, default=50, help="machine texts kept per (domain, generator, attack)")
    s.add_argument("--human-per-cell", type=int, default=500,
                   help="human texts kept per (domain, attack); RAID's thresholds come from these, so 1%% FPR needs "
                        "several hundred unattacked ones per domain")
    s.add_argument("--force", action="store_true", help="rebuild even if the sample exists")

    s = sub.add_parser("score", help="score one component on a split (GPU, needs DagsHub)")
    s.add_argument("--component", required=True)
    s.add_argument("--split", required=True, choices=SPLITS)
    s.add_argument("--device", default="cuda")
    s.add_argument("--smoke", type=int, default=0,
                   help="score only the first N texts, write nothing, and project the full run's time")

    s = sub.add_parser("evaluate", help="compare candidates on the labelled train sample (offline)")
    s.add_argument("--candidates", nargs="+", required=True)
    s.add_argument("--weight-meld", type=float, default=0.5)

    s = sub.add_parser("submit", help="write the leaderboard files for one candidate (offline)")
    s.add_argument("--candidate", required=True)
    s.add_argument("--name", required=True, help="the submission folder name on the leaderboard")
    s.add_argument("--contact", required=True, help="contact_info for metadata.json (the leaderboard requires it)")
    s.add_argument("--detector-name", default=None, help="the name shown on the leaderboard (default: --name)")
    s.add_argument("--date", default=None, help="date_released, YYYY-MM-DD (default: today)")
    s.add_argument("--website")
    s.add_argument("--paper-link")
    s.add_argument("--huggingface-link")
    s.add_argument("--github-link")
    s.add_argument("--weight-meld", type=float, default=0.5)

    args = ap.parse_args()

    if args.cmd == "sample":
        if SAMPLE_PATH.exists() and not args.force:
            raise SystemExit(f"{SAMPLE_PATH} exists; every score file is tied to it. Pass --force to rebuild "
                             "(and rescore everything on train-sample)")
        frame = build_sample(raid_csv("train.csv"), args.per_cell, args.human_per_cell)
        SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(SAMPLE_PATH, index=False)
        human = frame[frame["model"].eq("human") & frame["attack"].eq("none")].groupby("domain").size()
        print(f"{len(frame)} texts -> {SAMPLE_PATH}\n"
              f"  {frame['model'].ne('human').sum()} machine, {frame['model'].eq('human').sum()} human\n"
              f"  unattacked human texts per domain (they set the thresholds): {human.to_dict()}")
        if (human < 300).any():
            print("  WARNING: under 300 in some domain; the 1% FPR column will be noisy there")

    elif args.cmd == "score":
        component = components_of(args.component)
        if len(component) != 1:
            raise SystemExit("score one component at a time; a pair is combined later by evaluate/submit")
        component = component[0]
        frame = load_split(args.split)
        fn, info = load_component(component, args.device)
        info["git_commit"] = git_commit()
        if args.smoke:
            rows = frame.head(args.smoke)
            start = time.time()
            logits = np.asarray(fn(rows["generation"].tolist()), dtype=np.float64)
            rate = len(rows) / (time.time() - start)
            ok = len(logits) == len(rows) and np.isfinite(logits).all()
            print(f"SMOKE {component} on {args.split}: {len(rows)} texts, {rate:.1f} texts/s, scores "
                  f"{'finite' if ok else 'NOT FINITE'} (range {logits.min():.2f}..{logits.max():.2f}, T "
                  f"{info['temperature']:.3f})\n  the full split ({len(frame)} texts) would take "
                  f"~{len(frame) / rate / 3600:.1f} h at this rate (a rough guess: includes warm-up)")
            if not ok:
                sys.exit(1)
            return
        score_chunks(frame, fn, scores_dir(component, args.split), info)
        print(f"done: {scores_dir(component, args.split)}")

    elif args.cmd == "evaluate":
        table = evaluate(args.candidates, args.weight_meld)
        pd.set_option("display.width", 200)
        for col in [f"tpr@{f:g}" for f in TARGET_FPRS] + ["auroc"]:
            print(f"\n{col} on the train sample (higher is better):")
            print(table.pivot(index="view", columns="candidate", values=col).round(3).to_string())
        print(f"\nwrote {OUT / 'eval'}/summary.csv and one JSON per candidate")

    elif args.cmd == "submit":
        folder = submit(args)
        print(f"wrote {folder}/metadata.json and predictions.json\n"
              f"  next: copy the folder to leaderboard/submissions/{args.name}/ in your fork of liamdugan/raid "
              "and open a pull request; the bot comments the results on it")


if __name__ == "__main__":
    main()
