import pandas as pd

from profiling import profile

_UNSET = object()


def _row(id, question=_UNSET, instructor_answer="A", student_answer=_UNSET):
    return {
        "id": id,
        "question": f"question for {id}" if question is _UNSET else question,
        "instructor_answer": instructor_answer,
        "student_answer": f"answer for {id}" if student_answer is _UNSET else student_answer,
    }


def test_profile_flags_planted_issues():
    df = pd.DataFrame(
        [
            _row("clean.1"),
            _row("dup_id.1", student_answer="first copy"),
            _row("dup_id.1", student_answer="second copy"),
            _row("dup_answer.1", question="Q2", student_answer="same answer"),
            _row("dup_answer.2", question="Q2", student_answer="same answer"),
            _row("mojibake.1", student_answer="donÃ¢â‚¬â„¢t know"),
            _row("html_entity.1", student_answer="if x &lt; y"),
            _row("curly_quotes.1", student_answer="it’s a “pointer”"),
            _row("blank.1", student_answer="   "),
            _row("missing.1", student_answer=None),
        ]
    )

    report = profile(df)

    assert report["row_count"] == 10
    assert set(report["duplicate_ids"]) == {"dup_id.1"}
    assert set(report["duplicate_answer_ids"]) == {"dup_answer.1", "dup_answer.2"}
    assert set(report["encoding_artifact_ids"]) == {"mojibake.1", "html_entity.1"}
    assert report["blank_text_ids"] == ["blank.1"]
    assert report["missing_text_ids"] == ["missing.1"]
    assert "clean.1" not in (
        report["duplicate_ids"]
        + report["encoding_artifact_ids"]
        + report["blank_text_ids"]
        + report["missing_text_ids"]
    )
    assert "curly_quotes.1" not in report["encoding_artifact_ids"]
