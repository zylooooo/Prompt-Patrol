#!/bin/bash
## runs finetune_radar.py on the SCIS GPU, once per seed. every option after the script name goes straight to finetune_radar.py
##
##  the team rules: at least 3 seeds per setting (SEEDS, default "1 2 3"), the seed in the run name (finetune_radar.py adds
##  -s<seed> itself, e.g. radar-lora-extended-s1), the extended corpus and --min-words 10 (both finetune_radar.py's defaults)
##
##  submit from your own folder (~/faheem), which holds the Prompt-Patrol clone checked out on radar-lora:
##
##  smoke run -> pipeline check on the GPU, one seed, tagged run_role=smoke so report tables drop it:
##      SEEDS=1 sbatch Prompt-Patrol/ml-training/cluster/finetune_radar.sh --epochs 1 --max-train-rows 200 --model-name radar-smoke
##
##  one setting, seeds 1 2 3 -> e.g. run C (improved LoRA, the defaults):
##      sbatch Prompt-Patrol/ml-training/cluster/finetune_radar.sh --method lora
##
##  run B -> desklib's recipe on RADAR, for the like-for-like row (its own --model-name so the harness keeps it apart):
##      sbatch Prompt-Patrol/ml-training/cluster/finetune_radar.sh --method lora --targets query,value --r 64 --alpha 128 \
##          --dropout 0.05 --balance --no-class-weights --model-name radar-lora-desklib-recipe
##
##  final runs -> "final" first, then the chosen settings. for each seed: in-distribution, then train on mohler / sprag / engsaf
##  (each tested on the other two). that is 4 runs per seed, so give each seed its own job to stay inside the 2-hour limit:
##      SEEDS=1 sbatch Prompt-Patrol/ml-training/cluster/finetune_radar.sh final --method lora
##
##  the log is written to ~/faheem/<user>.<jobid>.out. it ends with the MLflow run id for each run.
##  rules: max 1 running and 2 submitted jobs for the whole group, so agree GPU slots with the team. never `scancel -u`.
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

SEEDS="${SEEDS:-1 2 3}"
FINAL=0
if [ "$1" = "final" ]; then
    FINAL=1
    shift
fi

for S in $SEEDS; do
    if [ "$FINAL" = 1 ]; then
        echo "################ seed $S: in-distribution ################"
        python finetune_radar.py "$@" --seed "$S" || echo "seed $S in-distribution FAILED"

        for D in mohler sprag engsaf; do
            echo "################ seed $S: train on $D, test on the other two ################"
            python finetune_radar.py "$@" --seed "$S" --train-on "$D" || echo "seed $S train-on-$D FAILED"
        done
    else
        echo "################ seed $S ################"
        python finetune_radar.py "$@" --seed "$S" || echo "seed $S FAILED"
    fi
done

ls -l outputs/*_scores.parquet 2>/dev/null | tail -n 12
