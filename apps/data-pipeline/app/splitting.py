import hashlib
import json
import logging
from datetime import UTC, datetime

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

from config import DATASET_REVISION, SPLIT_RATIOS, SPLIT_SEED
from mohler.cleaning import CLEANED_PATH

logger = logging.getLogger(__name__)

SPLITS_DIR = CLEANED_PATH.parent.parent / "splits"

SPLITS_PATH = SPLITS_DIR / "mohler_splits_latest.parquet"


def compute_split_version() -> str:
    """A short id identifying exactly how the dataset was split, so we can track changes over time.
    Affected by the dataset revision, the random seed, and the split ratios.
    """
    payload = f"{DATASET_REVISION}|{SPLIT_SEED}|{SPLIT_RATIOS}"
    return hashlib.sha256(payload.encode()).hexdigest()[:8]


def normalise_question(text: str) -> str:
    """Case and whitespace folded, so two spellings of one question count as one (the rule corpus/build.py uses)."""
    return " ".join(str(text).lower().split())


def question_keys(df: pd.DataFrame) -> pd.Series:
    """The normalised question of every row. A row without question text would fall out of every
    per-question grouping (and so out of every leakage check), so it stops the run instead."""
    missing = df["question"].isna() | (df["question"].astype(str).str.strip() == "")
    if missing.any():
        ids = df.loc[missing, "id"].tolist()[:3] if "id" in df.columns else list(df.index[missing][:3])
        raise ValueError(f"{int(missing.sum())} rows have no question text, first {ids}")
    return df["question"].map(normalise_question)


def split_by_question(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split rows into train/val/test, keeping every answer to a question together.
    Questions that differ only in case or whitespace are kept together too.
    """
    keys = question_keys(df)
    # Label each group by its first-sorting original spelling, not the folded key: GroupShuffleSplit
    # orders groups by label, so this leaves the split unchanged wherever no spellings merge.
    groups = df["question"].groupby(keys).transform("min")
    test_size = SPLIT_RATIOS["test"]
    train_size = SPLIT_RATIOS["train"]
    val_size = SPLIT_RATIOS["val"]

    test_splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=SPLIT_SEED)
    train_val_idx, test_idx = next(test_splitter.split(df, groups=groups))
    train_val_df = df.iloc[train_val_idx]
    test_df = df.iloc[test_idx]

    relative_val_size = val_size / (train_size + val_size)
    val_splitter = GroupShuffleSplit(n_splits=1, test_size=relative_val_size, random_state=SPLIT_SEED)
    train_idx, val_idx = next(val_splitter.split(train_val_df, groups=groups.iloc[train_val_idx]))
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
