#!/bin/bash
#SBATCH --job-name=pp-meld-sweep
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=%u.%j.out
# MELD LoRA with desklib's winning recipe, on the EXTENDED corpus: LoRA on every linear layer (Wqkv, Wo and the
# MLP's Wi; Wo matches both attn.Wo and mlp.Wo), rank 64 (alpha 128), up to 8 epochs, and the epoch picked by
# partial AUROC at 1% FPR on val answers of >= 10 words (--select pauroc). The current MELD runs
# (extended_meld.sh) use Wqkv,Wo, rank 16 and 3 epochs, picked by plain val AUROC.
#
# One learning rate per job, so each run fits the 2-hour limit (~10 min per epoch on a 3090; lower EPOCHS if the
# first epochs log much slower). Sweep runs are seed 1, tagged run_role=sweep, named meld-lora-sw-...; the log ends
# with every sweep run so far ranked on VALIDATION ONLY:
#
#   cd ~/faheem && LR=1e-4 sbatch Prompt-Patrol/ml-training/cluster/sweep_meld_extended.sh
#   cd ~/faheem && LR=2e-4 sbatch Prompt-Patrol/ml-training/cluster/sweep_meld_extended.sh
#
# Then the winner with three seeds, one seed per job, as normal runs (named meld-lora-qkvoi-r64-...):
#
#   cd ~/faheem && LR=1e-4 ROLE=train SEEDS=1 sbatch Prompt-Patrol/ml-training/cluster/sweep_meld_extended.sh
#
# Other settings via the environment: R, DROPOUT, EPOCHS, TARGETS, SELECT (pauroc or auroc) and REVISION (a MELD
# checkpoint on the HF Hub; default the 23 Sep release). E.g. Tori's recipe on the 27 Oct release, one seed:
#
#   cd ~/faheem && LR=1e-4 R=16 EPOCHS=3 TARGETS=Wqkv,Wo SELECT=auroc REVISION=ddfc9c789b8c8d0f92d3774265316d418c96dc67 \
#       sbatch Prompt-Patrol/ml-training/cluster/sweep_meld_extended.sh
#
# Skips the untouched baseline (it is in the meld-lora-extended runs already). Needs the extended corpus
# (`dvc pull` in ml-training/). Override the repo location with PP_DIR=... as in run_py.sh.

set -u

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0
source "$HOME/venvs/prompt-patrol/bin/activate"

cd "${PP_DIR:-$SLURM_SUBMIT_DIR/Prompt-Patrol}/ml-training" || exit 1
export PYTHONUNBUFFERED=1
echo "branch $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)$(git diff --quiet || echo ' (UNCOMMITTED CHANGES)')"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "no GPU visible"

LR="${LR:?set LR, e.g. LR=1e-4}"
R="${R:-64}"
ALPHA=$((2 * R))
DROPOUT="${DROPOUT:-0.05}"
EPOCHS="${EPOCHS:-8}"
TARGETS="${TARGETS:-Wqkv,Wo,Wi}"
SELECT="${SELECT:-pauroc}"
REVISION="${REVISION:-}"
ROLE="${ROLE:-sweep}"
SEEDS="${SEEDS:-1}"
OWNER="${OWNER:-faheem}"

# the targets in the name: Wqkv,Wo -> qkvo, Wqkv,Wo,Wi -> qkvoi; a non-default MELD checkpoint adds -rev<first 8 chars>
SETTING="lr${LR}-$(echo "$TARGETS" | tr -d 'W,')-r${R}-e${EPOCHS}${REVISION:+-rev${REVISION:0:8}}"
if [ "$ROLE" = "sweep" ]; then
  NAME="meld-lora-sw-$SETTING"
else
  NAME="meld-lora-$SETTING"
fi

for S in $SEEDS; do
  echo "################ MELD LoRA $NAME, extended corpus, seed $S ################"
  python finetune_meld_lora.py --device cuda --data extended --min-words 10 --no-baseline \
    --lr "$LR" --r "$R" --alpha "$ALPHA" --dropout "$DROPOUT" --targets "$TARGETS" --epochs "$EPOCHS" \
    --batch-size 1 --select "$SELECT" --seed "$S" --owner "$OWNER" --run-role "$ROLE" \
    ${REVISION:+--meld-revision "$REVISION"} \
    --model-name "$NAME" --run-name "$NAME-extended-s$S" \
    || echo "$NAME seed $S FAILED"
done

echo "################ every MELD sweep run so far, ranked on VALIDATION (answers >= 10 words) ################"
python - <<'EOF'
import glob, json

rows = []
for path in glob.glob("outputs/meld-lora-sw-*_results.json"):
    run = json.load(open(path))
    best = run["tuned"]["best_epoch"]
    epoch = run["training_history"][best - 1]
    rows.append((epoch["val_pauroc"], epoch["val_auroc_used"], best, path.split("/")[-1].removesuffix("_results.json")))
# partial AUROCs within 0.002 count as tied and the higher val AUROC wins, as in the epoch choice
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
