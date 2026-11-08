#!/bin/bash
#SBATCH --job-name=pp-raid
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=%u.%j.out
# RAID benchmark (eval_raid.py). Trains nothing and logs nothing to DagsHub; it only READS runs from it.
#
#   STEP=sample  once: downloads RAID's train.csv and keeps a fixed labelled sample (outputs/raid/data/).
#                No GPU work; give it --time=03:00:00, the download is many GB.
#   STEP=score   scores each of COMPONENTS on SPLIT (train-sample or test), one after another. Each starts with
#                a 64-text smoke pass that prints texts/s and the projected hours, then scores in chunks of 2000.
#                Chunks already on disk are skipped, so if the job hits its time limit, submit it again unchanged
#                and it carries on.
#
#   cd ~/tori && STEP=sample sbatch --time=03:00:00 Prompt-Patrol/ml-training/cluster/raid.sh
#   cd ~/tori && STEP=score SPLIT=train-sample COMPONENTS="desklib-v0.1 desklib-v0.1-extended meld-v0.1 meld-v0.1-extended" \
#     sbatch Prompt-Patrol/ml-training/cluster/raid.sh
#   cd ~/tori && STEP=score SPLIT=test COMPONENTS="desklib-v0.1-extended" sbatch Prompt-Patrol/ml-training/cluster/raid.sh
#
# COMPONENTS are names from eval_raid.py's PRESETS or kind:run (desklib:<run>, meld:<run>, meld-soup:<run>).
# A desklib+meld pair is never scored here: score both halves, then evaluate/submit combines them (on any machine).
# Then: python eval_raid.py evaluate --candidates ...   and   python eval_raid.py submit ...  (see eval_raid.py)
#
# One-time setup in the venv (NOT plain `pip install raid-bench`: it would downgrade numpy and pandas):
#   pip install --no-deps raid-bench==0.2.0
# RAID's CSVs go to RAID_CACHE_DIR (default below); point it at scratch if home is small.
# Override the repo location with PP_DIR=... as in run_py.sh.

set -u

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0
source "$HOME/venvs/prompt-patrol/bin/activate"

cd "${PP_DIR:-$SLURM_SUBMIT_DIR/Prompt-Patrol}/ml-training" || exit 1
export PYTHONUNBUFFERED=1 MLFLOW_DISABLE_AGENT_HINT=1
export RAID_CACHE_DIR="${RAID_CACHE_DIR:-$HOME/raid-cache}"
echo "branch $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)$(git diff --quiet || echo ' (UNCOMMITTED CHANGES)')"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "no GPU visible"
python -c "import raid" 2>/dev/null || { echo "raid-bench missing: pip install --no-deps raid-bench==0.2.0" >&2; exit 1; }

STEP="${STEP:?set STEP=sample or STEP=score}"

if [ "$STEP" = "sample" ]; then
  python eval_raid.py sample
  exit $?
fi
[ "$STEP" = "score" ] || { echo "STEP must be sample or score" >&2; exit 1; }

SPLIT="${SPLIT:?set SPLIT=train-sample or SPLIT=test}"
COMPONENTS="${COMPONENTS:?set COMPONENTS, e.g. COMPONENTS=\"desklib-v0.1 meld-v0.1\"}"
FAILED=""
for C in $COMPONENTS; do
  echo "################ $C on $SPLIT: smoke ################"
  if ! python eval_raid.py score --component "$C" --split "$SPLIT" --smoke 64; then
    echo "$C smoke FAILED; skipping it" >&2; FAILED="$FAILED $C"; continue
  fi
  echo "################ $C on $SPLIT ################"
  python eval_raid.py score --component "$C" --split "$SPLIT" || { echo "$C FAILED" >&2; FAILED="$FAILED $C"; }
done

du -sh outputs/raid/scores/* 2>/dev/null
[ -z "$FAILED" ] || { echo "failed:$FAILED" >&2; exit 1; }
