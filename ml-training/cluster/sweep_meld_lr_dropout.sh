#!/bin/bash
# Stage 1 MELD LoRA sweep: learning rate x dropout.
#
# Rank, alpha, target modules, seed, epoch budget, and batch size are held
# constant so this round measures optimization and regularization only.
# Configurations are selected by validation AUROC; test metrics are reported
# for inspection but must not be used to choose a configuration.
#
#   cd ~/tori && sbatch Prompt-Patrol/ml-training/cluster/sweep_meld_lr_dropout.sh
#
# Override the repository location with PP_DIR=... as in run_py.sh.
# The MELD fine-tuning source must be present at ml-training/finetune_meld_lora.py.
#SBATCH --job-name=pp-meld-lrdo
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

EPOCHS=3
BATCH_SIZE=1
R=16
ALPHA=32
SEED=42
TARGETS="Wqkv,Wo"

for LR in 2.5e-5 5e-5 1e-4; do
  for DROPOUT in 0.05 0.10; do
    NAME="meld-lora-sweep-lr${LR}-drop${DROPOUT}-r${R}-e${EPOCHS}"
    echo "################ lr=$LR dropout=$DROPOUT ################"

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
      || echo "run lr=$LR dropout=$DROPOUT FAILED"
  done
done

echo
echo "################ MELD LR/DROPOUT SUMMARY ################"

python - <<'PY'
import glob
import json

rows = []
for path in glob.glob("outputs/meld-lora-sweep-*_results.json"):
    with open(path) as stream:
        payload = json.load(stream)

    args = payload["args"]
    tuned = payload["tuned"]
    results = tuned["results"]
    rows.append({
        "val_auroc": tuned["best_val_auroc"],
        "best_epoch": tuned["best_epoch"],
        "lr": args["lr"],
        "dropout": args["dropout"],
        "test_auroc": results["auroc"],
        "test_tpr": results["deployed_tpr"],
        "test_fpr": results["deployed_fpr"],
    })

rows.sort(key=lambda row: row["val_auroc"], reverse=True)
print(
    f"{'val_auc':>8} {'test_auc':>8} {'test_tpr':>9} {'test_fpr':>9} "
    f"{'lr':>9} {'drop':>6} {'epoch':>6}"
)
for row in rows:
    print(
        f"{row['val_auroc']:8.4f} "
        f"{row['test_auroc']:8.4f} "
        f"{row['test_tpr']:9.4f} "
        f"{row['test_fpr']:9.4f} "
        f"{row['lr']:9.2e} "
        f"{row['dropout']:6.2f} "
        f"{row['best_epoch']:6d}"
    )
PY
