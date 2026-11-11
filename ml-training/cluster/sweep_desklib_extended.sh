#!/bin/bash
# Hyperparameter sweep for the desklib LoRA run on the EXTENDED corpus. The earlier sweeps ran on the
# old corpus and their best cell sat on the edge of the grid (val AUROC still rising with rank), so this
# looks for headroom in three things that might lift TPR at 1% FPR:
#   - which layers get an adapter: q+v (current), q+k+v, q+k+v plus the feed-forward layers
#   - rank: 64 (current) and 128, with alpha = 2 x rank
#   - epochs: 5 (current) and 8 (the best epoch is restored by val AUROC, so more epochs cannot hurt val)
# 3 x 2 x 2 = 12 runs, all lr 2e-4, seed 1. Still LoRA (no DoRA).
#
# One seed per cell, so the cells are a coarse ranking: the top cells get re-run with 3 seeds afterwards.
# Runs are tagged run_role=sweep and ranked by VALIDATION only (val AUROC, with val TPR at 1% FPR as a
# check); the test split is never used to choose. The cell q+v / r64 / 5 epochs is the current setting.
#
#   cd ~/malcolm && sbatch Prompt-Patrol/ml-training/cluster/sweep_desklib_extended.sh
#
# Needs `dvc pull` in ml-training/ first. Override the repo location with PP_DIR=... as in run_py.sh.
# Finished runs keep their files if the job hits its time limit; rerun only the missing cells.
#SBATCH --job-name=pp-sweepx
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

cd "${PP_DIR:-$HOME/malcolm/Prompt-Patrol}/ml-training"

LR=2e-4
SEED=1
declare -A TARGETS=(
  [qv]="query_proj,value_proj"
  [qkv]="query_proj,key_proj,value_proj"
  [qkvf]="query_proj,key_proj,value_proj,intermediate.dense,output.dense"
)

for TAG in qv qkv qkvf; do
  for R in 64 128; do
    for E in 5 8; do
      NAME="desklib-lora-sweepx-${TAG}-r${R}-e${E}"
      echo "################ targets=$TAG r=$R epochs=$E ################"
      python finetune_desklib_lora.py --data extended --min-words 10 --run-role sweep --no-baseline \
        --lr "$LR" --r "$R" --alpha $((2 * R)) --epochs "$E" --targets "${TARGETS[$TAG]}" \
        --seed "$SEED" --run-name "$NAME" || echo "run $NAME FAILED"
    done
  done
done

echo
echo "################ SWEEP SUMMARY (validation only, ranked by val AUROC) ################"
python - <<'EOF'
import glob, json, os
import pandas as pd
import harness

PREFIX = "desklib-lora-sweepx-"
rows = []
for path in sorted(glob.glob(f"outputs/{PREFIX}*_scores.parquet")):
    name = os.path.basename(path).removesuffix("_scores.parquet")
    v = harness.validation_table(harness.load_run(path), models=["desklib-lora"]).iloc[0]
    best_epoch = json.load(open(f"outputs/{name}_results.json"))["tuned"]["best_epoch"]
    rows.append({"setting": name.removeprefix(PREFIX), "best_epoch": best_epoch,
                 "val_auroc": v["val_auroc"], "val_tpr": v["val_tpr"], "val_fpr": v["val_fpr"]})
if rows:
    table = pd.DataFrame(rows).sort_values("val_auroc", ascending=False)
    print(table.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
else:
    print("no finished runs found")

ref = "outputs/desklib-lora-extended-s1_scores.parquet"
if os.path.exists(ref):
    r = harness.validation_table(harness.load_run(ref), models=["desklib-lora"]).iloc[0]
    print(f"\nsame setting as cell qv-r64-e5, run earlier as extended seed 1: "
          f"val_auroc {r['val_auroc']:.4f}  val_tpr {r['val_tpr']:.4f}  val_fpr {r['val_fpr']:.4f}"
          f"\n(the gap between that run and the qv-r64-e5 cell above is the noise floor for a repeat of one setting)")
EOF
