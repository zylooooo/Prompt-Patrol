#!/bin/bash
# Second hyperparameter round for the desklib LoRA run. Round 1 (sweep_desklib.sh)
# found val AUROC rising with both learning rate and rank, the best cell sitting on
# the edge of the grid (lr 2e-4, r 32), and every run still improving at its last
# epoch (3). This round extends past those edges: lr {2e-4, 4e-4} x r {32, 64},
# trained for 5 epochs. Ranked by VALIDATION AUROC only. Round-1 best for reference:
# lr 2e-4, r 32, 3 epochs, val AUROC 0.9443.
#
#   cd ~/malcolm && sbatch Prompt-Patrol/ml-training/cluster/sweep_desklib_round2.sh
#
# Override the repo location with PP_DIR=... as in run_py.sh.
#SBATCH --job-name=pp-sweep2
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

EPOCHS=5
for LR in 2e-4 4e-4; do
  for R in 32 64; do
    echo "################ lr=$LR r=$R epochs=$EPOCHS ################"
    python finetune_desklib_lora.py --run-role sweep --no-baseline \
      --lr "$LR" --r "$R" --alpha $((2 * R)) --epochs "$EPOCHS" \
      --run-name "desklib-lora-sweep2-lr${LR}-r${R}-e${EPOCHS}" || echo "run lr=$LR r=$R FAILED"
  done
done

echo
echo "################ SWEEP ROUND 2 SUMMARY (ranked by val AUROC) ################"
python - <<'EOF'
import json, glob
rows = []
for f in glob.glob("outputs/desklib-lora-sweep2-*_results.json"):
    d = json.load(open(f))
    a, t = d["args"], d["tuned"]
    rows.append((t["best_val_auroc"], a["lr"], a["r"], a["epochs"], t["best_epoch"], t["temperature"]))
rows.sort(reverse=True)
print(f"{'val_auroc':>9} {'lr':>8} {'r':>3} {'epochs':>6} {'best_ep':>7} {'T':>6}")
for v, lr, r, ne, ep, T in rows:
    print(f"{v:9.4f} {lr:8.0e} {r:3d} {ne:6d} {ep:7d} {T:6.2f}")
print("\nround-1 best (already run): val_auroc 0.9443  lr 2e-04  r 32  epochs 3  best_ep 3")
EOF
