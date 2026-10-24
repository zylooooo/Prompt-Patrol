"""The per-answer scores file (scores.py): what it accepts and what it refuses."""

import numpy as np
import pandas as pd
import pytest
from scipy.special import expit

import scores


def make_scores():
    """A valid file: one untouched and one tuned model, 4 answers per split."""
    logit = np.array([-2.0, -1.0, 1.0, 2.0])
    rows = []
    for model, temperature in (("demo-untouched", 1.0), ("demo-lora", 2.0)):
        for split in ("val", "test"):
            rows.append(pd.DataFrame({
                "run_id": "run1", "model": model, "seed": 42, "split": split,
                "answer_id": [f"{split}-{i}" for i in range(4)],
                "question_id": ["q1", "q1", "q2", "q2"],
                "y_true": [0, 0, 1, 1],
                "logit": logit,
                "y_prob": expit(logit / temperature),
            }))
    return pd.concat(rows, ignore_index=True)[scores.COLUMNS]


def test_a_valid_file_passes_unchanged():
    df = make_scores()
    pd.testing.assert_frame_equal(scores.validate(df), df)


def test_score_rows_builds_the_columns_from_a_frame():
    frame = pd.DataFrame({"answer_id": ["a", "b"], "question_id": ["q", "q"], "label": [0, 1]})
    out = scores.score_rows("demo-lora", "val", frame, [-1.0, 1.0], expit([-1.0, 1.0]))
    assert out["y_true"].tolist() == [0, 1]
    assert out["split"].tolist() == ["val", "val"]
    assert out["model"].unique().tolist() == ["demo-lora"]


def test_score_rows_refuses_a_length_mismatch():
    frame = pd.DataFrame({"answer_id": ["a", "b"], "question_id": ["q", "q"], "label": [0, 1]})
    with pytest.raises(ValueError, match="rows but"):
        scores.score_rows("m", "val", frame, [0.0], [0.5])


@pytest.mark.parametrize("change, message", [
    (lambda d: d.drop(columns=["question_id"]), "missing columns"),
    (lambda d: d.assign(split=d["split"].replace("test", "train")), "only val and test"),
    (lambda d: d[~((d["model"] == "demo-lora") & (d["split"] == "test"))], "needs both val and test"),
    (lambda d: pd.concat([d, d.iloc[[0]]], ignore_index=True), "repeat within a split"),
    (lambda d: d.assign(y_true=d["y_true"].replace(1, 2)), "must be 0"),
    (lambda d: d.assign(y_prob=d["y_prob"].where(d.index != 0, 1.5)), "probability in"),
    (lambda d: d.assign(logit=d["logit"].where(d.index != 0, np.inf)), "finite"),
    (lambda d: d.assign(y_prob=d["y_prob"].where(~(d["model"] == "demo-untouched"), 0.5)), "sigmoid"),
])
def test_a_bad_file_is_refused(change, message):
    with pytest.raises(ValueError, match=message):
        scores.validate(change(make_scores()))


def test_tuned_models_may_differ_from_sigmoid_of_logit():
    # temperature scaling makes y_prob differ from sigmoid(logit) for a tuned model, and that is fine
    df = make_scores()
    tuned = df[df["model"] == "demo-lora"]
    assert not np.allclose(tuned["y_prob"], expit(tuned["logit"]))
    scores.validate(df)
