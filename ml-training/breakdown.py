## where detection degrades (PP-184): the test results of one model, broken down by answer length in tokens, paraphrase
## strength, share of AI text (spliced and edited answers) and the quality tier the AI answer was written at.
## each axis gets one table and one plot, at the thresholds fitted on validation for 0.1%, 1% and 5% FPR.
##
##      python breakdown.py                       # the final model, desklib + MELD averaged 50/50, scores fetched from DagsHub
##      python breakdown.py --run NAME=GLOB       # any scores files already on disk, e.g. --run radar="outputs/radar-*_scores.parquet"
##      python breakdown.py --no-log              # write the tables and plots locally only

from __future__ import annotations

import argparse
import glob
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit, logit

import harness
import metrics
from scores import COLUMNS, OUT_DIRECTORY, load_scores, validate

TARGET_FPRS = (0.001, 0.01, 0.05)
TOKEN_EDGES = (16, 24, 32, 48, 64)  # desklib tokens; each bin holds 277 to 804 test answers of 10+ words
EDIT_EDGES = (0.2, 0.4)  # share of words a human changed in an edited answer
FINAL_PAIR = ("desklib-lora-confirm-qkvf-r64-e8", "meld-lora-extended")
FINAL_NAME = "desklib+meld"
SEEDS = (1, 2, 3)
EXPERIMENT = "E3-reliability"
OUT = OUT_DIRECTORY / "breakdown"
SPLITS = harness.SPLITS_DIR

##  downloads each run's per-answer scores file from the predictions/ folder of its DagsHub run, unless already on disk
##
##  names:  MLflow run names, e.g. meld-lora-extended-s1
##  dest:   folder to save them in
def fetch_scores(names: list[str], dest: Path) -> list[Path]:
    import mlflow
    from tracking import setup_mlflow

    setup_mlflow()
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        path = dest / f"{name}_scores.parquet"
        if not path.exists():
            runs = mlflow.search_runs(search_all_experiments=True, order_by=["attributes.start_time DESC"],
                                      filter_string=f"attributes.run_name = '{name}' and attributes.status = 'FINISHED'")
            if runs.empty:
                raise SystemExit(f"no finished DagsHub run named {name}")
            got = mlflow.artifacts.download_artifacts(run_id=runs.run_id.iloc[0], artifact_path=f"predictions/{path.name}",
                                                      dst_path=str(dest / "download"))
            Path(got).rename(path)
        paths.append(path)
    return paths

##  the final model's scores: each tuned model's calibrated probability turned back into a logit, the two averaged with equal
##  weight, seed k of one model paired with seed k of the other (the rule in the final report, Section 3.2.9)
def average_pair(a_paths: list[Path], b_paths: list[Path], name: str) -> pd.DataFrame:
    def tuned(path):
        s = load_scores(path)
        return s[~s.model.str.endswith("-untouched")].set_index(["split", "answer_id"])

    parts = []
    for seed, (pa, pb) in enumerate(zip(a_paths, b_paths), start=1):
        a, b = tuned(pa), tuned(pb)
        b = b.loc[a.index]
        z = (logit(np.clip(a.y_prob.values, 1e-7, 1 - 1e-7)) + logit(np.clip(b.y_prob.values, 1e-7, 1 - 1e-7))) / 2
        parts.append(validate(pd.DataFrame({"run_id": f"{name}-s{seed}", "model": name, "seed": seed,
                                            "split": a.index.get_level_values(0), "answer_id": a.index.get_level_values(1),
                                            "question_id": a.question_id.values, "y_true": a.y_true.astype(np.int64).values,
                                            "logit": z, "y_prob": expit(z)})[COLUMNS]))
    return pd.concat(parts, ignore_index=True)

##  per-answer details the breakdowns need beyond the harness metadata: quality tier, token count, the AI share of a spliced
##  answer and how much of an edited answer a human changed
def answer_details() -> pd.DataFrame:
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer
    from eval_desklib_zeroshot import DESKLIB_REPO

    rows = pd.concat([pd.read_parquet(SPLITS / f"{harness.CORPUS}-{s}.parquet") for s in ("val", "test")])
    tokenizer = AutoTokenizer.from_pretrained(snapshot_download(DESKLIB_REPO))
    rows["n_tokens"] = [len(ids) for ids in tokenizer(rows.answer.astype(str).tolist(), add_special_tokens=False)["input_ids"]]
    spliced = pd.read_parquet(SPLITS / "v0.1-spliced.parquet", columns=["answer_id", "ai_fraction"])
    edited = pd.read_parquet(SPLITS / "v0.1-human_edited.parquet", columns=["answer_id", "edit_distance"])
    rows = rows.merge(spliced, on="answer_id", how="left").merge(edited, on="answer_id", how="left")
    return rows.set_index("answer_id")[["tier", "n_tokens", "ai_fraction", "edit_distance"]]

def token_bin(n: int) -> str:
    if n < TOKEN_EDGES[0]:
        return f"under {TOKEN_EDGES[0]} tokens"
    for lo, hi in zip(TOKEN_EDGES, TOKEN_EDGES[1:]):
        if n < hi:
            return f"{lo}-{hi - 1} tokens"
    return f"{TOKEN_EDGES[-1]}+ tokens"

def edit_bin(share: float) -> str:
    lo, hi = EDIT_EDGES
    return f"edited, under {lo:.0%} changed" if share < lo else f"edited, {lo:.0%}-{hi:.0%} changed" if share < hi \
        else f"edited, {hi:.0%}+ changed"

##  each axis maps a test answer to its group, or None to leave it out. the order of `groups` is the order in tables and plots
AXES = {
    "length": {
        "title": "By answer length (desklib tokens)",
        "group": lambda r: token_bin(r.n_tokens),
        "groups": [token_bin(0)] + [token_bin(e) for e in TOKEN_EDGES],
    },
    "paraphrase": {
        "title": "By paraphrase strength",
        "group": lambda r: {"raw-ai": "not paraphrased", "paraphrased-light": "light paraphrase",
                            "paraphrased-heavy": "heavy paraphrase"}.get(r.slice),
        "groups": ["not paraphrased", "light paraphrase", "heavy paraphrase"],
    },
    "ai_share": {
        "title": "By share of AI text (spliced and edited answers)",
        "group": lambda r: {"spliced-25": "spliced, 25% AI", "spliced-50": "spliced, 50% AI",
                            "spliced-75": "spliced, 75% AI", "raw-ai": "fully AI"}.get(r.slice)
        or (edit_bin(r.edit_distance) if r.slice == "edited-simulated" else None)
        or ("edited by a person (genuine)" if r.slice == "edited-genuine" else None),
        "groups": ["fully AI", edit_bin(0), edit_bin(EDIT_EDGES[0]), edit_bin(EDIT_EDGES[1]),
                   "spliced, 75% AI", "spliced, 50% AI", "spliced, 25% AI", "edited by a person (genuine)"],
    },
    "tier": {
        "title": "By the quality tier the AI answer was written at",
        "group": lambda r: f"{r.tier}, fully AI only" if r.slice == "raw-ai" and isinstance(r.tier, str) else None,
        "extra": lambda r: f"{r.tier}, all AI answers" if r.y_true == 1 and isinstance(r.tier, str) else None,
        "groups": [f"{t}, {scope}" for scope in ("fully AI only", "all AI answers") for t in ("correct", "partial", "weak", "wrong")],
    },
}

##  one row per (run, group): AI answers caught and human answers flagged at each frozen validation threshold
def axis_rows(df: pd.DataFrame, axis: dict) -> pd.DataFrame:
    out = []
    for run_id, d in df.groupby("run_id"):
        val = d[(d.split == "val") & (d.n_words >= harness.MIN_WORDS)]
        thresholds = {f: metrics.threshold_at_fpr(val.y_true, val.y_prob, f) for f in TARGET_FPRS}
        test = d[(d.split == "test") & (d.n_words >= harness.MIN_WORDS)].copy()
        mappers = [axis["group"]] + ([axis["extra"]] if "extra" in axis else [])
        for mapper in mappers:
            test["group"] = [mapper(r) for r in test.itertuples()]
            for group, g in test.dropna(subset=["group"]).groupby("group"):
                ai, human = g[g.y_true == 1], g[g.y_true == 0]
                row = {"run_id": run_id, "group": group, "n_ai": len(ai), "n_human": len(human)}
                for f, thr in thresholds.items():
                    row[f"tpr_at_fpr_{f}"] = (ai.y_prob >= thr).mean() if len(ai) else np.nan
                    row[f"fpr_at_fpr_{f}"] = (human.y_prob >= thr).mean() if len(human) else np.nan
                out.append(row)
    return pd.DataFrame(out)

##  mean and spread over runs; a rate resting on fewer than metrics.MIN_SLICE_N answers is marked inconclusive
def summarise(rows: pd.DataFrame, order: list[str]) -> pd.DataFrame:
    rates = [c for c in rows.columns if c.startswith(("tpr_", "fpr_"))]
    table = rows.groupby("group").agg(n_ai=("n_ai", "first"), n_human=("n_human", "first"), n_runs=("run_id", "nunique"),
                                      **{f"{c}_mean": (c, "mean") for c in rates}, **{f"{c}_std": (c, "std") for c in rates})
    table["tpr_inconclusive"] = table.n_ai.between(1, metrics.MIN_SLICE_N - 1)
    table["fpr_inconclusive"] = table.n_human.between(1, metrics.MIN_SLICE_N - 1)
    return table.reindex([g for g in order if g in table.index]).reset_index()

##  detection at each FPR target per group, shades of one blue from strict (0.1%) to loose (5%); inconclusive groups hatched
def plot_axis(table: pd.DataFrame, title: str, model: str, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    table = table[table.n_ai > 0]
    x = np.arange(len(table))
    width = 0.8 / len(TARGET_FPRS)
    fig, ax = plt.subplots(figsize=(max(6.4, 1.1 * len(table) + 2), 4.6))
    for i, f in enumerate(TARGET_FPRS):
        y = table[f"tpr_at_fpr_{f}_mean"] * 100
        bars = ax.bar(x + (i - 1) * width, y, width * 0.92, yerr=table[f"tpr_at_fpr_{f}_std"] * 100,
                      color="#2a78d6", alpha=(0.35, 0.65, 1.0)[i], error_kw={"elinewidth": 0.8, "ecolor": "#52514e"},
                      label=f"at {f:.1%} FPR")
        for bar, weak in zip(bars, table.tpr_inconclusive):
            if weak:
                bar.set_hatch("///")
    import textwrap
    labels = [f"{textwrap.fill(g, 14)}\n(n={n})" for g, n in zip(table.group, table.n_ai)]
    ax.set_xticks(x, labels, fontsize=8)
    ax.set_ylabel("AI answers caught (%)")
    ax.set_ylim(0, 100)
    ax.grid(axis="y", color="#e4e3df")
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8, ncol=len(TARGET_FPRS), loc="upper center", bbox_to_anchor=(0.5, -0.28))
    ax.set_title(f"{title}: {model}, test, mean of {int(table.n_runs.max())} runs (hatched: under {metrics.MIN_SLICE_N} answers)",
                 fontsize=9, loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)

##  logs every table and plot to one DagsHub run in E3-reliability, plus each group's 1% FPR detection rate as a metric
def log_to_mlflow(model: str, sources: list[str], tables: dict[str, pd.DataFrame], out: Path, owner: str) -> str:
    import mlflow
    from tracking import _git_state, setup_mlflow

    setup_mlflow(EXPERIMENT)
    with mlflow.start_run(run_name=f"breakdown-{model}") as run:
        mlflow.set_tags({"owner": owner, "ticket": "PP-184", "run_role": "evaluation", **_git_state()})
        mlflow.log_params({"model": model, "sources": ",".join(sources)[:500], "corpus": harness.CORPUS,
                           "min_words": harness.MIN_WORDS, "target_fprs": ",".join(map(str, TARGET_FPRS)),
                           "token_edges": ",".join(map(str, TOKEN_EDGES)), "min_group_n": metrics.MIN_SLICE_N})
        for axis, table in tables.items():
            for _, r in table[table.n_ai > 0].iterrows():
                key = "".join(c if c.isalnum() or c in "_-./ " else "_" for c in f"{axis}/{r.group}/tpr_at_fpr_0.01")
                mlflow.log_metric(key, float(r["tpr_at_fpr_0.01_mean"]))
        mlflow.log_artifacts(str(out), "breakdown")
        return run.info.run_id

def main() -> None:
    ap = argparse.ArgumentParser(description="Detection broken down by length, paraphrase, AI share and quality tier (PP-184).")
    ap.add_argument("--run", action="append", default=[], metavar="NAME=GLOB",
                    help="a model's scores files on disk; leave out to use the final model fetched from DagsHub")
    ap.add_argument("--no-log", action="store_true", help="skip logging to DagsHub")
    ap.add_argument("--owner", default="faheem", help="the owner tag on the DagsHub run")
    args = ap.parse_args()

    if args.run:
        name, pattern = args.run[0].split("=", 1)
        sources = sorted(glob.glob(pattern))
        if not sources:
            raise SystemExit(f"no files match {pattern}")
        scores = pd.concat([load_scores(p) for p in sources])
        scores = scores[~scores.model.str.endswith("-untouched")].assign(model=name)
    else:
        name = FINAL_NAME
        a = fetch_scores([f"{FINAL_PAIR[0]}-s{s}" for s in SEEDS], OUT / "scores")
        b = fetch_scores([f"{FINAL_PAIR[1]}-s{s}" for s in SEEDS], OUT / "scores")
        sources = [p.stem for p in a + b]
        scores = average_pair(a, b, name)

    df = harness.attach_meta(scores, harness.load_meta()).join(answer_details(), on="answer_id")
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    tables = {}
    for axis, spec in AXES.items():
        table = summarise(axis_rows(df, spec), spec["groups"])
        table.to_csv(out / f"{axis}.csv", index=False)
        plot_axis(table, spec["title"], name, out / f"{axis}.png")
        tables[axis] = table
        shown = table[["group", "n_ai", "n_human", "tpr_inconclusive", "fpr_inconclusive"]
                      + [f"{k}_at_fpr_{f}_mean" for f in TARGET_FPRS for k in ("tpr", "fpr")]]
        print(f"\n{spec['title']}\n{shown.round(3).to_string(index=False)}")

    print(f"\ntables and plots in {out}")
    if not args.no_log:
        print(f"logged to DagsHub {EXPERIMENT}, run {log_to_mlflow(name, sources, tables, out, args.owner)}")


if __name__ == "__main__":
    main()
