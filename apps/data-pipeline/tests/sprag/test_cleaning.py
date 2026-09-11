import pandas as pd

from sprag.cleaning import clean

_UNSET = object()


def _row(id, qid=_UNSET, question=_UNSET, student_answer=_UNSET, score1=0, score2=0, reference_answer="ref"):
    return {
        "id": id,
        "QuestionID": id if qid is _UNSET else qid,
        "QuestionText": f"question for {id}" if question is _UNSET else question,
        "StudentAnswer": f"answer for {id}" if student_answer is _UNSET else student_answer,
        "Score1": score1,
        "Score2": score2,
        "Reference Answer": reference_answer,
    }


def test_clean_fixes_encoding_and_drops_duplicates():
    df = pd.DataFrame(
        [
            _row("keep.1", qid="Q1"),
            _row("dup.1", qid="Q3", student_answer="push"),
            _row("dup.2", qid="Q3", student_answer="push"),
            _row("entity.1", qid="Q4", student_answer="if x &lt; y"),
        ]
    )

    cleaned, log = clean(df)

    assert log["input_row_count"] == 4
    assert log["output_row_count"] == 3
    assert log["encoding_fixed_ids"] == ["entity.1"]
    assert log["duplicate_dropped_ids"] == ["dup.2"]
    assert set(cleaned["id"]) == {"keep.1", "dup.1", "entity.1"}
    assert cleaned.loc[cleaned["id"] == "entity.1", "StudentAnswer"].iloc[0] == "if x < y"


def test_clean_fixes_encoding_before_deduping():
    df = pd.DataFrame(
        [
            _row("a.1", qid="Q1", student_answer="x &lt; y"),
            _row("a.2", qid="Q1", student_answer="x < y"),
        ]
    )

    cleaned, log = clean(df)

    assert log["output_row_count"] == 1
    assert log["duplicate_dropped_ids"] == ["a.2"]
    assert cleaned["id"].tolist() == ["a.1"]


def test_clean_drops_code_eliciting_rows():
    df = pd.DataFrame(
        [
            _row("prose.1", question="What is a list in Python?"),
            _row("code.1", question="Write a Python function to reverse a string."),
        ]
    )

    cleaned, log = clean(df)

    assert log["code_eliciting_dropped_ids"] == ["code.1"]
    assert cleaned["id"].tolist() == ["prose.1"]


def test_clean_does_not_flag_missing_values_as_encoding_fixed():
    df = pd.DataFrame(
        [
            _row("missing.1", student_answer=None),
        ]
    )

    cleaned, log = clean(df)

    assert log["encoding_fixed_ids"] == []


def test_clean_drops_missing_and_blank_answers():
    df = pd.DataFrame(
        [
            _row("missing.1", student_answer=None),
            _row("blank.1", student_answer="   "),
            _row("real.1", student_answer="a real answer"),
        ]
    )

    cleaned, log = clean(df)

    assert set(log["missing_or_blank_dropped_ids"]) == {"missing.1", "blank.1"}
    assert cleaned["id"].tolist() == ["real.1"]


def test_clean_drops_all_but_one_missing_answer_as_missing_not_duplicate():
    # Regression: multiple missing answers count as "duplicates" of each
    # other under pandas .duplicated() (NaN == NaN there), which used to let
    # one all-blank row survive as the dedup "first" copy per question.
    df = pd.DataFrame(
        [
            _row("missing.1", qid="Q1", student_answer=None),
            _row("missing.2", qid="Q1", student_answer=None),
            _row("real.1", qid="Q1", student_answer="a real answer"),
        ]
    )

    cleaned, log = clean(df)

    assert set(log["missing_or_blank_dropped_ids"]) == {"missing.1", "missing.2"}
    assert log["duplicate_dropped_ids"] == []
    assert cleaned["id"].tolist() == ["real.1"]


def test_clean_drops_score_columns():
    df = pd.DataFrame([_row("a.1")])

    cleaned, log = clean(df)

    assert log["dropped_columns"] == ["Score1", "Score2"]
    assert "Score1" not in cleaned.columns
    assert "Score2" not in cleaned.columns
