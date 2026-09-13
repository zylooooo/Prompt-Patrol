import pandas as pd

from mohler.cleaning import clean


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


def test_clean_drops_score_columns():
    df = pd.DataFrame(
        [
            {**_row("a.1", "Q1", "answer one"), "score_grader_1": 3.0, "score_grader_2": 4.0, "score_avg": 3.5},
        ]
    )

    cleaned, log = clean(df)

    assert log["dropped_columns"] == ["score_grader_1", "score_grader_2", "score_avg"]
    assert "score_grader_1" not in cleaned.columns
    assert "score_grader_2" not in cleaned.columns
    assert "score_avg" not in cleaned.columns


def test_clean_handles_missing_score_columns_gracefully():
    df = pd.DataFrame([_row("a.1", "Q1", "answer one")])

    cleaned, log = clean(df)

    assert log["dropped_columns"] == []
    assert "id" in cleaned.columns
