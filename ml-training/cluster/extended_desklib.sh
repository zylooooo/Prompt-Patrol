#!/bin/bash
# desklib LoRA on the EXTENDED corpus (v0.1-extended), one run per seed, with the settings chosen by
# the two validation sweeps on the old corpus: lr 2e-4, r 64, alpha 128, 5 epochs (best epoch kept).
# Each run also scores the untouched model on the same rows, and writes
# outputs/<run>_scores.parquet for harness.py. Three seeds is the minimum for any result we compare
# or report (a single run can look good or bad by luck).
#
#   cd ~/malcolm && sbatch Prompt-Patrol/ml-training/cluster/extended_desklib.sh
#   SEEDS="1 2 3 4 5" sbatch ...        # more seeds
#
# Needs the extended corpus: `dvc pull` in ml-training/ first (git checkout main, after the
# extended-corpus PR). Override the repo location with PP_DIR=... as in run_py.sh.
#SBATCH --job-name=pp-ext-desklib
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
COMMON="--data extended --min-words 10 --lr $LR --r $R --alpha $ALPHA --epochs $EPOCHS"

for S in $SEEDS; do
  echo "################ desklib LoRA, extended corpus, seed $S ################"
  python finetune_desklib_lora.py $COMMON --seed "$S" --run-name "desklib-lora-extended-s$S" \
    || echo "seed $S FAILED"
done

ls -l outputs/desklib-lora-extended-s*_scores.parquet
