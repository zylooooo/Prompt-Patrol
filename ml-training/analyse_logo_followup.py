"""
E3 follow-ups to analyse_logo.py, from the same DagsHub runs. Trains nothing and logs nothing.

analyse_logo.py's gap intervals resample questions only. Desklib's deployed TPR moves 10-18 points between
training seeds, so those intervals are too narrow. Every interval here resamples BOTH whole questions and
training seeds (with replacement, per side), and every fold is scored on one shared question draw, so pooled
numbers keep the correlation that the shared human test answers create.

Rules (log-odds, threshold fitted at 1% FPR on the fold's own val, frozen):
    desklib-untouched   base desklib, never fine-tuned (one score set)
    desklib             desklib-lora-logo-<fold>-s{1,2,3}
    meld                meld-lora-logo-<fold>-s{1,2,3}, the individual seeds before souping
    meld-soup           meld-lora-soup-logo-<fold>-s1 (ONE run: its seed variance is not captured)
    desklib+meld        desklib seed s + the fold's soup, 50/50 log-odds (the shipped rule; seed variance
                        is desklib's only)
    desklib+meld-s      desklib seed s + MELD seed s, 50/50 (a proxy for the shipped rule that does carry
                        MELD's seed variance)

Writes into --out (default outputs/analysis/logo, next to analyse_logo.py's files):
  headline.csv        the shipped-rule seen/unseen/gap table analyse_logo.py prints, from its gaps.csv
  seed_gaps.csv       per fold, rule and metric: control minus fold, question+seed interval, Bonferroni
                      interval over the folds, and the gap of every control-seed x fold-seed pair (min/max)
  pooled_gap.csv      per rule and metric: the gap averaged over all folds, and the worst fold
  vs_untouched.csv    on the unseen generator: tuned (without it) minus untouched desklib
  rule_compare.csv    on the unseen generator: desklib+meld minus each single model, per fold and pooled
  gap_forest.png      seed-aware deployed-TPR gap per generator, three rules

    python analyse_logo_followup.py
    python analyse_logo_followup.py --bootstrap-n 200      # quick look
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

import harness
import metrics
from analyse_logo import CONTROL, _z, fold_frame, held_out_generator, load_rules, score
from combined_data import LOGO_FOLDS

METRICS = ("deployed_tpr", "auroc")
GAP_RULES = ("desklib", "meld", "meld-soup", "desklib+meld", "desklib+meld-s")
COMPARE = (("desklib+meld", "desklib"), ("desklib+meld", "meld"), ("desklib+meld", "meld-soup"),
           ("meld", "desklib"))
UNTOUCHED = "desklib-untouched"


##  every rule of one fold: analyse_logo's four plus the individual MELD seeds and the seed-paired ensemble
def all_rules(fold: str, seeds: list[int]) -> dict[str, dict[int, pd.Series]]:
    from ensemble_scores import find_scores

    rules = load_rules(fold, seeds)
    meld = {s: _z(find_scores(f"meld-lora-logo-{fold}-s{s}"), untouched=False) for s in seeds}
    rules["meld"] = meld
    rules["desklib+meld-s"] = {s: 0.5 * z + 0.5 * meld[s].reindex(z.index) for s, z in rules["desklib"].items()}
    return rules


##  deployed TPR and AUROC, fast enough to run inside the bootstrap
def fast_metrics(y: np.ndarray, p: np.ndarray, t: float) -> tuple[float, float]:
    pos = y == 1
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan"), float("nan")
    ranks = rankdata(p)
    auroc = (ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float((p[pos] >= t).mean()), float(auroc)


##  one side (seen or unseen) of one fold: per rule, per seed, the scored test rows
##  returns {rule: [(y, p, threshold), ...one per seed]} and the answer ids every entry is scored on
def side(rules: dict, frame: pd.DataFrame, on: pd.Series, fpr: float) -> tuple[dict, pd.Index]:
    out, ids = {}, None
    for rule, by_seed in rules.items():
        out[rule] = []
        for _, z in sorted(by_seed.items()):
            r = score(z, frame, on, fpr)
            if ids is None:
                ids = r["_ids"]
            elif not r["_ids"].equals(ids):
                raise ValueError("rules of one side were scored on different answers")
            out[rule].append((r["_y"], r["_p"], r["threshold"]))
    return out, ids


##  the metric of every (rule, seed) on one set of rows: {rule: array of shape (n_seeds, len(METRICS))}
def evaluate(scored: dict, idx: np.ndarray) -> dict[str, np.ndarray]:
    return {rule: np.array([fast_metrics(y[idx], p[idx], t) for y, p, t in entries])
            for rule, entries in scored.items()}


def interval(draws: np.ndarray, alpha: float) -> tuple[float, float]:
    draws = draws[np.isfinite(draws)]
    if not len(draws):
        return float("nan"), float("nan")
    return float(np.percentile(draws, 100 * alpha / 2)), float(np.percentile(draws, 100 * (1 - alpha / 2)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folds", default=",".join(LOGO_FOLDS))
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--min-words", type=int, default=harness.MIN_WORDS)
    ap.add_argument("--target-fpr", type=float, default=metrics.HEADLINE_FPR)
    ap.add_argument("--bootstrap-n", type=int, default=metrics.BOOTSTRAP_N)
    ap.add_argument("--out", default="outputs/analysis/logo")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    seeds = [int(s) for s in args.seeds.split(",") if s]
    folds = [f for f in args.folds.split(",") if f]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    alpha, alpha_adj = 0.05, 0.05 / len(folds)

    # 1. the table analyse_logo.py prints, saved
    gaps_file = out / "gaps.csv"
    if gaps_file.exists():
        g = pd.read_csv(gaps_file)
        g = g[(g["rule"] == "desklib+meld") & (g["metric"] == "deployed_tpr")].sort_values("gap", ascending=False)
        g[["generator", "seen", "unseen", "gap", "ci_low", "ci_high", "gap_is_clear"]].to_csv(
            out / "headline.csv", index=False)

    # 2. score every rule and seed once, on both sides of every fold
    control_frame = fold_frame(CONTROL, args.min_words)
    control_rules = all_rules(CONTROL, seeds)
    sides = {}
    for fold in folds:
        frame = fold_frame(fold, args.min_words)
        generator = held_out_generator(frame)
        unseen, ids = side(all_rules(fold, seeds), frame, pd.Series(True, index=frame.index), args.target_fpr)
        seen, seen_ids = side(control_rules, control_frame,
                              control_frame["generator"].isin(["human", generator]), args.target_fpr)
        if not ids.equals(seen_ids):
            raise ValueError(f"{fold}: control and fold were not scored on the same test answers")
        questions = frame.loc[ids, "question_id"].to_numpy()
        members = {q: np.flatnonzero(questions == q) for q in np.unique(questions)}
        sides[fold] = {"generator": generator, "seen": seen, "unseen": unseen, "members": members,
                       "n": len(ids)}
        print(f"{fold}: scored")

    # every question any fold tests on; one draw of these is shared by all folds
    universe = np.array(sorted(set().union(*(s["members"] for s in sides.values()))))

    def rows(fold: str, draw: np.ndarray | None) -> np.ndarray:
        s = sides[fold]
        if draw is None:
            return np.arange(s["n"])
        parts = [s["members"][q] for q in draw if q in s["members"]]
        return np.concatenate(parts) if parts else np.array([], dtype=int)

    # point estimates (all seeds, all rows) and B draws of (question resample, seed resample per side)
    rng = np.random.default_rng(args.seed)
    n_seeds = len(seeds)

    def replicate(draw, seed_pick):
        # {fold: {"seen": {rule: metrics (len(METRICS),)}, "unseen": ...}}, metric averaged over picked seeds
        res = {}
        for fold in folds:
            idx = rows(fold, draw)
            res[fold] = {}
            for name in ("seen", "unseen"):
                pick = seed_pick["control"] if name == "seen" else seed_pick[fold]
                per_seed = evaluate(sides[fold][name], idx)
                res[fold][name] = {rule: (v[pick] if len(v) == n_seeds else v).mean(axis=0)
                                   for rule, v in per_seed.items()}
        return res

    all_seeds = {k: np.arange(n_seeds) for k in ("control", *folds)}
    point = replicate(None, all_seeds)
    draws = []
    for b in range(args.bootstrap_n):
        draw = rng.choice(universe, size=len(universe), replace=True)
        pick = {k: rng.integers(0, n_seeds, size=n_seeds) for k in ("control", *folds)}
        draws.append(replicate(draw, pick))
        if (b + 1) % 100 == 0:
            print(f"bootstrap {b + 1}/{args.bootstrap_n}")

    def collect(fn) -> tuple[float, np.ndarray]:
        return fn(point), np.array([fn(d) for d in draws])

    # 3. seed-aware gap per fold, plus every seed pair's gap
    seed_rows = []
    for fold in folds:
        full = rows(fold, None)
        seen_ps = evaluate(sides[fold]["seen"], full)
        unseen_ps = evaluate(sides[fold]["unseen"], full)
        for rule in GAP_RULES:
            for m, metric in enumerate(METRICS):
                est, d = collect(lambda r: r[fold]["seen"][rule][m] - r[fold]["unseen"][rule][m])
                pairs = np.array([a - b for a in seen_ps[rule][:, m] for b in unseen_ps[rule][:, m]])
                lo, hi = interval(d, alpha)
                lo_adj, hi_adj = interval(d, alpha_adj)
                seed_rows.append({
                    "generator": sides[fold]["generator"], "rule": rule, "metric": metric,
                    "seen": point[fold]["seen"][rule][m], "unseen": point[fold]["unseen"][rule][m],
                    "gap": est, "ci_low": lo, "ci_high": hi, "clear": bool(lo > 0 or hi < 0),
                    "ci_low_bonf": lo_adj, "ci_high_bonf": hi_adj, "clear_bonf": bool(lo_adj > 0 or hi_adj < 0),
                    "seed_pair_gap_min": pairs.min(), "seed_pair_gap_max": pairs.max(),
                    "seed_pairs_same_sign": int(np.sum(np.sign(pairs) == np.sign(est))), "n_seed_pairs": len(pairs)})
    seed_gaps = pd.DataFrame(seed_rows)
    seed_gaps.round(4).to_csv(out / "seed_gaps.csv", index=False)

    # 4. pooled gap: the mean over folds, on the shared draws
    pooled_rows = []
    for rule in GAP_RULES:
        for m, metric in enumerate(METRICS):
            est, d = collect(lambda r: np.mean([r[f]["seen"][rule][m] - r[f]["unseen"][rule][m] for f in folds]))
            lo, hi = interval(d, alpha)
            worst = seed_gaps[(seed_gaps["rule"] == rule) & (seed_gaps["metric"] == metric)].nlargest(1, "gap").iloc[0]
            pooled_rows.append({"rule": rule, "metric": metric, "mean_gap": est, "ci_low": lo, "ci_high": hi,
                                "clear": bool(lo > 0 or hi < 0),
                                "mean_seen": np.mean([point[f]["seen"][rule][m] for f in folds]),
                                "mean_unseen": np.mean([point[f]["unseen"][rule][m] for f in folds]),
                                "worst_generator": worst["generator"], "worst_gap": worst["gap"],
                                "worst_ci_low": worst["ci_low"], "worst_ci_high": worst["ci_high"]})
    pd.DataFrame(pooled_rows).round(4).to_csv(out / "pooled_gap.csv", index=False)

    # 5 and 6. paired comparisons on the unseen generator (same rows, same fold): per fold and pooled
    def paired(a: str, b: str, name: str) -> list[dict]:
        found = []
        for m, metric in enumerate(METRICS):
            for fold in [*folds, "pooled"]:
                if fold == "pooled":
                    fn = lambda r: np.mean([r[f]["unseen"][a][m] - r[f]["unseen"][b][m] for f in folds])
                    generator = "all (mean)"
                else:
                    fn = lambda r, f=fold: r[f]["unseen"][a][m] - r[f]["unseen"][b][m]
                    generator = sides[fold]["generator"]
                est, d = collect(fn)
                lo, hi = interval(d, alpha)
                found.append({"comparison": name, "generator": generator, "metric": metric,
                              "a": a, "b": b, "diff": est, "ci_low": lo, "ci_high": hi,
                              "clear": bool(lo > 0 or hi < 0), "share_a_better": float(np.mean(d > 0))})
        return found

    vs = [r for rule in ("desklib", "meld", "desklib+meld") for r in paired(rule, UNTOUCHED, f"{rule} - untouched")]
    pd.DataFrame(vs).round(4).to_csv(out / "vs_untouched.csv", index=False)
    cmp_ = [r for a, b in COMPARE for r in paired(a, b, f"{a} - {b}")]
    pd.DataFrame(cmp_).round(4).to_csv(out / "rule_compare.csv", index=False)

    forest(seed_gaps, out / "gap_forest.png")

    shipped = seed_gaps[(seed_gaps["rule"] == "desklib+meld") & (seed_gaps["metric"] == "deployed_tpr")]
    print("\ndesklib + MELD, deployed TPR gap (seen - unseen), interval over questions AND seeds:")
    for _, r in shipped.sort_values("gap", ascending=False).iterrows():
        print(f"  {r['generator']:<17} {r['gap']:+.1%} [{r['ci_low']:+.1%}, {r['ci_high']:+.1%}]"
              f"{'  CLEAR' if r['clear'] else ''}{'  (survives Bonferroni)' if r['clear_bonf'] else ''}"
              f"  seed pairs agreeing {r['seed_pairs_same_sign']}/{r['n_seed_pairs']}")
    print(f"\nWrote headline, seed_gaps, pooled_gap, vs_untouched, rule_compare (.csv) and gap_forest.png to {out}")


##  forest plot: the deployed-TPR gap per generator, one row per generator, three rules offset vertically
def forest(seed_gaps: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, muted, surface = "#0b0b0b", "#52514e", "#fcfcfb"
    rules = (("desklib", "#2a78d6", "o"), ("meld", "#eb6834", "s"), ("desklib+meld", "#1baf7a", "D"))
    d = seed_gaps[seed_gaps["metric"] == "deployed_tpr"]
    order = (d[d["rule"] == "desklib+meld"].sort_values("gap")["generator"].tolist())

    fig, ax = plt.subplots(figsize=(7, 0.6 * len(order) + 1.4), facecolor=surface)
    ax.set_facecolor(surface)
    ax.axvline(0, color=muted, linewidth=1)
    for k, (rule, colour, marker) in enumerate(rules):
        sub = d[d["rule"] == rule].set_index("generator").loc[order]
        y = np.arange(len(order)) + (k - 1) * 0.22
        ax.hlines(y, 100 * sub["ci_low"], 100 * sub["ci_high"], color=colour, linewidth=2)
        ax.plot(100 * sub["gap"], y, marker, color=colour, markersize=8, markeredgecolor=surface,
                markeredgewidth=1.5, linestyle="none", label="meld (single seeds)" if rule == "meld" else rule)
    ax.set_yticks(np.arange(len(order)), order, color=ink)
    ax.set_xlabel("Deployed TPR lost when the generator is held out (points; >0 = worse unseen)", color=ink)
    ax.set_title("Cost of an unseen generator (95% CI, questions + seeds)", color=ink, loc="left")
    ax.tick_params(colors=muted)
    ax.grid(axis="x", color="#e6e5e1", linewidth=0.8)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(muted)
    ax.legend(frameon=False, loc="lower right", labelcolor=ink)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
