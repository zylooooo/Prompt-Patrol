#!/bin/bash
# Small hyperparameter sweep for the desklib LoRA run: learning rate x rank,
# one job, runs back to back (the group may only have one job running).
# The default config (lr 1e-4, r 16) already ran, so it is skipped here.
# Runs are tagged run_role=sweep and ranked by VALIDATION AUROC only.
#
#   cd ~/malcolm && sbatch Prompt-Patrol/ml-training/cluster/sweep_desklib.sh
#
# Override the repo location with PP_DIR=... as in run_py.sh.
#SBATCH --job-name=pp-sweep
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

for LR in 5e-5 1e-4 2e-4; do
  for R in 8 16 32; do
    if [ "$LR" = "1e-4" ] && [ "$R" = "16" ]; then continue; fi
    echo "################ lr=$LR r=$R ################"
    # --no-baseline: the untouched-model score is already known and identical every run
    python finetune_desklib_lora.py --run-role sweep --no-baseline \
      --lr "$LR" --r "$R" --alpha $((2 * R)) \
      --run-name "desklib-lora-sweep-lr${LR}-r${R}" || echo "run lr=$LR r=$R FAILED"
  done
done

echo
echo "################ SWEEP SUMMARY (ranked by val AUROC) ################"
python - <<'EOF'
import json, glob
rows = []
for f in glob.glob("outputs/desklib-lora-sweep-*_results.json"):
    d = json.load(open(f))
    a, t = d["args"], d["tuned"]
    rows.append((t["best_val_auroc"], a["lr"], a["r"], t["best_epoch"], t["temperature"]))
rows.sort(reverse=True)
print(f"{'val_auroc':>9} {'lr':>8} {'r':>3} {'epoch':>5} {'T':>6}")
for v, lr, r, ep, T in rows:
    print(f"{v:9.4f} {lr:8.0e} {r:3d} {ep:5d} {T:6.2f}")
print("\nreference (already run): val_auroc 0.9172  lr 1e-04  r 16  epoch 3")
EOF
