#!/bin/bash
# Final MELD LoRA runs.
# The first run is in-distribution. The remaining runs train on one dataset
# and evaluate on every row from the other two datasets.
#
#   cd ~/malcolm && sbatch Prompt-Patrol/ml-training/cluster/final_meld.sh
#
# Override the repository location with PP_DIR=... as in run_py.sh.
# Run this only after the smoke test succeeds.
#SBATCH --job-name=pp-meld
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

cd "${PP_DIR:-$HOME/malcolm/Prompt-Patrol}/ml-training"

EPOCHS=3
BATCH_SIZE=1
COMMON="--device cuda --epochs $EPOCHS --batch-size $BATCH_SIZE"

echo "################ in-distribution ################"
python finetune_meld_lora.py $COMMON \
  --run-name meld-lora-final-in-distribution \
  || echo "in-distribution FAILED"

for D in mohler sprag engsaf; do
  echo "################ train on $D, test on the other two ################"
  python finetune_meld_lora.py $COMMON \
    --train-on "$D" \
    --run-name "meld-lora-final-train-$D" \
    || echo "train-on-$D FAILED"
done
