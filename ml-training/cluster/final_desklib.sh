#!/bin/bash
# Final desklib LoRA runs with the config chosen by the two validation sweeps:
# lr 2e-4, r 64, alpha 128, 5 epochs (best epoch is restored by val AUROC).
# Four runs back to back, each scored against the untouched model on the same rows:
#   1. in-distribution (all three datasets, held-out test partition)
#   2-4. train on one dataset, test on every row of the other two
# These are the headline results (run_role=train), not sweep runs.
#
#   cd ~/malcolm && sbatch Prompt-Patrol/ml-training/cluster/final_desklib.sh
#
# Override the repo location with PP_DIR=... as in run_py.sh.
#SBATCH --job-name=pp-final
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
COMMON="--lr $LR --r $R --alpha $ALPHA --epochs $EPOCHS"

echo "################ in-distribution ################"
python finetune_desklib_lora.py $COMMON --run-name desklib-lora-final-in-distribution \
  || echo "in-distribution FAILED"

for D in mohler sprag engsaf; do
  echo "################ train on $D, test on the other two ################"
  python finetune_desklib_lora.py $COMMON --train-on "$D" --run-name "desklib-lora-final-train-$D" \
    || echo "train-on-$D FAILED"
done
