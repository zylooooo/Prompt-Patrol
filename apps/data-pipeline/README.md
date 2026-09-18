# data-pipeline

Assembles the labelled corpus other epics train and evaluate on. Covers
dataset ingest, profiling and cleaning for Mohler, SPRAG and EngSAF,
question-level splits, the generation harness that produces the raw
AI answers, and the splicer that builds mixed-authorship documents.

## Pipeline order

Per-dataset steps (loader/profiling/cleaning) live under `app/<dataset>/` and
run as modules, from inside `app/`:

```
cd app
python -m mohler.loader        # pull the pinned Mohler revision -> data/raw/
python -m mohler.profiling     # report duplicates/encoding issues -> data/profile_report.json
python -m mohler.cleaning      # fix + dedupe -> data/cleaned/, data/cleaning_log.json
```

Cross-dataset steps stay flat in `app/` and run directly, from inside
`apps/data-pipeline`:

```
python app/splitting.py     # question-level train/val/test -> data/splits/
python app/leakage_check.py # verify no question crosses a split boundary
python app/logo_folds.py    # leave-one-generator-out folds (needs AI-generated data first)
```

## Generation harness

`app/harness/config.yaml` drives every run. It sets the question file, the
dataset namespace, sample counts per tier, decoding parameters, the budget
cap and the generator list, which mixes API and local Ollama models. The
pilot and the full run are the same code with different config values. Run
the harness once per dataset so generation stays separate for each corpus.

A generator entry can carry provider switches through `extra_body`. The
config uses this to turn off DeepSeek and qwen3 reasoning, since both
think by default and can spend the whole token budget before writing any
visible answer.

### Running it

Copy `.env.example` to `.env` and fill in the API keys. The local
generators need Ollama running with the configured models pulled. Then,
from inside `app/`:

```
python -m harness.generate                                # dry run, prints the call plan
python -m harness.generate --questions 1 --tag smoke --go # one question, real calls
python -m harness.generate --tag pilot --go               # full run per config
```

Nothing spends money without `--go`.

### Output records

Each run writes `data/generated/<run_id>/answers.jsonl`, one JSON record
per generated answer, plus `run_report.json` with per-generator success
counts and token usage. Record shape:

    {
      "answer_id": "mohler/E03.Q03/gpt-5.5/weak/01",
      "question_id": "mohler/E03.Q03",
      "generator": "gpt-5.5",
      "model_version": "gpt-5.5-2026-04-23",
      "prompt_template": "weak_v1",
      "tier": "weak",
      "params_honoured": {"max_completion_tokens": 400},
      "usage": {"prompt_tokens": 211, "completion_tokens": 87},
      "timestamp": "2026-09-18T08:51:46+00:00",
      "answer": "..."
    }

Notes:
- answer_id is built from the question id, generator, tier and sequence,
  so re-running the same config reproduces the same ids.
- params_honoured records the decoding parameters the call actually
  sent, which differ by provider. gpt-5 models take max_completion_tokens
  and set their own sampling, Claude takes max_tokens only, Gemini and
  DeepSeek take both temperature and max_tokens.
- answer is never empty. Reasoning traces are discarded, and a response
  whose whole token budget went to reasoning counts as a failure in the
  run report instead of being written.
- The splicer links spliced documents to answer_id and question_id.
  Splits and folds key on question_id and generator. Cost reporting sums
  usage.

## Splicer

Builds the mixed-authorship documents for the partial-AI class. Each
document starts from an eligible human answer, and k of its n sentences
are replaced, at their original positions, with sentences from one AI
answer to the same question. Every sentence carries a human or ai label.
No model calls, it only recombines answers that already exist.

`app/splicer/config.yaml` sets the human corpus, the harness output to
draw from, the target AI fractions and the seed. Sentence segmentation
uses spaCy, so install the model once:

```
python -m spacy download en_core_web_sm
```

Then, from inside `app/`:

```
python -m splicer.build_spliced
```

Output goes to `data/spliced/spliced.jsonl`, one record per document.
The record schema is documented in `docs/spliced-schema.md`, and the
segmenter validation evidence lives in `docs/segmentation_review_v1.md`
to `v3`.

## Shared artifact storage

One person produces a finished file and **pushes** it once to a
shared, private storage location on HuggingFace (promt-patrol)
Everyone else can **pull** that exact same file
down instead of regenerating it themselves.

Every push also comes back with a "commit hash" - a short code that
identifies that exact version of the file. Once MLflow tracking is wired up
for training runs, this hash gets logged automatically as part of each run's
parameters.

### One-time setup

1. **Create your own personal access token.** Go to
   (https://huggingface.co/settings/tokens), click "New token," give it **Write** access.
2. **Make your token available in your terminal.** Every time you open a new
   terminal window and want to push or pull, run this first (replace with
   your actual token):
   ```bash
   export HF_TOKEN=hf_your_own_token_here
   ```
   This only lasts for that one terminal window/session - you'll need to run
   it again next time you open a new terminal.
4. **Check it actually worked**, before trying anything else:
   ```bash
   python3 -c "from huggingface_hub import whoami; print(whoami())"
   ```
   If this prints your HuggingFace account info, you're set up correctly.

### Push an artifact

Make sure you've done the one-time setup above and exported your token in
this terminal session first. Then, from inside `apps/data-pipeline`:

```bash
python3 -c "
from pathlib import Path
from artifact_store import push_artifact

commit_hash = push_artifact(
    local_path=Path('data/splits/mohler_splits_2cc2d581.parquet'),
    path_in_repo='mohler/splits/mohler_splits_2cc2d581.parquet',
    commit_message='initial question-level split, 70/15/15',
)
print('Pushed. Version id:', commit_hash)
"
```

Replace the two file paths with whatever you're actually pushing, and the commit message

### Pull an artifact

To get the newest version of a file:

```bash
python3 -c "
from pathlib import Path
from artifact_store import pull_artifact

path = pull_artifact('mohler/splits/mohler_splits_2cc2d581.parquet', Path('data/splits'))
print('Downloaded to:', path)
"
```

To get one *specific past* version instead of the newest (using the commit
hash from when it was pushed):

```bash
python3 -c "
from pathlib import Path
from artifact_store import pull_artifact

path = pull_artifact(
    'mohler/splits/mohler_splits_2cc2d581.parquet',
    Path('data/splits'),
    revision='paste-the-commit-hash-here',
)
print('Downloaded to:', path)
"
```

### Verifying a push worked correctly

This pushes a file, immediately pulls that exact version back down, and
checks the bytes match perfectly. Useful the first time you set 
this up.

```bash
python3 -c "
from pathlib import Path
from artifact_store import verify_roundtrip

ok = verify_roundtrip(
    local_path=Path('data/splits/mohler_splits_2cc2d581.parquet'),
    path_in_repo='mohler/splits/mohler_splits_2cc2d581.parquet',
    commit_message='verify round-trip',
    download_dir=Path('/tmp/verify'),
)
print('Round-trip OK:', ok)
"
```
