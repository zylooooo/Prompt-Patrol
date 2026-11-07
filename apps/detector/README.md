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
what makes compose's health gate meaningful: the API and worker wait for a
detector that can actually score, instead of the first real check paying the
load time and timing out.

## Backends

`DETECTOR_BACKEND` picks the model. Each has its own Dockerfile, because the
weights are baked into the image.

|                     | `roberta` (default)                             | `desklib`                                                                |
| ------------------- | ----------------------------------------------- | ------------------------------------------------------------------------ |
| Image               | `Dockerfile`                                    | `Dockerfile.desklib`                                                     |
| Model               | `openai-community/roberta-base-openai-detector` | `desklib/ai-text-detector-academic-v1.01` + the LoRA adapter in `model/` |
| `model_version`     | `roberta-base-openai-detector-v0`               | `desklib-academic-lora-v1`                                               |
| Tokens read         | 512                                             | 256, as in training                                                      |
| Score               | The model's "fake" class probability            | Temperature-scaled sigmoid of the logit — a calibrated probability       |
| Image size / memory | ~500 MB model                                   | ~1.7 GB model; give Docker about 8 GB                                    |

The desklib backend also runs the text through `app/clean.py` before scoring,
the same cleanup the training corpus had. Only the copy sent to the model is
cleaned; the answer the API stores is untouched. `clean.py` is a hand-kept
copy of `apps/data-pipeline/app/corpus/clean.py` — change both together, or
the model scores text that looks different from what it trained on.

To run desklib, use the compose override from `apps/`:

```sh
docker compose -f docker-compose.yml -f docker-compose.desklib.yml up -d --build
```

The override also sets the matching model version, threshold and abstention
band on the API and worker. Switching the detector image without them leaves
the API judging desklib scores against the baseline's thresholds.

## Why the images look the way they do

- **The model is baked in.** The Dockerfile downloads the weights at build
  time and then sets `HF_HUB_OFFLINE=1`, so startup is a local disk read and a
  missing model is a loud startup failure rather than a silent download in
  production. Don't mount a cache volume over the HuggingFace cache path — it
  would shadow the baked model with whatever an older build left behind.
- **torch comes from the CPU-only index.** The default PyPI wheel bundles CUDA
  libraries this service never uses and adds several GB to the image.
- **`app/` is copied last**, so editing code doesn't invalidate the model
  layer and trigger a re-download.
- **Requests are serialised.** The tokenizer refuses concurrent use, and a
  forward pass is CPU-bound anyway, so one lock guards scoring. Batch rows are
  therefore scored one at a time, however many arrive together.

## Running it on its own

```sh
pip install -r requirements.txt     # requirements-desklib.txt for desklib
cd app && python main.py            # serves on :8001; DETECTOR_PORT to change
```

Outside Docker the model downloads to your HuggingFace cache on first start.
For desklib, also set `DETECTOR_BACKEND=desklib` and
`DESKLIB_ADAPTER_DIR=../model/desklib-lora-adapter`.

## Tests

```sh
pip install -r requirements-dev.txt
pytest
```

The tests don't load a real model. `ruff check .` is the linter.

If you change the `/score` request or response shape, update
`apps/e2e/detector-stub.py` too — the end-to-end suite runs against that stub,
not this service.
