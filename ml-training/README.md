# ml-training

Trains, evaluates and logs the AI-answer detectors. One config object describes a
run, one script executes it, and everything lands on the shared DagsHub MLflow
server so the comparison table in the report can be rebuilt from scratch.

| File                                           | What it is                                                                          |
| ---------------------------------------------- | ----------------------------------------------------------------------------------- |
| [`config.py`](config.py)                       | The schema, and the only place defaults live. One `RunConfig` fully describes a run  |
| [`experiments.py`](experiments.py)             | The registry — every experiment in the study, as a `RunConfig`                       |
| [`trial-training.py`](trial-training.py)       | The runner. Takes a `RunConfig` and executes it end to end                           |
| [`metrics.py`](metrics.py)                     | The official metric set. Every detector is scored through `evaluate()`               |
| [`tracking.py`](tracking.py)                   | MLflow / DagsHub. Every run is opened with `start_run()`                             |
| [`reporting.py`](reporting.py)                 | Pulls finished runs back out into the report tables                                  |
| [`make_trial_splits.py`](make_trial_splits.py) | One-off script that built the trial split file. Not part of the training pipeline    |

## Setup

1. `python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt`
2. `cp .env.example .env` and fill in `MLFLOW_TRACKING_USERNAME` / `_PASSWORD`. The
   password is a **DagsHub access token**, not your account password. The DagsHub
   login is shared across the team, which is why every config carries an `owner`
   field — that field is the only way to tell whose run is whose.
3. Give DVC the same credentials and `.venv/bin/dvc pull` — see
   [The data, and DVC](#the-data-and-dvc). Skipping the pull fails with a clear
   `FileNotFoundError` rather than training on nothing.

## The data, and DVC

Nothing in `data/` is in git. [`data.dvc`](data.dvc) holds the md5 of the directory
and DVC fetches the bytes from the DagsHub remote, so the parquet files never bloat
the repo and everyone still trains on provably the same bytes.

The remote is already committed and needs no edit — `.dvc/config` at the repo root
names it, and it is the same DagsHub repo the MLflow server lives in:

```ini
[core]
    remote = origin
['remote "origin"']
    url = https://dagshub.com/zylooooo/Prompt-Patrol.dvc
```

What is deliberately *not* committed is the credential. Each person puts their own in
`.dvc/config.local`, which is gitignored. Write it with `dvc remote modify --local`
rather than by hand — `--local` is the whole safety mechanism, and the command cannot
forget it the way you can:

```bash
.venv/bin/dvc remote modify --local origin auth basic
.venv/bin/dvc remote modify --local origin user <dagshub-username>
.venv/bin/dvc remote modify --local origin password <dagshub-access-token>
```

Same pair as `.env`: the shared DagsHub username, and an **access token** (DagsHub →
Settings → Tokens), not the account password. Drop the `--local` and the token lands
in `.dvc/config`, which *is* tracked — i.e. you have committed a credential.

Then fetch:

```bash
.venv/bin/dvc pull
```

That writes three files: `data/trial-data.parquet`, `data/splits/trial-v0.2.parquet`
and its manifest. `.venv/bin/dvc status` says `Data and pipelines are up to date.`
when your working tree matches `data.dvc`. Run `dvc pull` again after any `git pull`
that touches `data.dvc` — git moved the pointer, but only DVC moves the bytes.

### Changing the data

```bash
.venv/bin/dvc add data                     # rewrites data.dvc with the new md5
.venv/bin/dvc push                         # uploads the bytes
git add data.dvc && git commit             # publishes which bytes to fetch
```

The commit is the step that is easy to forget. `dvc push` moves the bytes, but
`data.dvc` is what tells everyone else which bytes to want, so a push without the
commit is invisible to the rest of the team — and a commit without the push points
them at bytes the remote does not have.

## Run an experiment

```bash
.venv/bin/python trial-training.py TRIAL --inspect   # dry check, no training
.venv/bin/python trial-training.py TRIAL             # the real run
```

The argument is the **variable name in `experiments.py`**, so `ROBERTA_LORA`,
`ROBERTA_DORA` and `ROBERTA_FULL` all work the same way. It defaults to `TRIAL`.
Get the name wrong and it prints the available ones rather than guessing.

Always `--inspect` a new config first. It loads the data, runs the leakage checks
and builds the model without training or touching MLflow, so a broken split or a
typo'd `target_modules` costs you five seconds instead of a whole run.

The real run does these in order, and the order *is* the protocol:

1. Train, evaluating on validation each epoch, early-stopping on
   `optim.metric_for_best_model`.
2. Predict on validation, fit the calibrator, pick the threshold at
   `calibration.target_fpr` — **then freeze both**.
3. Predict on test once, with that frozen boundary, and score it.
4. Log metrics, per-answer predictions, slice rows, `thresholds.json` and the
   adapter weights.

## Design your own experiment

Add a `RunConfig` to `experiments.py`. Defaults live in `config.py` and only there,
so an entry states only what it **changes**:

```python
MY_RUN = RunConfig(
    experiment="E2-finetune",          # groups runs on the MLflow server
    run_name="roberta-base-lora-r32",  # the label in the runs list
    owner=OWNER,                       # your SMU id — the DagsHub login is shared
    model=ModelConfig(**ROBERTA, tuning_method="lora"),
    data=DataConfig(splits=SPLITS),
    optim=OptimConfig(learning_rate=1e-4),
    peft=PeftConfig(r=32, alpha=64),
)
```

What each block controls:

| Block         | Controls                                                                 |
| ------------- | ------------------------------------------------------------------------ |
| `model`       | which checkpoint, pinned to a commit sha, and **`tuning_method`**         |
| `data`        | which split file, and the split strategy                                  |
| `peft`        | adapter rank, alpha, dropout, which modules get an adapter                |
| `optim`       | learning rate, epochs, batch size, precision, early stopping, class weights |
| `calibration` | calibrator, the FPR budget, and the abstention band                       |

**`model.tuning_method` is the only switch that changes what runs.** `lora` / `dora`
build an adapter, `full_ft` trains everything, `zeroshot` / `api` train nothing and
are rejected by this script. Because LoRA and DoRA differ by exactly one field, the
gap between them is attributable to the method rather than to a script edit — which
is the whole point of writing DoRA as a `.variant()` of LoRA rather than as a second
config that has drifted.

For a sweep, use `.variant()` and let the loop do the work:

```python
for r in (8, 16, 32):
    run(ROBERTA_LORA.variant(f"lora-r{r}", **{"peft.r": r, "peft.alpha": 2 * r}))
```

`.variant()` re-validates, and raises on a field name that doesn't exist — so a
typo'd override fails immediately instead of silently training the parent config.

Before you run, check:

- **`owner` is you.** Otherwise your run is indistinguishable from everyone else's.
- **`run_role="smoke"`** if this is a pipeline shakedown. `reporting.py` drops those
  from every table, so a test can never be mistaken for a result.
- **Your tree is committed.** `start_run()` tags `git_dirty=true` when it isn't, and
  a dirty tree means the logged code is not the code that ran.
- **`cfg.fingerprint()`** identifies a run by its content, ignoring `run_name`,
  `notes` and `owner`. Two runs with the same fingerprint are duplicates — check the
  server before spending an hour reproducing one.

## What a run produces

```
config.resolved.json              every field, after validation and defaults
env/environment.json              python, torch, platform, GPU
thresholds.json                   the frozen boundary: threshold, calibrator params,
                                  abstention band. The web app loads exactly this,
                                  so what is served is provably what was evaluated
predictions/{val,test}_…parquet   per-answer y_true, y_prob (calibrated) and
                                  y_prob_raw (model output), plus ids and slice keys
slices/test_slices.csv            per-generator and per-length-bin rows
model/                            adapter + tokenizer — LoRA/DoRA runs only
```

The predictions table is the most valuable of these. With it, any later question
about a different threshold, a different slice or a different calibrator is answered
from a parquet file instead of from a GPU, so a rerun is never needed to answer a new
question. Full fine-tunes skip `model/` deliberately — ~500 MB per run would make the
shared repo unusable, and those runs are reproducible from the config and the git sha.

## Reading results back

```bash
.venv/bin/python reporting.py --out reports/
```

Writes `headline_e2.csv` and `logo_e3.csv`. It works without anyone remembering what a
run was called, because the full config is logged as params — which is the point of
logging it.

## The evaluation protocol

The headline number is **TPR at a fixed 1% FPR**: how much AI is caught while wrongly
flagging at most 1% of human answers. A false positive here is a student wrongly
accused, which is why it gets a fixed budget instead of being traded off.

The threshold and calibrator are fitted on **validation**, frozen, and only then
applied to **test**. Picking them on test inflates the result and is not defensible in
the report, so `evaluate()` logs both: `deployed_*` is the frozen-threshold number an
instructor would actually get, and `oracle_*` is the best case if the threshold had
been retuned on test. **The gap between them is itself a finding**, and so is
`deployed_fpr` drifting above the budget — that means the 1% promise did not survive
the val → test transfer.

`metrics.py` also reports `deployed_ppv_at_prevalence_*`. Precision measured on a
25%-AI corpus badly overstates what an instructor sees, because the real marking pile
is closer to 5% AI — and at 1% FPR with 5% prevalence, a flag can still be wrong about
half the time. That is the number that speaks to wrongful accusation.

Splits are grouped **by question**, never by row. Every question in the trial corpus
has exactly one AI answer, so a row-level split would put a question's human answers
in train and its AI answer in test, and the detector would score the topic instead of
the authorship. `load_splits()` raises if a question ever spans two partitions.

## Gotchas

- **Apple Silicon has no bf16.** Set `optim.precision="fp32"` or the run dies in
  `TrainingArguments`. Keep `dataloader_num_workers=0` too; MPS deadlocks above 0.
- **`TrainingArguments` takes `warmup_steps`, not a ratio.** The config stores a ratio,
  because that is the quantity that stays meaningful when the corpus or the batch size
  changes; `training_arguments()` converts it.
- **The `MISSING classifier.*` load report is correct.** The classification head is
  not in the pretrained checkpoint and is randomly initialised, which is exactly why
  `peft.modules_to_save=["classifier"]` exists — without it you would ship a tuned
  adapter bolted to a random head.
- **A 1% FPR budget needs enough negatives to spend it on.** With 51 validation
  negatives the budget is 0.51 false positives, i.e. zero, so the headline threshold
  can land above every score and flag nothing. `thresholds.json` records
  `val_false_positive_budget` so you can see when this has happened.
- **The trial corpus has two known label leaks and must never be cited.** 21 human
  answers carry unstripped `<br>` markup and no AI answer does, so `<br>` alone
  identifies a human with certainty — fix that in
  `apps/data-pipeline/data/cleaned/cleaned_data.ipynb` before any real run.
  Separately, 98.8% of AI answers end in a full stop against 65.5% of human ones,
  which is genuine signal but shallow enough that a good score here proves
  punctuation matching rather than detection.
- **Slicing by `generator` is vacuous on the trial corpus**, where `generator` is only
  `human`/`ai_generated` and therefore *is* the label. Those slice rows have no
  negatives (or no positives) and carry no information. The same corpus cannot run
  E3 leave-one-generator-out at all, for the same reason.
