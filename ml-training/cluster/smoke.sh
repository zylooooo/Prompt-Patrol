#!/bin/bash
# Smoke run: dry-check the wiring, then run one config end to end and log it to
# DagsHub MLflow. Defaults to TRIAL (RoBERTa LoRA on the 340-row trial corpus,
# a pipeline check whose numbers are never cited).
#
#   cd ~/<yourname> && sbatch Prompt-Patrol/ml-training/cluster/smoke.sh
#   cd ~/<yourname> && sbatch Prompt-Patrol/ml-training/cluster/smoke.sh ROBERTA_LORA
#
# Needs your own ml-training/.env and DVC credentials (see cluster/setup_me.sh).
#SBATCH --job-name=trial-smoke
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=%u.%j.out

CONFIG=${1:-TRIAL}

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0
source "$HOME/venvs/prompt-patrol/bin/activate"

cd "$SLURM_SUBMIT_DIR/Prompt-Patrol/ml-training"
python trial-training.py "$CONFIG" --inspect && python trial-training.py "$CONFIG"
