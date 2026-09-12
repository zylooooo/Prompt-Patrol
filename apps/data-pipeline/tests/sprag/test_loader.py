from sprag.loader import load_raw_corpus

EXPECTED_COLUMNS = {
    "id",
    "QuestionID",
    "StudentAnswer",
    "Score1",
    "Score2",
    "QuestionText",
    "QuestionType",
    "Reference Answer",
}


def test_load_raw_corpus_shape():
    df = load_raw_corpus()

    assert set(df.columns) == EXPECTED_COLUMNS
    assert len(df) == 2929
    assert df["QuestionID"].nunique() == 68


def test_load_raw_corpus_id_is_unique():
    df = load_raw_corpus()

    assert df["id"].is_unique


def test_load_raw_corpus_has_no_null_question_join():
    df = load_raw_corpus()

    # A null QuestionText/Reference Answer would mean an answer's QuestionID
    # didn't match anything in Question_data.csv
    assert df["QuestionText"].notna().all()
    assert df["Reference Answer"].notna().all()
