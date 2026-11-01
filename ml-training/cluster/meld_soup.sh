#!/bin/bash
#SBATCH --job-name=pp-meld-soup
#SBATCH --partition=project
#SBATCH --account=cs480
#SBATCH --qos=cs480qos
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --output=%u.%j.out
# MELD "soups": several fine-tuned MELD seeds averaged into ONE model (soup_meld_lora.py). Trains nothing; it
# downloads each member's adapter and head from DagsHub (or uses outputs/), scores val and test, and logs a run.
#
#   1. a check: seed 1 rebuilt alone must reproduce its own saved val scores. If it prints MISMATCH, stop - the
#      merge is wrong and the soups below mean nothing;
#   2. the pair soups, numbered like the score-average control in analyse_ensemble.py: soup s = seeds s and s+1;
#   3. the soup of all three seeds.
#
#   cd ~/tori && sbatch Prompt-Patrol/ml-training/cluster/meld_soup.sh
#   BASE=meld-lora-lr1e-4-qkvo-r32-e3-d0.10-extended sbatch ...   # soups of another 3-seed MELD setting
#
# Then compare, on the login node or locally (scores files come from DagsHub):
#   python analyse_ensemble.py --extra "MELD soup (pair)=meld-lora-soup-pair" \
#       --extra "MELD soup (3)=meld-lora-soup-all@1" --out outputs/analysis/soups
#
# Override the repo location with PP_DIR=... as in run_py.sh.

set -u

module purge
module load Python/3.11.11-GCCcore-13.3.0
module load CUDA/12.4.0
source "$HOME/venvs/prompt-patrol/bin/activate"

cd "${PP_DIR:-$SLURM_SUBMIT_DIR/Prompt-Patrol}/ml-training" || exit 1
export PYTHONUNBUFFERED=1
echo "branch $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)$(git diff --quiet || echo ' (UNCOMMITTED CHANGES)')"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "no GPU visible"

BASE="${BASE:-meld-lora-extended}"
# soups of the default base keep the short names; another base gets its own prefix
PREFIX="${PREFIX:-meld-lora-soup}"
[ "$BASE" != "meld-lora-extended" ] && PREFIX="${PREFIX}-${BASE%-extended}"
OWNER="${OWNER:-tori}"

echo "################ check: rebuild $BASE-s1 alone ################"
python soup_meld_lora.py --runs "$BASE-s1" --check --offline | tee /dev/stderr | grep -q "OK" || {
  echo "the rebuilt seed 1 does not reproduce its saved scores; not running the soups" >&2
  exit 1
}

for S in 1 2 3; do
  NEXT=$(( S % 3 + 1 ))
  echo "################ soup of seeds $S and $NEXT ################"
  python soup_meld_lora.py --runs "$BASE-s$S,$BASE-s$NEXT" --seed "$S" --owner "$OWNER" \
    --model-name "$PREFIX-pair" --run-name "$PREFIX-pair-s$S" || echo "pair soup $S FAILED"
done

echo "################ soup of seeds 1, 2 and 3 ################"
python soup_meld_lora.py --runs "$BASE-s1,$BASE-s2,$BASE-s3" --seed 1 --owner "$OWNER" \
  --model-name "$PREFIX-all" --run-name "$PREFIX-all-s1" || echo "3-seed soup FAILED"

ls -l outputs/"$PREFIX"-*_scores.parquet
