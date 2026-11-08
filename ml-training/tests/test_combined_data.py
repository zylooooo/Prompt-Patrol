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


def weight_frame():
    return pd.DataFrame({
        "label": [0, 0, 1, 1, 1, 1],
        "dataset": ["mohler", "sprag", "mohler", "mohler", "sprag", "sprag"],
        "slice": ["human", "human", "raw-ai", "spliced-25", "spliced-50", "paraphrased-heavy"],
    })


def test_no_weight_spec_gives_equal_weights():
    assert combined_data.row_weights(weight_frame(), "").tolist() == [1.0] * 6


def test_weights_match_wildcards_and_keep_each_label_averaging_one():
    w = combined_data.row_weights(weight_frame(), "slice=spliced-*:3")
    # AI rows 3, 3, 1, 1 before rescaling, to mean 1
    assert w[2:].tolist() == pytest.approx([0.5, 1.5, 1.5, 0.5])
    assert w[:2].tolist() == [1.0, 1.0]


def test_conditions_combine_with_and():
    w = combined_data.row_weights(weight_frame(), "dataset=mohler&slice=human:3")
    assert w[:2].tolist() == pytest.approx([1.5, 0.5])


def test_a_rule_that_matches_nothing_is_refused():
    with pytest.raises(ValueError, match="matches no training row"):
        combined_data.row_weights(weight_frame(), "slice=splcied-*:2")


@pytest.mark.parametrize("spec", ["slice=human", "slice:2", "slice=human:0", "nosuch=x:2"])
def test_a_malformed_rule_is_refused(spec):
    with pytest.raises(ValueError):
        combined_data.row_weights(weight_frame(), spec)
