from engsaf.loader import load_raw_corpus

EXPECTED_COLUMNS = {
    "id",
    "question_id",
    "question",
    "student_answer",
    "reference_answer",
    "mark_scheme",
    "score",
    "rationale",
    "split",
}


def test_load_raw_corpus_shape():
    df = load_raw_corpus()

    assert set(df.columns) == EXPECTED_COLUMNS
    assert len(df) == 5579
    assert df["question_id"].nunique() == 118


def test_load_raw_corpus_id_is_unique():
    df = load_raw_corpus()

    assert df["id"].is_unique


def test_load_raw_corpus_has_no_nulls_in_text_columns():
    df = load_raw_corpus()

    assert df["question"].notna().all()
    assert df["student_answer"].notna().all()
    assert df["reference_answer"].notna().all()
