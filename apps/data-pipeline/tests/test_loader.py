from loader import load_raw_corpus

EXPECTED_COLUMNS = {
    "id",
    "question",
    "instructor_answer",
    "student_answer",
    "score_grader_1",
    "score_grader_2",
    "score_avg",
    "split",
}


def test_load_raw_corpus_shape():
    df = load_raw_corpus()

    assert set(df.columns) == EXPECTED_COLUMNS
    assert len(df) == 2442
    assert (df["split"] == "open_ended").sum() == 2273
    assert (df["split"] == "close_ended").sum() == 169


def test_load_raw_corpus_ids_unique_and_sorted():
    df = load_raw_corpus()

    assert df["id"].is_unique
    assert list(df["id"]) == sorted(df["id"])
