# desklib + MELD detector: handoff

The new detector combines two models, desklib and MELD, into one score. The model files and calibration are
ready on DagsHub, and step 1 of the [next steps](#next-steps) downloads them into
`apps/detector/model/desklib-meld/`. **What is left is building it into the detector and API.**

Compared with the desklib model live today, on the test set it **catches 70% of AI answers instead of 51%, while
wrongly flagging half as many students** (0.5% vs 1.2%).

## Results

Test set, answers of 10+ words. The threshold was fixed on validation before test was looked at.

| | **desklib + MELD (new)** | desklib (live today) |
| --- | --- | --- |
| AI answers caught | **70.3%** [63.2, 77.5] | 51.4% |
| Students wrongly flagged | **0.52%** [0.0, 1.4] | 1.18% |
| AUROC | **0.981** | 0.957 |

The gains are real, not noise: +18.6 pts AI caught [+16.0, +21.6] and +0.025 AUROC [+0.017, +0.032]. Brackets are
95% intervals that resample whole questions.

AI caught, by type of answer:

| Raw AI | Edited | Paraphrased (light / heavy) | Spliced: 25% / 50% / 75% AI |
| --- | --- | --- | --- |
| 75% | 88% | 78% / 84% | **32%** / 56% / 63% |

Students wrongly flagged, by dataset: Mohler 1.2% (4 of 346), EngSAF 0%, SPRAG 0%.

These match the experiment that chose this model (E7 in
[the experiment results](desklib-meld-experiment-results.md#e7-the-final-combination-5-nov-2026)): AUROC 0.979,
and 74.7% caught at exactly 1% FPR, against 75.8% here. Scoring through the detector's code gives the same
scores as training did, so nothing was lost in packaging.

## How it scores an answer

1. Answers under 10 words are not scored. The API marks them `uncertain`.
2. Clean the text once with `clean_text`, and give the same cleaned text to both models.
3. **desklib** reads the first 256 tokens and returns a logit. **MELD** reads the whole answer, in windows, and
   returns a score.
4. Combine them: `z = 0.5 · desklib_logit / 3.332 + 0.5 · meld_score / 2.233`, then `probability = sigmoid(z)`.
5. The API compares the probability with the threshold, **0.9458**: above means `ai_generated`, below means
   `human_written`, and within the abstention band means `uncertain`.

Average the two **log-odds** as in step 4, not the two probabilities. Otherwise the threshold no longer means
"1% of students wrongly flagged". All the numbers are in `desklib-meld.json`, so code should read them from
there and not copy them.

## What's in `apps/detector/model/desklib-meld/`

| File | What it is |
| --- | --- |
| `desklib-meld.json` | The config: threshold, both temperatures, the formula, base models with pinned revisions, token limits, and versions for the API |
| `desklib-lora-adapter/` | desklib's fine-tuned weights (54 MB). Loads the same way as today's `desklib-lora-adapter/` |
| `meld-soup-adapter/` + `meld-soup-head.safetensors` | MELD's fine-tuned weights (42 MB): three training runs averaged into one model |
| `golden.json` | 23 answers with the probability each should get. Use it to test the new backend |
| `report.json` | Full numbers: validation choices, test results, checks, and the abstention-band table |

## Next steps

### 1. Download the model files

The files are not in git. Everyone downloads the same copy from DagsHub:

```bash
cd ml-training
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once, if you don't have the venv
cp .env.example .env    # once: your DagsHub username, a DagsHub access token, and the repo owner and name
.venv/bin/python release_desklib_meld.py --fetch --run-id 04da6e99ed3e41c9ae6742ae5c0fcbf1
```

This puts the 8 files in `apps/detector/model/desklib-meld/`, about 96 MB. It needs no GPU and no data. Keep
`--run-id` as it is: without it, you get the newest release run instead of this one. Running it again replaces the
folder with a fresh copy.

### 2. Pick the abstention band. Do not use the API default of 0.08.

With this model, a band of ±0.08 (or even ±0.05) around 0.9458 marks **every** AI answer `uncertain`, so the
detector would never flag anything. This is because the combined probability almost never goes above about 0.995.

On validation:

| Band | Students flagged | Students uncertain | AI flagged | AI uncertain |
| --- | --- | --- | --- | --- |
| none | 1.0% | 0% | 76.1% | 0.1% |
| **±0.005 (suggested)** | 0.57% | 0.9% | 72.8% | 5.7% |
| ±0.01 | 0.28% | 1.6% | 68.0% | 13.3% |
| ±0.02 | 0% | 2.7% | 43.5% | 40.7% |

**Suggested: ±0.005**, the same band desklib + RADAR uses. It halves the false flags at a cost of 3 pts of AI
caught. Choose from this table only, never from test numbers.

### 3. Decide on the stricter threshold for Mohler (optional)

Mohler students are wrongly flagged more than the others: 2.1% on validation and 1.2% on test, against a 1% target.
A stricter threshold of **0.9539** keeps every dataset within 1% on validation. It catches 70.3% of validation AI
instead of 76.1%. The default is to keep 0.9458.

### 4. Build the detector backend (detector team)

Copy the pattern of `apps/detector/app/ensemble.py`, which is desklib + RADAR:
- [ ] `DETECTOR_BACKEND=desklib-meld`, which loads desklib as `desklib.py` does, but with this bundle's adapter and
  temperature.
- [ ] Load MELD from `anon-review-meld-2026/meld` at the revision in `desklib-meld.json`, using `meld.py` from that
  same revision. Build `Scorer(model_dir)`, merge `meld-soup-adapter` into `scorer.model.backbone`, and load
  `meld-soup-head.safetensors` into `scorer.model` with `strict=False`. Then the score is
  `scorer.score(clean_text(text))["score"]`. **Ignore** the `flagged` and threshold that MELD returns: they are
  MELD's own, not ours.
- [ ] Pin desklib's base model to the `base_revision` in `desklib-meld.json`. Today's `desklib.py` downloads it
  without one.
- [ ] Refuse to start if `desklib-meld.json` doesn't match the code, as `ensemble.py` does.
- [ ] A test that scores every answer in `golden.json` and matches each probability within 0.002.
- [ ] The Docker build copies `apps/detector/model/`, so run step 1 before building the image. Unlike the
  desklib and RADAR adapters, these files are not committed, partly because `golden.json` holds corpus text.
  Add `apps/detector/model/desklib-meld/` to `.gitignore` so nobody commits them by accident.
- [ ] Measure memory and latency on the target machine (`ml-training/measure_latency.py`). MELD's base model is
  about 4 GB and desklib's about 1.7 GB, so budget at least 6 GB. Long answers take longer, because MELD reads the
  whole answer.

### 5. Configure the API

Add `apps/docker-compose.desklib-meld.yml`, modelled on `docker-compose.ensemble.yml`:

```yaml
DETECTOR_MODEL_VERSION: desklib-meld-ensemble-v1
DETECTOR_THRESHOLD: "0.945775"        # or 0.9539 if step 3 chose the stricter one
ABSTENTION_BAND: "0.005"              # from step 2
DETECTOR_CALIBRATION_VERSION: desklib3.332-meld2.233-thr0.9458-v1
```

### 6. Recommended: one source for the threshold

Today the detector reads its numbers from the JSON, but the threshold that decides a verdict is a separate copy,
typed into the API's compose file. Nothing checks that the two agree. If someone updates the model but not the
compose file, the API applies a stale threshold to new scores and gives no error.

The cleanest fix is for the detector to return `calibration_version` and `threshold` with each score. The API
would then use those values, or check them against its own. This changes the contract between detector and API,
so it is the detector team's call. If they adopt it, it should cover desklib + RADAR too.

## Known limits

- **Spliced answers** (a student's answer with part of it replaced by AI) are the weak spot. Only 32% of those that
  are 25% AI are caught.
- **Mohler** is slightly over the 1% false-flag target (see step 3).
- **The 10-word minimum has no evidence behind it for these models.** It is the app's existing rule, and every
  evaluation used answers of 10+ words only. The corpus has answers down to 3 words, so checking whether 10 is the
  right floor costs no GPU time. Changing the floor would need a new threshold fit on validation.

## Where it came from

- DagsHub run `release-desklib-meld-ensemble-v1` (`04da6e99ed3e41c9ae6742ae5c0fcbf1`), made by
  `ml-training/release_desklib_meld.py` on 6 Nov 2026 at commit `7f0a610`. Step 1 downloads it.
- desklib: `desklib-lora-qkvf-r64-e8-extended-s2`, the best of 3 seeds by validation AUROC.
- MELD: `meld-lora-extended-s1/s2/s3` averaged into one model (the "3-seed soup").
- The calibration was fitted on validation only. Test was read once.
