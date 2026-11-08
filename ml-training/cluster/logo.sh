#!/bin/bash
#SBATCH --job-name=pp-logo
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=%u.%j.out
# E3 leave-one-generator-out for the shipped detector (desklib + MELD 3-seed soup). Each fold retrains the
# shipped recipes with one generator removed from train and val, then tests on human test + that generator's
# test answers (data/splits/v0.1-logo-<fold>.parquet, from build_logo_splits.py).
#
# The folds are raw answers only (v0.1, not v0.1-extended: every paraphrased and edited row in the extended
# corpus was rewritten by deepseek-v4-pro, which would leak DeepSeek into every fold). So the `control` fold
# trains the same recipes on all of v0.1. analyse_logo.py compares each fold with the control on the SAME test
# answers, so the gap is the unseen generator alone, not the smaller training set.
#
#   desklib: LoRA q,k,v + feed-forward, rank 64, lr 2e-4, up to 8 epochs  (desklib-lora-qkvf-r64-e8, ~10 min a seed)
#            the untouched desklib is scored too, as a reference that never saw any of our generators
#   meld:    LoRA Wqkv,Wo, rank 16, lr 1e-4, 3 epochs, Sep release      (meld-lora-extended, ~30 min a seed)
#            then the 3-seed soup of the fold (~10 min), only if all three seeds finished
#
# One family per job, FOLDS run one after another. Folds: claude deepseek gemini gpt llama qwen control, or `all`.
#
#   cd ~/tori && FAMILY=desklib FOLDS=all sbatch Prompt-Patrol/ml-training/cluster/logo.sh
#   cd ~/tori && FAMILY=meld FOLDS="control claude" sbatch Prompt-Patrol/ml-training/cluster/logo.sh
#
# Rough cost: desklib, all 7 folds ~4 h. MELD ~1 h 40 per fold, so 2-3 folds per job within --time=06:00:00.
# Runs log to the E3-reliability experiment as <family>-lora-logo-<fold>-s<seed> and meld-lora-soup-logo-<fold>-s1.
# Re-submitting a fold re-trains it: check DagsHub first. Override the repo location with PP_DIR=... as in run_py.sh.

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
FOLDS="${FOLDS:?set FOLDS to some of: claude deepseek gemini gpt llama qwen control (or all)}"
SEEDS="${SEEDS:-1 2 3}"
OWNER="${OWNER:-tori}"
EXPERIMENT=E3-reliability
[ "$FOLDS" = "all" ] && FOLDS="control claude deepseek gemini gpt llama qwen"

for F in $FOLDS; do
  case "$F" in
    control) DATA=v0.1 ;;
    claude|deepseek|gemini|gpt|llama|qwen) DATA="logo-$F" ;;
    *) echo "unknown fold $F" >&2; exit 1 ;;
  esac
  BASE="${FAMILY}-lora-logo-$F"
  OK=0
  for S in $SEEDS; do
    echo "################ $BASE-s$S (data $DATA) ################"
    if [ "$FAMILY" = "desklib" ]; then
      python finetune_desklib_lora.py --data "$DATA" --experiment "$EXPERIMENT" --min-words 10 \
        --lr 2e-4 --r 64 --alpha 128 --epochs 8 \
        --targets query_proj,key_proj,value_proj,intermediate.dense,output.dense \
        --seed "$S" --owner "$OWNER" --model-name "$BASE" --run-name "$BASE-s$S" \
        && OK=$((OK + 1)) || echo "$BASE-s$S FAILED"
    elif [ "$FAMILY" = "meld" ]; then
      python finetune_meld_lora.py --device cuda --data "$DATA" --experiment "$EXPERIMENT" --min-words 10 \
        --no-baseline --lr 1e-4 --dropout 0.05 --r 16 --alpha 32 --targets Wqkv,Wo --epochs 3 --batch-size 1 \
        --seed "$S" --owner "$OWNER" --model-name "$BASE" --run-name "$BASE-s$S" \
        && OK=$((OK + 1)) || echo "$BASE-s$S FAILED"
    else
      echo "FAMILY must be desklib or meld" >&2; exit 1
    fi
  done

  if [ "$FAMILY" = "meld" ]; then
    MEMBERS=$(for S in $SEEDS; do printf '%s,' "$BASE-s$S"; done)
    MEMBERS="${MEMBERS%,}"
    if [ "$OK" -ne "$(echo $SEEDS | wc -w)" ]; then
      echo "not souping $F: only $OK seed(s) finished; rerun the failed seed with SEEDS=<n> FOLDS=$F, then the soup" >&2
      continue
    fi
    FIRST=$(echo $SEEDS | cut -d' ' -f1)
    echo "################ check: rebuild $BASE-s$FIRST alone ################"
    if ! python soup_meld_lora.py --data "$DATA" --runs "$BASE-s$FIRST" --check --offline | tee /dev/stderr | grep -q "OK"; then
      echo "the rebuilt $BASE-s$FIRST does not reproduce its saved scores; not souping $F" >&2
      continue
    fi
    echo "################ soup of $MEMBERS ################"
    python soup_meld_lora.py --data "$DATA" --experiment "$EXPERIMENT" --runs "$MEMBERS" --seed 1 --owner "$OWNER" \
      --model-name "meld-lora-soup-logo-$F" --run-name "meld-lora-soup-logo-$F-s1" || echo "soup $F FAILED"
  fi
done

ls -l outputs/*-logo-*_scores.parquet
