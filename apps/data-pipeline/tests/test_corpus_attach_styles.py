import pandas as pd
import pytest

from corpus.attach_styles import attach, check


def corpus():
    rows = [
        {"answer": "student text here", "label": 0, "partition": "train", "question_id": "mohler/Q1",
         "answer_id": "mohler/Q1.A1", "generator": "human", "n_words": 3, "dataset": "mohler", "tier": None},
        {"answer": "model text one", "label": 1, "partition": "train", "question_id": "mohler/Q1",
         "answer_id": "mohler/Q1/m/correct/01", "generator": "m", "n_words": 3, "dataset": "mohler", "tier": "correct"},
        {"answer": "model text two", "label": 1, "partition": "test", "question_id": "mohler/Q2",
         "answer_id": "mohler/Q2/m/wrong/01", "generator": "m", "n_words": 3, "dataset": "mohler", "tier": "wrong"},
    ]
    return pd.DataFrame(rows)


def para(source, strength="light", answer="a reworded model answer", **extra):
    return {"paraphrase_id": f"{source}/para-{strength}", "source_answer_id": source, "strength": strength,
            "answer": answer, "similarity": 0.9, "surface_change": 0.3, "paraphraser": "p", **extra}


def test_rows_take_the_partition_of_their_source():
    frame, _ = attach([para("mohler/Q1/m/correct/01"), para("mohler/Q2/m/wrong/01")], corpus(), "paraphrased")
    assert dict(zip(frame["source_answer_id"], frame["partition"])) == {
        "mohler/Q1/m/correct/01": "train", "mohler/Q2/m/wrong/01": "test"}
    assert set(frame["label"]) == {1} and set(frame["tier"]) == {"correct", "wrong"}


def test_sources_outside_the_corpus_are_dropped_and_counted():
    frame, stats = attach([para("mohler/Q1/m/correct/01"), para("mohler/Q9/m/weak/01")], corpus(), "paraphrased")
    assert len(frame) == 1 and stats["dropped_source_not_in_corpus"] == 1


def test_a_human_answer_is_never_a_source():
    _, stats = attach([para("mohler/Q1.A1")], corpus(), "paraphrased")
    assert stats["dropped_source_not_in_corpus"] == 1


def test_text_is_cleaned_and_short_answers_dropped():
    frame, stats = attach([para("mohler/Q1/m/correct/01", answer="**bold**   answer  here"),
                           para("mohler/Q2/m/wrong/01", answer="two words")], corpus(), "paraphrased")
    assert list(frame["answer"]) == ["bold answer here"] and stats["dropped_below_floor"] == 1


def test_style_names_carry_strength_and_edit_source():
    frame, _ = attach([para("mohler/Q1/m/correct/01", "heavy")], corpus(), "paraphrased")
    assert list(frame["style"]) == ["paraphrased-heavy"]
    edit = {"edit_id": "e1", "source_answer_id": "mohler/Q1/m/correct/01", "answer": "an edited model answer",
            "edit_source": "genuine", "edit_types": ["reword"], "edit_distance": 0.2}
    frame, _ = attach([edit], corpus(), "human_edited")
    assert list(frame["style"]) == ["human_edited-genuine"]


def test_duplicate_ids_stop_the_run():
    record = para("mohler/Q1/m/correct/01")
    with pytest.raises(SystemExit):
        attach([record, record], corpus(), "paraphrased")


def test_a_mismatched_question_stops_the_run():
    with pytest.raises(SystemExit):
        attach([para("mohler/Q1/m/correct/01", question_id="mohler/Q2")], corpus(), "paraphrased")


def test_check_stops_a_row_outside_its_partition():
    frame, _ = attach([para("mohler/Q1/m/correct/01")], corpus(), "paraphrased")
    with pytest.raises(SystemExit):
        check(frame, {"question_partitions": {"mohler/Q1": "test"}})
