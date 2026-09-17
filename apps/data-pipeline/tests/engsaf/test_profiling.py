import pandas as pd

from engsaf.profiling import is_in_scope, profile

_UNSET = object()

_IN_SCOPE_QUESTION = "Define Priority Inversion in single line."
_OUT_OF_SCOPE_QUESTION = "What is an orthotropic material ?"


def _row(id, qid=_UNSET, question=_UNSET, student_answer=_UNSET, reference_answer="ref"):
    return {
        "id": id,
        "question_id": id if qid is _UNSET else qid,
        "question": f"question for {id}" if question is _UNSET else question,
        "student_answer": f"answer for {id}" if student_answer is _UNSET else student_answer,
        "reference_answer": reference_answer,
    }


def test_is_in_scope_matches_known_in_scope_question_regardless_of_whitespace():
    assert is_in_scope(_IN_SCOPE_QUESTION)
    assert is_in_scope("  Define   Priority Inversion \n in single line.  ")


def test_is_in_scope_rejects_out_of_scope_question():
    assert not is_in_scope(_OUT_OF_SCOPE_QUESTION)


def test_profile_flags_planted_issues():
    df = pd.DataFrame(
        [
            _row("clean.1", question=_IN_SCOPE_QUESTION),
            _row("dup.1", qid="Q1", question=_IN_SCOPE_QUESTION, student_answer="same"),
            _row("dup.2", qid="Q1", question=_IN_SCOPE_QUESTION, student_answer="same"),
            _row("mojibake.1", question=_IN_SCOPE_QUESTION, student_answer="donÃ¢â‚¬â„¢t know"),
            _row("blank.1", question=_IN_SCOPE_QUESTION, student_answer="   "),
            _row("missing.1", question=_IN_SCOPE_QUESTION, student_answer=None),
        ]
    )

    report = profile(df)

    assert report["row_count"] == 6
    assert set(report["duplicate_answer_ids"]) == {"dup.1", "dup.2"}
    assert report["encoding_artifact_ids"] == ["mojibake.1"]
    assert report["blank_text_ids"] == ["blank.1"]
    assert report["missing_text_ids"] == ["missing.1"]


def test_profile_flags_out_of_scope_questions_by_text():
    df = pd.DataFrame(
        [
            _row("scoped.1", qid="Q1", question=_IN_SCOPE_QUESTION),
            _row("scoped.2", qid="Q1", question=_IN_SCOPE_QUESTION),
            _row("other.1", qid="Q2", question=_OUT_OF_SCOPE_QUESTION),
        ]
    )

    report = profile(df)

    assert report["out_of_scope_question_ids"] == ["Q2"]
    assert report["out_of_scope_ids"] == ["other.1"]
