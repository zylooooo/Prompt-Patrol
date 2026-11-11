#!/bin/bash
# Confirm sweep candidates with several seeds. The sweep (sweep_desklib_extended.sh) ranks 12 settings
# with ONE seed each, which is a coarse screen; this re-runs the chosen cells with seeds 1 2 3 so they can be
# compared with the current setting (q+v, r64, 5 epochs; extended_desklib.sh, model name `desklib-lora`).
# Still LoRA, lr 2e-4, alpha = 2 x rank, extended corpus, 10+ words, run_role=train (these are results).
#
# Each cell is TAG:RANK:EPOCHS, TAG one of qv, qkv, qkvf (the layers that get an adapter, see the sweep):
#   cd ~/malcolm && sbatch Prompt-Patrol/ml-training/cluster/confirm_desklib_extended.sh
#   CELLS="qkv:64:8 qkvf:64:8" SEEDS="1 2 3" sbatch ...      # the defaults
#
# Every cell gets its own model name, desklib-lora-<tag>-r<R>-e<E>, so the harness keeps settings apart; the
# seeds of one cell share it. Choose between settings by VALIDATION (printed first), then look at test.
# Needs `dvc pull` in ml-training/ first. Override the repo location with PP_DIR=... as in run_py.sh.
# Finished runs keep their files if the job hits its time limit; rerun only the missing seeds.
#SBATCH --job-name=pp-confirm
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
CELLS="${CELLS:-qkv:64:8 qkvf:64:8}"
SEEDS="${SEEDS:-1 2 3}"
declare -A TARGETS=(
  [qv]="query_proj,value_proj"
  [qkv]="query_proj,key_proj,value_proj"
  [qkvf]="query_proj,key_proj,value_proj,intermediate.dense,output.dense"
)

for CELL in $CELLS; do
  IFS=: read -r TAG R E <<< "$CELL"
  if [ -z "${TARGETS[$TAG]}" ] || [ -z "$R" ] || [ -z "$E" ]; then
    echo "bad cell '$CELL' (want TAG:RANK:EPOCHS with TAG qv, qkv or qkvf)"; continue
  fi
  MODEL="desklib-lora-${TAG}-r${R}-e${E}"
  for S in $SEEDS; do
    echo "################ $MODEL seed $S ################"
    # --no-baseline: the untouched model is already scored in the extended_desklib.sh runs
    python finetune_desklib_lora.py --data extended --min-words 10 --no-baseline \
      --lr "$LR" --r "$R" --alpha $((2 * R)) --epochs "$E" --targets "${TARGETS[$TAG]}" \
      --seed "$S" --model-name "$MODEL" --run-name "desklib-lora-confirm-${TAG}-r${R}-e${E}-s${S}" \
      || echo "run $MODEL seed $S FAILED"
  done
done

echo
echo "################ CONFIRMATION SUMMARY ################"
python - <<'EOF'
import glob
import harness

files = (sorted(glob.glob("outputs/desklib-lora-extended-s*_scores.parquet"))
         + sorted(glob.glob("outputs/desklib-lora-confirm-*_scores.parquet")))
df = harness.load_runs(files)
fmt = lambda x: f"{x:.4f}"

print("--- VALIDATION (choose the setting here): mean and std over seeds ---")
val = harness.validation_table(df)
print(val.groupby("model")[["val_auroc", "val_tpr"]].agg(["count", "mean", "std"]).to_string(float_format=fmt))

print("\n--- TEST, 10+ words: mean and std over seeds ---")
table = harness.compare_models(df, bootstrap_n=200, min_words=(harness.MIN_WORDS,))
cols = ["model", "n_runs", "deployed_tpr_mean", "deployed_tpr_std", "deployed_fpr_mean",
        "oracle_tpr_at_fpr_0.01_mean", "auroc_mean", "auroc_std"]
print(harness.aggregate_seeds(table)[cols].to_string(index=False, float_format=fmt))

print("\n--- each candidate minus the current setting (desklib-lora), deployed TPR ---")
for model in sorted(set(df["model"]) - {"desklib-lora", "desklib-untouched"}):
    r = harness.compare_pair(df, model, "desklib-lora", bootstrap_n=200)
    print(f"{model}: diff {r['diff']:+.4f}  95% CI [{r['ci_low']:+.4f}, {r['ci_high']:+.4f}]  "
          f"runs {r['n_runs_a']} vs {r['n_runs_b']}  clear={r['gap_is_clear']}")
EOF
