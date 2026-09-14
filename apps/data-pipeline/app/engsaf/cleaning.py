import json
import logging

import ftfy
import pandas as pd

from engsaf.loader import OUTPUT_PATH
from engsaf.profiling import _ENCODING_ARTIFACT_CONFIG, TEXT_COLUMNS, is_in_scope

logger = logging.getLogger(__name__)

CLEANED_PATH = OUTPUT_PATH.parent.parent / "cleaned" / "engsaf_cleaned.parquet"
LOG_PATH = OUTPUT_PATH.parent.parent / "engsaf_cleaning_log.json"

DROPPED_COLUMNS = ["score", "rationale", "mark_scheme"]


def _fix_encoding(text):
    return ftfy.fix_text(text, config=_ENCODING_ARTIFACT_CONFIG) if isinstance(text, str) else text


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Fix encoding, drop missing/blank answers, dedupe, then drop
    out-of-scope (non OS/software-engineering) questions and grader columns.
    """
    input_row_count = len(df)
    df = df.copy()

    fixed_ids = set()
    for col in TEXT_COLUMNS:
        before = df[col]
        after = before.apply(_fix_encoding)
        changed = before.apply(lambda t: isinstance(t, str)) & (before != after)
        fixed_ids.update(df.loc[changed, "id"])
        df[col] = after

    blank_or_missing_mask = df["student_answer"].isna() | (df["student_answer"].str.strip() == "")
    missing_dropped_ids = sorted(df.loc[blank_or_missing_mask, "id"].tolist())
    df = df[~blank_or_missing_mask]

    dup_mask = df.duplicated(subset=["question", "student_answer"], keep="first")
    duplicate_dropped_ids = sorted(df.loc[dup_mask, "id"].tolist())
    df = df[~dup_mask]

    out_of_scope_mask = ~df["question"].apply(is_in_scope)
    out_of_scope_dropped_ids = sorted(df.loc[out_of_scope_mask, "id"].tolist())
    df = df[~out_of_scope_mask]

    dropped_columns = [col for col in DROPPED_COLUMNS if col in df.columns]
    df = df.drop(columns=dropped_columns).reset_index(drop=True)

    log = {
        "input_row_count": input_row_count,
        "output_row_count": len(df),
        "encoding_fixed_ids": sorted(fixed_ids),
        "missing_or_blank_dropped_ids": missing_dropped_ids,
        "duplicate_dropped_ids": duplicate_dropped_ids,
        "out_of_scope_dropped_ids": out_of_scope_dropped_ids,
        "dropped_columns": dropped_columns,
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
        "Cleaned %d -> %d rows (%d encoding fixes, %d missing/blank dropped, "
        "%d duplicates dropped, %d out-of-scope dropped, columns dropped: %s) -> %s",
        log["input_row_count"],
        log["output_row_count"],
        len(log["encoding_fixed_ids"]),
        len(log["missing_or_blank_dropped_ids"]),
        len(log["duplicate_dropped_ids"]),
        len(log["out_of_scope_dropped_ids"]),
        log["dropped_columns"],
        CLEANED_PATH,
    )


if __name__ == "__main__":
    main()
