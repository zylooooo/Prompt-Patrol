#!/bin/bash
## runs finetune_radar.py on the SCIS GPU. every option after the script name goes straight to finetune_radar.py
##
##  submit from your own folder (~/faheem), which holds the Prompt-Patrol clone checked out on radar-lora:
##
##  smoke run -> pipeline check on the GPU, ~10 min, tagged run_role=smoke so report tables drop it:
##      sbatch Prompt-Patrol/ml-training/cluster/finetune_radar.sh --epochs 1 --max-train-rows 200 --run-name radar-smoke
##
##  one run -> any finetune_radar.py options, e.g. run C (improved LoRA, the defaults):
##      sbatch Prompt-Patrol/ml-training/cluster/finetune_radar.sh --method lora
##
##  run B -> desklib's recipe on RADAR, for the like-for-like row:
##      sbatch Prompt-Patrol/ml-training/cluster/finetune_radar.sh --method lora --targets query,value --r 64 --alpha 128 \
##          --dropout 0.05 --balance --no-class-weights --run-name radar-lora-desklib-recipe
##
##  final runs -> "final" first, then the chosen settings. runs in-distribution, then train on mohler / sprag / engsaf
##  (each tested on the other two), back to back in ONE job, because the group may only have 2 jobs submitted at a time:
##      sbatch Prompt-Patrol/ml-training/cluster/finetune_radar.sh final --method lora --lr 2e-4 --r 32
##
##  the log is written to ~/faheem/<user>.<jobid>.out. it ends with the MLflow run id for each run.
##  rules: max 1 running job for the whole group, so agree GPU slots with the team. never `scancel -u`.
##  PP_DIR=... overrides where the clone is (default: the folder you submitted from + /Prompt-Patrol)
#SBATCH --job-name=pp-radar
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

cd "${PP_DIR:-$SLURM_SUBMIT_DIR/Prompt-Patrol}/ml-training" || exit 1

##  what ran where, at the top of the log: the commit and branch (DagsHub tags them too), and the GPU
echo "branch $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)$(git diff --quiet || echo ' (UNCOMMITTED CHANGES)')"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "no GPU visible"

if [ "$1" = "final" ]; then
    shift
    echo "################ in-distribution ################"
    python finetune_radar.py "$@" || echo "in-distribution FAILED"

    for D in mohler sprag engsaf; do
        echo "################ train on $D, test on the other two ################"
        python finetune_radar.py "$@" --train-on "$D" || echo "train-on-$D FAILED"
    done
else
    python finetune_radar.py "$@"
fi
