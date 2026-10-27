#!/bin/bash
# MELD LoRA on the EXTENDED corpus (v0.1-extended), one run per seed, with the stage-1 sweep's
# learning rate (1e-4) and the Wqkv,Wo targets. Set DROPOUT / R from the stage-2 sweep's best
# validation AUROC before submitting. Each run also scores the untouched model on the same rows,
# and writes outputs/<run>_scores.parquet for harness.py. Three seeds is the minimum for any
# result we compare or report.
#
#   cd ~/tori && sbatch Prompt-Patrol/ml-training/cluster/extended_meld.sh
#   SEEDS="1 2 3 4 5" DROPOUT=0.10 R=32 sbatch ...
#
# Needs the extended corpus: `dvc pull` in ml-training/ first. Override the repo location with
# PP_DIR=... as in run_py.sh.
#SBATCH --job-name=pp-ext-meld
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=%u.%j.out

set -u

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0
source "$HOME/venvs/prompt-patrol/bin/activate"

cd "${PP_DIR:-$HOME/tori/Prompt-Patrol}/ml-training"

LR=1e-4
DROPOUT="${DROPOUT:-0.05}"
R="${R:-16}"
ALPHA=$((2 * R))
EPOCHS=3
BATCH_SIZE=1
SEEDS="${SEEDS:-1 2 3}"
OWNER="${OWNER:-tori}"
COMMON="--device cuda --data extended --min-words 10 --lr $LR --dropout $DROPOUT --r $R --alpha $ALPHA \
  --targets Wqkv,Wo --epochs $EPOCHS --batch-size $BATCH_SIZE --owner $OWNER"

for S in $SEEDS; do
  echo "################ MELD LoRA, extended corpus, seed $S ################"
  python finetune_meld_lora.py $COMMON --seed "$S" --run-name "meld-lora-extended-s$S" \
    || echo "seed $S FAILED"
done

ls -l outputs/meld-lora-extended-s*_scores.parquet
