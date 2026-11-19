"""
Fits a threshold and an abstention band for each strictness level of the released desklib + MELD detector, from the
validation scores its release run already logged. Trains nothing, scores nothing, needs no GPU and logs nothing.

    lenient   1% of student answers above the threshold on val  (the release's own threshold)
    standard  2%
    strict    5%    a stricter detector flags more answers, and so more students by mistake

No recalibration: the temperatures and the MELD weight do not depend on where the line is drawn, so each level's
threshold is just a different cut of the same calibrated probabilities.

Bands: every level gets a band of the same width in log-odds as the reference (lenient) level's, whose band is chosen
on val as the widest on the grid leaving at most MAX_AI_UNCERTAIN of AI answers uncertain (that picks the release's
own +-0.005). A fixed probability band would not mean the same thing at each level: the calibrated probabilities pile
up near 0.95, so +-0.005 there is as wide in log-odds as roughly +-0.015 at 0.81. Choosing each band by an
uncertain-share budget instead runs away where answers are sparse (at 0.81 it never binds and takes any width).

In order:
  1. downloads predictions/desklib-meld-ensemble-v1_scores.parquet from the release run on DagsHub (cached in
     outputs/strictness/; --scores uses a local copy instead);
  2. keeps val answers of >= MIN_WORDS words (what the release fitted on), with n_words from the local extended corpus;
  3. CHECK: refits the 1% threshold and requires it to equal the bundle's, so these are the scores it was fitted on;
  4. VALIDATION ONLY: each level's threshold; the reference level's band (the uncertain-budget rule above) and its
     width in log-odds; every other level's band at that same width; a band table under the API's rule for each;
  5. TEST, information only: each level's frozen threshold and band applied once, nothing fitted on it;
  6. --write: apps/detector/app/strictness_levels.json, which the detector reports with every score.

    python fit_strictness_levels.py                    # fit and print, write nothing outside outputs/
    python fit_strictness_levels.py --write            # also write the detector's strictness_levels.json
    python fit_strictness_levels.py --band strict=0.02 --write    # override one level's band by hand
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.special import logit

import metrics
from combined_data import load_corpus
from scores import OUT_DIRECTORY, load_scores

# The release's names, copied rather than imported: release_desklib_meld pulls in torch and the detector's code, none
# of which this needs. tests/test_fit_strictness_levels.py checks they still match.
MODEL_VERSION = "desklib-meld-ensemble-v1"
RUN_NAME = f"release-{MODEL_VERSION}"
MIN_WORDS = 10
DETECTOR_TARGET = Path(__file__).resolve().parent.parent / "apps" / "detector" / "model" / "desklib-meld"

LEVELS = {"lenient": 0.01, "standard": 0.02, "strict": 0.05}
# lowest threshold first: strict flags the most, lenient the fewest
BY_THRESHOLD = ("strict", "standard", "lenient")
LEVELS_VERSION = "lenient1-standard2-strict5-logitband-v1"
REFERENCE_LEVEL = "lenient"         # its threshold must reproduce the bundle's (CHECK); its band sets the width
BANDS = (0.0, 0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.05, 0.08)
MAX_AI_UNCERTAIN = 0.06             # 0.005 at 1% leaves 5.7% of AI uncertain; 0.0075 would pass this, 0.01 not
BAND_DECIMALS = 4
THRESHOLD_TOLERANCE = 1e-6          # the bundle rounds its threshold to 6 decimals
SCORES_FILE = f"{MODEL_VERSION}_scores.parquet"
WORK = OUT_DIRECTORY / "strictness"
TARGET = Path(__file__).resolve().parent.parent / "apps" / "detector" / "app" / "strictness_levels.json"


def latest_run(run_name: str):
    import mlflow

    runs = mlflow.search_runs(search_all_experiments=True, filter_string=f"tags.mlflow.runName = '{run_name}'",
                              order_by=["attributes.start_time DESC"], output_format="list")
    runs = [r for r in runs if r.info.status == "FINISHED"]
    if not runs:
        raise SystemExit(f"no finished run named {run_name} on DagsHub")
    return runs[0]


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip() + \
            ("" if subprocess.call(["git", "diff", "--quiet"]) == 0 else "-dirty")
    except Exception:
        return "unknown"


def fetch_scores(run_id: str | None) -> tuple[Path, str]:
    # imported here, not at the top: CI installs only requirements-test.txt, which has no mlflow
    import mlflow
    from tracking import setup_mlflow

    setup_mlflow()
    run = mlflow.get_run(run_id) if run_id else latest_run(RUN_NAME)
    if run.info.run_name != RUN_NAME or run.info.status != "FINISHED":
        raise SystemExit(f"run {run.info.run_id} is {run.info.run_name} ({run.info.status}), not a finished {RUN_NAME}")
    cached = WORK / run.info.run_id / SCORES_FILE
    if not cached.exists():
        got = Path(mlflow.artifacts.download_artifacts(run_id=run.info.run_id,
                                                       artifact_path=f"predictions/{SCORES_FILE}",
                                                       dst_path=tempfile.mkdtemp(prefix="strictness-")))
        cached.parent.mkdir(parents=True, exist_ok=True)
        got.replace(cached)
    return cached, run.info.run_id


##  one split's ensemble probabilities, joined to the corpus for n_words and dataset, answers >= MIN_WORDS only
def split_scores(scores: pd.DataFrame, corpus: pd.DataFrame, split: str) -> pd.DataFrame:
    s = scores[(scores["split"] == split) & (scores["model"] == MODEL_VERSION)]
    joined = s.merge(corpus[["answer_id", "n_words", "dataset", "label"]], on="answer_id", how="left")
    if joined["n_words"].isna().any():
        raise SystemExit(f"{int(joined['n_words'].isna().sum())} {split} answers are not in the local extended corpus: "
                         "pull the data (dvc pull) at the revision the release used")
    if len(s) != len(corpus) or (joined["label"] != joined["y_true"]).any():
        raise SystemExit(f"{split}: the logged scores do not line up with the local extended corpus "
                         f"({len(s)} scored vs {len(corpus)} in the corpus, or labels differ)")
    return joined[joined["n_words"] >= MIN_WORDS].reset_index(drop=True)


##  the API's verdicts (apps/api checks_service._decide: uncertain if |p - threshold| <= band, else AI if p > threshold)
def verdicts(y: np.ndarray, p: np.ndarray, threshold: float, band: float) -> dict:
    uncertain = np.abs(p - threshold) <= band
    flagged = (p > threshold) & ~uncertain
    return {"band": band,
            "humans_flagged": float(flagged[y == 0].mean()), "humans_uncertain": float(uncertain[y == 0].mean()),
            "ai_flagged": float(flagged[y == 1].mean()), "ai_uncertain": float(uncertain[y == 1].mean())}


##  the reference level's band: the widest on the grid leaving at most MAX_AI_UNCERTAIN of AI answers uncertain
def choose_band(table: list[dict]) -> float:
    return max(r["band"] for r in table if r["ai_uncertain"] <= MAX_AI_UNCERTAIN)


##  width in log-odds of the API's uncertain zone [threshold - band, threshold + band]
def logit_width(threshold: float, band: float) -> float:
    if not (0 < threshold - band and threshold + band < 1):
        raise ValueError(f"band {band} around {threshold} leaves (0, 1)")
    return float(logit(threshold + band) - logit(threshold - band))


##  the probability band around threshold whose uncertain zone is `width` wide in log-odds, rounded to BAND_DECIMALS
def band_for_width(threshold: float, width: float) -> float:
    if width <= 0:
        return 0.0
    edge = min(threshold, 1 - threshold) * (1 - 1e-9)
    if logit_width(threshold, edge) < width:
        raise ValueError(f"no band around {threshold} is {width} wide in log-odds")
    return round(brentq(lambda b: logit_width(threshold, b) - width, 0.0, edge, xtol=1e-12), BAND_DECIMALS)


def per_dataset_flagged(frame: pd.DataFrame, threshold: float) -> dict:
    human = frame[frame["y_true"] == 0]
    return {d: {"n_human": int(len(g)), "wrongly_flagged": float((g["y_prob"] > threshold).mean())}
            for d, g in human.groupby("dataset")}


##  strict's threshold < standard's < lenient's, and no level's uncertain zone reaches a neighbour's threshold (else
##  one level would call 'uncertain' an answer the next one already decides)
def check_order(levels: dict) -> None:
    for lower, upper in zip(BY_THRESHOLD, BY_THRESHOLD[1:]):
        lo, hi = levels[lower], levels[upper]
        if not lo["threshold"] < hi["threshold"]:
            raise SystemExit(f"{lower}'s threshold {lo['threshold']:.6f} is not below {upper}'s {hi['threshold']:.6f}")
        if lo["threshold"] + lo["abstention_band"] >= hi["threshold"]:
            raise SystemExit(f"{lower}'s band reaches {upper}'s threshold. Narrow it with --band {lower}=...")
        if hi["threshold"] - hi["abstention_band"] <= lo["threshold"]:
            raise SystemExit(f"{upper}'s band reaches {lower}'s threshold. Narrow it with --band {upper}=...")


def parse_overrides(specs: list[str]) -> dict[str, float]:
    out = {}
    for spec in specs:
        level, _, value = spec.partition("=")
        if level not in LEVELS or not value:
            raise SystemExit(f"--band takes level=value with level in {list(LEVELS)}, got {spec!r}")
        out[level] = float(value)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", default=None, help="the release run to read scores from (default: the newest one)")
    ap.add_argument("--scores", type=Path, default=None, help="a local copy of the scores file instead of DagsHub")
    ap.add_argument("--band", action="append", default=[], metavar="LEVEL=BAND",
                    help="override the chosen band for one level (repeatable)")
    ap.add_argument("--write", action="store_true", help=f"write {TARGET.relative_to(TARGET.parents[3])}")
    args = ap.parse_args()
    overrides = parse_overrides(args.band)

    bundle_path = DETECTOR_TARGET / "desklib-meld.json"
    if not bundle_path.exists():
        raise SystemExit(f"no bundle at {bundle_path}: run release_desklib_meld.py --fetch first")
    bundle = json.loads(bundle_path.read_text())
    if bundle["model_version"] != MODEL_VERSION:
        raise SystemExit(f"the installed bundle is {bundle['model_version']}, this script is for {MODEL_VERSION}")

    # ---- 1-2. scores
    if args.scores:
        path, run_id = args.scores, args.run_id or "local"
    else:
        path, run_id = fetch_scores(args.run_id)
    scores = load_scores(path)
    corpus = load_corpus("extended")
    val, test = split_scores(scores, corpus["val"], "val"), split_scores(scores, corpus["test"], "test")
    yv, pv = val["y_true"].to_numpy(), val["y_prob"].to_numpy()
    yt, pt = test["y_true"].to_numpy(), test["y_prob"].to_numpy()
    print(f"scores from {run_id}: val {len(val)} answers of >= {MIN_WORDS} words ({int((yv == 0).sum())} human), "
          f"test {len(test)}")

    # ---- 3. CHECK
    refit = metrics.threshold_at_fpr(yv, pv, LEVELS[REFERENCE_LEVEL])
    if abs(refit - bundle["threshold"]) > THRESHOLD_TOLERANCE:
        raise SystemExit(f"CHECK failed: the {LEVELS[REFERENCE_LEVEL]:.0%} threshold refit on these scores is "
                         f"{refit:.6f}, the bundle's is {bundle['threshold']}; these are not the scores it was fitted on")
    print(f"CHECK: {LEVELS[REFERENCE_LEVEL]:.0%} threshold refit {refit:.6f} = bundle {bundle['threshold']}")

    # ---- 4-5. each level
    report: dict = {"model_version": MODEL_VERSION, "bundle_calibration_version": bundle["calibration_version"],
                    "source_run_id": run_id, "git_commit": git_commit(), "levels_version": LEVELS_VERSION,
                    "levels": {}}
    thresholds = {level: metrics.threshold_at_fpr(yv, pv, fpr) for level, fpr in LEVELS.items()}
    reference_band = choose_band([verdicts(yv, pv, thresholds[REFERENCE_LEVEL], b) for b in BANDS])
    if reference_band == BANDS[-1]:
        raise SystemExit(f"{REFERENCE_LEVEL}'s band is the top of the grid ({BANDS[-1]}): the rule never bound")
    width = logit_width(thresholds[REFERENCE_LEVEL], reference_band)
    report["band_rule"] = {"reference_level": REFERENCE_LEVEL, "reference_band": reference_band,
                           "logit_width": width, "max_ai_uncertain": MAX_AI_UNCERTAIN}
    print(f"BANDS: {REFERENCE_LEVEL} +-{reference_band} (widest leaving <= {MAX_AI_UNCERTAIN:.0%} of AI uncertain) "
          f"is {width:.4f} wide in log-odds; every level gets that width")
    for level, fpr in LEVELS.items():
        threshold = thresholds[level]
        chosen = band_for_width(threshold, width)
        band = overrides.get(level, chosen)
        table = [verdicts(yv, pv, threshold, b) for b in sorted(set(BANDS) | {band})]
        report["levels"][level] = {
            "target_fpr": fpr, "threshold": threshold, "abstention_band": band, "band_by_rule": chosen,
            "band_logit_width": logit_width(threshold, band),
            "n_humans_above_threshold": int((pv[yv == 0] > threshold).sum()),
            "val": verdicts(yv, pv, threshold, band), "val_band_table": table,
            "val_per_dataset_wrongly_flagged": per_dataset_flagged(val, threshold),
            "test_information_only": verdicts(yt, pt, threshold, band),
            "test_per_dataset_wrongly_flagged": per_dataset_flagged(test, threshold),
        }
        t = report["levels"][level]["test_information_only"]
        print(f"\n{level.upper()} ({fpr:.0%} FPR): threshold {threshold:.6f} "
              f"({report['levels'][level]['n_humans_above_threshold']} val student answers above it), "
              f"band +-{band}" + (f" (rule chose {chosen}, overridden)" if level in overrides else ""))
        print("  val band table:")
        for row in table:
            mark = " <" if row["band"] == band else ""
            print(f"    +-{row['band']:<7} students flagged {row['humans_flagged']:6.2%}  uncertain "
                  f"{row['humans_uncertain']:6.2%} | AI flagged {row['ai_flagged']:6.1%}  uncertain "
                  f"{row['ai_uncertain']:6.1%}{mark}")
        print("  val wrongly flagged per dataset (no band): "
              + ", ".join(f"{d} {v['wrongly_flagged']:.1%} of {v['n_human']}"
                          for d, v in report["levels"][level]["val_per_dataset_wrongly_flagged"].items()))
        print(f"  TEST (information only): students flagged {t['humans_flagged']:.2%}, uncertain "
              f"{t['humans_uncertain']:.2%} | AI flagged {t['ai_flagged']:.1%}, uncertain {t['ai_uncertain']:.1%}")

    check_order(report["levels"])

    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "report.json").write_text(json.dumps(report, indent=2))
    print(f"\nreport -> {WORK / 'report.json'}")

    if args.write:
        out = {
            "model_version": MODEL_VERSION,
            "bundle_calibration_version": bundle["calibration_version"],
            "levels_version": LEVELS_VERSION,
            "levels": {level: {"target_fpr": v["target_fpr"], "threshold": round(float(v["threshold"]), 6),
                               "abstention_band": v["abstention_band"]}
                       for level, v in report["levels"].items()},
            "fitted_on": f"v0.1-extended val (answers >= {MIN_WORDS} words), scores logged by {RUN_NAME}",
            "source_run_id": run_id,
            "band_rule": f"every level's uncertain zone {width:.4f} wide in log-odds, the width of {REFERENCE_LEVEL}'s "
                         f"+-{reference_band} (the widest on {list(BANDS)} leaving <= {MAX_AI_UNCERTAIN:.0%} of AI "
                         "answers uncertain)" + (f"; overridden by hand: {overrides}" if overrides else ""),
            "fitted": date.today().isoformat(),
            "git_commit": report["git_commit"],
        }
        TARGET.write_text(json.dumps(out, indent=2) + "\n")
        print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
