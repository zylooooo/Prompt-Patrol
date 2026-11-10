"""
Compares one changed setting with its control: new run minus old run, on val and test, with 95% intervals that
resample whole questions. The paired tables of the experiment results (E2 rank 32, E3 Oct release, E4 weights) come
from here.

Models are run-name bases as in analyse_ensemble.py (run <base>-s<seed>), paired by seed number. Each comparison is
made three ways, because a gain can be seed noise that disappears once seeds are averaged:
  single model            new seed s against old seed s
  2 seeds averaged        new seeds s and s+1 averaged, against the same for old
  inside the pair         new averaged 50/50 with --partner, against old with the same partner

Metrics: AUROC and TPR at exactly 1% FPR on val and test, TPR at the frozen val threshold on test, and the students
wrongly flagged in each dataset at each model's own frozen threshold. Writes compare.csv into --out.

    python compare_runs.py --new meld-lora-sw-lr1e-4-qkvo-r16-e3-revddfc9c78-extended --old meld-lora-extended \\
        --partner desklib-lora-confirm-qkvf-r64-e8 --out outputs/analysis/E3
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit

import harness
import metrics
from analyse_ensemble import load_model


##  one paired difference, new minus old, over the given rows
def diff(frame, rows, za, zb, ta, tb, metric, n):
    r = metrics.paired_bootstrap_diff(frame.loc[rows, "y_true"].to_numpy(),
                                      [expit(z[rows]).to_numpy() for z in za], [expit(z[rows]).to_numpy() for z in zb],
                                      ta, tb, frame.loc[rows, "question_id"].to_numpy(), harness.PAIR_METRICS[metric],
                                      n=n)
    return {k: r[k] for k in ("diff", "ci_low", "ci_high")} | {"real_gap": bool(r["ci_low"] > 0 or r["ci_high"] < 0)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new", required=True, help="run-name base of the changed setting")
    ap.add_argument("--old", required=True, help="run-name base of its control")
    ap.add_argument("--partner", required=True, help="run-name base of the other model of the pair")
    ap.add_argument("--seeds", default="1,2,3", help="seeds, paired by number")
    ap.add_argument("--min-words", type=int, default=harness.MIN_WORDS)
    ap.add_argument("--target-fpr", type=float, default=metrics.HEADLINE_FPR)
    ap.add_argument("--bootstrap-n", type=int, default=metrics.BOOTSTRAP_N)
    ap.add_argument("--out", required=True, help="folder for compare.csv")
    args = ap.parse_args()

    seeds = [int(s) for s in args.seeds.split(",") if s]
    nxt = {s: seeds[(i + 1) % len(seeds)] for i, s in enumerate(seeds)}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    NEW, OLD, P = (load_model(b, seeds) for b in (args.new, args.old, args.partner))
    frame = OLD[["split", "question_id", "y_true"]].join(
        harness.load_meta().set_index("answer_id")[["n_words", "dataset"]], how="inner")
    frame = frame[frame["n_words"] >= args.min_words]
    for name, Z in (("--new", NEW), ("--partner", P)):
        if not frame.index.isin(Z.index).all():
            raise SystemExit(f"{name} does not cover every answer that --old does")
    NEW, OLD, P = NEW.loc[frame.index], OLD.loc[frame.index], P.loc[frame.index]
    val = frame["split"] == "val"

    comparisons = {
        "single model": (lambda s: NEW[s], lambda s: OLD[s]),
        "2 seeds averaged": (lambda s: 0.5 * NEW[s] + 0.5 * NEW[nxt[s]], lambda s: 0.5 * OLD[s] + 0.5 * OLD[nxt[s]]),
        "inside the pair": (lambda s: 0.5 * NEW[s] + 0.5 * P[s], lambda s: 0.5 * OLD[s] + 0.5 * P[s]),
    }
    rows = []
    for name, (fa, fb) in comparisons.items():
        za, zb = [fa(s) for s in seeds], [fb(s) for s in seeds]
        ta, tb = ([metrics.threshold_at_fpr(frame.loc[val, "y_true"], expit(z[val]), args.target_fpr) for z in zs]
                  for zs in (za, zb))
        for split in ("val", "test"):
            m = frame["split"] == split
            for metric in ["auroc", "oracle_tpr_at_fpr_0.01"] + (["deployed_tpr"] if split == "test" else []):
                rows.append({"comparison": name, "split": split, "metric": metric, "group": "all",
                             **diff(frame, m, za, zb, ta, tb, metric, args.bootstrap_n)})
            # students wrongly flagged per dataset; the rates themselves too, since a few students move them a lot
            for d in sorted(frame.loc[m, "dataset"].unique()):
                h = m & (frame["y_true"] == 0) & (frame["dataset"] == d)
                rows.append({"comparison": name, "split": split, "metric": "deployed_fpr", "group": d,
                             "n": int(h.sum()),
                             "new": np.mean([(expit(z[h]) >= t).mean() for z, t in zip(za, ta)]),
                             "old": np.mean([(expit(z[h]) >= t).mean() for z, t in zip(zb, tb)]),
                             **diff(frame, h, za, zb, ta, tb, "deployed_fpr", args.bootstrap_n)})
    table = pd.DataFrame(rows)
    table.round(4).to_csv(out / "compare.csv", index=False)
    pd.set_option("display.width", 250)
    print(f"{args.new} minus {args.old} (95% interval):")
    print(table.round(4).to_string(index=False))
    print(f"\nwrote {out}/compare.csv")


if __name__ == "__main__":
    main()
