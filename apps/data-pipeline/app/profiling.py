import json
import logging

import ftfy
import pandas as pd
from ftfy import TextFixerConfig

from loader import OUTPUT_PATH

logger = logging.getLogger(__name__)

REPORT_PATH = OUTPUT_PATH.parent.parent / "profile_report.json"

TEXT_COLUMNS = ["question", "instructor_answer", "student_answer"]
 
_ENCODING_ARTIFACT_CONFIG = TextFixerConfig(uncurl_quotes=False)


def _rows_matching(df: pd.DataFrame, predicate) -> pd.DataFrame:
    mask = pd.Series(False, index=df.index)
    for col in TEXT_COLUMNS:
        mask |= df[col].apply(predicate)
    return df[mask]


def _has_encoding_artifact(text) -> bool:
    return isinstance(text, str) and ftfy.fix_text(text, config=_ENCODING_ARTIFACT_CONFIG) != text


def _is_blank(text) -> bool:
    return isinstance(text, str) and text.strip() == ""


def profile(df: pd.DataFrame) -> dict:
    dup_ids = df[df["id"].duplicated(keep=False)]
    dup_answers = df[df.duplicated(subset=["question", "student_answer"], keep=False)]
    encoding_artifact_rows = _rows_matching(df, _has_encoding_artifact)
    blank_rows = _rows_matching(df, _is_blank)
    missing_rows = df[df[TEXT_COLUMNS].isna().any(axis=1)]

    return {
        "row_count": len(df),
        "duplicate_ids": sorted(dup_ids["id"].tolist()),
        "duplicate_answer_ids": sorted(dup_answers["id"].tolist()),
        "encoding_artifact_ids": sorted(encoding_artifact_rows["id"].tolist()),
        "blank_text_ids": sorted(blank_rows["id"].tolist()),
        "missing_text_ids": sorted(missing_rows["id"].tolist()),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    df = pd.read_parquet(OUTPUT_PATH)
    report = profile(df)

    for key, value in report.items():
        if isinstance(value, list):
            logger.info("%s: %d", key, len(value))
        else:
            logger.info("%s: %s", key, value)

    REPORT_PATH.write_text(json.dumps(report, indent=2))
    logger.info("Wrote report -> %s", REPORT_PATH)


if __name__ == "__main__":
    main()
