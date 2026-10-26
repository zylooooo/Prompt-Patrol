#!/bin/bash
# desklib LoRA that also sees the QUESTION, on the extended corpus, one run per seed. The input becomes
# "<question> [SEP] <answer>" instead of the answer alone. Everything else matches the current LoRA run
# (extended_desklib.sh: query+value layers, rank 64, alpha 128, lr 2e-4, 5 epochs, best epoch kept), so a
# difference is down to the question. Model name `desklib-lora-question`; it is compared with the answer-only
# `desklib-lora`. Three seeds is the minimum for anything we compare or report.
#
# Splits are by question, so the model never sees a test question in training and cannot memorise them.
# The untouched baseline stays answer-only (it comes from the extended_desklib.sh runs). The 10-word rule still
# counts the answer's words only. Only useful for the app if the app collects the question.
#
#   cd ~/malcolm && sbatch Prompt-Patrol/ml-training/cluster/question_desklib_extended.sh
#   SEEDS="1 2 3 4 5" sbatch ...        # more seeds
#
# Run extended_desklib.sh first (the answer-only runs come from it). Needs `dvc pull` in ml-training/
# (the question text is in data/sources). Override the repo location with PP_DIR=... as in run_py.sh.
#SBATCH --job-name=pp-question
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=%u.%j.out

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0
source "$HOME/venvs/prompt-patrol/bin/activate"

cd "${PP_DIR:-$HOME/malcolm/Prompt-Patrol}/ml-training"

LR=2e-4
R=64
ALPHA=128
EPOCHS=5
SEEDS="${SEEDS:-1 2 3}"

for S in $SEEDS; do
  echo "################ desklib LoRA + question, extended corpus, seed $S ################"
  python finetune_desklib_lora.py --question --data extended --min-words 10 \
    --lr "$LR" --r "$R" --alpha "$ALPHA" --epochs "$EPOCHS" \
    --seed "$S" --model-name desklib-lora-question --run-name "desklib-lora-question-extended-s$S" \
    || echo "seed $S FAILED"
done

echo
echo "################ QUESTION-CONTEXT SUMMARY ################"
python - <<'EOF'
import glob
import harness

files = (sorted(glob.glob("outputs/desklib-lora-extended-s*_scores.parquet"))
         + sorted(glob.glob("outputs/desklib-lora-question-extended-s*_scores.parquet")))
df = harness.load_runs(files)
fmt = lambda x: f"{x:.4f}"

print("--- VALIDATION: mean and std over seeds ---")
val = harness.validation_table(df)
print(val.groupby("model")[["val_auroc", "val_tpr"]].agg(["count", "mean", "std"]).to_string(float_format=fmt))

print("\n--- TEST, 10+ words: mean and std over seeds ---")
table = harness.compare_models(df, bootstrap_n=200, min_words=(harness.MIN_WORDS,))
cols = ["model", "n_runs", "deployed_tpr_mean", "deployed_tpr_std", "deployed_fpr_mean",
        "oracle_tpr_at_fpr_0.01_mean", "auroc_mean", "auroc_std"]
print(harness.aggregate_seeds(table)[cols].to_string(index=False, float_format=fmt))

print("\n--- desklib-lora-question minus desklib-lora (the interval covers question sampling only, NOT seed "
      "spread: compare the difference with the std above) ---")
for metric in ("deployed_tpr", "oracle_tpr_at_fpr_0.01", "auroc"):
    r = harness.compare_pair(df, "desklib-lora-question", "desklib-lora", metric=metric, bootstrap_n=200)
    print(f"{metric}: diff {r['diff']:+.4f}  95% CI [{r['ci_low']:+.4f}, {r['ci_high']:+.4f}]  "
          f"runs {r['n_runs_a']} vs {r['n_runs_b']}")

print("\n--- per slice, 10+ words: mean rate over seeds (TPR; FPR for the human row) ---")
a = harness.slice_summary(df, "desklib-lora")[["slice_value", "rate_type", "n", "rate_mean", "rate_std"]]
b = harness.slice_summary(df, "desklib-lora-question")[["slice_value", "rate_mean", "rate_std"]]
merged = a.merge(b, on="slice_value", suffixes=("_answer_only", "_with_question"))
print(merged.to_string(index=False, float_format=fmt))
EOF
