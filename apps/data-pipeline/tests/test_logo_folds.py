import pandas as pd
import pytest

from logo_folds import leave_one_generator_out


def _make_corpus():
    rows = []
    for i in range(10):
        rows.append({"id": f"human.{i}", "generator": "human", "partition": "train" if i < 7 else "test"})
    for generator in ("gpt", "claude", "gemini"):
        for i in range(5):
            rows.append({"id": f"{generator}.{i}", "generator": generator, "partition": "train"})
    return pd.DataFrame(rows)


def test_leave_one_generator_out_produces_one_fold_per_ai_generator():
    df = _make_corpus()
    folds = leave_one_generator_out(df)
    assert set(folds) == {"gpt", "claude", "gemini"}


def test_held_out_generator_is_test_only():
    df = _make_corpus()
    folds = leave_one_generator_out(df)

    gpt_fold = folds["gpt"]
    assert set(gpt_fold["test"].loc[gpt_fold["test"]["generator"] == "gpt", "id"]) == {f"gpt.{i}" for i in range(5)}
    assert "gpt" not in gpt_fold["train"]["generator"].values


def test_other_generators_stay_in_train_only():
    df = _make_corpus()
    folds = leave_one_generator_out(df)

    gpt_fold = folds["gpt"]
    assert set(gpt_fold["train"].loc[gpt_fold["train"]["generator"] == "claude", "id"]) == {f"claude.{i}" for i in range(5)}
    assert "claude" not in gpt_fold["test"]["generator"].values
    assert "gemini" not in gpt_fold["test"]["generator"].values


def test_human_rows_keep_their_existing_partition_in_every_fold():
    df = _make_corpus()
    folds = leave_one_generator_out(df)

    expected_human_train = {f"human.{i}" for i in range(7)}
    expected_human_test = {f"human.{i}" for i in range(7, 10)}

    for fold in folds.values():
        human_train_ids = set(fold["train"].loc[fold["train"]["generator"] == "human", "id"])
        human_test_ids = set(fold["test"].loc[fold["test"]["generator"] == "human", "id"])
        assert human_train_ids == expected_human_train
        assert human_test_ids == expected_human_test


def test_no_row_appears_in_both_train_and_test_within_a_fold():
    df = _make_corpus()
    folds = leave_one_generator_out(df)

    for fold in folds.values():
        assert set(fold["train"]["id"]).isdisjoint(set(fold["test"]["id"]))


def test_raises_without_generator_column():
    df = pd.DataFrame([{"id": "a", "partition": "train"}])
    with pytest.raises(ValueError, match="generator"):
        leave_one_generator_out(df)


def test_raises_with_only_human_generator():
    df = pd.DataFrame([{"id": "a", "generator": "human", "partition": "train"}])
    with pytest.raises(ValueError, match="No AI generators"):
        leave_one_generator_out(df)
