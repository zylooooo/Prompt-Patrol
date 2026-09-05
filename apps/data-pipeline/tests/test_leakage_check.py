import pandas as pd

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
