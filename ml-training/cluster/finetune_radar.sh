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
##  LoRA sweep -> "sweep" first. one LoRA run per learning rate x rank x dropout (alpha = 2 x rank), seed 1 by default,
##  tagged run_role=sweep. each setting gets its own --model-name (radar-lora-sw-lr<lr>-r<rank>-d<dropout>), and the log ends
##  with every sweep run so far ranked on VALIDATION ONLY (partial AUROC at 1% FPR, then val AUROC). test is never used to pick.
##  the full grid (3 x 3 x 2 = 18 runs, ~5 min each) doesn't fit one 2-hour job, so split it by learning rate across jobs:
##      LRS="1e-4 2e-4" sbatch Prompt-Patrol/ml-training/cluster/finetune_radar.sh sweep
##      LRS="4e-4"      sbatch Prompt-Patrol/ml-training/cluster/finetune_radar.sh sweep
##  defaults: LRS="1e-4 2e-4 4e-4", RANKS="16 32 64", DROPOUTS="0.05 0.1", SEEDS="1". then run the winners with seeds 1 2 3
##  as normal runs, keeping their --model-name, e.g.:
##      sbatch Prompt-Patrol/ml-training/cluster/finetune_radar.sh --method lora --lr 4e-4 --r 64 --alpha 128 --dropout 0.1 \
##          --model-name radar-lora-sw-lr4e-4-r64-d0.1
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

##  python holds back output written to a file, so without this the log stays silent until a run ends. this makes `tail -f` live
export PYTHONUNBUFFERED=1

##  what ran where, at the top of the log: the commit and branch (DagsHub tags them too), and the GPU
echo "branch $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)$(git diff --quiet || echo ' (UNCOMMITTED CHANGES)')"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "no GPU visible"

MODE=runs
if [ "$1" = "final" ] || [ "$1" = "sweep" ]; then
    MODE="$1"
    shift
fi

##  the LoRA grid: one run per learning rate x rank x dropout, then every sweep run so far ranked on validation
if [ "$MODE" = "sweep" ]; then
    SEEDS="${SEEDS:-1}"
    for LR in ${LRS:-1e-4 2e-4 4e-4}; do
        for R in ${RANKS:-16 32 64}; do
            for D in ${DROPOUTS:-0.05 0.1}; do
                for S in $SEEDS; do
                    NAME="radar-lora-sw-lr${LR}-r${R}-d${D}"
                    echo "################ sweep: lr $LR, rank $R, dropout $D, seed $S ################"
                    python finetune_radar.py "$@" --method lora --lr "$LR" --r "$R" --alpha "$((2 * R))" --dropout "$D" \
                        --seed "$S" --run-role sweep --model-name "$NAME" || echo "$NAME seed $S FAILED"
                done
            done
        done
    done

    echo "################ every sweep run so far, ranked on VALIDATION (answers >= 10 words) ################"
    python - <<'EOF'
import glob, json

rows = []
for path in glob.glob("outputs/radar-lora-sw-*_results.json"):
    run = json.load(open(path))
    best = run["history"][run["thresholds"]["best_epoch"] - 1]
    rows.append((best["val_pauroc"], best["val_auroc"], run["thresholds"]["best_epoch"], run["run"]))
# like finetune_radar.py's epoch choice: partial AUROCs within 0.002 count as tied, and the higher val AUROC wins the tie.
# sort by partial AUROC, then swap neighbours that are tied but in the wrong AUROC order until none are left
rows.sort(reverse=True)
swapped = True
while swapped:
    swapped = False
    for i in range(len(rows) - 1):
        if rows[i][0] - rows[i + 1][0] <= 0.002 and rows[i + 1][1] > rows[i][1]:
            rows[i], rows[i + 1] = rows[i + 1], rows[i]
            swapped = True
for pauroc, auroc, epoch, name in rows:
    print(f"  val partial AUROC@1% {pauroc:.4f}  val AUROC {auroc:.4f}  best epoch {epoch}  {name}")
EOF
    exit 0
fi

SEEDS="${SEEDS:-1 2 3}"
FINAL=0
if [ "$MODE" = "final" ]; then
    FINAL=1
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
