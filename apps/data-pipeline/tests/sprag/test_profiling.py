import pandas as pd

from sprag.profiling import profile

_UNSET = object()


def _row(id, qid=_UNSET, question=_UNSET, student_answer=_UNSET, reference_answer="ref"):
    return {
        "id": id,
        "QuestionID": id if qid is _UNSET else qid,
        "QuestionText": f"question for {id}" if question is _UNSET else question,
        "StudentAnswer": f"answer for {id}" if student_answer is _UNSET else student_answer,
        "Reference Answer": reference_answer,
    }


def test_profile_flags_planted_issues():
    df = pd.DataFrame(
        [
            _row("clean.1"),
            _row("dup.1", qid="Q1", student_answer="same"),
            _row("dup.2", qid="Q1", student_answer="same"),
            _row("mojibake.1", student_answer="donÃ¢â‚¬â„¢t know"),
            _row("blank.1", student_answer="   "),
            _row("missing.1", student_answer=None),
        ]
    )

    report = profile(df)

    assert report["row_count"] == 6
    assert set(report["duplicate_answer_ids"]) == {"dup.1", "dup.2"}
    assert report["encoding_artifact_ids"] == ["mojibake.1"]
    assert report["blank_text_ids"] == ["blank.1"]
    assert report["missing_text_ids"] == ["missing.1"]


def test_profile_flags_code_eliciting_questions_by_text_not_type():
    df = pd.DataFrame(
        [
            _row("code.1", question="Write a Python function to reverse a string."),
            _row("code.2", question="Write a recursive script to compute factorial."),
            _row("prose.1", question="Write about Python's key features."),
            _row("prose.2", question="Write down the mutable data structures in Python."),
            _row("prose.3", question="How to convert a string to lower case in Python?"),
        ]
    )

    report = profile(df)

    assert set(report["code_eliciting_question_ids"]) == {"code.1", "code.2"}
    assert set(report["code_eliciting_ids"]) == {"code.1", "code.2"}
