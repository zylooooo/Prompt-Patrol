#!/bin/bash
# Generic GPU job: run any ml-training script on one GPU. The script name and
# its arguments are passed straight through, so a new script needs no new .sh.
#
#   cd ~/<yourname> && sbatch Prompt-Patrol/ml-training/cluster/run_py.sh eval_desklib_zeroshot.py
#   cd ~/<yourname> && sbatch Prompt-Patrol/ml-training/cluster/run_py.sh finetune_desklib_lora.py --train-on mohler
#
# Slurm copies this file when the job starts, so the repo location cannot be
# derived from $0. It defaults to ~/malcolm/Prompt-Patrol; override with
#   PP_DIR=$HOME/<yourname>/Prompt-Patrol sbatch --export=ALL,PP_DIR ... run_py.sh <script>
# The log lands in the folder you ran sbatch from: <user>.<jobid>.out
#SBATCH --job-name=pp-run
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=%u.%j.out

if [ $# -lt 1 ]; then
  echo "usage: sbatch run_py.sh <script.py> [args...]" >&2
  exit 1
fi

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0
source "$HOME/venvs/prompt-patrol/bin/activate"

cd "${PP_DIR:-$HOME/malcolm/Prompt-Patrol}/ml-training"
python "$@"
