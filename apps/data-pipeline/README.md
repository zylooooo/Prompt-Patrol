# data-pipeline

Assembles the labelled corpus the detector is trained and evaluated on.
Covers dataset ingest, profiling and cleaning for Mohler, SPRAG and
EngSAF, question-level splits, the generation harness that produces the
raw AI answers, the paraphrase and human-edit passes, the splicer that
builds spliced answers from a corpus version, and the corpus build that turns
cleaned answers and harness runs into fine-tuning corpus versions.

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
python app/logo_folds.py    # leave-one-generator-out folds (needs a generator column, which splitting.py does not write)
```

These work on Mohler human answers only.
The fine-tuning corpus is split by `corpus.build`, see Corpus build.

## Generation harness

`app/harness/configs/` holds one config per dataset: `mohler.yaml`,
`sprag.yaml` and `engsaf.yaml`. Each sets the question file, the dataset
namespace, the course named in the student persona, sample counts per
tier, decoding parameters and the generator list, which mixes API and
local Ollama models. The three differ only in the question file,
namespace and course, and a test fails if anything else drifts apart, so
a generator or decoding change goes into all three. Every run covers one
dataset, so generation stays separate for each corpus.

The prompts are written so that nothing but the writing tells the two
labels apart. Every quality-tier answer is asked for about N words,
where N is the length of a student answer to the same question, drawn
with the answer id as seed, so generated lengths follow the students'.
N is never below 3, and the corpus builder drops shorter answers on
both sides.
The prompts also name the course, keep an exam answer's neutral tone,
and forbid markdown and remarks about certainty or memory. The weak,
partial and wrong tiers put their weakness in the content, not in casual
wording.

A generator entry can carry provider switches through `extra_body`. Each
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
generator list stay the same. All three configs leave `rewrite`
commented out, and the corpus build, paraphrase and human-edit passes
all skip rewrites through `is_rewrite` in `app/harness/prompts.py`, so
they only build on answers the model wrote itself. The splicer reads a
corpus version, which holds no rewrites.

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
python -m harness.generate --dataset mohler                                 # dry run, prints the call plan
python -m harness.generate --dataset mohler --questions 1 --tag smoke --go  # one question, real calls
python -m harness.generate --dataset mohler --tag pilot --go                # full run
python -m harness.generate --dataset mohler --resume <run_id> --go          # continue an interrupted run
```

`--dataset` is required, so a run never falls back to another corpus.
`--config <path>` takes any other config instead. Run folders are named
`<timestamp>-<dataset>-<tag>` under `data/generated/`, and `--resume`
takes a folder name there, so finish a run before moving it to
`data/ai_runs/` (see Corpus build).

Nothing spends money without `--go`. A resumed run skips every answer
the folder already holds, so an interrupted run is finished without
paying for those calls twice. It plans from the current config and
`--questions` and ignores `--tag`, so resume with the dataset and
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
      "prompt_template": "weak_v3",
      "tier": "weak",
      "target_words": 23,
      "course": "an introductory C++ programming and data structures course",
      "params_honoured": {"max_completion_tokens": 800},
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
- quality-tier records carry target_words and course, which with the
  template fix the exact prompt sent. A resume stops if the folder holds
  any answer made with another template or course, or for another
  dataset. rewrite records carry
  source_answer_id instead, the id of the student answer they polish.
- a generator that fails three calls in a row is abandoned for the rest
  of the run, so a dead endpoint or bad key cannot stall every remaining
  call. The run report then shows fewer requested calls than the plan.
- Spliced answers record both source answer ids and their question_id.
  Each question goes wholly to train, val or test, and every record
  follows its question there through question_id. Ids asking the same
  question, by identical text or as the twins listed in
  `app/corpus/config.yaml`, count as one question and land on the same
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
python -m paraphrase.generate --answers ../data/ai_runs/mohler-v3-20260930/answers.jsonl            # dry run
python -m paraphrase.generate --answers ../data/ai_runs/mohler-v3-20260930/answers.jsonl --tag pilot --go
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
python -m human_edit.assign --answers ../data/ai_runs/mohler-v3-20260930/answers.jsonl
python -m human_edit.collect --returned <folder with the edited sheets>
python -m human_edit.simulate --answers ../data/ai_runs/mohler-v3-20260930/answers.jsonl --tag pilot       # dry run
python -m human_edit.simulate --answers ../data/ai_runs/mohler-v3-20260930/answers.jsonl --tag pilot --go
python -m human_edit.compare --run ../data/human_edit/simulated/<run_id>
python -m human_edit.build --run ../data/human_edit/simulated/<run_id>
```

1. `assign` writes one CSV per editor plus `manifest.jsonl` into
   `data/human_edit/sheets/`. Each answer goes to one editor, and each
   editor gets a mix of generators and tiers. `edited_answer` starts as a
   copy of the original and editors change it in place. Question text
   comes from `questions_file` in the config, so `--answers` must be a
   run of the config's `dataset`.
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
   passed off as genuine. `--push <path_in_repo>` uploads the file
   through `app/artifact_store.py` to the HuggingFace repo
   prompt-patrol/corpus and records the version id in
   `build_report.json`. That repo is not the team store. Shared data
   lives in DVC on DagsHub, see Corpus build.

## Splicer

Builds spliced answers: a student answer with some of its sentences
replaced, in place, by the first sentences of an AI answer to the same
question. They test whether a detector trained on whole answers catches
answers that are only partly AI. No model calls, it only recombines
answers a corpus version already holds.

The splicer reads a built corpus version, so its cleanup, wrong-tier
trim and partitions carry over. Each configured partition is spliced
only from its own rows, test by default, so no sentence the detector
trained on reaches a spliced answer. Spliced answers are grouped by the
share of their words that are AI into bands 25, 50 and 75, and each
partition, dataset and band holds `answers_per_band` of them, split
evenly across the models, with one student answer starting at most
`max_base_uses` of them per band. Every spliced answer is labelled 1.
`app/splicer/config.yaml` holds these settings. From inside `app/`:

```
python -m splicer.build_spliced                                    # reads corpus from config.yaml
python -m splicer.build_spliced --corpus data/corpus/v0.1.parquet  # or name a version
```

Paths in `config.yaml` and in `--corpus` are relative to
`apps/data-pipeline`, even though the command runs from inside `app/`.

Output goes to `data/corpus/<version>-spliced.parquet` and
`<version>-spliced_manifest.json`, next to the corpus. The build stops if
a partition, dataset and band cannot be filled, naming it, and a failed
build keeps the previous files. Publish the pair to
`ml-training/data/splits/` the same way as the corpus version. The
columns are documented in `docs/spliced-schema.md`, and the segmenter
validation evidence lives in `docs/segmentation_review_v1.md` to `v3`.
The spliced answers cluster heavily by question, so read the Reporting
section of `docs/spliced-schema.md` before quoting detection rates.

## Corpus build

`app/corpus/build.py` turns the cleaned human corpora and one full
harness run per dataset into a fine-tuning corpus version, in the shape
ml-training's `load_splits()` reads. No model calls.

- Labels: cleaned student answers are 0 with generator `human`, raw
  harness answers are 1. Rewrite-tier records are skipped.
- Split: each dataset is split on its own, 70/15/15 by question with the
  seed in `app/config.py`, so every dataset appears in train, val and
  test. Ids sharing a question text, and the twins listed under
  `same_question` in `app/corpus/config.yaml`, land in one partition.
- Keep: a dataset's `keep` setting thins an ai tier to a share of its
  answers before the floor and the train cap, drawn per partition and
  generator with the split seed, so each generator keeps the same share
  in train, val and test. v0.1 keeps half of the wrong tier on every
  dataset. Graded blind on one scale, fully wrong answers are 1.6 to 5.8
  times more common among ai answers than among students, and a
  detector could learn that instead of the writing. Thinning also
  raises the ai share at full marks, which at half is already 1.1 to 1.3
  times the students', so going further trades one skew for another.
  The paraphrase and human-edit passes read a run's answers.jsonl, so a
  set meant to match a corpus version should keep only the ai
  answer_ids found in that version's parquet. The splicer reads the
  corpus version itself.
- Balance: in train, each question keeps at most as many human answers
  as it has ai answers, so no dataset is mostly human. Val and test keep every
  human answer, since they set and measure the false-positive rate.
- Cleanup: every answer, human and ai, goes through `clean_text` in
  `app/corpus/clean.py` (HTML escapes, line breaks, list markers,
  answer-sheet labels, LaTeX arrows, empty call brackets, curly quotes
  and dashes, backticks and bold, and a full stop where a line ended a
  sentence without one), so formatting only one side uses cannot give
  the label away. The detector has to apply the same function to
  submitted text.
- Floor: answers under 3 words are dropped on both sides. The harness
  never asks for fewer and models seldom write fewer, while some
  students do, so these answers would give the label away. The detector
  therefore has no evidence on answers that short. The app already
  reports answers under 10 words as too short to judge, so its floor
  must never go below this one.
- Checks: the build stops if a question or question group spans two
  partitions, an answer_id repeats, an answer is empty, any dataset
  lacks human or ai answers in any partition, a run answers questions
  outside its dataset, a tier mixes prompt templates or courses, a
  question has no text, `same_question` names an unknown id or dataset,
  a dataset has a setting the builder does not read, or `keep` names a
  tier the run lacks or a share that is 0, negative or above 1.

Each dataset's `ai_answers` in `app/corpus/config.yaml` points at its
full harness run under `data/ai_runs/`, where finished runs are moved
from `data/generated/` and renamed by dataset, prompt version and date.
The config notes each folder's original run id. The runs cannot be
regenerated identically, so `data/ai_runs/` is tracked with DVC on the
DagsHub remote that ml-training uses, through the pointer file
`data/ai_runs.dvc`. Without them locally, set up DVC as in
ml-training's README and run `dvc pull apps/data-pipeline/data/ai_runs.dvc`
from the repo root. To add a run, pull the existing runs first, move
the new run in and add a row for it to `data/ai_runs/README.md`, then
run `dvc add apps/data-pipeline/data/ai_runs` from the repo root,
commit the updated pointer and `dvc push`. `dvc add`
records only what is in the folder, so adding from a clone without the
other runs would publish a folder without them. Then from inside `app/`:

```
python -m corpus.build                     # every dataset in the config
python -m corpus.build --datasets mohler   # a check build, written as v0.1-only-mohler
```

Output goes to `data/corpus/<version>.parquet` and
`<version>_manifest.json`. The manifest records the source files and
their hashes, rows per partition and dataset, the generators, the
prompt template behind each tier, the cleanup version, the twin pairs
used, the keep shares, the answers dropped by keep, by the floor, by
the train cap and as rewrite records, questions without ai answers, and
the partition of every question.

To publish a version, copy both files into `ml-training/data/splits/`
and follow "Changing the data" in `ml-training/README.md`. Run
`dvc pull` there first. `dvc add data` records only what is in the
folder, so adding from a clone that lacks the other files in
`ml-training/data/` would publish a folder without them. Corpus v0.1 is
published.

## Shared artifact storage

Shared data is stored with DVC on the team's DagsHub remote, named in
`.dvc/config` at the repo root and also used by ml-training. Git holds
only the pointer files and the remote holds the bytes. DVC comes with
ml-training's requirements, or install it on its own with
`pip install "dvc[http]==3.67.1"`. Set its credentials as in "The data,
and DVC" in `ml-training/README.md`, then run `dvc pull` from the repo
root. Two pointer files cover everything shared:

- `apps/data-pipeline/data/ai_runs.dvc`: the finished harness runs in
  `data/ai_runs/`. Adding a run is covered under Corpus build.
- `ml-training/data.dvc`: the published corpus versions in
  `ml-training/data/splits/`, plus copies of the three cleaned corpora
  in `ml-training/data/sources/`, the files v0.1 was built from. The
  corpus build reads `data/cleaned/`, so copy them there to rebuild
  v0.1 without running the cleaning steps.

Nothing else under `data/` is in git or DVC.

`app/artifact_store.py` is not the team store. Its `push_artifact`,
`pull_artifact` and `verify_roundtrip` push to and pull from a private
HuggingFace dataset repo, prompt-patrol/corpus (ARTIFACT_REPO_ID in
`app/config.py`), with the commit hash of each push as the version id.
In `app/`, only `python -m human_edit.build --push` calls it.
`push_artifact` creates the repo if it is missing, which needs an
HF_TOKEN with write access to the prompt-patrol organisation.
