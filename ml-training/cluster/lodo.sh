#!/bin/bash
#SBATCH --job-name=pp-lodo
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=%u.%j.out
# Leave one dataset out, on the EXTENDED corpus: train and pick the epoch on two datasets, then test on EVERY answer
# of the third (all of its partitions - the model has never seen that course). This is the closest thing we have to
# a new course in deployment. The old-corpus runs trained on ONE dataset and fell to AUROC 0.81-0.91 on the others.
#
# One family and one held-out dataset per job; the seeds run one after another. Each family uses its best recipe:
#   desklib: LoRA q,k,v + feed-forward, rank 64, lr 2e-4, up to 8 epochs   (~10 min a seed)
#   meld:    LoRA Wqkv,Wo, rank 16, lr 1e-4, 3 epochs, Sep release          (~30 min a seed, plus scoring the
#            held-out set: about 1.7k answers for engsaf, 3.7k for sprag, 5.5k for mohler; the untouched
#            baseline is skipped, since scoring it would double that)
#
#   cd ~/tori && FAMILY=desklib HOLDOUT=engsaf sbatch Prompt-Patrol/ml-training/cluster/lodo.sh
#   cd ~/tori && FAMILY=meld HOLDOUT=mohler sbatch --time=08:00:00 Prompt-Patrol/ml-training/cluster/lodo.sh
#
# The thresholds are fitted on the training datasets' val rows, so the held-out FPR says whether the 1% promise
# survives a new course. Results are in the runs' MLflow metrics and charts; harness.py can't join these scores files
# to the corpus val/test files (their test rows come from every partition). Override the repo with PP_DIR=...

set -u

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0
source "$HOME/venvs/prompt-patrol/bin/activate"

cd "${PP_DIR:-$SLURM_SUBMIT_DIR/Prompt-Patrol}/ml-training" || exit 1
export PYTHONUNBUFFERED=1
echo "branch $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)$(git diff --quiet || echo ' (UNCOMMITTED CHANGES)')"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "no GPU visible"

FAMILY="${FAMILY:?set FAMILY=desklib or FAMILY=meld}"
HOLDOUT="${HOLDOUT:?set HOLDOUT=mohler, sprag or engsaf}"
SEEDS="${SEEDS:-1 2 3}"
OWNER="${OWNER:-tori}"
case "$HOLDOUT" in
  mohler) TRAIN_ON=sprag,engsaf ;;
  sprag) TRAIN_ON=mohler,engsaf ;;
  engsaf) TRAIN_ON=mohler,sprag ;;
  *) echo "HOLDOUT must be mohler, sprag or engsaf" >&2; exit 1 ;;
esac

for S in $SEEDS; do
  NAME="${FAMILY}-lora-lodo-${HOLDOUT}-extended-s$S"
  echo "################ $NAME: train on $TRAIN_ON, test on all of $HOLDOUT ################"
  if [ "$FAMILY" = "desklib" ]; then
    python finetune_desklib_lora.py --data extended --min-words 10 --train-on "$TRAIN_ON" \
      --lr 2e-4 --r 64 --alpha 128 --epochs 8 \
      --targets query_proj,key_proj,value_proj,intermediate.dense,output.dense \
      --seed "$S" --owner "$OWNER" --model-name "desklib-lora-lodo-$HOLDOUT" --run-name "$NAME" \
      || echo "$NAME FAILED"
  elif [ "$FAMILY" = "meld" ]; then
    python finetune_meld_lora.py --device cuda --data extended --min-words 10 --train-on "$TRAIN_ON" --no-baseline \
      --lr 1e-4 --r 16 --alpha 32 --targets Wqkv,Wo --epochs 3 --batch-size 1 \
      --seed "$S" --owner "$OWNER" --model-name "meld-lora-lodo-$HOLDOUT" --run-name "$NAME" \
      || echo "$NAME FAILED"
  else
    echo "FAMILY must be desklib or meld" >&2; exit 1
  fi
done
