"""
E7: picks the final desklib + MELD pair on val only. Test is never read here; the chosen pair then goes through
analyse_ensemble.py once, for the report.

Every desklib candidate is paired with every MELD candidate, seeds paired by number (a single-seed MELD, e.g. the
3-seed soup "@1", is paired with each desklib seed). Each pair is the 50/50 log-odds average, as in
analyse_ensemble.py, on answers of >= --min-words words.

The rule, set before the run:
  1. a candidate is dropped if any of its seeds has val AUROC under 0.90 on its own (the plan's failed-run rule,
     the part that can be checked from the scores file)
  2. pairs are ranked by the pair's val AUROC, mean over seeds; the top pair is the final combination
  3. near-ties: among pairs within 0.001 of the best val AUROC (about one seed's spread), the highest-ranked pair
     with no setting rejected by its own experiment wins (REJECTED below); if every such pair has one, the top pair
  4. val TPR at exactly 1% FPR is reported beside it but does not decide: it rests on about 7 human answers

Writes val_ranking.csv into --out and prints the analyse_ensemble.py command for the winner.

    python pick_final.py --out outputs/analysis/E7
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from scipy.special import expit
from sklearn.metrics import roc_auc_score

import harness
import metrics
from analyse_ensemble import load_model

DESKLIB = [
    "desklib-lora-confirm-qkvf-r64-e8",               # confirm runs, the reference so far
    "desklib-lora-qkvf-r64-e8-extended",              # reference rerun (3 Nov)
    "desklib-lora-qkvf-r64-e8-mohlerneg-extended",    # E4a
    "desklib-lora-qkvf-r64-e8-hardai-extended",       # E5a
]
MELD = [
    "meld-lora-extended",                                              # Sep release
    "meld-lora-lr1e-4-qkvo-r32-e3-extended",                           # E2 rank 32
    "meld-lora-sw-lr1e-4-qkvo-r16-e3-revddfc9c78-extended",            # E3 Oct release
    "meld-lora-lr1e-4-qkvo-r16-e3-revddfc9c78-pauroc-extended",        # Oct, epoch by partial AUROC
    "meld-lora-lr1e-4-qkvo-r16-e3-mohlerneg-extended",                 # E4b
    "meld-lora-lr1e-4-qkvo-r16-e3-revddfc9c78-pauroc-hardai-extended", # E5b
    "meld-lora-soup-pair",                                             # E1 pair soups (Sep)
    "meld-lora-soup-all@1",                                            # E1 3-seed soup (Sep)
]
FAILED_VAL_AUROC = 0.90
TIE = 0.001
# settings that failed their own experiment's rule (desklib-meld-experiment-results.md); they still rank, but lose
# near-ties
REJECTED = {
    "meld-lora-lr1e-4-qkvo-r32-e3-extended": "E2: val AUROC below rank 16",
    "desklib-lora-qkvf-r64-e8-mohlerneg-extended": "E4a: Mohler val false flags not lower",
    "meld-lora-lr1e-4-qkvo-r16-e3-mohlerneg-extended": "E4b: Mohler val false flags not lower",
    "meld-lora-lr1e-4-qkvo-r16-e3-revddfc9c78-pauroc-extended": "epoch by partial AUROC not adopted",
    "desklib-lora-qkvf-r64-e8-hardai-extended": "E5a: spliced-25 unchanged on val",
}


def parse(spec: str, seeds: list[int]) -> tuple[str, list[int]]:
    base, _, s = spec.partition("@")
    return base, ([int(x) for x in s.split(",")] if s else seeds)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desklib", action="append", help="desklib run-name base[@seeds] (repeatable; default: all)")
    ap.add_argument("--meld", action="append", help="MELD run-name base[@seeds] (repeatable; default: all)")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--min-words", type=int, default=harness.MIN_WORDS)
    ap.add_argument("--target-fpr", type=float, default=metrics.HEADLINE_FPR)
    ap.add_argument("--out", default="outputs/analysis/E7")
    args = ap.parse_args()

    seeds = [int(s) for s in args.seeds.split(",") if s]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    meta = harness.load_meta().set_index("answer_id")[["n_words"]]

    # val rows only, from here on
    def load(spec):
        base, s = parse(spec, seeds)
        z = load_model(base, s)
        z = z[z["split"] == "val"].join(meta, how="inner")
        return base, s, z[z["n_words"] >= args.min_words]

    families = {"desklib": [load(c) for c in args.desklib or DESKLIB],
                "meld": [load(c) for c in args.meld or MELD]}
    ref = families["desklib"][0][2]
    y, index = ref["y_true"], ref.index

    singles, failed = {}, set()
    for family, cands in families.items():
        for base, s, z in cands:
            if not index.isin(z.index).all():
                raise SystemExit(f"{base} does not cover every val answer")
            for seed in s:
                auc = roc_auc_score(y, z.loc[index, seed])
                singles[(base, seed)] = auc
                if auc < FAILED_VAL_AUROC:
                    failed.add(base)
                    print(f"dropped {base}: seed {seed} val AUROC {auc:.3f} (failed run)")

    rows = []
    for d_base, d_seeds, D in families["desklib"]:
        for m_base, m_seeds, M in families["meld"]:
            if {d_base, m_base} & failed:
                continue
            pairs = list(zip(d_seeds, m_seeds)) if len(m_seeds) > 1 else [(s, m_seeds[0]) for s in d_seeds]
            per_seed = []
            for sd, sm in pairs:
                z = 0.5 * D.loc[index, sd] + 0.5 * M.loc[index, sm]
                per_seed.append({"auroc": roc_auc_score(y, z),
                                 "tpr": metrics.oracle_tpr_at_fpr(y, expit(z), args.target_fpr)})
            p = pd.DataFrame(per_seed)
            rows.append({"desklib": d_base, "meld": m_base, "n_seeds": len(pairs),
                         "pair_val_auroc": p["auroc"].mean(), "pair_val_auroc_sd": p["auroc"].std(),
                         "pair_val_tpr_at_1pct": p["tpr"].mean(),
                         "desklib_val_auroc": sum(singles[(d_base, s)] for s, _ in pairs) / len(pairs),
                         "meld_val_auroc": sum(singles[(m_base, s)] for _, s in pairs) / len(pairs)})

    ranking = pd.DataFrame(rows).sort_values("pair_val_auroc", ascending=False).reset_index(drop=True)
    ranking["rejected"] = ["; ".join(REJECTED[b] for b in (d, m) if b in REJECTED)
                           for d, m in zip(ranking["desklib"], ranking["meld"])]
    ranking["near_tie"] = ranking["pair_val_auroc"] >= ranking["pair_val_auroc"].iloc[0] - TIE
    ranking.round(4).to_csv(out / "val_ranking.csv", index=False)
    pd.set_option("display.width", 250, "display.max_colwidth", 60)
    print(ranking.round(4).to_string())

    clean = ranking[ranking["near_tie"] & (ranking["rejected"] == "")]
    best = clean.iloc[0] if len(clean) else ranking.iloc[0]
    print(f"\nfinal pair (val AUROC {best.pair_val_auroc:.4f}): {best.desklib} + {best.meld}")
    meld_spec = next(c for c in (args.meld or MELD) if c.partition("@")[0] == best.meld)
    print("report it once on test with:")
    print(f"  python analyse_ensemble.py --a {best.desklib} --b {meld_spec} --out {out}")


if __name__ == "__main__":
    main()
