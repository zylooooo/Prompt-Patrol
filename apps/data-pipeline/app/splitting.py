import hashlib
import json
import logging
from datetime import UTC, datetime

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

from cleaning import CLEANED_PATH
from config import DATASET_REVISION, SPLIT_RATIOS, SPLIT_SEED

logger = logging.getLogger(__name__)

SPLITS_DIR = CLEANED_PATH.parent.parent / "splits"

SPLITS_PATH = SPLITS_DIR / "mohler_splits_latest.parquet"


def compute_split_version() -> str:
    """A short id identifying exactly how the dataset was split, so we can track changes over time.
    Affected by the dataset revision, the random seed, and the split ratios.
    """
    payload = f"{DATASET_REVISION}|{SPLIT_SEED}|{SPLIT_RATIOS}"
    return hashlib.sha256(payload.encode()).hexdigest()[:8]


def split_by_question(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split rows into train/val/test, keeping every answer to a question together.
    """
    test_size = SPLIT_RATIOS["test"]
    train_size = SPLIT_RATIOS["train"]
    val_size = SPLIT_RATIOS["val"]

    test_splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=SPLIT_SEED)
    train_val_idx, test_idx = next(test_splitter.split(df, groups=df["question"]))
    train_val_df = df.iloc[train_val_idx]
    test_df = df.iloc[test_idx]

    relative_val_size = val_size / (train_size + val_size)
    val_splitter = GroupShuffleSplit(n_splits=1, test_size=relative_val_size, random_state=SPLIT_SEED)
    train_idx, val_idx = next(val_splitter.split(train_val_df, groups=train_val_df["question"]))
    train_df = train_val_df.iloc[train_idx]
    val_df = train_val_df.iloc[val_idx]

    return {"train": train_df, "val": val_df, "test": test_df}


def build_manifest(splits: dict[str, pd.DataFrame], version: str) -> dict:
    return {
        "split_version": version,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_dataset_revision": DATASET_REVISION,
        "seed": SPLIT_SEED,
        "ratios": SPLIT_RATIOS,
        "partitions": {
            name: {"rows": len(split_df), "questions": int(split_df["question"].nunique())}
            for name, split_df in splits.items()
        },
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    df = pd.read_parquet(CLEANED_PATH)
    splits = split_by_question(df)
    version = compute_split_version()

    for name, split_df in splits.items():
        logger.info(
            "%s: %d rows, %d questions",
            name,
            len(split_df),
            split_df["question"].nunique(),
        )

    combined = pd.concat(
        [split_df.assign(partition=name) for name, split_df in splits.items()],
        ignore_index=True,
    )

    SPLITS_DIR.mkdir(parents=True, exist_ok=True)
    versioned_path = SPLITS_DIR / f"mohler_splits_{version}.parquet"
    manifest_path = SPLITS_DIR / f"mohler_splits_{version}_manifest.json"

    combined.to_parquet(versioned_path, index=False)
    combined.to_parquet(SPLITS_PATH, index=False)
    manifest_path.write_text(json.dumps(build_manifest(splits, version), indent=2))

    logger.info("Wrote split version %s -> %s", version, versioned_path)
    logger.info("Wrote manifest -> %s", manifest_path)
    logger.info("Updated latest pointer -> %s", SPLITS_PATH)


if __name__ == "__main__":
    main()
