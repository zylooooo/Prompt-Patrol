#!/bin/bash
# desklib DoRA on the EXTENDED corpus, one run per seed. Everything is the same as the current LoRA run
# (extended_desklib.sh: query+value layers, rank 64, alpha 128, lr 2e-4, 5 epochs, best epoch kept) except
# that the adapter is DoRA, so any difference is down to DoRA. Model name `desklib-dora`; the LoRA runs it is
# compared with are `desklib-lora`. Three seeds is the minimum for anything we compare or report.
#
#   cd ~/malcolm && sbatch Prompt-Patrol/ml-training/cluster/dora_desklib_extended.sh
#   SEEDS="1 2 3 4 5" sbatch ...        # more seeds
#
# Run extended_desklib.sh first (the LoRA runs and the untouched baseline come from it). Needs `dvc pull` in
# ml-training/. Override the repo location with PP_DIR=... as in run_py.sh.
#SBATCH --job-name=pp-dora
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
  echo "################ desklib DoRA, extended corpus, seed $S ################"
  # --no-baseline: the untouched model is already scored in the extended_desklib.sh runs
  python finetune_desklib_lora.py --dora --data extended --min-words 10 --no-baseline \
    --lr "$LR" --r "$R" --alpha "$ALPHA" --epochs "$EPOCHS" \
    --seed "$S" --model-name desklib-dora --run-name "desklib-dora-extended-s$S" \
    || echo "seed $S FAILED"
done

echo
echo "################ DORA SUMMARY ################"
python - <<'EOF'
import glob
import harness

files = (sorted(glob.glob("outputs/desklib-lora-extended-s*_scores.parquet"))
         + sorted(glob.glob("outputs/desklib-dora-extended-s*_scores.parquet")))
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

print("\n--- desklib-dora minus desklib-lora (the interval covers question sampling only, NOT seed spread: "
      "compare the difference with the std above) ---")
for metric in ("deployed_tpr", "oracle_tpr_at_fpr_0.01", "auroc"):
    r = harness.compare_pair(df, "desklib-dora", "desklib-lora", metric=metric, bootstrap_n=200)
    print(f"{metric}: diff {r['diff']:+.4f}  95% CI [{r['ci_low']:+.4f}, {r['ci_high']:+.4f}]  "
          f"runs {r['n_runs_a']} vs {r['n_runs_b']}")
EOF
