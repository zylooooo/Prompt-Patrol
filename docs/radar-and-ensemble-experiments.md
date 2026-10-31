# RADAR and model-combination experiments (21 Oct – 31 Oct 2026)

Faheem's detector work for Prompt Patrol: fine-tuning RADAR, building a desklib + RADAR detector, and testing
combinations of the team's tuned models (Malcolm's desklib, Tori's MELD, RADAR).

Jira: PP-547, PP-548 (subtasks PP-549 to PP-560), PP-556, PP-567 (subtasks PP-568 to PP-577). Runs: DagsHub MLflow, experiments
`zeroshot-baselines` and `E2-finetune`, run names `radar-*` and `meld-lora-sw-*`.

## Key results

| Result | Numbers (extended test set, answers of 10+ words) | Status |
| --- | --- | --- |
| RADAR fine-tuned alone | AUROC 0.950, 49.3% of AI caught at exactly 1% FPR, vs desklib best 0.970 and 64.0% (real gaps) | Not selected |
| desklib + RADAR in the detector, vs the live desklib | AI caught 63.9% vs 51.4% (+12.1 pts [+9.1, +16.0]), heavily paraphrased AI 69% vs 41%; students wrongly flagged 1.57% vs 1.18% | Built, merged to `main` (PR #76), opt-in |
| desklib best + MELD, averaged 50/50 | AUROC 0.978 vs 0.970, 72.7% vs 64.0% of AI caught at exactly 1% FPR (real gaps), students wrongly flagged 0.7% | Best result found; not built |
| desklib + MELD cost | ~2x desklib's CPU time per answer, ~7 GB memory in use (desklib alone 2.5 GB) | Measured |

## How everything was measured

The team protocol (Malcolm, 23 Oct), used for every result here unless stated:

- **Data:** extended corpus v0.1-extended (train 4,764 balanced; val 2,661; test 3,533). Test slices: human,
  raw AI, spliced 25/50/75% AI, lightly and heavily paraphrased AI, genuinely and simulated edited AI.
- **Answers of 10+ words only** for fitting and metrics, since the app doesn't score shorter answers.
- **Threshold:** fitted on val at 1% false-positive rate (FPR), frozen, then test scored once. Test was never
  used to choose anything.
- **Seeds:** 3 per setting (1, 2, 3) for anything compared or reported. Single-seed results are marked.
- **Comparisons:** Malcolm's `harness.py`. Confidence intervals resample whole questions; a gap is "real" when
  the 95% interval excludes zero.
- **Metrics:**
  - **AI caught at exactly 1% FPR** (oracle TPR): every model compared at the same false-flag rate. The fairest
    single comparison.
  - **AI caught at the val threshold** (deployed TPR), always read together with **students wrongly flagged**
    (deployed FPR). The threshold doesn't carry over to test perfectly, so this can go up just by flagging more
    students.
  - **AUROC:** overall ranking quality.
- **Combinations:** each model's temperature-scaled logit, averaged, then a sigmoid.

## 1. Scores file (21 Oct)

- **What:** `ml-training/scores.py` saves one row per val and test answer (split, answer id, question id, label,
  logit, probability) for every run, so `harness.py` can compare any runs later without re-scoring.
- **Why:** Malcolm's harness needs the same per-answer format from every model.
- **Code:** commits 743d38d, 8a16ae9, 26a2c31 (`main`).

## 2. RADAR setup and checks (25 Oct, PP-549, PP-550, PP-553)

- **Model:** `TrustSafeAI/RADAR-Vicuna-7B`, a RoBERTa-large classifier, pinned to revision `4ff1f23a`. Two
  outputs, [AI, human]; we use one logit = AI minus human.
- **Label order:** output 0 = AI, taken from the authors' own example on the model card. It can't be confirmed by
  scoring text, because untouched RADAR scores almost any modern text ~0.99 (PEP docs vs AI rewrites 0.997 vs
  0.996). Fine-tuning learns the direction from our labels, so the results don't depend on it.
- **`radar.py --check`** tests what can be tested instead:
  - every weight loads;
  - the logit equals the authors' formula (gap 7e-8);
  - scores stay attached to their answers (shuffled vs in-order gap 2e-5).
- **Code:** `ml-training/radar.py` (commits 8f08a44, 720407b).

## 3. RADAR zero-shot (25 Oct, PP-551, PP-552)

| | AUROC | AI caught at exactly 1% FPR |
| --- | --- | --- |
| RADAR untouched | 0.297 | 0.3% |
| desklib untouched | 0.669 | 4.7% |

Untouched RADAR is worse than chance on our short answers: it scores almost everything as AI (~0.95) and rates
human answers slightly more AI-like than real AI answers. It was run locally (scoring only, ~1 min). Code:
`ml-training/eval_radar_zeroshot.py`.

## 4. RADAR fine-tuning (25 Oct, PP-548, PP-554 to PP-557)

- **Settings tried**, 3 seeds each:
  - LoRA on all encoder linear layers, rank 32, lr 2e-4 (`radar-lora`);
  - desklib's recipe: LoRA on query/value, rank 64, balanced, no class weights (`radar-lora-desklib-recipe`);
  - full fine-tune with layer-wise learning-rate decay: 5 epochs, 8 epochs, 8 epochs at lr 3e-5, and 12 epochs
    with layer decay 0.95.
- **Epoch selection:** best val partial AUROC at 1% FPR; ties within 0.002 go to the higher val AUROC.
- **Results:**

| Model | AUROC | AI caught at exactly 1% FPR | AI caught, val threshold | Students wrongly flagged |
| --- | --- | --- | --- | --- |
| RADAR untouched | 0.297 | 0.3% | 0.1% | 0.0% |
| RADAR LoRA (all linear, r32) | 0.945 | n/a | 52.0% | 0.9% |
| RADAR full fine-tune, 8 epochs (best) | 0.950 | 49.3% | 56.9% | 1.3% |
| RADAR full, 12 epochs, layer decay 0.95 | 0.952 | 47.6% | 54.7% | 1.5% |
| desklib LoRA (Malcolm) | 0.963 | 58.2% | 55.0% | 0.7% |
| desklib best, qkvf r64 e8 (Malcolm) | 0.970 | 64.0% | 55.6% | 0.3% |

- **Conclusion: RADAR alone is not selected.** Against desklib best, AI caught at exactly 1% FPR is −16.4 pts
  [−35.3, −2.7] and AUROC −0.018 [−0.030, −0.009], both real gaps. Fine-tuning still took RADAR from worse than
  chance (0.30) to 0.95.
- **Not run:** train-on-one-dataset runs (PP-558). They would only describe a model that isn't being shipped.
- **Code:** `ml-training/finetune_radar.py` (`--method lora|dora|full`), `ml-training/cluster/finetune_radar.sh`.

## 5. desklib + RADAR score average (25 Oct, PP-548)

| | AUROC | AI caught at exactly 1% FPR | AI caught, val threshold | Students wrongly flagged |
| --- | --- | --- | --- | --- |
| desklib best | 0.970 | 64.0% | 55.6% | 0.3% |
| desklib best + RADAR full-e8, 50/50 | 0.970 | 65.9% | 64.9% | 0.9% |

- **AI caught at the val threshold:** +9.4 pts [+7.4, +11.7], a real gap, still within the 1% FPR target.
- **At exactly 1% FPR:** +2.0 pts [−5.4, +9.3]; AUROC +0.000.
- **Why it helps:** the combination's val threshold carries over to test better. desklib alone uses only 0.3% of
  the 1% budget. It does not rank answers better.
- **Code:** `ml-training/ensemble_scores.py`.

## 6. CPU cost of desklib + RADAR (25 Oct, PP-559)

- **Method:** `ml-training/measure_latency.py` scores 100 real test answers one at a time on CPU, cut at 256
  tokens, each setup in a fresh process, on a Mac CPU.

| | Median per answer | Answers/s | Memory in use | Peak while loading |
| --- | --- | --- | --- | --- |
| desklib | 80 ms | 12.2 | 2.5 GB | 4.2 GB |
| RADAR | 42 ms | 23.0 | 1.7 GB | 1.7 GB |
| desklib + RADAR | 118 ms | 8.3 | 3.7 GB | 4.2 GB |

- **Result:** ~1.5x desklib's time, and the detector's Fargate task would need 8 GB instead of 4 GB.
- **Caveat:** Fargate's CPU is slower than the Mac's, so read the times as a best case and the ratio as the
  result.

## 7. desklib + RADAR as a detector backend (25 Oct, PR #74, #75, #76, PP-567)

- **What:** an opt-in backend, `DETECTOR_BACKEND=ensemble`. The default stack is unchanged.
  - Code: `apps/detector/app/ensemble.py`, `Dockerfile.ensemble`, `apps/docker-compose.ensemble.yml`.
  - Each answer is cleaned once, scored by the live desklib and by RADAR with a LoRA adapter merged in, and the
    two temperature-scaled logits are averaged.
- **Calibration:** `ml-training/calibrate_ensemble.py` scores val and test with the detector's own desklib code.
  On val only, it:
  - refits RADAR's temperature;
  - picks the RADAR seed (seed 3, LoRA, stored in half precision, 29 MB);
  - fits the 1% FPR threshold (0.9028).

  It then tests once.
- **Abstention band ±0.005, chosen on val:** false flags on val drop from 1.00% to 0.85%, with 68.0% of AI
  flagged and 2.4% returned as uncertain.
- **Results** (test, against the live desklib at its deployed threshold 0.9608):

| | Live desklib | desklib + RADAR |
| --- | --- | --- |
| AI caught | 51.4% | 63.9% |
| AI caught at exactly 1% FPR | 48.7% | 60.1% |
| AUROC | 0.957 | 0.966 |
| Heavily paraphrased AI caught | 41% | 69% |
| Lightly paraphrased AI caught | 48% | 69% |
| Edited AI caught | 69% | 84% |
| Students wrongly flagged | 1.18% | 1.57% |

- **Paired gaps, all real:** AI caught +12.1 pts [+9.1, +16.0], at exactly 1% FPR +11.4 [+3.4, +27.0], AUROC
  +0.010 [+0.006, +0.015].
- **Checks:**
  - The detector reproduces the calibration's scores (max difference 5e-6, using the detector's own library
    versions), also checked in the built container.
  - 12 detector tests were added.
- **Open issue:** the test false-flag rate (1.57%) is above the 1% target.
- **Licence:** RADAR is licensed for non-commercial use only.
- **Status:** merged into `main` (PR #76, 31 Oct).

## 8. RADAR LoRA sweep (25 Oct, PP-556)

- **What:** `finetune_radar.sh sweep` ran 18 LoRA runs on seed 1 (learning rate 1e-4/2e-4/4e-4 × rank 16/32/64
  × dropout 0.05/0.1), ranked on validation only. The top 3 were then run with 3 seeds.
- **Why:** PP-556 had compared methods instead of running the full grid.
- **Top 3 on val** (partial AUROC at 1% FPR): lr 1e-4 r64 d0.05 (0.791), lr 2e-4 r32 d0.05 (0.780), lr 4e-4 r16
  d0.05 (0.770).
- **3-seed test results:**

| Setting | AUROC | AI caught at exactly 1% FPR | AI caught, val threshold | Students wrongly flagged |
| --- | --- | --- | --- | --- |
| lr 1e-4, r64, d0.05 | 0.952 | 55.8% | 51.4% | 0.8% |
| lr 2e-4, r32, d0.05 | 0.939 | | | |
| lr 4e-4, r16, d0.05 | 0.746 (unstable across seeds) | | | |

- **Conclusion:** the best setting is a small real gain over the untuned LoRA (AUROC +0.006), and still behind
  desklib best (−0.018, real).
  - Paired with desklib best, it adds +1.4 pts AI caught at the val threshold (could be noise).
  - The full fine-tune adds +7 to +9 pts in the same pairing.
- **Code:** commit 1ca47ad.

## 9. Full RADAR fine-tune in the detector (26 Oct, PP-567)

- **What:**
  - `finetune_radar.py --save-model` saves a full fine-tune in half precision (681 MB). Commit 24f7177.
  - The 8-epoch full fine-tune was rerun with 3 seeds as `radar-full-e8-saved`.
- **Against desklib best:** desklib + the rerun catches +7.0 pts more AI at the val threshold [+4.9, +9.2], with
  students wrongly flagged 0.3% → 0.9%. Every seed beats its desklib seed, and heavily paraphrased AI goes from
  66% to 77%.
- **Against the live desklib** (`calibrate_ensemble.py`, now taking full models or adapters; commit f5926e6):
  - 64.9% of AI caught and 1.97% wrongly flagged, vs the LoRA version's 63.9% and 1.57%.
  - Every difference from the LoRA version could be noise (+1.1 pts AI caught, −1.7 pts at exactly 1% FPR).
- **Not shipped:**
  - no measurable gain with the live desklib, and more false flags;
  - its 681 MB weights can't go in git, so every build would need DagsHub storage and a token.

  The detector changes for it (a download script that checks the file's hash, build secrets, loader) are kept as
  a patch.

## 10. Combinations of the team's tuned models (30 Oct, PP-567)

3 seeds each, 50/50 average, test:

| | AUROC | AI caught at exactly 1% FPR | AI caught, val threshold | Students wrongly flagged |
| --- | --- | --- | --- | --- |
| desklib best (qkvf r64 e8) | 0.970 | 64.0% | 55.6% | 0.3% |
| MELD (`meld-lora`, Tori) | 0.971 | 62.0% | 65.3% | 1.2% |
| RADAR full fine-tune | 0.949 | 54.3% | 54.1% | 1.1% |
| **desklib + MELD** | **0.978** | **72.7%** | **70.2%** | **0.7%** |
| desklib + MELD + RADAR | 0.976 | 71.3% | 67.0% | 0.7% |
| desklib + RADAR | 0.970 | 64.1% | 62.6% | 0.9% |

- **desklib + MELD minus desklib best, all real gaps:**
  - AUROC +0.008 [+0.005, +0.011];
  - AI caught at exactly 1% FPR +8.8 pts [+3.9, +13.3];
  - AI caught at the val threshold +14.6 pts [+12.4, +16.7].
- **Why it matters:** it's the only combination that improves the ranking itself, not just how well the threshold
  carries over. Adding RADAR as a third model adds nothing; it is the same kind of model as desklib.
- **By answer type, desklib best → desklib + MELD:**
  - heavily paraphrased 66% → 83%;
  - lightly paraphrased 61% → 76%;
  - raw AI 63% → 76%;
  - edited (simulated) 74% → 87%;
  - 25%-spliced 20% → 33%.
- **Also checked:** Malcolm's question-context desklib (PP-545). Giving the model the question doesn't improve
  AUROC (+0.002) or AI caught at exactly 1% FPR (−2.1 pts), both could be noise. Its +8.2 pts at the val
  threshold comes with 1.4% of students wrongly flagged.

## 11. Weighting desklib vs MELD (30 Oct, PP-567)

- **Method:** MELD's weight chosen per seed on val only. Validation picked 0.90, 0.70 and 0.75 for seeds 1 to 3.
- **Result vs 50/50 on test:** AUROC −0.0007 (real but tiny, worse), AI caught at exactly 1% FPR +0.1 pts, at the
  val threshold +1.7 pts (both could be noise).
- **Test from 50% to 80% MELD is flat:** AUROC 0.977–0.978, and AI caught at exactly 1% FPR moves by under 1 pt.
- **Conclusion:** keep 50/50. It needs nothing fitted and sits in the middle of the plateau.

## 12. MELD's CPU cost (30 Oct, PP-567)

- **Method:** `measure_latency.py` now includes `meld` and `desklib+meld` (branch `meld-latency`, commit
  a951a0a).
- **Model size:** MELD (revision `8990324`, the one Tori's runs use) has a 1B-parameter ModernBERT backbone
  (`jhu-clsp/ettin-encoder-1b`) with 4.1 GB of weights.

| 1 CPU thread | Median per answer | Answers/s | Memory in use | Peak while loading |
| --- | --- | --- | --- | --- |
| desklib | 84 ms | 11.9 | 2.5 GB | 4.2 GB |
| desklib + RADAR | 132 ms | 7.4 | 3.8 GB | 4.2 GB |
| MELD | 78 ms | 12.2 | 4.6 GB | 9.1 GB |
| desklib + MELD | 165 ms | 5.9 | 6.8 GB | 10.3 GB |

- **Speed is fine** (~2x desklib).
- **Memory is the cost.** MELD's loader briefly holds two copies of its weights, hence the 9–10 GB peak.
  desklib + MELD would need a 16 GB detector task as it loads today.
- **Smaller MELD, tested and rejected** (MELD alone, Mac CPU):
  - half precision (bfloat16 / float16): 2.6 GB in use but 17x / 10x slower;
  - 8-bit integer layers: 7x slower and no memory saving.
  - Not tested on x86, which is what Fargate uses.

## 13. MELD with desklib's recipe (30–31 Oct, PP-567)

- **Why:** desklib's best came from LoRA on more layers (including the feed-forward ones), rank 64 and 8 epochs.
  MELD's runs used rank 16, attention layers only (`Wqkv,Wo`) and 3 epochs.
- **What** (branch `meld-sweep`, from `tori/tuning`; commits 9ec7ca6, 4b61409, 2dd5fdf):
  - `finetune_meld_lora.py` gets `--select pauroc`, `--model-name` and `--offline`, all off by default.
  - `cluster/sweep_meld_extended.sh` runs the recipe: `Wqkv,Wo,Wi`, rank 64, 8 epochs.
  - Two learning rates, seed 1. 1e-4 first; 2e-4 was replaced with 5e-5 after the 1e-4 run trained unstably.

| Seed 1, test | AUROC | AI caught at exactly 1% FPR | AI caught, val threshold | Students wrongly flagged |
| --- | --- | --- | --- | --- |
| Tori's MELD (rank 16, 3 epochs) | 0.973 | 64.3% | 68.8% | 1.4% |
| lr 1e-4, rank 64 + Wi (kept epoch 2) | 0.926 | 54.0% | 63.4% | 2.1% |
| lr 5e-5, rank 64 + Wi (kept epoch 3) | 0.965 | 65.0% | 67.1% | 1.0% |
| desklib best + Tori's MELD | 0.980 | 75.1% | 69.3% | 0.7% |
| desklib best + lr 5e-5 MELD | 0.978 | 72.0% | 68.1% | 0.8% |

- **Conclusion: no gain, so the direction is stopped.**
  - lr 5e-5 ties Tori's MELD (all differences could be noise); lr 1e-4 is clearly worse.
  - Both runs overfit after epoch 3: training loss fell to 0.03–0.06 while validation loss rose.
- **Lesson:** picking MELD's epoch by partial AUROC at 1% FPR is too noisy at this val size. It jumped
  0.55–0.78 between epochs, and at 1% FPR it rests on only a few of the ~880 val human answers. Plain val AUROC is
  steadier for MELD.
- **Cost:** ~9 min per epoch on an RTX 3090, 4.7 GB of memory, ~80 min per 8-epoch run.

## 14. Sentence-level scoring for spliced answers (31 Oct, PP-567)

- **Why:** spliced answers with 25% AI sentences are the weakest slice, even for desklib + MELD (33%).
- **What:** every val answer with 2+ sentences was split at . ! ? and line breaks (6,299 sentences from 2,283
  answers), and every sentence was scored on its own. Rules tried:
  - the best sentence;
  - the average of the whole answer and the best sentence;
  - the higher of the two;
  - minimum sentence lengths of 3, 5 and 8 words.
- **Models:** MELD seed 1 (reproduces Tori's scores to 1e-4) and the live desklib. Validation only; test was never
  scored with these rules.

| Val, 10+ words | Rule | AUROC | AI caught at exactly 1% FPR | 25%-spliced caught |
| --- | --- | --- | --- | --- |
| MELD | whole answer | 0.976 | 74.7% | 33% |
| MELD | best sentence | 0.952 | 53.5% | 29% |
| MELD | average of whole and best sentence | 0.968 | 71.5% | 35% |
| desklib (live) | whole answer | 0.945 | 48.5% | 29% |
| desklib (live) | best sentence | 0.916 | 37.4% | 25% |

- **Conclusion: worse in every case, so it's dropped.**
  - Human sentences scored alone often look AI-like, so the 1% threshold rises.
  - MELD already scores token by token and keeps its most AI-like stretch.
  - Spliced answers would need a model trained on sentence-level labels.

## 15. Newer MELD release (31 Oct, PP-567)

- **What changed in it:** MELD's 27 Oct release (`ddfc9c78`, config v83) has one prototype per generator (60
  generators across 7 families) instead of per family, and folds em dashes to commas before scoring.
- **Zero-shot comparison** (scored locally; my setup reproduces Tori's untouched-MELD scores exactly with the
  Sep release):

| Untouched, test | AUROC | AI caught at exactly 1% FPR | AI caught, val threshold | Students wrongly flagged |
| --- | --- | --- | --- | --- |
| MELD Sep release | 0.677 | 16.6% | 19.6% | 2.5% |
| MELD Oct release | 0.756 | 12.3% | 13.0% | 1.2% |

- **Oct minus Sep:** AUROC +0.078 [+0.050, +0.113], a real gap; at exactly 1% FPR −4.4 pts (could be noise).
- **Mixed result.** Both are far below the fine-tuned MELD (0.973), so the base release matters less than the
  fine-tuning.
- **Fine-tuned on the Oct release** (PP-577): Tori's exact recipe (rank 16, `Wqkv,Wo`, 3 epochs, lr 1e-4, epoch by
  AUROC), seed 1, run `meld-lora-sw-lr1e-4-qkvo-r16-e3-revddfc9c78`. Compared with her seed-1 run on the Sep release:

| Seed 1, test | AUROC | AI caught at exactly 1% FPR | AI caught, val threshold | Students wrongly flagged |
| --- | --- | --- | --- | --- |
| MELD, Sep release (Tori) | 0.973 | 64.3% | 68.8% | 1.4% |
| MELD, Oct release | 0.975 | 69.2% | 65.7% | 0.9% |
| desklib best + MELD Sep | 0.980 | 75.1% | 69.3% | 0.7% |
| desklib best + MELD Oct | 0.981 | 73.5% | 66.9% | 0.4% |

- **Conclusion: no gain, so seeds 2 and 3 weren't run.**
  - MELD alone: every difference could be noise.
  - Inside desklib + MELD: AUROC and AI caught at exactly 1% FPR could be noise. AI caught at the val threshold is
    −2.4 pts [−4.2, −1.0], a real gap, but it comes with fewer students wrongly flagged (0.4% vs 0.7%), so its
    threshold is just stricter.
  - Keep the Sep release.

## What didn't work, and why

| Idea | Result | Why |
| --- | --- | --- |
| RADAR alone | −0.018 AUROC, −16 pts at exactly 1% FPR vs desklib best | Weaker on short answers even after fine-tuning |
| Full RADAR instead of LoRA, next to the live desklib | No measurable gain, more false flags | The gain only shows next to desklib best |
| RADAR as a third model with desklib + MELD | No gain | Same kind of model as desklib, so no new evidence |
| Question context (Malcolm) | No ranking gain | Its threshold gain comes with 1.4% false flags |
| Tuning the desklib/MELD weight | Same as 50/50 | Weights chosen on val don't carry to test |
| Smaller MELD on CPU | 7–17x slower | CPU half-precision and 8-bit kernels are slow |
| MELD with desklib's recipe | Tie or worse | Extra capacity overfits MELD |
| Sentence-level scoring | Worse everywhere | Human sentences alone look AI-like |
| MELD's 27 Oct release, fine-tuned | Same as the Sep release | Fine-tuning matters far more than the base release |

## Open items

- **desklib + MELD is the strongest result but isn't built.** It needs MELD in the detector, ~7 GB of memory and
  a 16 GB task.
- **The shipped desklib + RADAR ensemble wrongly flags 1.57% of students on test,** above the 1% target.
- **Untested ideas:**
  - a perplexity-based score (e.g. Binoculars) as a different kind of third input;
  - a model trained on sentence-level labels for spliced answers;
  - a GPTZero comparison on the test set.
- **Licence:** RADAR is non-commercial only.

## Where things are

| What | Where |
| --- | --- |
| RADAR training, zero-shot, latency, ensemble scripts | `ml-training/` on `main` (PR #74) |
| desklib + RADAR detector backend, calibration, sweep mode, `--save-model` | `main` (PR #76) |
| MELD in the latency script | branch `meld-latency` (commit a951a0a, no PR yet) |
| MELD sweep job and options | branch `meld-sweep` (from `tori/tuning`, no PR yet) |
| Run metrics and per-answer scores files | DagsHub MLflow `E2-finetune` / `zeroshot-baselines`, `predictions/` |
| Write-ups with all numbers | Jira PP-548, PP-552, PP-556, PP-559, PP-560, PP-567, PP-577 |
