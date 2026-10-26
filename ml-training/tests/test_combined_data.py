"""combined_data.load_extended: what it reads and what it refuses."""

import pandas as pd
import pytest

import combined_data


def write_corpus(tmp_path, **edits):
    """A tiny valid extended corpus. `edits` maps a partition to a function that changes its frame."""
    rows = {"train": ("t", "q1"), "val": ("v", "q2"), "test": ("s", "q3")}
    for part, (prefix, question) in rows.items():
        frame = pd.DataFrame({
            "answer_id": [f"{prefix}1", f"{prefix}2"],
            "question_id": question,
            "answer": "some short answer",
            "label": [0, 1],
            "partition": part,
            "n_words": 3,
            "dataset": "mohler",
            "slice": ["human", "raw-ai"],
            "core": True,
        })
        edits.get(part, lambda f: f)(frame).to_parquet(tmp_path / f"v0.1-extended-{part}.parquet", index=False)
    return tmp_path


def test_load_extended_returns_the_three_partitions(tmp_path):
    frames = combined_data.load_extended(data_dir=write_corpus(tmp_path))
    assert sorted(frames) == ["test", "train", "val"]
    assert all(len(f) == 2 for f in frames.values())
    assert {"slice", "core", "n_words", "question_id"} <= set(frames["test"].columns)


def test_a_file_holding_another_partition_is_refused(tmp_path):
    write_corpus(tmp_path, val=lambda f: f.assign(partition="train"))
    with pytest.raises(ValueError, match="another partition"):
        combined_data.load_extended(data_dir=tmp_path)


def test_a_repeated_answer_id_across_files_is_refused(tmp_path):
    write_corpus(tmp_path, test=lambda f: f.assign(answer_id=["t1", "s2"]))
    with pytest.raises(ValueError, match="not unique"):
        combined_data.load_extended(data_dir=tmp_path)


def test_a_question_in_two_partitions_is_refused(tmp_path):
    write_corpus(tmp_path, test=lambda f: f.assign(question_id="q1"))  # q1 is a train question
    with pytest.raises(ValueError, match="span partitions"):
        combined_data.load_extended(data_dir=tmp_path)


def test_a_missing_file_says_to_pull_the_data(tmp_path):
    with pytest.raises(FileNotFoundError, match="dvc pull"):
        combined_data.load_extended(data_dir=tmp_path)


def test_load_corpus_refuses_an_unknown_name():
    with pytest.raises(ValueError, match="unknown corpus"):
        combined_data.load_corpus("v9")


def write_sources(tmp_path, **edits):
    """Tiny cleaned source files whose ids match write_corpus()'s question ids after the dataset prefix."""
    frames = {
        "engsaf": pd.DataFrame({"id": ["a1", "a2"], "question_id": ["Q1", "Q1"], "question": ["What is a stack?"] * 2}),
        "mohler": pd.DataFrame({"id": ["E01.Q02.A00", "E01.Q02.A01"], "question": ["Define a queue."] * 2}),
        "sprag": pd.DataFrame({"id": ["s1"], "QuestionID": ["PythonQ003"], "QuestionText": ["How to sort a list?"]}),
    }
    for name, frame in frames.items():
        edits.get(name, lambda f: f)(frame).to_parquet(tmp_path / f"{name}_cleaned.parquet", index=False)
    return tmp_path


def test_load_questions_maps_each_dataset_id_to_its_text(tmp_path):
    questions = combined_data.load_questions(sources_dir=write_sources(tmp_path))
    assert questions == {"engsaf/Q1": "What is a stack?", "mohler/E01.Q02": "Define a queue.",
                         "sprag/PythonQ003": "How to sort a list?"}


def test_load_questions_covers_every_question_in_the_frames(tmp_path):
    frames = {"train": pd.DataFrame({"question_id": ["engsaf/Q1"]}), "test": pd.DataFrame({"question_id": ["sprag/PythonQ003"]})}
    assert len(combined_data.load_questions(frames, sources_dir=write_sources(tmp_path))) == 3
    frames["val"] = pd.DataFrame({"question_id": ["mohler/E09.Q09"]})
    with pytest.raises(ValueError, match="no question text"):
        combined_data.load_questions(frames, sources_dir=tmp_path)


def test_load_questions_refuses_an_id_with_two_texts_and_ignores_blank_text(tmp_path):
    write_sources(tmp_path, engsaf=lambda f: f.assign(question=["What is a stack?", "What is a heap?"]))
    with pytest.raises(ValueError, match="more than one text"):
        combined_data.load_questions(sources_dir=tmp_path)
    write_sources(tmp_path, sprag=lambda f: f.assign(QuestionText=["  "]))
    assert "sprag/PythonQ003" not in combined_data.load_questions(sources_dir=tmp_path)


def test_load_questions_says_to_pull_the_data(tmp_path):
    with pytest.raises(FileNotFoundError, match="dvc pull"):
        combined_data.load_questions(sources_dir=tmp_path)
