"""
Analyses a two-model combination (e.g. desklib + MELD) from the runs' scores files, with the controls
that say where its gain comes from, and writes every table and figure to one folder.

Models are run-name bases: run <base>-s<seed> for each seed. Each model's calibrated score is turned
back into log-odds, combinations average log-odds, and every rule gets its threshold fitted on val at
1% FPR (answers of >= --min-words words), frozen, then test scored once. Nothing is fitted on test.

What it writes into --out:
  rules.csv / rules_by_seed.csv   each rule on val and test: AUROC, TPR at exactly 1% FPR, TPR and FPR at the
                                  frozen threshold, and the same with a stricter threshold that keeps EVERY
                                  dataset's val false-flag rate at or under 1%
  paired.csv                      A+B minus each other rule, 95% interval resampling whole questions
  weight_curve.csv/.png           the share given to B, from 0 to 1: val and test
  slices.csv, slices.png          AI caught per slice, dataset and answer length at each rule's threshold, val
                                  and test in the table, test in the figure
  dataset_fpr.csv/.png            students wrongly flagged per dataset, val and test
  roc_low_fpr.csv/.png            TPR against FPR up to 5%, mean over seeds
  seed_spread.png                 TPR at exactly 1% FPR, every seed of every rule
  agreement.csv                   rank correlation of A vs B, and of each model's seed pairs

Rules: A, B, A+B (50/50), and two controls - A's seed s averaged with its seed s+1, and the same for B.
A combination that only matches its own stronger member's seed pair adds averaging, not new evidence.
--extra adds any other run, e.g. a MELD soup, as its own rule.

    python analyse_ensemble.py --a desklib-lora-confirm-qkvf-r64-e8 --b meld-lora-extended \\
        --out outputs/analysis/desklib-meld
    python analyse_ensemble.py --a desklib-lora-confirm-qkvf-r64-e8 --b meld-lora-extended \\
        --extra "soup=meld-lora-soup-pair" --extra "soup of 3=meld-lora-soup-all@1" --out outputs/analysis/soups
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd
from scipy.special import expit, logit
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score, roc_curve

import harness
import metrics
from ensemble_scores import find_scores, tuned_rows

EPS = 1e-7
WEIGHTS = np.round(np.linspace(0, 1, 11), 1)
LENGTH_BINS = [9, 20, 40, 80, 10_000]
LENGTH_LABELS = ["10-20", "21-40", "41-80", "81+"]
FPR_GRID = np.geomspace(1e-3, 0.05, 60)
# categorical slots in fixed order (validated for colour-vision deficiency on the light surface);
# rules keep their colour whatever else is plotted
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6", "#008300", "#e34948"]
SURFACE, INK, MUTED = "#fcfcfb", "#1f1f1e", "#6b6a64"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "text.color": INK, "axes.grid": True, "grid.color": "#e4e3de", "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 2, "lines.markersize": 7,
    "legend.frameon": False,
})


class Rule:
    """One way to score answers: a function of the seed giving log-odds for every row, and its seeds."""

    def __init__(self, name, fn, seeds, color, control=False):
        self.name, self.fn, self.seeds, self.color, self.control = name, fn, list(seeds), color, control

    @property
    def style(self):
        return {"color": self.color, "linestyle": "--" if self.control else "-",
                "markerfacecolor": SURFACE if self.control else self.color}


##  every seed of one run-name base, as log-odds in one table
##  returns a frame indexed by answer_id with one column per seed, plus split, question_id and y_true
def load_model(base: str, seeds: list[int]) -> pd.DataFrame:
    out = None
    for seed in seeds:
        _, rows = tuned_rows(find_scores(f"{base}-s{seed}"))
        rows = rows.set_index("answer_id")
        z = logit(np.clip(rows["y_prob"], EPS, 1 - EPS)).rename(seed)
        out = rows[["split", "question_id", "y_true"]].join(z) if out is None else out.join(z, how="inner")
    if out is None:
        raise SystemExit(f"no seeds given for {base}")
    return out


##  a rule on one seed: threshold at 1% FPR on val, frozen, then test; also the strict threshold that keeps
##  every dataset's val false-flag rate within budget
def score_rule(z: pd.Series, frame: pd.DataFrame, target_fpr: float) -> dict:
    val, test = frame["split"] == "val", frame["split"] == "test"
    yv, yt, pv, pt = frame.loc[val, "y_true"], frame.loc[test, "y_true"], expit(z[val]), expit(z[test])
    threshold = metrics.threshold_at_fpr(yv, pv, target_fpr)
    strict = max(metrics.threshold_at_fpr(yv[frame.loc[val, "dataset"] == d], pv[frame.loc[val, "dataset"] == d],
                                          target_fpr) for d in frame.loc[val, "dataset"].unique())
    out = {"val_auroc": roc_auc_score(yv, z[val]), "val_tpr_at_1pct": metrics.oracle_tpr_at_fpr(yv, pv, target_fpr),
           "auroc": roc_auc_score(yt, z[test]), "tpr_at_1pct": metrics.oracle_tpr_at_fpr(yt, pt, target_fpr),
           "threshold": threshold}
    for tag, thr in (("", threshold), ("strict_", strict)):
        flagged = pt >= thr
        out[f"{tag}deployed_tpr"] = float(flagged[yt == 1].mean())
        out[f"{tag}deployed_fpr"] = float(flagged[yt == 0].mean())
    return out


def flags(z: pd.Series, frame: pd.DataFrame, target_fpr: float) -> pd.Series:
    """Every val and test row flagged or not, at the rule's frozen val threshold."""
    val = frame["split"] == "val"
    return expit(z) >= metrics.threshold_at_fpr(frame.loc[val, "y_true"], expit(z[val]), target_fpr)


def save(fig, out: Path, name: str):
    fig.savefig(out / name, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_weight_curve(curve: pd.DataFrame, a: str, b: str, out: Path):
    fig, (left, right) = plt.subplots(1, 2, figsize=(10, 3.8))
    for split, color, marker in (("val", PALETTE[0], "o"), ("test", PALETTE[1], "s")):
        g = curve[curve["split"] == split]
        left.plot(g["weight_b"], g["tpr_at_1pct"], marker=marker, color=color, label=split)
        right.plot(g["weight_b"], g["auroc"], marker=marker, color=color, label=split)
    left.set(xlabel=f"share given to {b}", ylabel="AI caught at exactly 1% FPR", title="TPR at 1% FPR")
    right.set(xlabel=f"share given to {b}", ylabel="AUROC", title="AUROC")
    for ax in (left, right):
        ax.axvline(0.5, color=MUTED, linewidth=1, linestyle=":")
        ax.legend()
    fig.suptitle(f"{a} + {b}: mean over seeds. Pick the weight from val only", fontsize=10, color=MUTED)
    save(fig, out, "weight_curve.png")


def plot_grouped_bars(table: pd.DataFrame, rules: list[Rule], value: str, groups: list[str], ax, xlabel):
    """Horizontal bars, one per rule within each group, with a surface gap between neighbours."""
    height = 0.8 / len(rules)
    for i, rule in enumerate(rules):
        sub = table[table["rule"] == rule.name].set_index("group").reindex(groups)
        y = np.arange(len(groups)) + (i - (len(rules) - 1) / 2) * height
        ax.barh(y, sub[value], height=height, color=rule.color, edgecolor=SURFACE, linewidth=1.5,
                hatch="//" if rule.control else None, label=rule.name)
    ax.set_yticks(np.arange(len(groups)), groups)
    ax.invert_yaxis()
    ax.set(xlabel=xlabel)
    ax.grid(axis="y", visible=False)


def legend_below(fig, ax, n):
    """One legend for a multi-panel figure, under the panels so it never covers a bar."""
    fig.legend(*ax.get_legend_handles_labels(), loc="lower center", ncol=min(n, 4), fontsize=9,
               bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=(0, 0.08, 1, 1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", default="desklib-lora-confirm-qkvf-r64-e8", help="run-name base of model A")
    ap.add_argument("--b", default="meld-lora-extended",
                    help="run-name base of model B; base@seed pairs that one seed with every seed of A (its seed-pair "
                         "control is then the same model twice)")
    ap.add_argument("--seeds", default="1,2,3", help="seeds of A and B, paired by number")
    ap.add_argument("--extra", action="append", default=[],
                    help='another rule, "label=run-name base[@seeds]", e.g. "soup=meld-lora-soup-pair" (repeatable)')
    ap.add_argument("--min-words", type=int, default=harness.MIN_WORDS)
    ap.add_argument("--target-fpr", type=float, default=metrics.HEADLINE_FPR)
    ap.add_argument("--bootstrap-n", type=int, default=metrics.BOOTSTRAP_N)
    ap.add_argument("--out", default="outputs/analysis/ensemble", help="folder for the tables and figures")
    args = ap.parse_args()

    seeds = [int(s) for s in args.seeds.split(",") if s]
    nxt = {s: seeds[(i + 1) % len(seeds)] for i, s in enumerate(seeds)}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    b_base, _, b_seed = args.b.partition("@")
    if b_seed:  # one seed of B (e.g. the 3-seed soup) paired with every seed of A
        B = load_model(b_base, [int(b_seed)])
        B = B[["split", "question_id", "y_true"]].join(pd.DataFrame({s: B[int(b_seed)] for s in seeds}))
    else:
        B = load_model(b_base, seeds)
    A = load_model(args.a, seeds)
    frame = A[["split", "question_id", "y_true"]].join(
        harness.load_meta().set_index("answer_id")[["n_words", "slice", "dataset"]], how="inner")
    frame = frame[frame["n_words"] >= args.min_words]
    frame["length"] = pd.cut(frame["n_words"], LENGTH_BINS, labels=LENGTH_LABELS)
    if not B.index.isin(frame.index).sum() == len(frame):
        raise SystemExit(f"{args.b} does not cover the same answers as {args.a}")
    A, B = A.loc[frame.index], B.loc[frame.index]

    a_name, b_name = args.a.removesuffix("-extended"), b_base.removesuffix("-extended")
    rules = [
        Rule(a_name, lambda s: A[s], seeds, PALETTE[0]),
        Rule(b_name, lambda s: B[s], seeds, PALETTE[1]),
        Rule("A+B 50/50", lambda s: 0.5 * A[s] + 0.5 * B[s], seeds, PALETTE[2]),
        Rule("control: A seed pair", lambda s: 0.5 * A[s] + 0.5 * A[nxt[s]], seeds, PALETTE[0], control=True),
        Rule("control: B seed pair", lambda s: 0.5 * B[s] + 0.5 * B[nxt[s]], seeds, PALETTE[1], control=True),
    ]
    for i, spec in enumerate(args.extra):
        label, _, target = spec.partition("=")
        base, _, extra_seeds = target.partition("@")
        extra_seeds = [int(s) for s in extra_seeds.split(",")] if extra_seeds else seeds
        Z = load_model(base, extra_seeds).reindex(frame.index)
        if Z.isna().any().any():
            raise SystemExit(f"{base} does not cover every answer that {args.a} does")
        rules.append(Rule(label, lambda s, Z=Z: Z[s], extra_seeds, PALETTE[3 + i % 5]))

    # 1. every rule, every seed
    by_seed = pd.DataFrame([{"rule": r.name, "seed": s, **score_rule(r.fn(s), frame, args.target_fpr)}
                            for r in rules for s in r.seeds])
    by_seed.to_csv(out / "rules_by_seed.csv", index=False)
    summary = by_seed.drop(columns="seed").groupby("rule", sort=False).agg(["mean", "std"])
    summary.columns = [f"{m}_{s}" for m, s in summary.columns]
    summary.insert(0, "n_seeds", by_seed.groupby("rule", sort=False).size())
    summary.round(4).to_csv(out / "rules.csv")
    pd.set_option("display.width", 250)
    print(summary[["n_seeds", "val_auroc_mean", "val_tpr_at_1pct_mean", "auroc_mean", "tpr_at_1pct_mean",
                   "tpr_at_1pct_std", "deployed_tpr_mean", "deployed_fpr_mean", "strict_deployed_tpr_mean",
                   "strict_deployed_fpr_mean"]].round(3).to_string())

    # 2. A+B against every other rule, whole questions resampled
    test = frame["split"] == "test"
    def runs(rule):
        zs = [rule.fn(s) for s in rule.seeds]
        val = frame["split"] == "val"
        return ([expit(z[test]).to_numpy() for z in zs],
                [metrics.threshold_at_fpr(frame.loc[val, "y_true"], expit(z[val]), args.target_fpr) for z in zs])
    combo = runs(rules[2])
    paired = []
    for other in rules[:2] + rules[3:]:
        theirs = runs(other)
        for metric in ("auroc", "oracle_tpr_at_fpr_0.01", "deployed_tpr"):
            r = metrics.paired_bootstrap_diff(frame.loc[test, "y_true"].to_numpy(), combo[0], theirs[0], combo[1],
                                              theirs[1], frame.loc[test, "question_id"].to_numpy(),
                                              harness.PAIR_METRICS[metric], n=args.bootstrap_n)
            paired.append({"vs": other.name, "metric": metric, **{k: r[k] for k in ("diff", "ci_low", "ci_high")},
                           "real_gap": bool(r["ci_low"] > 0 or r["ci_high"] < 0)})
    paired = pd.DataFrame(paired)
    paired.round(4).to_csv(out / "paired.csv", index=False)
    print("\nA+B 50/50 minus each rule (95% interval):")
    print(paired.round(4).to_string(index=False))

    # 3. the weight on B
    curve = []
    for w in WEIGHTS:
        for s in seeds:
            r = score_rule((1 - w) * A[s] + w * B[s], frame, args.target_fpr)
            for split, prefix in (("val", "val_"), ("test", "")):
                curve.append({"weight_b": w, "seed": s, "split": split, "auroc": r[f"{prefix}auroc"],
                              "tpr_at_1pct": r[f"{prefix}tpr_at_1pct"]})
    curve = pd.DataFrame(curve).groupby(["weight_b", "split"], as_index=False)[["auroc", "tpr_at_1pct"]].mean()
    curve.round(4).to_csv(out / "weight_curve.csv", index=False)
    plot_weight_curve(curve, a_name, b_name, out)

    # 4. where each rule catches AI, and whom it wrongly flags
    main_rules = [r for r in rules if not r.control]
    slice_rows, fpr_rows = [], []
    for rule in main_rules:
        flagged = pd.concat([flags(rule.fn(s), frame, args.target_fpr) for s in rule.seeds], axis=1).mean(axis=1)
        f = frame.assign(flagged=flagged)
        for split in ("val", "test"):
            ai = f[(f["split"] == split) & (f["y_true"] == 1)]
            for by in ("slice", "dataset", "length"):
                for group, g in ai.groupby(by, observed=True):
                    slice_rows.append({"rule": rule.name, "split": split, "by": by, "group": str(group),
                                       "n": len(g), "tpr": g["flagged"].mean()})
        human = f[f["y_true"] == 0]
        for (split, dataset), g in human.groupby(["split", "dataset"]):
            fpr_rows.append({"rule": rule.name, "split": split, "group": dataset, "n_human": len(g),
                             "wrongly_flagged": int(round(g["flagged"].sum())), "fpr": g["flagged"].mean()})
    slices, dataset_fpr = pd.DataFrame(slice_rows), pd.DataFrame(fpr_rows)
    slices.round(4).to_csv(out / "slices.csv", index=False)
    dataset_fpr.round(4).to_csv(out / "dataset_fpr.csv", index=False)

    panels = [("slice", "Answer type"), ("dataset", "Dataset"), ("length", "Answer length (words)")]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), gridspec_kw={"width_ratios": [1.6, 1, 1]})
    for ax, (by, title) in zip(axes, panels):
        t = slices[(slices["split"] == "test") & (slices["by"] == by) & (slices["group"] != "human")]
        groups = list(dict.fromkeys(t["group"]))
        plot_grouped_bars(t, main_rules, "tpr", groups, ax, "AI caught at the val threshold")
        ax.set(title=title, xlim=(0, 1))
    legend_below(fig, axes[0], len(main_rules))
    save(fig, out, "slices.png")

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharex=True)
    for ax, split in zip(axes, ("val", "test")):
        t = dataset_fpr[dataset_fpr["split"] == split]
        plot_grouped_bars(t, main_rules, "fpr", sorted(t["group"].unique()), ax, "students wrongly flagged")
        ax.axvline(args.target_fpr, color=MUTED, linestyle=":", linewidth=1)
        ax.set(title=split)
        ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=1))
    fig.suptitle(f"Students wrongly flagged per dataset. Dotted line: the {args.target_fpr:.0%} budget, "
                 "which the threshold meets on all datasets pooled", fontsize=10, color=MUTED)
    legend_below(fig, axes[0], len(main_rules))
    save(fig, out, "dataset_fpr.png")

    # 5. the low-FPR region of the test ROC, and the seed spread
    roc_rows = []
    for rule in rules:
        for s in rule.seeds:
            fpr, tpr, _ = roc_curve(frame.loc[test, "y_true"], rule.fn(s)[test])
            roc_rows += [{"rule": rule.name, "seed": s, "fpr": x, "tpr": y}
                         for x, y in zip(FPR_GRID, np.interp(FPR_GRID, fpr, tpr))]
    roc = pd.DataFrame(roc_rows)
    roc.round(5).to_csv(out / "roc_low_fpr.csv", index=False)
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for rule in rules:
        g = roc[roc["rule"] == rule.name].groupby("fpr")["tpr"].mean()
        ax.plot(g.index, g.values, label=rule.name, **rule.style)
    ax.axvline(args.target_fpr, color=MUTED, linestyle=":", linewidth=1)
    ax.set(xscale="log", xlabel="false positive rate (test, log scale)", ylabel="AI caught (mean over seeds)",
           title="Test ROC, low false-positive region", ylim=(0, 1))
    ax.legend(fontsize=8, loc="lower right")
    save(fig, out, "roc_low_fpr.png")

    fig, ax = plt.subplots(figsize=(7, 0.5 * len(rules) + 1.2))
    for i, rule in enumerate(rules):
        v = by_seed.loc[by_seed["rule"] == rule.name, "tpr_at_1pct"]
        ax.scatter(v, [i] * len(v), s=60, color=rule.color, edgecolor=rule.color,
                   facecolor=SURFACE if rule.control else rule.color, linewidth=2, zorder=3)
        ax.plot([v.mean()] * 2, [i - 0.3, i + 0.3], color=INK, linewidth=2)
    ax.set_yticks(range(len(rules)), [r.name for r in rules])
    ax.invert_yaxis()
    ax.set(xlabel="AI caught at exactly 1% FPR, test (dots: seeds; bar: mean)", title="How much each seed moves it")
    ax.grid(axis="y", visible=False)
    save(fig, out, "seed_spread.png")

    # 6. how differently the models rank answers (low agreement is what a combination needs)
    agree = []
    for s in seeds:
        t = frame[test]
        for label in ("human", "AI"):
            m = (t["y_true"] == (label == "AI")).to_numpy()
            idx = t.index[m]
            agree += [{"seed": s, "answers": label, "pair": pair, "spearman": spearmanr(x[idx], y[idx])[0]}
                      for pair, x, y in ((f"A vs B", A[s], B[s]), ("A seed pair", A[s], A[nxt[s]]),
                                         ("B seed pair", B[s], B[nxt[s]]))]
    agree = pd.DataFrame(agree)
    agree.round(3).to_csv(out / "agreement.csv", index=False)
    print("\nrank agreement (Spearman, test, mean over seeds):")
    print(agree.groupby(["pair", "answers"])["spearman"].mean().round(2).unstack().to_string())
    print(f"\nwrote tables and figures to {out}/")


if __name__ == "__main__":
    main()
