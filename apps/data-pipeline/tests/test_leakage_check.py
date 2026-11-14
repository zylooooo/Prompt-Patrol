import pandas as pd
import pytest

from leakage_check import find_leaking_questions


def test_find_leaking_questions_detects_a_planted_leak():
    df = pd.DataFrame(
        [
            {"question": "Q1", "partition": "train"},
            {"question": "Q1", "partition": "train"},
            {"question": "Q2", "partition": "val"},
            {"question": "Q3", "partition": "test"},
            # Q4 appears in both train and val.
            {"question": "Q4", "partition": "train"},
            {"question": "Q4", "partition": "val"},
        ]
    )

    leaking = find_leaking_questions(df)

    assert leaking == {"Q4": ["train", "val"]}


def test_find_leaking_questions_clean_split_finds_nothing():
    df = pd.DataFrame(
        [
            {"question": "Q1", "partition": "train"},
            {"question": "Q1", "partition": "train"},
            {"question": "Q2", "partition": "val"},
            {"question": "Q3", "partition": "test"},
        ]
    )

    assert find_leaking_questions(df) == {}


def test_find_leaking_questions_matches_case_and_whitespace_variants():
    df = pd.DataFrame(
        [
            {"question": "What is a stack?", "partition": "train"},
            {"question": "what is a  stack? ", "partition": "test"},
        ]
    )

    assert find_leaking_questions(df) == {"What is a stack?": ["test", "train"]}


def test_find_leaking_questions_refuses_rows_without_question_text():
    df = pd.DataFrame(
        [
            {"question": "Q1", "partition": "train"},
            {"question": None, "partition": "train"},
            {"question": None, "partition": "test"},
        ]
    )

    with pytest.raises(ValueError, match="no question text"):
        find_leaking_questions(df)
