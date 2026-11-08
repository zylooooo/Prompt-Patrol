"""
E3 leave-one-generator-out for the shipped detector (desklib + MELD 3-seed soup), from the runs that
cluster/logo.sh logs. Trains nothing and reads only scores files (outputs/, else DagsHub).

For every fold (one generator held out of train and val) and for the control (every generator in
training, data v0.1), each rule gets its threshold fitted on that fold's own val at 1% FPR (answers of
>= --min-words words), frozen, then test scored once:

    desklib-untouched   the base desklib, which never saw any of our generators (a reference)
    desklib             desklib-lora-logo-<fold>-s<seed>
    meld-soup           meld-lora-soup-logo-<fold>-s1
    desklib+meld        desklib seed s with the fold's soup, log-odds averaged 50/50 (the shipped rule)

The gap is the point. A fold's test set is human test + its generator's test answers, and the control's
test set restricted to those same answers is the same rows, so:

    gap = control (generator seen in training) - fold (generator never seen)

is paired by answer, with a 95% interval that resamples whole questions. It isolates the unseen generator:
both sides train on raw answers only, so the missing spliced/paraphrased/edited rows cancel.

Writes into --out:
  by_seed.csv     every rule, fold and seed: AUROC, TPR at exactly 1% FPR, deployed TPR and FPR
  summary.csv     the same, mean and sd over seeds
  gaps.csv        control minus fold per generator, rule and metric, with the interval

    python analyse_logo.py
    python analyse_logo.py --folds claude,gpt --bootstrap-n 200      # while runs are still coming in
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit, logit
from sklearn.metrics import roc_auc_score

import harness
import metrics
from combined_data import LOGO_FOLDS, load_corpus

EPS = 1e-7
CONTROL = "control"
GAP_RULES = ("desklib", "meld-soup", "desklib+meld")


##  the val and test rows of one fold with the columns the analysis needs, answers of >= min_words words only
##
##  fold:   a LOGO_FOLDS slug or "control"
##  returns a frame indexed by answer_id: split, question_id, y_true, generator
def fold_frame(fold: str, min_words: int) -> pd.DataFrame:
    frames = load_corpus("v0.1" if fold == CONTROL else f"logo-{fold}")
    rows = pd.concat([frames[s].assign(split=s) for s in ("val", "test")], ignore_index=True)
    rows = rows[rows["n_words"] >= min_words]
    return rows.rename(columns={"label": "y_true"}).set_index("answer_id")[
        ["split", "question_id", "y_true", "generator"]]


##  one scores file's rows of one model as log-odds, indexed by answer_id
def _z(path: Path, untouched: bool) -> pd.Series:
    from scores import load_scores

    scores = load_scores(path)
    pick = scores["model"].str.endswith("-untouched")
    rows = scores[pick if untouched else ~pick]
    if rows["model"].nunique() != 1:
        raise SystemExit(f"{path.name}: expected one {'untouched' if untouched else 'tuned'} model, "
                         f"found {sorted(rows['model'].unique())}")
    return pd.Series(logit(np.clip(rows["y_prob"].to_numpy(), EPS, 1 - EPS)), index=rows["answer_id"].to_numpy())


##  every rule of one fold, from the runs logo.sh logs
##  returns {rule: {seed: log-odds Series indexed by answer_id}}
def load_rules(fold: str, seeds: list[int]) -> dict[str, dict[int, pd.Series]]:
    from ensemble_scores import find_scores

    desklib = {s: find_scores(f"desklib-lora-logo-{fold}-s{s}") for s in seeds}
    soup = _z(find_scores(f"meld-lora-soup-logo-{fold}-s1"), untouched=False)
    tuned = {s: _z(p, untouched=False) for s, p in desklib.items()}
    return {
        "desklib-untouched": {seeds[0]: _z(desklib[seeds[0]], untouched=True)},
        "desklib": tuned,
        "meld-soup": {1: soup},
        "desklib+meld": {s: 0.5 * z + 0.5 * soup.reindex(z.index) for s, z in tuned.items()},
    }


##  one rule on one seed: threshold at target_fpr on every val row of the fold, frozen, then the test rows in `on`
##
##  z:      log-odds for the fold's val and test rows (indexed by answer_id)
##  frame:  fold_frame() of the same fold
##  on:     boolean mask over frame selecting the test rows to score (e.g. human + one generator)
##  returns AUROC, TPR at exactly target_fpr, deployed TPR/FPR, the threshold, and the test probs and labels
def score(z: pd.Series, frame: pd.DataFrame, on: pd.Series, target_fpr: float) -> dict:
    z = z.reindex(frame.index)
    if z.isna().any():
        raise ValueError(f"{int(z.isna().sum())} answers of the fold have no score")
    val = frame["split"] == "val"
    threshold = metrics.threshold_at_fpr(frame.loc[val, "y_true"], expit(z[val]), target_fpr)
    test = (frame["split"] == "test") & on
    y, p = frame.loc[test, "y_true"].to_numpy(), expit(z[test].to_numpy())
    point = metrics.operating_point_metrics(y, p, threshold)
    return {"auroc": float(roc_auc_score(y, p)), "tpr_at_1pct": metrics.oracle_tpr_at_fpr(y, p, target_fpr),
            "deployed_tpr": point["recall"], "deployed_fpr": point["fpr"], "threshold": threshold,
            "n_ai": int(y.sum()), "n_human": int(len(y) - y.sum()),
            "_ids": frame.index[test], "_y": y, "_p": p}


##  the one held-out generator of a LOGO fold, read from its test rows
def held_out_generator(frame: pd.DataFrame) -> str:
    gens = set(frame.loc[(frame["split"] == "test") & (frame["y_true"] == 1), "generator"])
    if len(gens) != 1:
        raise ValueError(f"a LOGO fold's test AI should come from one generator, found {sorted(gens)}")
    return gens.pop()


##  control minus fold on the same test answers, for one rule and metric, every seed of each side
##
##  control, fold:  {seed: score() result} for the rule, the control restricted to the fold's generator
##  returns diff (seen - unseen) and its 95% interval, resampling whole questions
def gap(control: dict[int, dict], fold: dict[int, dict], groups: np.ndarray, metric: str, n: int) -> dict:
    ref = next(iter(fold.values()))
    for side in (*control.values(), *fold.values()):
        if not side["_ids"].equals(ref["_ids"]):
            raise ValueError("control and fold were not scored on the same test answers")
    return metrics.paired_bootstrap_diff(
        ref["_y"], [r["_p"] for r in control.values()], [r["_p"] for r in fold.values()],
        [r["threshold"] for r in control.values()], [r["threshold"] for r in fold.values()],
        groups, harness.PAIR_METRICS[metric], n=n)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folds", default=",".join(LOGO_FOLDS), help="comma-separated held-out generators")
    ap.add_argument("--seeds", default="1,2,3", help="desklib seeds; the soup is one run per fold")
    ap.add_argument("--min-words", type=int, default=harness.MIN_WORDS)
    ap.add_argument("--target-fpr", type=float, default=metrics.HEADLINE_FPR)
    ap.add_argument("--bootstrap-n", type=int, default=metrics.BOOTSTRAP_N)
    ap.add_argument("--out", default="outputs/analysis/logo")
    args = ap.parse_args()

    seeds = [int(s) for s in args.seeds.split(",") if s]
    folds = [f for f in args.folds.split(",") if f]
    if bad := set(folds) - set(LOGO_FOLDS):
        raise SystemExit(f"unknown fold(s) {sorted(bad)}; choose from {LOGO_FOLDS}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    control_frame = fold_frame(CONTROL, args.min_words)
    control_rules = load_rules(CONTROL, seeds)
    rows, gaps = [], []
    everything = pd.Series(True, index=control_frame.index)
    for rule, by_seed in control_rules.items():
        for seed, z in by_seed.items():
            r = score(z, control_frame, everything, args.target_fpr)
            rows.append({"rule": rule, "fold": CONTROL, "test_on": "all", "seed": seed,
                         **{k: v for k, v in r.items() if not k.startswith("_")}})

    for fold in folds:
        try:
            frame, rules = fold_frame(fold, args.min_words), load_rules(fold, seeds)
        except SystemExit as missing:
            print(f"skipping {fold}: {missing}")
            continue
        generator = held_out_generator(frame)
        seen_on = control_frame["generator"].isin(["human", generator])
        unseen, seen = {}, {}
        for rule, by_seed in rules.items():
            for seed, z in by_seed.items():
                unseen.setdefault(rule, {})[seed] = r = score(z, frame, pd.Series(True, index=frame.index),
                                                              args.target_fpr)
                rows.append({"rule": rule, "fold": fold, "test_on": generator, "seed": seed,
                             **{k: v for k, v in r.items() if not k.startswith("_")}})
            for seed, z in control_rules[rule].items():
                seen.setdefault(rule, {})[seed] = r = score(z, control_frame, seen_on, args.target_fpr)
                rows.append({"rule": rule, "fold": CONTROL, "test_on": generator, "seed": seed,
                             **{k: v for k, v in r.items() if not k.startswith("_")}})

        test = frame[frame["split"] == "test"]
        groups = test.loc[unseen["desklib"][seeds[0]]["_ids"], "question_id"].to_numpy()
        for rule in GAP_RULES:
            for metric in harness.PAIR_METRICS:
                g = gap(seen[rule], unseen[rule], groups, metric, args.bootstrap_n)
                gaps.append({"generator": generator, "fold": fold, "rule": rule, "metric": metric,
                             "seen": float(np.mean([harness.PAIR_METRICS[metric](r["_y"], r["_p"], r["threshold"])
                                                    for r in seen[rule].values()])),
                             "unseen": float(np.mean([harness.PAIR_METRICS[metric](r["_y"], r["_p"], r["threshold"])
                                                      for r in unseen[rule].values()])),
                             "gap": g["diff"], "ci_low": g["ci_low"], "ci_high": g["ci_high"],
                             "gap_is_clear": bool(g["ci_low"] > 0 or g["ci_high"] < 0)})
        print(f"{fold}: done")

    by_seed = pd.DataFrame(rows)
    by_seed.to_csv(out / "by_seed.csv", index=False)
    value_cols = ["auroc", "tpr_at_1pct", "deployed_tpr", "deployed_fpr"]
    summary = (by_seed.groupby(["rule", "fold", "test_on"], sort=False)[value_cols]
               .agg(["mean", "std"]).round(4))
    summary.columns = [f"{c}_{s}" for c, s in summary.columns]
    summary.reset_index().to_csv(out / "summary.csv", index=False)
    if not gaps:
        print(f"no fold had all its runs; wrote {out}/by_seed.csv and summary.csv (control only)")
        return
    gaps = pd.DataFrame(gaps)
    gaps.to_csv(out / "gaps.csv", index=False)

    shipped = gaps[(gaps["rule"] == "desklib+meld") & (gaps["metric"] == "deployed_tpr")].sort_values("unseen")
    print("\ndesklib + MELD, deployed TPR at the fold's own frozen threshold (worst unseen generator first):")
    for _, g in shipped.iterrows():
        print(f"  {g['generator']:<17} seen {g['seen']:.1%}  unseen {g['unseen']:.1%}  "
              f"gap {g['gap']:+.1%} [{g['ci_low']:+.1%}, {g['ci_high']:+.1%}]{'  CLEAR' if g['gap_is_clear'] else ''}")
    print(f"\nWrote {out}/by_seed.csv, summary.csv and gaps.csv")


if __name__ == "__main__":
    main()
