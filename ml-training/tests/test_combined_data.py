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
