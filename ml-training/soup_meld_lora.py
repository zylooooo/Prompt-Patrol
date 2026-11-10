"""
Averages several fine-tuned MELD runs into ONE model (a "model soup") and evaluates it like any run.

Why: averaging two MELD seeds' scores catches about as much AI at 1% FPR as desklib + MELD does
(72.3% vs 72.7% on the extended test set), because single MELD seeds are noisy (51% to 70%). Scoring
with two MELDs costs two 4 GB models; a soup is one. This script tests whether averaging the weights
keeps the gain of averaging the scores.

What is averaged, with every member trained from the same MELD checkpoint:
  - the backbone: each member's LoRA update merged into a full weight change (scale * B @ A, exact,
    from PEFT's get_delta_weight), averaged over members, added to the base weights. Averaging the
    A and B matrices separately would not equal this, so they are never averaged directly;
  - the prototype head (everything outside the backbone): averaged tensor by tensor.

Then the usual protocol: temperature and the 1% FPR threshold fitted on val (answers of >= --min-words
words), frozen, test scored once. Writes outputs/<run>_scores.parquet for harness.py and
analyse_ensemble.py, logs the metrics and charts to MLflow, and trains nothing.

Members are MLflow run names. Each one's adapter and head come from outputs/<run>_adapter and
outputs/<run>_head.pt if present, otherwise from the run's model/ artifacts on DagsHub.

    # the soup of seeds 1 and 2, compared later with the score average of the same two seeds
    python soup_meld_lora.py --runs meld-lora-extended-s1,meld-lora-extended-s2 \
        --run-name meld-lora-soup-pair-s1 --seed 1
    # one member only: rebuilds that run and checks it reproduces its own saved scores (a test of the merge)
    python soup_meld_lora.py --runs meld-lora-extended-s1 --check --offline
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import mlflow
import numpy as np
import torch

from combined_data import CORPORA, load_corpus
from finetune_meld_lora import MLFLOW_EXPERIMENT, OUT_DIR, evaluate_protocol, load_meld, predict_logits
from meld_lora_plots import log_lora_charts
from scores import load_scores, save_scores, score_rows

##  finds one member's adapter folder and head file: outputs/ first, otherwise the run's model/ artifacts
##
##  run_name:   the member's MLflow run name
##  returns (adapter folder, head file, the MELD revision it was trained on, the run id)
def member_files(run_name: str) -> tuple[Path, Path, str, str]:
    runs = mlflow.search_runs(search_all_experiments=True, filter_string=f"tags.mlflow.runName = '{run_name}'",
                              output_format="list")
    runs = [r for r in runs if r.info.status == "FINISHED"]
    if not runs:
        raise SystemExit(f"no finished run named {run_name} on DagsHub")
    run = runs[0]
    revision = run.data.params.get("meld_revision")
    if not revision:
        raise SystemExit(f"{run_name} did not log meld_revision, so the base checkpoint is unknown")

    adapter, head = OUT_DIR / f"{run_name}_adapter", OUT_DIR / f"{run_name}_head.pt"
    if not (adapter.exists() and head.exists()):
        folder = Path(mlflow.artifacts.download_artifacts(run_id=run.info.run_id, artifact_path="model",
                                                          dst_path=tempfile.mkdtemp(prefix="meld-soup-")))
        adapter, head = folder / "adapter", folder / f"{run_name}_head.pt"
        if not (adapter.exists() and head.exists()):
            raise SystemExit(f"{run_name} has no model/adapter and model/{run_name}_head.pt artifacts")
    return adapter, head, revision, run.info.run_id

##  the full weight change one LoRA adapter makes to the backbone, per wrapped layer
##  wraps the backbone with the adapter, reads every layer's merged update, then removes the adapter again,
##  so the backbone comes back unchanged
##
##  model:      the MELD model (its .backbone is the plain ModernBERT)
##  adapter:    the member's adapter folder
##  returns {module name in the backbone: weight change, float32 on CPU}
def lora_deltas(model, adapter: Path) -> dict[str, torch.Tensor]:
    from peft import PeftModel
    from peft.tuners.lora import LoraLayer

    wrapped = PeftModel.from_pretrained(model.backbone, str(adapter))
    deltas = {}
    for name, module in wrapped.named_modules():
        if isinstance(module, LoraLayer) and "default" in module.lora_A:
            deltas[name.removeprefix("base_model.model.")] = module.get_delta_weight("default").detach().float().cpu()
    model.backbone = wrapped.unload()
    if not deltas:
        raise RuntimeError(f"{adapter} wrapped no layer of the MELD backbone")
    return deltas

##  averages the members' head tensors (everything outside the backbone). float tensors are averaged; any other
##  tensor (e.g. a boolean generator-membership mask) must be the same in every member and is kept as is
##
##  heads:  one state dict per member, as saved to <run>_head.pt
##  returns the averaged state dict
def average_heads(heads: list[dict]) -> dict:
    keys = set(heads[0])
    if any(set(h) != keys for h in heads):
        raise SystemExit("the members' heads have different tensors; were they trained on the same MELD release?")
    out = {}
    for key in heads[0]:
        tensors = [h[key] for h in heads]
        if tensors[0].is_floating_point():
            out[key] = torch.stack([t.float() for t in tensors]).mean(0).to(tensors[0].dtype)
        elif all(torch.equal(tensors[0], t) for t in tensors[1:]):
            out[key] = tensors[0]
        else:
            raise SystemExit(f"head tensor {key} differs between members and can't be averaged")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", required=True, help="comma-separated MLflow run names of the members")
    ap.add_argument("--run-name", default="", help="default: meld-lora-soup-<members' seeds>")
    ap.add_argument("--model-name", default="meld-lora-soup",
                    help="the scores file's model column, which harness.py groups seeds by")
    ap.add_argument("--seed", type=int, default=1,
                    help="the seed recorded in the scores file. Number pair soups after their first member so "
                         "analyse_ensemble.py lines soup s up with the score average of seeds s and s+1")
    ap.add_argument("--data", default="extended", choices=CORPORA,
                    help="the corpus the members were trained on; val and test are scored from it")
    ap.add_argument("--experiment", default=MLFLOW_EXPERIMENT,
                    help="MLflow experiment to log to; E3 runs go to E3-reliability")
    ap.add_argument("--min-words", type=int, default=10)
    ap.add_argument("--target-fpr", type=float, default=0.01)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--owner", default="tori")
    ap.add_argument("--check", action="store_true",
                    help="with one member: compare the rebuilt model's val logits with that run's saved scores")
    ap.add_argument("--offline", action="store_true", help="log to a temporary local folder, not DagsHub")
    args = ap.parse_args()

    members = [r for r in args.runs.split(",") if r]
    if args.check and len(members) != 1:
        raise SystemExit("--check rebuilds one run; pass exactly one member")
    run_name = args.run_name or "meld-lora-soup-" + "-".join(m.rsplit("-", 1)[-1] for m in members)

    from tracking import log_split_metrics, setup_mlflow

    # members are always looked up on DagsHub, even when the soup itself is logged offline
    setup_mlflow()
    files = [member_files(m) for m in members]
    revisions = {rev for _, _, rev, _ in files}
    if len(revisions) != 1:
        raise SystemExit(f"members were trained on different MELD releases {sorted(revisions)}; they can't be averaged")
    revision = revisions.pop()

    frames = load_corpus(args.data)
    val, test = frames["val"].reset_index(drop=True), frames["test"].reset_index(drop=True)
    meld, scorer, model_dir = load_meld(args.device, revision)
    model, tokenizer, device = scorer.model, scorer.tok, scorer.device

    summed: dict[str, torch.Tensor] = {}
    heads = []
    for member, (adapter, head, _, _) in zip(members, files):
        for name, delta in lora_deltas(model, adapter).items():
            summed[name] = summed[name] + delta if name in summed else delta
        heads.append(torch.load(head, map_location="cpu"))
        print(f"read {member}: {len(summed)} LoRA layers")
    with torch.no_grad():
        for name, delta in summed.items():
            weight = model.backbone.get_submodule(name).weight
            weight += (delta / len(members)).to(weight.device, weight.dtype)
    result = model.load_state_dict(average_heads(heads), strict=False)
    if result.unexpected_keys:
        raise RuntimeError(f"head tensors matched nothing in the model: {result.unexpected_keys[:3]}")

    val_logits = predict_logits(meld, model, tokenizer, val["answer"], device, scorer.cap, scorer.window)
    if args.check:
        from ensemble_scores import find_scores

        saved = load_scores(find_scores(members[0]))
        saved = saved[(saved["split"] == "val") & ~saved["model"].str.endswith("-untouched")]
        saved = saved.set_index("answer_id")["logit"].reindex(val["answer_id"]).to_numpy()
        gap = float(np.max(np.abs(saved - val_logits)))
        print(f"CHECK: rebuilt {members[0]} vs its saved val logits, max difference {gap:.2e} "
              f"({'OK' if gap < 1e-3 else 'MISMATCH - the merge does not reproduce the run'})")
        return
    test_logits = predict_logits(meld, model, tokenizer, test["answer"], device, scorer.cap, scorer.window)
    tuned, val_prob, test_prob = evaluate_protocol(val, test, val_logits, test_logits, args.target_fpr, True,
                                                   args.min_words)
    r = tuned["results"]
    print(f"soup of {len(members)}: auroc={r['auroc']:.4f} deployed_tpr={r['deployed_tpr']:.4f} "
          f"deployed_fpr={r['deployed_fpr']:.4f} (answers of >= {args.min_words} words)")

    if args.offline:
        tmp = Path(tempfile.mkdtemp(prefix="meld-soup-offline-"))
        mlflow.set_tracking_uri(f"sqlite:///{tmp / 'mlflow.db'}")
        mlflow.create_experiment(args.experiment, artifact_location=(tmp / "artifacts").as_uri())
        print(f"OFFLINE: logging to {mlflow.get_tracking_uri()}, nothing goes to DagsHub")
    mlflow.set_experiment(args.experiment)
    with mlflow.start_run(run_name=run_name):
        mlflow.set_tags({"owner": args.owner, "run_role": "train", "tuning_method": "lora-soup",
                         "model_family": "meld", "data_mode": "in-distribution"})
        mlflow.log_params({"base_model": "anon-review-meld-2026/meld", "meld_revision": model_dir.name,
                           "data": args.data, "min_words": args.min_words, "target_fpr": args.target_fpr,
                           "soup_members": ",".join(members), "soup_member_run_ids": ",".join(f[3] for f in files),
                           "model_name": args.model_name, "seed": args.seed,
                           "val_n": len(val), "test_n": len(test)})
        log_split_metrics(r, "test")
        mlflow.log_metrics({"temperature": tuned["temperature"], "threshold": tuned["threshold"]})
        used = (test["n_words"] >= args.min_words).to_numpy()
        log_lora_charts(run_name, "meld", test[used].reset_index(drop=True), test_prob[used], None, [],
                        r, tuned["threshold"], args.target_fpr, OUT_DIR)
        scores_path = save_scores(run_name, args.seed, [
            score_rows(args.model_name, "val", val, val_logits, val_prob),
            score_rows(args.model_name, "test", test, test_logits, test_prob)])
        payload = {"run": run_name, "members": members, "args": vars(args),
                   "tuned": {k: v for k, v in tuned.items() if k != "results"}
                   | {"results": {k: float(v) for k, v in r.items()}}}
        Path(OUT_DIR / f"{run_name}_results.json").write_text(json.dumps(payload, indent=2, default=float))
        print(f"Wrote {scores_path.name} and {run_name}_results.json")


if __name__ == "__main__":
    main()
