#!/bin/bash
# Build (or rebuild) the shared training environment and record what was installed.
# Normally only ONE person runs this, because everyone shares ~/venvs/prompt-patrol.
#
#   cd ~/<yourname> && sbatch Prompt-Patrol/ml-training/cluster/setup_env.sh
#   cd ~/<yourname> && sbatch Prompt-Patrol/ml-training/cluster/setup_env.sh $HOME/venvs/verify
#
# The optional argument is the venv path. Use a different one to test that a
# clean install reproduces the committed versions without touching the shared env.
#SBATCH --job-name=setup-env
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:40:00
#SBATCH --output=%u.%j.out

VENV=${1:-$HOME/venvs/prompt-patrol}
ML="$SLURM_SUBMIT_DIR/Prompt-Patrol/ml-training"
RECORD="$SLURM_SUBMIT_DIR/env-record-$(basename "$VENV")"

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0

python3.11 -m venv "$VENV"
source "$VENV/bin/activate"
pip install --upgrade pip

# If a freeze file is committed, use it to pin the transitive packages too.
CONSTRAINTS=""
if [ -f "$ML/cluster/env-record/pip-freeze.txt" ]; then
  CONSTRAINTS="-c $ML/cluster/env-record/pip-freeze.txt"
fi
pip install -r "$ML/requirements.txt" $CONSTRAINTS

mkdir -p "$RECORD"
pip freeze > "$RECORD/pip-freeze.txt"
nvidia-smi > "$RECORD/nvidia-smi.txt"
python -c "import torch, transformers, peft; print('torch', torch.__version__, 'cuda', torch.version.cuda, 'available', torch.cuda.is_available(), torch.cuda.get_device_name(0)); print('transformers', transformers.__version__, 'peft', peft.__version__)"

if [ -f "$ML/cluster/env-record/pip-freeze.txt" ]; then
  echo "--- diff against committed freeze (empty means identical) ---"
  diff "$ML/cluster/env-record/pip-freeze.txt" "$RECORD/pip-freeze.txt" && echo "IDENTICAL"
fi
