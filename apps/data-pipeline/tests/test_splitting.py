from unittest.mock import patch

import pandas as pd
import pytest

from splitting import build_manifest, compute_split_version, split_by_question


def _make_corpus(n_questions=40, answers_per_question=10):
    rows = []
    for q in range(n_questions):
        for a in range(answers_per_question):
            rows.append({"id": f"Q{q}.A{a}", "question": f"question {q}", "student_answer": f"answer {a}"})
    return pd.DataFrame(rows)


def test_split_by_question_no_leakage():
    df = _make_corpus()
    splits = split_by_question(df)

    question_sets = {name: set(split_df["question"]) for name, split_df in splits.items()}
    assert question_sets["train"].isdisjoint(question_sets["val"])
    assert question_sets["train"].isdisjoint(question_sets["test"])
    assert question_sets["val"].isdisjoint(question_sets["test"])


def test_split_by_question_preserves_all_rows():
    df = _make_corpus()
    splits = split_by_question(df)

    total = sum(len(split_df) for split_df in splits.values())
    assert total == len(df)
    all_ids = pd.concat(splits.values())["id"]
    assert set(all_ids) == set(df["id"])


def test_split_by_question_ratios_are_approximately_right():
    df = _make_corpus(n_questions=100, answers_per_question=5)
    splits = split_by_question(df)

    total = len(df)
    assert 0.60 < len(splits["train"]) / total < 0.80
    assert 0.05 < len(splits["val"]) / total < 0.25
    assert 0.05 < len(splits["test"]) / total < 0.25


def test_split_by_question_is_deterministic():
    df = _make_corpus()
    first = split_by_question(df)
    second = split_by_question(df)

    for name in ("train", "val", "test"):
        assert list(first[name]["id"]) == list(second[name]["id"])


def test_compute_split_version_is_deterministic():
    assert compute_split_version() == compute_split_version()


def test_compute_split_version_changes_with_seed():
    original = compute_split_version()
    with patch("splitting.SPLIT_SEED", 999):
        changed = compute_split_version()
    assert changed != original


def test_compute_split_version_changes_with_dataset_revision():
    original = compute_split_version()
    with patch("splitting.DATASET_REVISION", "some-other-commit"):
        changed = compute_split_version()
    assert changed != original


def test_build_manifest_contents():
    df = _make_corpus(n_questions=10, answers_per_question=4)
    splits = split_by_question(df)

    manifest = build_manifest(splits, "abc12345")

    assert manifest["split_version"] == "abc12345"
    assert set(manifest["partitions"]) == {"train", "val", "test"}
    assert manifest["partitions"]["train"]["rows"] == len(splits["train"])
    assert manifest["partitions"]["train"]["questions"] == splits["train"]["question"].nunique()


def test_split_by_question_keeps_case_and_whitespace_variants_together():
    df = _make_corpus()
    # half the answers to each question spell it differently
    df.loc[df.index % 2 == 1, "question"] = df["question"].str.upper() + "  "
    splits = split_by_question(df)

    question_sets = {name: set(split_df["question"].str.lower().str.strip()) for name, split_df in splits.items()}
    assert question_sets["train"].isdisjoint(question_sets["val"])
    assert question_sets["train"].isdisjoint(question_sets["test"])
    assert question_sets["val"].isdisjoint(question_sets["test"])


def test_split_by_question_refuses_rows_without_question_text():
    df = _make_corpus()
    df.loc[3, "question"] = None
    with pytest.raises(ValueError, match="no question text"):
        split_by_question(df)
