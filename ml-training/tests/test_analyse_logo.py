"""analyse_logo: thresholds come from val only, and a gap only compares the same test answers."""

import numpy as np
import pandas as pd
import pytest

import analyse_logo


def frame(n_q=40, seed=0):
    """Val and test rows: per question two humans and one gpt answer, plus one claude answer in test."""
    rows = []
    for q in range(n_q):
        split = "val" if q < n_q // 2 else "test"
        gens = ["human", "human", "gpt-5.5"] + (["claude-sonnet-5"] if split == "test" else [])
        for i, g in enumerate(gens):
            rows.append({"answer_id": f"q{q}-{i}", "split": split, "question_id": f"q{q}",
                         "y_true": int(g != "human"), "generator": g})
    return pd.DataFrame(rows).set_index("answer_id")


def separable(f, shift=4.0, seed=0):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(size=len(f)) + shift * f["y_true"].to_numpy(), index=f.index)


def test_threshold_is_fitted_on_val_only():
    f = frame()
    z = separable(f)
    on = pd.Series(True, index=f.index)
    before = analyse_logo.score(z, f, on, 0.01)
    # changing every test score cannot move a threshold that was fitted on val
    z2 = z.where(f["split"] == "val", z + 100)
    after = analyse_logo.score(z2, f, on, 0.01)
    assert before["threshold"] == after["threshold"]
    assert after["deployed_tpr"] == 1.0


def test_a_missing_score_is_refused():
    f = frame()
    with pytest.raises(ValueError, match="no score"):
        analyse_logo.score(separable(f).iloc[:-1], f, pd.Series(True, index=f.index), 0.01)


def test_held_out_generator_must_be_unique():
    f = frame()
    assert analyse_logo.held_out_generator(f[f["generator"] != "gpt-5.5"]) == "claude-sonnet-5"
    with pytest.raises(ValueError, match="one generator"):
        analyse_logo.held_out_generator(f)


def test_identical_sides_give_a_zero_gap_and_different_answers_are_refused():
    f = frame()
    on = f["generator"].isin(["human", "claude-sonnet-5"])
    r = analyse_logo.score(separable(f), f, on, 0.01)
    groups = f.loc[r["_ids"], "question_id"].to_numpy()
    g = analyse_logo.gap({1: r}, {1: r}, groups, "auroc", n=50)
    assert g["diff"] == 0 and g["ci_low"] == 0 and g["ci_high"] == 0

    other = analyse_logo.score(separable(f), f, f["generator"].isin(["human", "gpt-5.5"]), 0.01)
    with pytest.raises(ValueError, match="same test answers"):
        analyse_logo.gap({1: r}, {1: other}, groups, "auroc", n=50)
