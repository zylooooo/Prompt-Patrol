import logging
from pathlib import Path

from datasets import concatenate_datasets, load_dataset

from config import DATASET_CONFIG, DATASET_REPO_ID, DATASET_REVISION

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "raw" / "mohler_raw.parquet"


def load_raw_corpus():
    """Pull the raw Mohler ASAG corpus at the pinned revision.

    Concatenates the open_ended and close_ended splits into one table, keeping
    a `split` column since that distinction is dropped by concatenation.
    """
    ds = load_dataset(
        DATASET_REPO_ID,
        name=DATASET_CONFIG,
        revision=DATASET_REVISION,
    )

    for split_name, split in ds.items():
        ds[split_name] = split.add_column("split", [split_name] * len(split))

    combined = concatenate_datasets(list(ds.values())).sort("id")
    return combined.to_pandas()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    df = load_raw_corpus()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_PATH, index=False)

    logger.info("Loaded %d rows (%s) -> %s", len(df), DATASET_REVISION[:12], OUTPUT_PATH)


if __name__ == "__main__":
    main()
