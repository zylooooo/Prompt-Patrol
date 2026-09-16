import json
import logging

import ftfy
import pandas as pd

from sprag.loader import OUTPUT_PATH
from sprag.profiling import _CODE_ELICITING_PATTERN, _ENCODING_ARTIFACT_CONFIG, TEXT_COLUMNS

logger = logging.getLogger(__name__)

CLEANED_PATH = OUTPUT_PATH.parent.parent / "cleaned" / "sprag_cleaned.parquet"
LOG_PATH = OUTPUT_PATH.parent.parent / "sprag_cleaning_log.json"

SCORE_COLUMNS = ["Score1", "Score2"]


def _normalize_line_endings(text):
    return text.replace("\r\n", "\n") if isinstance(text, str) else text


def _fix_encoding(text):
    return ftfy.fix_text(text, config=_ENCODING_ARTIFACT_CONFIG) if isinstance(text, str) else text


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Fix encoding, drop duplicate answers, drop scores, drop code-eliciting rows.
    """
    input_row_count = len(df)
    df = df.copy()

    fixed_ids = set()
    for col in TEXT_COLUMNS:
        normalized = df[col].apply(_normalize_line_endings)
        fixed = normalized.apply(_fix_encoding)
        changed = df[col].apply(lambda t: isinstance(t, str)) & (normalized != fixed)
        fixed_ids.update(df.loc[changed, "id"])
        df[col] = fixed

    # Multiple missing StudentAnswers count as "duplicates" of each other to
    # pandas (NaN == NaN under .duplicated()), so this has to run before dedup -
    # otherwise one all-blank row survives as the dedup "first" copy per group.
    blank_or_missing_mask = df["StudentAnswer"].isna() | (df["StudentAnswer"].str.strip() == "")
    missing_dropped_ids = sorted(df.loc[blank_or_missing_mask, "id"].tolist())
    df = df[~blank_or_missing_mask]

    dup_mask = df.duplicated(subset=["QuestionID", "StudentAnswer"], keep="first")
    duplicate_dropped_ids = sorted(df.loc[dup_mask, "id"].tolist())
    df = df[~dup_mask]

    code_mask = df["QuestionText"].str.contains(_CODE_ELICITING_PATTERN, na=False)
    code_dropped_ids = sorted(df.loc[code_mask, "id"].tolist())
    df = df[~code_mask]

    dropped_columns = [col for col in SCORE_COLUMNS if col in df.columns]
    df = df.drop(columns=dropped_columns).reset_index(drop=True)

    log = {
        "input_row_count": input_row_count,
        "output_row_count": len(df),
        "encoding_fixed_ids": sorted(fixed_ids),
        "missing_or_blank_dropped_ids": missing_dropped_ids,
        "duplicate_dropped_ids": duplicate_dropped_ids,
        "code_eliciting_dropped_ids": code_dropped_ids,
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
        "%d duplicates dropped, %d code-eliciting dropped, columns dropped: %s) -> %s",
        log["input_row_count"],
        log["output_row_count"],
        len(log["encoding_fixed_ids"]),
        len(log["missing_or_blank_dropped_ids"]),
        len(log["duplicate_dropped_ids"]),
        len(log["code_eliciting_dropped_ids"]),
        log["dropped_columns"],
        CLEANED_PATH,
    )


if __name__ == "__main__":
    main()
