#!/bin/bash
# Stage 2 MELD LoRA sweep: regularization x LoRA rank x seed.
#
# Stage 1 selected 1e-4 as the useful learning-rate range. This round keeps
# that LR fixed and measures dropout, rank, and seed stability:
#   dropout {0.05, 0.10} x rank {16, 32} x seed {42, 43}
#
# Configurations are selected using validation AUROC only. Test metrics are
# printed for later reporting and are never used by this script to select a run.
#
#   cd ~/malcolm && sbatch Prompt-Patrol/ml-training/cluster/sweep_meld_stage2.sh
#
# Override the repository location with PP_DIR=... as in run_py.sh.
#SBATCH --job-name=pp-meld-stage2
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=%u.%j.out

set -u

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0
source "$HOME/venvs/prompt-patrol/bin/activate"

cd "${PP_DIR:-$HOME/tori/Prompt-Patrol}/ml-training"

LR=1e-4
EPOCHS=3
BATCH_SIZE=1
TARGETS="Wqkv,Wo"

for DROPOUT in 0.05 0.10; do
  for R in 16 32; do
    ALPHA=$((2 * R))
    for SEED in 42 43; do
      NAME="meld-lora-stage2-lr${LR}-drop${DROPOUT}-r${R}-s${SEED}"
      echo "################ lr=$LR dropout=$DROPOUT r=$R seed=$SEED ################"

      python finetune_meld_lora.py \
        --run-role sweep \
        --no-baseline \
        --lr "$LR" \
        --dropout "$DROPOUT" \
        --r "$R" \
        --alpha "$ALPHA" \
        --targets "$TARGETS" \
        --epochs "$EPOCHS" \
        --batch-size "$BATCH_SIZE" \
        --seed "$SEED" \
        --run-name "$NAME" \
        || echo "run dropout=$DROPOUT r=$R seed=$SEED FAILED"
    done
  done
done

echo
echo "################ MELD STAGE 2 SUMMARY ################"

python - <<'PY'
import glob
import json
from collections import defaultdict

groups = defaultdict(list)
for path in glob.glob("outputs/meld-lora-stage2-*_results.json"):
    with open(path) as stream:
        payload = json.load(stream)
    args = payload["args"]
    tuned = payload["tuned"]
    results = tuned["results"]
    key = (args["dropout"], args["r"])
    groups[key].append({
        "val_auc": tuned["best_val_auroc"],
        "test_auc": results["auroc"],
        "test_tpr": results["deployed_tpr"],
        "test_fpr": results["deployed_fpr"],
        "epoch": tuned["best_epoch"],
        "seed": args["seed"],
    })

print(f"{'drop':>6} {'rank':>5} {'n':>3} {'val_auc':>15} "
      f"{'test_tpr':>15} {'test_fpr':>15}")
for (dropout, rank), rows in sorted(groups.items()):
    def mean(key):
        return sum(row[key] for row in rows) / len(rows)
    def sd(key):
        if len(rows) < 2:
            return 0.0
        avg = mean(key)
        return (sum((row[key] - avg) ** 2 for row in rows) / (len(rows) - 1)) ** 0.5
    print(
        f"{dropout:6.2f} {rank:5d} {len(rows):3d} "
        f"{mean('val_auc'):.4f} +/- {sd('val_auc'):.4f} "
        f"{mean('test_tpr'):.4f} +/- {sd('test_tpr'):.4f} "
        f"{mean('test_fpr'):.4f} +/- {sd('test_fpr'):.4f}"
    )
PY
