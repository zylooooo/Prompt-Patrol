DATASET_REPO_ID = "nkazi/MohlerASAG"

# This is the commit hash of the dataset version to use
DATASET_REVISION = "dac06732b42d01a5169f543f6d272f1476cced3e"

DATASET_CONFIG = "raw"

# Fixed so the split is reproducible across runs and machines.
SPLIT_SEED = 42

SPLIT_RATIOS = {"train": 0.7, "val": 0.15, "test": 0.15}
