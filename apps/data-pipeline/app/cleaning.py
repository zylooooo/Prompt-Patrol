import json
import logging

import ftfy
import pandas as pd

from loader import OUTPUT_PATH
from profiling import _ENCODING_ARTIFACT_CONFIG, TEXT_COLUMNS

logger = logging.getLogger(__name__)

CLEANED_PATH = OUTPUT_PATH.parent.parent / "cleaned" / "mohler_cleaned.parquet"
LOG_PATH = OUTPUT_PATH.parent.parent / "cleaning_log.json"


def _fix_encoding(text):
    return ftfy.fix_text(text, config=_ENCODING_ARTIFACT_CONFIG) if isinstance(text, str) else text


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Fix encoding artifacts, then drop duplicate answers, keeping the lowest id.

    Encoding is fixed before deduping.
    """
    input_row_count = len(df)
    df = df.copy()

    fixed_ids = set()
    for col in TEXT_COLUMNS:
        before = df[col]
        after = before.apply(_fix_encoding)
        fixed_ids.update(df.loc[before != after, "id"])
        df[col] = after

    # keep="first" keeps the lowest id.
    dup_mask = df.duplicated(subset=["question", "student_answer"], keep="first")
    dropped_ids = sorted(df.loc[dup_mask, "id"].tolist())
    df = df[~dup_mask].reset_index(drop=True)

    log = {
        "input_row_count": input_row_count,
        "output_row_count": len(df),
        "encoding_fixed_ids": sorted(fixed_ids),
        "duplicate_dropped_ids": dropped_ids,
    }
    return df, log


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    df = pd.read_parquet(OUTPUT_PATH)
    cleaned, log = clean(df)

    CLEANED_PATH.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_parquet(CLEANED_PATH, index=False)
    LOG_PATH.write_text(json.dumps(log, indent=2))

    logger.info(
        "Cleaned %d -> %d rows (%d encoding fixes, %d duplicates dropped) -> %s",
        log["input_row_count"],
        log["output_row_count"],
        len(log["encoding_fixed_ids"]),
        len(log["duplicate_dropped_ids"]),
        CLEANED_PATH,
    )


if __name__ == "__main__":
    main()
