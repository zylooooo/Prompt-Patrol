# Prompt Patrol — detector

The scoring service. Text in, a score in `[0,1]` out, higher meaning more
likely AI-written. See the [repo README](../../README.md) for running the full
stack; this file covers the detector only.

It is deliberately stateless and knows nothing else: no database, no user
identity, no thresholds, no verdicts. The API turns a score into a verdict,
stores it and decides who may see it. Keep it that way — anything that needs
to know _who_ asked or _what to do_ with a score belongs in `apps/api`.

## Endpoints

Internal only. Nothing outside the compose network calls this service; the
browser talks to the API, which calls `DETECTOR_URL`.

| Endpoint      | Request / response                                                                           |
| ------------- | -------------------------------------------------------------------------------------------- |
| `POST /score` | `{"text": "..."}` → `{"raw_score": 0.93, "truncated": false}`                                |
| `GET /health` | `{"status": "loading" \| "ready" \| "failed", "model_version": "..."}` — `503` until `ready` |

`raw_score` is a score, not a probability to show anyone — only the API's
`confidence` field is display-safe. `truncated` is `true` when the text was
longer than the model reads, so only its start was scored.

`/health` answers `503` while the model loads in a background thread, which is
what makes compose's health gate meaningful: the worker waits for a detector
that can actually score, instead of the first batch row paying the load time
and timing out. The API only waits for it to start, as in ECS, so sign-in works
while the models load.

## The model

**desklib + MELD** (`app/desklib_meld.py`): the fine-tuned desklib detector
and MELD, each over its own temperature, their log-odds averaged, so
`raw_score` is a calibrated probability. It is the only model in this service,
and production and `apps/docker-compose.yml` both run it. Everything about the
model, its calibration and the release is in
[`docs/desklib-meld-release.md`](../../docs/desklib-meld-release.md).

| File                  | What it is                                                                       |
| --------------------- | -------------------------------------------------------------------------------- |
| `app/baseline.py`     | What isn't model-specific: the scoring lock, the load status, the warm-up        |
| `app/desklib_meld.py` | The model: loads both parts, checks the bundle, scores                           |
| `app/desklib.py`      | desklib pieces `desklib_meld.py` builds on (model class, sigmoid, torch threads) |
| `app/clean.py`        | The text cleanup applied before scoring                                          |
| `Dockerfile`          | The runnable image: `app/` on top of the base image                              |
| `Dockerfile.base`     | The base image: Python, the libraries, both models and the release bundle        |

The text goes through `app/clean.py` before scoring, the same cleanup the
training corpus had. Only the copy sent to the models is cleaned; the answer the
API stores is untouched. `clean.py` is a hand-kept copy of
`apps/data-pipeline/app/corpus/clean.py`: change both together, or the model
scores text that looks different from what it trained on.

The earlier models (the RoBERTa baseline, desklib on its own, and desklib +
RADAR) were removed on 2026-11-17. They are in git history.

## Why the images look the way they do

- **Two layers.** `Dockerfile.base` holds the models and is built by hand,
  because MELD's repo is gated. It is public on GHCR and pinned by digest.
  `Dockerfile` adds only `app/`, so anyone can rebuild it in seconds with no
  credentials. See the release doc, step 7.
- **The model is baked in.** The base image sets `HF_HUB_OFFLINE=1`, so startup
  is a local disk read and a missing model is a loud startup failure rather
  than a silent download in production. Don't mount a volume over the model
  paths: it would shadow the baked model.
- **torch comes from the CPU-only index.** The default PyPI wheel bundles CUDA
  libraries this service never uses and adds several GB to the image.
- **Requests are serialised.** The tokenizers refuse concurrent use, and a
  forward pass is CPU-bound anyway, so one lock guards scoring. Batch rows are
  therefore scored one at a time, however many arrive together.

## Running it on its own

It needs the model files, so in practice run the image (`docker compose up
detector` from `apps/`). Outside Docker, stage the bundle and MELD's base model
as for the base image (`scripts/prepare_desklib_meld_base.sh`), install as for
the tests below, then:

```sh
cd app && DESKLIB_MELD_DIR=../model/desklib-meld MELD_BASE_DIR=../model/meld-base python main.py   # serves on :8001
```

torch runs one thread per CPU the process may use, logged at startup as
`torch threads: ...`. `DETECTOR_TORCH_THREADS` overrides it (production and the
compose file set 2); set it when Docker caps CPU with `--cpus`, which that count
does not see.

## Tests

```sh
pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu   # first, as in Dockerfile.base
pip install -r requirements-dev.txt
pytest
```

The tests don't load a real model, except the golden test, which runs only inside the image with the release's
`golden.json` mounted (see the release doc) and is skipped elsewhere. `ruff check .` is the linter.

If you change the `/score` request or response shape, update
`apps/e2e/detector-stub.py` too — the end-to-end suite runs against that stub,
not this service.
