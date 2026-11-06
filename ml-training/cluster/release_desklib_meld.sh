#!/bin/bash
#SBATCH --job-name=pp-release
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=%u.%j.out
# Builds the deployable desklib + MELD detector (release_desklib_meld.py). Trains nothing. One job, two steps:
#
#   1. a smoke pass on 120 val + 120 test answers that logs nothing - if any step of the pipeline breaks, the
#      job stops here, minutes in, instead of after the full scoring;
#   2. the real run: scores all of val + test, fits the calibration on val, reads test once, and logs the bundle
#      to DagsHub as run release-desklib-meld-ensemble-v1. Its two checks must pass or nothing is logged.
#
#   cd ~/tori && sbatch Prompt-Patrol/ml-training/cluster/release_desklib_meld.sh
#
# Then, on your laptop: python release_desklib_meld.py --fetch   (copies the bundle into apps/detector/model/desklib-meld/)
# Override the repo location with PP_DIR=... as in run_py.sh.

set -u

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0
source "$HOME/venvs/prompt-patrol/bin/activate"

cd "${PP_DIR:-$SLURM_SUBMIT_DIR/Prompt-Patrol}/ml-training" || exit 1
export PYTHONUNBUFFERED=1 MLFLOW_DISABLE_AGENT_HINT=1
echo "branch $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)$(git diff --quiet || echo ' (UNCOMMITTED CHANGES)')"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "no GPU visible"
OWNER="${OWNER:-tori}"

echo "################ smoke: 120 answers per split, nothing logged ################"
python release_desklib_meld.py --smoke 120 --owner "$OWNER" || { echo "smoke pass FAILED; not running the release" >&2; exit 1; }

echo "################ release: all of val + test ################"
python release_desklib_meld.py --owner "$OWNER" || { echo "release FAILED (see the checks above)" >&2; exit 1; }

ls -lR outputs/release/desklib-meld-ensemble-v1
