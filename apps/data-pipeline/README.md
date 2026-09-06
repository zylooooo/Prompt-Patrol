# data-pipeline

Assembles the labelled corpus other epics train and evaluate on.

## Pipeline order

```
python app/loader.py        # pull the pinned Mohler revision -> data/raw/
python app/profiling.py     # report duplicates/encoding issues -> data/profile_report.json
python app/cleaning.py      # fix + dedupe -> data/cleaned/, data/cleaning_log.json
python app/splitting.py     # question-level train/val/test -> data/splits/
python app/leakage_check.py # verify no question crosses a split boundary
python app/logo_folds.py    # leave-one-generator-out folds (needs AI-generated data first)
```

Each step reads the previous step's output file. `data/` is gitignored - nothing
here is committed to source control; every teammate regenerates it locally by
running these scripts in order, from inside this `apps/data-pipeline` folder.

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
