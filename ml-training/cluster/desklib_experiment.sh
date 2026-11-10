#!/bin/bash
#SBATCH --job-name=pp-desklib-exp
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=%u.%j.out
# desklib LoRA on the EXTENDED corpus with the best recipe from the re-sweep (LoRA on q, k, v and both feed-forward
# layers, rank 64, lr 2e-4, up to 8 epochs, the epoch kept by val AUROC), plus an optional loss weighting. All
# seeds run in one job (~10 min each), and each run logs its training curves, charts and adapter to MLflow.
#
# Without WEIGHTS it re-runs the recipe itself, which is the reference the weighted runs are compared with:
#
#   cd ~/tori && sbatch Prompt-Patrol/ml-training/cluster/desklib_experiment.sh
#
# Mohler's human answers counting double (every false flag of desklib + MELD on test was a Mohler student):
#
#   cd ~/tori && WEIGHTS='dataset=mohler&slice=human:2' TAG=mohlerneg \
#       sbatch Prompt-Patrol/ml-training/cluster/desklib_experiment.sh
#
# Spliced and paraphrased AI answers counting double (the weakest slices; train has 397 of each vs 1,191 raw AI):
#
#   cd ~/tori && WEIGHTS='slice=spliced-*:2,slice=paraphrased-*:2' TAG=hardai \
#       sbatch Prompt-Patrol/ml-training/cluster/desklib_experiment.sh
#
# Runs are named desklib-lora-qkvf-r64-e8[-<TAG>]-extended-s<seed>, and the scores file's model column is the same
# name without the seed, so analyse_ensemble.py can take it as --a. Needs the extended corpus (`dvc pull` in
# ml-training/). Override the repo location with PP_DIR=... as in run_py.sh.

set -u

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0
source "$HOME/venvs/prompt-patrol/bin/activate"

cd "${PP_DIR:-$SLURM_SUBMIT_DIR/Prompt-Patrol}/ml-training" || exit 1
export PYTHONUNBUFFERED=1
echo "branch $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)$(git diff --quiet || echo ' (UNCOMMITTED CHANGES)')"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "no GPU visible"

LR="${LR:-2e-4}"
R="${R:-64}"
ALPHA=$((2 * R))
EPOCHS="${EPOCHS:-8}"
TARGETS="${TARGETS:-query_proj,key_proj,value_proj,intermediate.dense,output.dense}"
WEIGHTS="${WEIGHTS:-}"
TAG="${TAG:-}"
SEEDS="${SEEDS:-1 2 3}"
OWNER="${OWNER:-tori}"
if [ -n "$WEIGHTS" ] && [ -z "$TAG" ]; then
  echo "WEIGHTS is set but TAG is not; give the weighting a short TAG so its runs get their own name" >&2
  exit 1
fi

# q,k,v,f in the name as in the re-sweep: query_proj,key_proj,value_proj,intermediate.dense,output.dense -> qkvf
SHORT=$(echo "$TARGETS" | sed -e 's/query_proj/q/; s/key_proj/k/; s/value_proj/v/; s/intermediate.dense,output.dense/f/' | tr -d ',')
NAME="desklib-lora-${SHORT}-r${R}-e${EPOCHS}${TAG:+-$TAG}-extended"

for S in $SEEDS; do
  echo "################ desklib $NAME, seed $S ################"
  python finetune_desklib_lora.py --data extended --min-words 10 --no-baseline \
    --lr "$LR" --r "$R" --alpha "$ALPHA" --epochs "$EPOCHS" --targets "$TARGETS" \
    ${WEIGHTS:+--weights "$WEIGHTS"} --seed "$S" --owner "$OWNER" --log-adapter \
    --model-name "$NAME" --run-name "$NAME-s$S" \
    || echo "$NAME seed $S FAILED"
done

ls -l outputs/"$NAME"-s*_scores.parquet
