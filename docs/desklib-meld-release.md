# desklib + MELD detector: handoff

The new detector combines two models, desklib and MELD, into one score. The model files and calibration are
ready on DagsHub, and step 1 of the [steps](#steps) downloads them into `apps/detector/model/desklib-meld/`.

**Status (12 Nov 2026):** the detector backend, its Docker images and the local compose setup are done (branch
`package-model`), and the detector now reports its own threshold to the API. Running locally works, and the base
image is on GHCR. **What is left is switching production over:** see
[what is left](#what-is-left).

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
   `human_written`, and within the abstention band (**±0.005**) means `uncertain`. The detector sends the
   threshold and band with every score, so the API needs no settings for this model.

Average the two **log-odds** as in step 4, not the two probabilities. Otherwise the threshold no longer means
"1% of students wrongly flagged". All the numbers are in `desklib-meld.json`, and the code reads them from there
(`apps/detector/app/desklib_meld.py`).

## What's in `apps/detector/model/desklib-meld/`

| File | What it is |
| --- | --- |
| `desklib-meld.json` | The config: threshold, both temperatures, the formula, base models with pinned revisions, token limits, and versions for the API |
| `desklib-lora-adapter/` | desklib's fine-tuned weights (54 MB). Loads the same way as today's `desklib-lora-adapter/` |
| `meld-soup-adapter/` + `meld-soup-head.safetensors` | MELD's fine-tuned weights (42 MB): three training runs averaged into one model |
| `golden.json` | 23 answers with the probability each should get. Use it to test the new backend. Not in the base image |
| `report.json` | Full numbers: validation choices, test results, checks, and the abstention-band table |

## Steps

### 1. Download the model files ✅

Done. Only needed again to build a new base image (step 7); everyone else gets the files inside the base image on
GHCR.

The files are not in git. Everyone downloads the same copy from DagsHub:

```bash
cd ml-training
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once, if you don't have the venv
cp .env.example .env    # once: your DagsHub username, a DagsHub access token, and the repo owner and name
DETECTOR_TORCH_THREADS=4 .venv/bin/python release_desklib_meld.py --fetch --run-id 04da6e99ed3e41c9ae6742ae5c0fcbf1
```

This puts the 8 files in `apps/detector/model/desklib-meld/`, about 96 MB. It needs no GPU and no data. Keep
`--run-id` as it is: without it, you get the newest release run instead of this one. Running it again replaces the
folder with a fresh copy.

`DETECTOR_TORCH_THREADS` is a workaround: `apps/detector/app/desklib.py` calls `os.process_cpu_count()`, which needs
Python 3.13, and this venv is 3.11. Without it the fetch fails with `AttributeError`.

### 2. Pick the abstention band ✅

**Done: ±0.005**, set in `desklib_meld.py` (`ABSTENTION_BAND`) and sent to the API with every score. Do not use the
API's default of 0.08.

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

### 3. Decide on the stricter threshold for Mohler (optional, open)

Mohler students are wrongly flagged more than the others: 2.1% on validation and 1.2% on test, against a 1% target.
A stricter threshold of **0.9539** keeps every dataset within 1% on validation. It catches 70.3% of validation AI
instead of 76.1%. **For now the default, 0.9458, is kept.** The threshold now comes from the detector, so adopting
0.9539 is a detector change, not an API setting.

### 4. Build the detector backend ✅

- [x] `DETECTOR_BACKEND=desklib-meld` (`apps/detector/app/desklib_meld.py`): desklib with this bundle's adapter and
  temperature.
- [x] MELD loaded with `meld.py` from the pinned revision: soup adapter merged into the backbone, head loaded with
  `strict=False`, MELD's own `flagged` and threshold ignored. MELD comes from a copy inside the base image, not from
  Hugging Face, because the repo is now gated.
- [x] desklib's base model pinned to the `base_revision` in `desklib-meld.json`.
- [x] Refuses to start if `desklib-meld.json` doesn't match the code, or if the staged MELD is a different revision.
- [x] `golden.json` test (`apps/detector/tests/test_desklib_meld.py`): all 23 probabilities match exactly. It runs
  inside the image with `golden.json` mounted in (the base image leaves it out, see step 7). CI skips it, since CI
  has no model files.
- [x] `apps/detector/model/desklib-meld/` and `apps/detector/model/meld-base/` are in `.gitignore`.
- [x] Docker images, in two layers:
  - `Dockerfile.desklib-meld-base`: Python, the libraries, both base models and this bundle. Built once by
    someone with the files, after `scripts/prepare_desklib_meld_base.sh` copies MELD from their Hugging Face cache.
  - `Dockerfile.desklib-meld`: the base plus `app/`. Anyone can rebuild it in seconds, with no model files, only the
    base image on GHCR (step 7).
  - Both pin transformers 5.16.1, torch 2.14 and peft 0.20 (`requirements-desklib-meld.txt`), the versions the
    release was scored with. The other detector images keep transformers 4.55.4.
- [ ] Memory and latency on the production machine (`ml-training/measure_latency.py`). Locally the detector peaks at
  **5.7 GB** and takes about 90 s to load. Long answers take longer, because MELD reads the whole answer.

### 5. Configure the API ✅

`apps/docker-compose.desklib-meld.yml` runs the detector. It sets no API settings, because of step 6. To make it
the default for a plain `docker compose up`, add this to `apps/.env`:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.desklib-meld.yml
```

Give Docker Desktop about 12 GB of memory.

### 6. One source for the threshold ✅

Every detector backend (RoBERTa, desklib, desklib + RADAR, desklib + MELD) now sends `model_version`,
`calibration_version`, `threshold` and `abstention_band` with each score and on `/health`, and the API applies those
values and records them on each check. The API's `DETECTOR_MODEL_VERSION`, `DETECTOR_CALIBRATION_VERSION`,
`DETECTOR_THRESHOLD` and `ABSTENTION_BAND` are now only a fallback for older detector images. When one is set and
disagrees, the detector's value is used and a warning is logged. Switching models is now only a matter of which
detector runs.

### 7. Share the base image ✅

**Pushed 12 Nov 2026** to the existing `prompt-patrol-detector` package on GHCR, for both x86_64 (ECS) and
ARM (Macs). Each machine pulls only its own architecture, about 5.9 GB:

```
ghcr.io/zylooooo/prompt-patrol-detector:ml-tori-20261112
  @sha256:5af123270be5d11b1a45ac61a9d604681147f0bbeb976c80982227f27ff260ec
```

The tag follows the manual-push convention (`ml-<name>-<yyyymmdd>`), so it can be repointed. Everything that uses it
(`Dockerfile.desklib-meld`, `apps/docker-compose.desklib-meld.yml`, CI) pins the digest, not only the tag. It is the
**base layer, not a runnable detector**: it has no `CMD`. The runnable image is `Dockerfile.desklib-meld` on top.

The package is **public**, like every image CI pushes there (`infra/README.md`), so pulling it needs no login, and
nothing needs to go in `apps/.env`: the compose file and the Dockerfile default to this image.

What it holds: Python and the libraries, desklib's and MELD's base models, and the release bundle's adapters, MELD
head, `desklib-meld.json` and `report.json`. It does **not** hold `golden.json` (corpus text):
`Dockerfile.desklib-meld-base.dockerignore` leaves it out, since only the golden test reads it. Never let corpus
text or student answers into this image: it is public. The adapters were trained on student answers but hold no
answer text, like `desklib-lora-adapter/`, which is in git and in the desklib images.


#### Building and pushing a new base image

Only needed when the bundle, the base models or the libraries change. It needs the bundle (step 1) and MELD
`8990324a` in your Hugging Face cache:

```bash
cd apps/detector
./scripts/prepare_desklib_meld_base.sh
docker login ghcr.io                        # GitHub username + a classic token with write:packages
docker buildx build --platform linux/amd64,linux/arm64 -f Dockerfile.desklib-meld-base \
  --label org.opencontainers.image.source=https://github.com/zylooooo/Prompt-Patrol \
  -t ghcr.io/zylooooo/prompt-patrol-detector:ml-<yourname>-<yyyymmdd> --push .
docker buildx imagetools inspect ghcr.io/zylooooo/prompt-patrol-detector:ml-<yourname>-<yyyymmdd>
docker logout ghcr.io
```

Never tag it with a commit SHA, which is what CI uses. `imagetools inspect` should list `linux/amd64` and
`linux/arm64`, plus two `unknown/unknown` entries: those are buildx's provenance attestations (build metadata), not
images. Copy the top `Digest` into `Dockerfile.desklib-meld`, `apps/docker-compose.desklib-meld.yml`, CI and this
step.

### 8. Switch production over (open)

The API and the detector can be deployed in either order (step 6).

- [x] The base image is on GHCR (step 7).
- [x] CD workflow, "Build detector image": `file: ./apps/detector/Dockerfile.desklib-meld` and cache scope
  `detector-desklib-meld`. No build arg: the Dockerfile's `BASE_IMAGE` default is the pinned GHCR image, which is
  public, so pull-request builds need no GHCR login either.
- [x] `infra/compute.tf`, detector task: `memory` from `"4096"` to `"8192"`. The model would run out of memory at
  4 GB.
- [ ] **`terraform apply` before the merge.** The deploy copies each service's latest task definition and swaps only
  the image, so the 8 GB only reaches the deploy if Terraform has registered it first. Services ignore task
  definition changes, so the apply rolls nothing by itself.
- [ ] After a deploy has run the new detector for a while: delete `DETECTOR_MODEL_VERSION`,
  `DETECTOR_CALIBRATION_VERSION`, `DETECTOR_THRESHOLD` and `ABSTENTION_BAND` from the API and worker environment in
  `infra/compute.tf`. Left in, they don't change any verdict, but they log a mismatch warning. Not in the same
  change: a rollback re-uses the latest task definition, and an API from before step 6 needs them.
- [ ] After the deploy: the screening page shows `desklib-meld-ensemble-v1 · desklib3.332-meld2.233-thr0.9458-v1`,
  there are no mismatch warnings in the API logs, and step 4's latency measurement is done.

## What is left

1. Switch production over ([step 8](#8-switch-production-over-open)).
2. Optional: decide on the Mohler threshold ([step 3](#3-decide-on-the-stricter-threshold-for-mohler-optional-open)).
3. Optional: fix `os.process_cpu_count()` in `desklib.py` so the ml-training scripts run on Python 3.11 without the
   workaround in step 1.

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
