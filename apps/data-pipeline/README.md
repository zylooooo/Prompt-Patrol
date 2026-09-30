# data-pipeline

Assembles the labelled corpus other epics train and evaluate on. Covers
dataset ingest, profiling and cleaning for Mohler, SPRAG and EngSAF,
question-level splits, the generation harness that produces the raw
AI answers, and the splicer that builds mixed-authorship documents.

## Setup

Python 3.13. From inside `apps/data-pipeline`:

```
python -m venv .venv
.venv\Scripts\activate       # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
```

requirements-dev.txt pulls in requirements.txt, the spaCy model and the
test tooling. Tests run with `pytest` from this folder.

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
dataset namespace, sample counts per tier, decoding parameters and the
generator list, which mixes API and local Ollama models. The
pilot and the full run are the same code with different config values. Run
the harness once per dataset so generation stays separate for each corpus.

A generator entry can carry provider switches through `extra_body`. The
config uses this to turn off DeepSeek and qwen3 reasoning, since both
think by default and can spend the whole token budget before writing any
visible answer.

The keys under `samples_per_question` are tier names, which map to
prompt templates through TIER_TO_TEMPLATE in
`app/harness/prompts.py`. Besides the four quality tiers there is a
rewrite tier, where the model polishes a real student answer instead of
writing its own. Its prompt follows Tufts, Zhao and Li (NAACL 2025).
Each generator and each sample polishes a different student answer to
the question while the question has enough of them, taken in an order
fixed by the question id. A rerun or resume polishes the same ones as
long as the question file, the rewrite count and the order of the
generator list stay the same. Rewrites count as ai, but the splicer,
paraphrase and human-edit passes all skip them through `is_rewrite` in
`app/harness/prompts.py`, so those passes only build on answers the
model wrote itself.

### Running it

Copy `.env.example` to `.env` and fill in the API keys. The local
generators need Ollama installed and running, with the configured
models pulled once:

```
ollama pull llama3.1:8b
ollama pull qwen3:8b
```

Then, from inside `app/`:

```
python -m harness.generate                                # dry run, prints the call plan
python -m harness.generate --questions 1 --tag smoke --go # one question, real calls
python -m harness.generate --tag pilot --go               # full run per config
python -m harness.generate --resume <run_id> --go         # continue an interrupted run
```

Nothing spends money without `--go`. A resumed run skips every answer
the folder already holds, so an interrupted run is finished without
paying for those calls twice. It plans from the current config and
`--questions` and ignores `--tag`, so resume with the config and
`--questions` the run started with.

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
  and set their own sampling, Claude takes max_tokens only, DeepSeek and
  the Ollama models take temperature and max_tokens, and Gemini takes
  temperature, max_output_tokens and thinking_level. A generator's
  extra_body, where set, is recorded with the rest.
- answer is never empty. Reasoning traces are discarded, and a response
  whose whole token budget went to reasoning counts as a failure in the
  run report instead of being written.
- rewrite records also carry source_answer_id, the id of the student
  answer they polish.
- a generator that fails three calls in a row is abandoned for the rest
  of the run, so a dead endpoint or bad key cannot stall every remaining
  call. The run report then shows fewer requested calls than the plan.
- The splicer links spliced documents to answer_id and question_id.
  Each question goes wholly to train, val or test, and every record
  follows its question there through question_id. Mohler asks two
  questions twice under different ids (E06.Q01 and E12.Q01, E09.Q01 and
  E12.Q06), so each pair counts as one question and lands on the same
  side. The leave-one-generator-out folds use generator to leave one
  model's answers out of training. Cost reporting sums usage.

## Paraphrase pass

`app/paraphrase/` rewords raw AI answers from the harness at two
strengths, light (synonym swaps, small reorderings) and heavy (fully
restructured sentences), so the detector is tested on reworded AI text.
Rewrite-tier records are skipped.
`app/paraphrase/config.yaml` sets the share of answers to cover, the
strengths, the paraphraser model and the two filter thresholds.

It runs in two steps, from inside `app/`:

```
python -m paraphrase.generate --answers ../data/generated/<run_id>/answers.jsonl            # dry run
python -m paraphrase.generate --answers ../data/generated/<run_id>/answers.jsonl --tag pilot --go
python -m paraphrase.filter --run ../data/paraphrased/<run_id> --spot-check 30
```

`generate` writes `data/paraphrased/<run_id>/candidates.jsonl` and
`run_report.json`. Every record links to its source through
`source_answer_id`, keeps the source's `generator` and `tier`, and stores
`strength`, `paraphraser`, `paraphraser_model_version`,
`paraphraser_settings` and `prompt_template`. A rerun with `--out` pointing
at an existing run folder skips paraphrases already written.

`filter` scores every candidate and writes `paraphrased.jsonl` (kept,
labelled `paraphrased`), `excluded.jsonl` (with `exclusion_reason`) and
`filter_report.json` with counts and score ranges per strength. Two scores:

- `similarity`: cosine similarity of source and paraphrase embeddings.
  Below `similarity_floor` the candidate is excluded as `meaning_lost`.
- `surface_change`: share of the word sequence that changed, 0 to 1.
  Below `min_surface_change` it is excluded as `trivial_rewrite`.

The thresholds in the config come from a hand spot-check of the pilot.
To redo that, set both to null so `filter` keeps and scores everything,
fill in the two blank columns of `spot_check.csv`, pick new values, and
rerun `filter`. No new paraphrases are paid for.

## Human-edited set

`app/human_edit/` builds the human_edited style: AI answers a student
touched up before submitting. Rewrite-tier records are never used as
sources. Editing rules are in
`docs/human_edit_protocol.md`, settings in `app/human_edit/config.yaml`.
Two subsets:

- **genuine**: team members edit answers by hand, following the protocol.
- **simulated**: an LLM applies the same kind of edits at scale. Its prompt
  is derived from the genuine edits, so it copies real behaviour.

Steps, from inside `app/`:

```
python -m human_edit.assign --answers ../data/generated/<run_id>/answers.jsonl
python -m human_edit.collect --returned <folder with the edited sheets>
python -m human_edit.simulate --answers ../data/generated/<run_id>/answers.jsonl --tag pilot       # dry run
python -m human_edit.simulate --answers ../data/generated/<run_id>/answers.jsonl --tag pilot --go
python -m human_edit.compare --run ../data/human_edit/simulated/<run_id>
python -m human_edit.build --run ../data/human_edit/simulated/<run_id> --push <path_in_repo>
```

1. `assign` writes one CSV per editor plus `manifest.jsonl` into
   `data/human_edit/sheets/`. Each answer goes to one editor, and each
   editor gets a mix of generators and tiers. `edited_answer` starts as a
   copy of the original and editors change it in place.
2. `collect` reads the returned sheets into `data/human_edit/genuine.jsonl`.
   Unchanged rows are dropped and counted. Unknown edit types, unknown ids
   and rows in the wrong sheet stop the run with a list of rows to fix.
3. `simulate` derives the prompt from the genuine edits (how often each
   edit type was used, how many types per answer, and a fixed set of
   genuine edits as examples) and saves it as `prompt_spec.json`. Answers
   already hand-edited are skipped. Dry run by default, and `--out`
   pointing at an existing run folder resumes it.
4. `compare` measures word-level edit distance for both subsets and writes
   `comparison.json` plus `comparison.md`, the section for the dataset card.
5. `build` writes `human_edited.jsonl`: every record labelled
   `human_edited`, linked to its source through `source_answer_id`, and
   carrying `edit_source` of `genuine` or `simulated`. The edit_source is
   set from the file a record came from, so a simulated edit can never be
   passed off as genuine. `--push` sends the file to the shared artifact
   repo and records the version id in `build_report.json`.

## Splicer

Builds the mixed-authorship documents for the partial-AI class. Each
document starts from an eligible human answer, and k of its n sentences
are replaced, at their original positions, with sentences from one AI
answer to the same question. Every sentence carries a human or ai label.
No model calls, it only recombines answers that already exist.

`app/splicer/config.yaml` sets the human corpus, the harness output to
draw from, the target AI fractions and the seed. Harness run folders
are timestamped, so first edit `ai_answers` to the run the harness
printed, or pass it directly. From inside `app/`:

```
python -m splicer.build_spliced                # reads ai_answers from config.yaml
python -m splicer.build_spliced --ai-answers data/generated/<run_id>/answers.jsonl   # or override it for one run
```

Output goes to `data/spliced/spliced_<dataset>.jsonl`, one record per
document.
The record schema is documented in `docs/spliced-schema.md`, and the
segmenter validation evidence lives in `docs/segmentation_review_v1.md`
to `v3`.

## Shared artifact storage

One person produces a finished file and **pushes** it once to a
shared, private HuggingFace dataset repo, prompt-patrol/corpus
(ARTIFACT_REPO_ID in app/config.py). Everyone else can **pull** that exact same file
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
   In PowerShell: `$env:HF_TOKEN = "hf_your_own_token_here"`
   This only lasts for that one terminal window/session - you'll need to run
   it again next time you open a new terminal.
3. **Check it actually worked**, before trying anything else:
   ```bash
   python -c "from huggingface_hub import whoami; print(whoami())"
   ```
   If this prints your HuggingFace account info, you're set up correctly.

### Push an artifact

Make sure you've done the one-time setup above and exported your token in
this terminal session first. Then, from inside `apps/data-pipeline`:

```bash
python -c "
import sys
sys.path.insert(0, 'app')
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
python -c "
import sys
sys.path.insert(0, 'app')
from pathlib import Path
from artifact_store import pull_artifact

path = pull_artifact('mohler/splits/mohler_splits_2cc2d581.parquet', Path('data/splits'))
print('Downloaded to:', path)
"
```

To get one *specific past* version instead of the newest (using the commit
hash from when it was pushed):

```bash
python -c "
import sys
sys.path.insert(0, 'app')
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
python -c "
import sys
sys.path.insert(0, 'app')
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
