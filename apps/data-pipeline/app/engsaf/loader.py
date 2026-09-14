import logging
from pathlib import Path

import pandas as pd
from datasets import concatenate_datasets, load_dataset

from config import ENGSAF_REPO_ID, ENGSAF_REVISION

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path(__file__).parent.parent.parent / "data" / "raw" / "engsaf_raw.parquet"


def load_raw_corpus() -> pd.DataFrame:
    """Pull the raw EngSAF corpus at the pinned revision.

    Concatenates the train/validation/test splits into one table, keeping a
    `split` column. The source has no per-question id, so one is synthesized
    (`question_id`) from the order questions first appear in this
    concatenation - stable as long as the pinned revision doesn't change.
    """
    ds = load_dataset(ENGSAF_REPO_ID, revision=ENGSAF_REVISION)

    for split_name, split in ds.items():
        ds[split_name] = split.add_column("split", [split_name] * len(split))

    df = concatenate_datasets(list(ds.values())).to_pandas()

    question_codes, _ = pd.factorize(df["question"])
    df.insert(0, "question_id", [f"Q{code}" for code in question_codes])
    df.insert(0, "id", df["question_id"] + ".A" + df.groupby("question_id").cumcount().astype(str))
    return df


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    df = load_raw_corpus()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_PATH, index=False)

    logger.info("Loaded %d rows (%s) -> %s", len(df), ENGSAF_REVISION[:12], OUTPUT_PATH)


if __name__ == "__main__":
    main()
