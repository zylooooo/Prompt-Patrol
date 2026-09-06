DATASET_REPO_ID = "nkazi/MohlerASAG"

# This is the commit hash of the dataset version to use
DATASET_REVISION = "dac06732b42d01a5169f543f6d272f1476cced3e"

DATASET_CONFIG = "raw"

# Fixed so the split is reproducible across runs and machines.
SPLIT_SEED = 42

SPLIT_RATIOS = {"train": 0.7, "val": 0.15, "test": 0.15}

# One shared repo for all corpus artifacts, distinguished by path within it
# (e.g. "mohler/cleaned", "mohler/splits") rather than one repo per artifact -
# mirrors how nkazi/MohlerASAG itself uses one repo with multiple configs.
ARTIFACT_REPO_ID = "prompt-patrol/corpus"
