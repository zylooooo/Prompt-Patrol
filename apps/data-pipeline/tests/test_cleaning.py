import pandas as pd

from cleaning import clean


def _row(id, question, student_answer, instructor_answer="A"):
    return {"id": id, "question": question, "instructor_answer": instructor_answer, "student_answer": student_answer}


def test_clean_fixes_encoding_and_drops_duplicates():
    df = pd.DataFrame(
        [
            _row("keep.1", "Q1", "unique answer one"),
            _row("keep.2", "Q2", "unique answer two"),
            _row("dup.1", "Q3", "push"),
            _row("dup.2", "Q3", "push"),
            _row("dup.3", "Q3", "push"),
            _row("entity.1", "Q4", "if x &lt; y"),
        ]
    )

    cleaned, log = clean(df)

    assert log["input_row_count"] == 6
    assert log["output_row_count"] == 4
    assert log["encoding_fixed_ids"] == ["entity.1"]
    assert log["duplicate_dropped_ids"] == ["dup.2", "dup.3"]

    assert set(cleaned["id"]) == {"keep.1", "keep.2", "dup.1", "entity.1"}
    assert cleaned.loc[cleaned["id"] == "entity.1", "student_answer"].iloc[0] == "if x < y"


def test_clean_fixes_encoding_before_deduping():
    df = pd.DataFrame(
        [
            _row("a.1", "Q1", "x &lt; y"),
            _row("a.2", "Q1", "x < y"),
        ]
    )

    cleaned, log = clean(df)

    assert log["output_row_count"] == 1
    assert log["duplicate_dropped_ids"] == ["a.2"]
    assert cleaned["id"].tolist() == ["a.1"]
