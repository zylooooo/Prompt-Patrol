# desklib + MELD: next experiments (planned 1 Nov 2026)

Follow-up to [radar-and-ensemble-experiments.md](radar-and-ensemble-experiments.md) §10–11, where desklib best +
MELD averaged 50/50 gave the best result so far (test AUROC 0.978, 72.7% of AI caught at exactly 1% FPR). This plan
says what to run next, in what order, how each result will be judged, and which script does it. Results go in
[desklib-meld-experiment-results.md](desklib-meld-experiment-results.md) as each experiment finishes (E1 and E2 done 1 Nov; MELD stays at rank 16. E3, E4 and the desklib reference rerun done
3 Nov; MELD moves to the Oct release, and Mohler weighting is not adopted. The new MELD baseline and E5 done 4 Nov; epoch selection stays on val AUROC,
the release is a tie, E5a is not adopted and E5b awaits a seed-2 rerun. 5 Nov: E5b adopted on 3 seeds; E6 skipped
for now; E7 done, final pair desklib reference rerun + MELD 3-seed soup).

Same protocol as before: extended corpus `v0.1-extended`, answers of 10+ words, threshold fitted on val at 1% FPR
and frozen, 3 seeds, and paired intervals that resample whole questions. **Every choice below is made on val.**
Test is read once per experiment, for the report.

## What the re-analysis found (from the existing scores files, nothing retrained)

`analyse_ensemble.py` with the default models reproduces §10 exactly, and adds controls that §10 didn't have:

| Test, 3 seeds | AUROC | AI caught at exactly 1% FPR | Spread over seeds |
| --- | --- | --- | --- |
| desklib best (`desklib-lora-confirm-qkvf-r64-e8`) | 0.970 | 64.0% | sd 4.6 pts |
| MELD (`meld-lora-extended`) | 0.971 | 62.0% | sd 9.7 pts (51% to 70%) |
| desklib + MELD, 50/50 | 0.978 | 72.7% | sd 2.7 pts |
| control: two desklib seeds averaged | 0.974 | 67.4% | |
| **control: two MELD seeds averaged** | 0.975 | **72.3%** | sd 2.8 pts |

1. **Most of the gain at 1% FPR is averaging, not desklib's evidence.** desklib + MELD minus two MELD seeds:
   +0.4 pts [−4.0, +7.3] at exactly 1% FPR, which could be noise. AUROC is +0.0025 [+0.0011, +0.0044], a real but small
   gain. desklib's own contribution shows on short answers (10–20 words), raw AI and edited AI.
2. **MELD's seeds are the weak point.** The same recipe gives 51% to 70% at 1% FPR depending on the seed.
3. **Every student wrongly flagged on test is in Mohler**: 1.5% of Mohler students, about 0% in SPRAG and EngSAF.
   Requiring at most 1% in every dataset on val costs 70% → 57% of AI caught.
4. **The weight doesn't need tuning.** Test is flat from 50% to 80% MELD (also in §11). Stacking, max and min rules
   were no better.
5. **Val and test have very different mixes.** Spliced answers are 5% of val and 23% of test, so val numbers run
   higher than test.

## Experiments, in order

| # | Question | How | Cost (RTX 3090) |
| --- | --- | --- | --- |
| **E1** | Can one MELD model give what two MELD seeds' scores give? | **Soups**: average seeds' merged LoRA updates and heads into one model. Pair soups (s1+s2, s2+s3, s3+s1) and a soup of all 3. No training | ~40 min, one job |
| **E2** | Is rank 32, the winner of MELD's old-corpus stage-2 sweep, better on extended? | `sweep_meld_extended.sh`, 3 seeds, dropout kept at 0.05 | ~1 h 45 |
| **E3** | Is the Oct MELD release better? Seed 1 alone was +4.9 pts at 1% FPR | Seeds 2 and 3 of the existing Oct run | ~1 h 10 |
| **E4** | Do fewer Mohler students get flagged if their answers count double in training? | `--weights 'dataset=mohler&slice=human:2'`, desklib (E4a) and MELD (E4b), 3 seeds each | 30 min + 1 h 45 |
| **E5** | Do the weak slices improve if spliced and paraphrased AI count double? | `--weights 'slice=spliced-*:2,slice=paraphrased-*:2'`, desklib (E5a) and MELD (E5b) | 30 min + 1 h 45 |
| **E6** | How much is lost on a course the model never saw? | Leave one dataset out, both models, 3 held-out datasets | ~1 h desklib, ~2–4 h per MELD job |
| **E7** | Final combination | `analyse_ensemble.py` with the best desklib and best MELD chosen on val, plus the soups | Local, minutes |

**Why E2 changes only the rank:** the extended MELD runs used the script's defaults (rank 16, dropout 0.05), which
are stage 1's recipe. Stage 2 on the old corpus (`sweep_meld_stage2.sh`, 2 seeds) then found rank 32 better on val
AUROC (0.965 vs 0.961), with dropout 0.05 and 0.10 tied at either rank. That result was never carried over. Keeping
dropout at 0.05 means E2 differs from `meld-lora-extended` in one setting only.

**About the weights:** each class's weights are rescaled to average 1, so the human and AI classes stay balanced.
Doubling Mohler's humans therefore *takes* weight from the other humans: Mohler 1.31, SPRAG and EngSAF 0.66. For AI:
spliced and paraphrased 1.5, raw and edited AI 0.75.

E1 needs no GPU training and decides how to read E2–E5, so it goes first. The group can have only one job running
at a time, so the order also keeps the queue short.

### How each is judged (decided now, before the results)

- **E1** succeeds if the pair soup's mean over 3 is within noise of the score-average control (72.3%) *and* clearly
  above a single MELD seed (62.0%). Then MELD in the detector ships as a soup, at one model's cost. If the soup only
  matches a single seed, weight averaging doesn't transfer here, and the plan stays desklib + MELD.
  - The job first rebuilds seed 1 alone and checks it reproduces that run's saved val logits. On a mismatch it stops.
- **E2 and E3**: adopt the setting only if its **val** AUROC mean beats `meld-lora-extended` (0.976). Then report
  test against it with `analyse_ensemble.py --extra`.
- **E4**: success is a lower Mohler false-flag rate on val (`dataset_fpr.png`) with AI caught at 1% FPR down by at
  most ~2 pts.
- **E5**: success is higher spliced-25/50 and paraphrased TPR on val with the same overall val AUROC.
- **Failed runs** (added 4 Nov, before any rerun): a run counts as failed if its train loss after epoch 1 is above
  0.69 (worse than guessing) or its val AUROC never reaches 0.90. A failed run is rerun once, under the same name and
  seed; the analysis takes the newest finished run of a name. The failed run's ID is recorded in the results. If the
  rerun also fails, the setting is reported as unstable, with the failure count. Applies first to E5b seed 2
  (`meld-lora-lr1e-4-qkvo-r16-e3-revddfc9c78-pauroc-hardai-extended-s2`).
- **E7** (added 5 Nov, before any test read; E6 skipped for now): `pick_final.py` pairs every desklib setting with
  every MELD setting and soup, 50/50, and reads **val only**. A setting with any seed under val AUROC 0.90 is dropped
  (the failed-run rule). Pairs rank by mean val AUROC. Near-ties: among pairs within 0.001 of the best (about one
  seed's spread), the highest-ranked pair with no setting rejected by its own experiment wins (E2 rank 32, E4a, E4b,
  E5a, epoch by partial AUROC); if every such pair has one, the top pair. Val TPR at 1% FPR is reported, not used.
  The winner is then read on test once with `analyse_ensemble.py`. Runs once the E5b seed-2 rerun is back.
- **E6** is descriptive: report each held-out dataset's AUROC, and whether its FPR stays at or under 1% at the
  threshold fitted on the other two.

## Commands

From your folder on the cluster (`cd ~/<you>`), with the branch checked out and `dvc pull` done. Check your
`--time` against the cost column.

```bash
# E1 soups: check, 3 pair soups, the 3-seed soup
sbatch Prompt-Patrol/ml-training/cluster/meld_soup.sh

# E2 MELD rank 32 (dropout stays 0.05), Sep release, 3 seeds
LR=1e-4 R=32 EPOCHS=3 TARGETS=Wqkv,Wo SELECT=auroc ROLE=train SEEDS="1 2 3" OWNER=<you> \
  sbatch --time=03:00:00 Prompt-Patrol/ml-training/cluster/sweep_meld_extended.sh

# E3 Oct release, seeds 2 and 3 (ROLE=sweep keeps the seed-1 run's name)
LR=1e-4 R=16 EPOCHS=3 TARGETS=Wqkv,Wo SELECT=auroc SEEDS="2 3" OWNER=<you> \
  REVISION=ddfc9c789b8c8d0f92d3774265316d418c96dc67 \
  sbatch --time=02:30:00 Prompt-Patrol/ml-training/cluster/sweep_meld_extended.sh

# E4a / E5a desklib, and E4b / E5b MELD
WEIGHTS='dataset=mohler&slice=human:2' TAG=mohlerneg sbatch Prompt-Patrol/ml-training/cluster/desklib_experiment.sh
WEIGHTS='slice=spliced-*:2,slice=paraphrased-*:2' TAG=hardai sbatch Prompt-Patrol/ml-training/cluster/desklib_experiment.sh
LR=1e-4 R=16 EPOCHS=3 TARGETS=Wqkv,Wo SELECT=auroc ROLE=train SEEDS="1 2 3" OWNER=<you> \
  WEIGHTS='dataset=mohler&slice=human:2' TAG=mohlerneg \
  sbatch --time=03:00:00 Prompt-Patrol/ml-training/cluster/sweep_meld_extended.sh
# (and the same with WEIGHTS='slice=spliced-*:2,slice=paraphrased-*:2' TAG=hardai)

# E6 leave one dataset out: one job per family and held-out dataset
FAMILY=desklib HOLDOUT=engsaf sbatch Prompt-Patrol/ml-training/cluster/lodo.sh
FAMILY=meld HOLDOUT=engsaf sbatch --time=04:00:00 Prompt-Patrol/ml-training/cluster/lodo.sh
# ... HOLDOUT=sprag, HOLDOUT=mohler (MELD on mohler: --time=08:00:00)
```

**desklib reference rerun:** the E4a/E5a weighted runs are compared against
`desklib_experiment.sh` with no `WEIGHTS`. That rerun has the same recipe as `desklib-lora-confirm-qkvf-r64-e8`, but
it also logs the new training curves and its adapter, which the confirm runs didn't. Run it once, before or with E4a.

**Analysis** (locally or on the login node; scores files download from DagsHub):

```bash
cd ml-training
python analyse_ensemble.py --out outputs/analysis/baseline                       # the table above
python analyse_ensemble.py --extra "MELD soup (pair)=meld-lora-soup-pair" \
    --extra "MELD soup (3)=meld-lora-soup-all@1" --out outputs/analysis/E1-soups
python analyse_ensemble.py --extra "MELD r32=meld-lora-lr1e-4-qkvo-r32-e3-extended" --out outputs/analysis/E2
python analyse_ensemble.py --extra "MELD Oct=meld-lora-sw-lr1e-4-qkvo-r16-e3-revddfc9c78-extended" --out outputs/analysis/E3
python analyse_ensemble.py --a desklib-lora-qkvf-r64-e8-mohlerneg-extended --out outputs/analysis/E4a
python analyse_ensemble.py --b meld-lora-lr1e-4-qkvo-r16-e3-mohlerneg-extended --out outputs/analysis/E4b
```

## What each run leaves behind for later analysis

| Where | What |
| --- | --- |
| MLflow run, per epoch | `train/loss`, `val/loss`, `val/auroc`, `val/pauroc`, `val/tpr_at_fpr_0.01`, learning rate, epoch time. **desklib now logs these too** |
| `plots/` (both families) | `training_curves.png`, with a new panel for val partial AUROC and TPR at 1% FPR per epoch, plus `roc.png`, `precision_recall.png`, `calibration.png`, `score_distribution.png`, `slice_metrics.png`, `ppv_by_prevalence.png` |
| `charts/` (both families) | the same data as CSVs: training history, curves, calibration bins, slice metrics, PPV by prevalence |
| `predictions/` | the scores file every analysis reads |
| `model/` | MELD adapter and head (always); desklib adapter (`desklib_experiment.sh` passes `--log-adapter`) |
| `analyse_ensemble.py --out` | `rules.csv`, `paired.csv`, `weight_curve.png`, `roc_low_fpr.png`, `seed_spread.png`, `slices.png`, `dataset_fpr.png`, `agreement.csv`, each figure with its CSV |

## Not planned, and why

- **Tuning the desklib/MELD weight, or stacking:** flat on test, and the val optimum (80% MELD) doesn't carry over.
- **Per-dataset thresholds:** a new course has no labelled answers to fit one on. E4 attacks the cause instead,
  and `strict_*` in `rules.csv` reports what a per-dataset cap would cost.
- **Rebuilding val to match test's slice mix:** that changes the corpus for every model and every earlier result.
  Raise it as a corpus v0.2 item instead.
- **MELD with desklib's bigger recipe:** §13 showed it overfits.
