# desklib + MELD: release log and handoff

This turns the combination chosen in E7 ([results](desklib-meld-experiment-results.md#e7-the-final-combination-5-nov-2026))
into files the detector can ship. This page records what was done and what is still open. Once the release run has
finished, it is also the handoff to whoever builds the detector backend.

**Chosen in E7 (val only):** desklib reference rerun (`desklib-lora-qkvf-r64-e8-extended`) + MELD 3-seed soup
(`meld-lora-soup-all-s1`, the average of `meld-lora-extended-s1/s2/s3`), 50/50 on calibrated log-odds. Expected on
test, from E7: AUROC 0.979, 74.7% of AI caught at exactly 1% FPR (mean over the 3 desklib seeds).

## Status

| Step | State |
| --- | --- |
| E7 decision recorded | done (5 Nov) |
| `release_desklib_meld.py` + tests for the soup-as-one-adapter maths | written (6 Nov), tests pass locally |
| `cluster/release_desklib_meld.sh` | written (6 Nov) |
| Release run on the cluster | **not run yet** |
| Bundle fetched into `apps/detector/model/desklib-meld/` and committed | not yet |
| Detector backend for MELD (`DETECTOR_BACKEND=desklib-meld`) | not started (detector team) |
| Abstention band for this model | open: pick from the val table in `report.json` |

## What was missing before the release (6 Nov)

1. **The MELD soup existed only as scores.** `soup_meld_lora.py` never saved its weights.
2. **No desklib seed had been picked.** E7's numbers are a mean over the 3 seeds, but the detector needs one.
3. **No threshold or calibration for the pair.** Those were fitted only inside the analysis, which writes to
   `outputs/`, a folder git ignores.
4. **The detector has no MELD code.** It runs desklib alone, or desklib + RADAR.

## How the release is built

`release_desklib_meld.py` trains nothing. The steps:
- **The soup becomes one LoRA adapter.** Stacking the members' A matrices, and their B matrices scaled by
  scale/3, gives a rank-48 adapter whose update is *exactly* the average of the members' updates. The heads are
  averaged as before. CHECK 1 compares this adapter's update with the averaged one.
- **It scores through the deployment path, with the half-precision files that ship.** That is the detector's
  `clean_text`, then desklib through `apps/detector/app/desklib.py`, and MELD through its own `Scorer.score`, all in
  float32. CHECK 2: the shipped soup must reproduce `meld-lora-soup-all-s1`'s saved val scores. If it does not,
  nothing is logged.
- **Val only:** fit each model's temperature; keep the desklib seed whose pair has the highest val AUROC (E7's
  rule); fit the 1% FPR threshold; tabulate the API's abstention bands.
- **Test, once:** the pair at the frozen threshold, per dataset and slice, compared with live desklib.
- **Logging:** the bundle goes to DagsHub as run `release-desklib-meld-ensemble-v1`.

## Running it

On the cluster (VPN on). The job does a 120-answer smoke pass first, then the real run, all in one slot:

```bash
cd ~/tori/Prompt-Patrol && git fetch && git checkout tori/tuning && git pull   # the branch with the script
cd ~/tori && myqueue                                                          # one running job for the group
sbatch Prompt-Patrol/ml-training/cluster/release_desklib_meld.sh
tail -f ~/tori/$USER.<jobid>.out
```

Then on a laptop with DagsHub credentials in `ml-training/.env`:

```bash
cd ml-training && python release_desklib_meld.py --fetch    # -> apps/detector/model/desklib-meld/
```

## The bundle (`apps/detector/model/desklib-meld/`)

| File | What it is |
| --- | --- |
| `desklib-meld.json` | Everything needed to score: threshold, both temperatures, the combination formula, base models and pinned revisions, token limits, source run ids, and the API settings (`model_version`, `calibration_version`) |
| `desklib-lora-adapter/` | The chosen desklib seed's adapter, fp16. Loads exactly like today's `desklib-lora-adapter/` |
| `meld-soup-adapter/` | The MELD soup as one rank-48 LoRA adapter, fp16, for MELD at the pinned revision |
| `meld-soup-head.safetensors` | The averaged MELD prototype head, loaded into `scorer.model` with `strict=False` |
| `golden.json` | About 23 val answers, scored on CPU in float32: each model's raw score and the final probability. A new backend should match these within `tolerance_probability` |
| `report.json` | The checks, the val seed choice, per-dataset false flags, the abstention-band table (val), the test results, and the paired comparison with live desklib |

`golden.json` holds the text of about 23 corpus answers. Check this is fine before committing it to the repo.

## Handoff notes for the detector

- **Combination:** `z = 0.5 * desklib_logit / T_desklib + 0.5 * meld_score / T_meld`, then
  `probability = sigmoid(z)`. The API flags an answer when `probability > threshold`. The values are in
  `desklib-meld.json`.
- **MELD scoring:** load `meld.py` from the pinned revision, build `Scorer(model_dir)`, merge the adapter into
  `scorer.model.backbone`, load the head, then `scorer.score(clean_text(text))["score"]`. **Ignore** MELD's own
  `flagged` and threshold.
- **Size:** the MELD base is about 4 GB (ModernBERT, hidden size 1792), and desklib is about 1.7 GB. Expect roughly
  6 GB+ of memory for the detector container. MELD scores long answers in windows, so latency grows with length.
  Measure it with `measure_latency.py`.
- **API settings:** `DETECTOR_MODEL_VERSION`, `DETECTOR_THRESHOLD` and `DETECTOR_CALIBRATION_VERSION` come from
  `desklib-meld.json`. **Do not keep the default `ABSTENTION_BAND` of 0.08:** pick a band from the val table in
  `report.json`, as was done for desklib + RADAR (±0.005).
- **The desklib base is unpinned.** `desklib.py` calls `snapshot_download` without a revision. The revision used for
  calibration is recorded in `desklib-meld.json`, so pin it there.
- **Known weakness:** Mohler students are wrongly flagged above the 1% budget (E7: 1.25% on test, 2.38% on val).
  `report.json` has the stricter threshold that keeps every dataset within 1% on val, and the AI it still catches.

## Log

- **5 Nov:** E7 picks desklib reference rerun + MELD 3-seed soup.
- **6 Nov:** release gaps found (above). Wrote `release_desklib_meld.py`, its tests and the cluster job. Not yet run.
