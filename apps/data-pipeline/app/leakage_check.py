import logging
import sys

import pandas as pd

from splitting import SPLITS_PATH

logger = logging.getLogger(__name__)


def find_leaking_questions(df: pd.DataFrame) -> dict[str, list[str]]:
    """Questions that appear in more than one partition, mapped to which ones."""
    question_partitions = df.groupby("question")["partition"].unique()
    leaking = question_partitions[question_partitions.apply(len) > 1]
    return {question: sorted(partitions) for question, partitions in leaking.items()}


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    df = pd.read_parquet(SPLITS_PATH)
    leaking = find_leaking_questions(df)

    if leaking:
        logger.error("Leakage found: %d questions span multiple partitions", len(leaking))
        for question, partitions in leaking.items():
            logger.error("  %r -> %s", question, partitions)
        sys.exit(1)

    logger.info("No leakage: every question stays within a single partition (%d questions checked)", df["question"].nunique())


if __name__ == "__main__":
    main()
