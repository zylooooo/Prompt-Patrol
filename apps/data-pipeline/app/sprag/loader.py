import logging
from pathlib import Path

import pandas as pd

from config import SPRAG_REPO, SPRAG_REVISION

logger = logging.getLogger(__name__)

_RAW_BASE_URL = f"https://raw.githubusercontent.com/{SPRAG_REPO}/{SPRAG_REVISION}/Data"

OUTPUT_PATH = Path(__file__).parent.parent.parent / "data" / "raw" / "sprag_raw.parquet"


def load_raw_corpus() -> pd.DataFrame:
    """Pull SPRAG's Python-question corpus at the pinned commit.

    Joins Question_data.csv (question text/type/reference answer) with
    PyResponses.csv (student answers/scores) on QuestionID.
    """
    questions = pd.read_csv(f"{_RAW_BASE_URL}/Question_data.csv")
    answers = pd.read_csv(f"{_RAW_BASE_URL}/PyResponses.csv")

    df = answers.merge(questions, on="QuestionID", how="left")

    df.insert(0, "id", df["QuestionID"] + ".A" + df.groupby("QuestionID").cumcount().astype(str))
    return df


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    df = load_raw_corpus()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_PATH, index=False)

    logger.info("Loaded %d rows (%s) -> %s", len(df), SPRAG_REVISION[:12], OUTPUT_PATH)


if __name__ == "__main__":
    main()
