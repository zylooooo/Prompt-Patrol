"""Known-answer tests for metrics.py: each expected value is worked out by hand in the comment."""

import numpy as np
import pytest

import metrics


def test_auroc_known_value():
    # the classic 4-answer example: 3 of the 4 (AI, human) pairs are ranked correctly -> 0.75
    out = metrics.ranking_metrics([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8])
    assert out["auroc"] == pytest.approx(0.75)


def test_auroc_is_nan_when_one_class_is_missing():
    assert np.isnan(metrics.ranking_metrics([1, 1, 1], [0.2, 0.5, 0.9])["auroc"])


def test_ece_mce_and_brier_known_values():
    # humans score 0.15 (bin 0.1-0.2, observed AI rate 0), AIs score 0.85 (bin 0.8-0.9, rate 1)
    # both bins are off by 0.15 and hold half the answers -> ECE = MCE = 0.15
    y, p = [0, 0, 1, 1], [0.15, 0.15, 0.85, 0.85]
    out = metrics.calibration_metrics(y, p)
    assert out["ece"] == pytest.approx(0.15)
    assert out["mce"] == pytest.approx(0.15)
    # Brier = mean squared error = 0.15^2 for every answer
    assert out["brier"] == pytest.approx(0.0225)


def test_perfectly_calibrated_scores_have_zero_ece():
    # 10 answers scored 0.3, exactly 3 of them AI: stated confidence matches the observed rate
    out = metrics.calibration_metrics([1] * 3 + [0] * 7, [0.3] * 10)
    assert out["ece"] == pytest.approx(0.0)


def test_operating_point_counts():
    # threshold 0.5 flags the scores >= 0.5: [0.8 (human), 0.9 (AI), 0.6 (AI)]
    y = [0, 0, 1, 1, 1]
    p = [0.2, 0.8, 0.9, 0.4, 0.6]
    out = metrics.operating_point_metrics(y, p, 0.5)
    assert (out["tp"], out["fp"], out["tn"], out["fn"]) == (2, 1, 1, 1)
    assert out["fpr"] == pytest.approx(0.5)
    assert out["recall"] == pytest.approx(2 / 3)
    assert out["precision"] == pytest.approx(2 / 3)


def test_threshold_at_fpr_known_value():
    # 100 humans scoring 0.00 ... 0.99 and 3 AI answers. At most 1 human may be flagged, so the
    # threshold can go down to 0.9899: that flags the human at 0.99 (FPR 1%) and AIs at 0.995 and
    # 0.9899 (TPR 2/3). One step lower (0.98) would flag a second human (FPR 2%).
    humans = np.arange(100) / 100
    ai = np.array([0.995, 0.9899, 0.5])
    y = np.r_[np.zeros(100), np.ones(3)]
    p = np.r_[humans, ai]

    thr = metrics.threshold_at_fpr(y, p, 0.01)
    assert thr == pytest.approx(0.9899)
    out = metrics.operating_point_metrics(y, p, thr)
    assert out["fpr"] == pytest.approx(0.01)
    assert out["recall"] == pytest.approx(2 / 3)


def test_threshold_at_fpr_keeps_the_budget_and_matches_the_oracle_on_its_own_data():
    rng = np.random.default_rng(0)
    y = np.r_[np.zeros(400), np.ones(300)].astype(int)
    p = np.r_[rng.beta(2, 6, 400), rng.beta(6, 2, 300)]
    for budget in (0.001, 0.01, 0.05):
        thr = metrics.threshold_at_fpr(y, p, budget)
        out = metrics.operating_point_metrics(y, p, thr)
        assert out["fpr"] <= budget
        # fitted and scored on the same rows, the frozen threshold gives exactly the oracle TPR
        assert out["recall"] == pytest.approx(metrics.oracle_tpr_at_fpr(y, p, budget))


def test_threshold_with_no_humans_flags_nothing():
    p = np.array([0.2, 0.5, 0.9])
    thr = metrics.threshold_at_fpr([1, 1, 1], p, 0.01)
    assert thr > p.max()


# --------------------------------------------------------------------------
# bootstrap by question
# --------------------------------------------------------------------------

def test_cluster_draw_takes_whole_questions():
    groups = np.repeat(np.arange(8), 5)  # 8 questions, 5 answers each
    members = metrics._cluster_members(groups, len(groups))
    assert len(members) == 8 and all(len(m) == 5 for m in members)

    idx = metrics._cluster_draw(members, np.random.default_rng(1))
    counts = np.bincount(idx, minlength=len(groups))
    for m in members:
        # every answer of a drawn question appears the same number of times (0 if not drawn)
        assert len(set(counts[m])) == 1


def test_bootstrap_by_question_is_wider_than_by_answer():
    # 10 questions of 10 answers. Every answer scores its question's value, so answers in a
    # question are identical: only 10 independent observations, and the interval must reflect that.
    groups = np.repeat(np.arange(10), 10)
    y = np.tile([1] * 5 + [0] * 5, 10)  # both classes appear in every question
    p = groups * 0.05
    fns = {"mean_score": lambda t, s: float(np.mean(s))}

    lo_a, hi_a = metrics.bootstrap_cis(y, p, fns, n=500, seed=3)["mean_score"]
    lo_q, hi_q = metrics.bootstrap_cis(y, p, fns, n=500, seed=3, groups=groups)["mean_score"]
    assert (hi_q - lo_q) > 2 * (hi_a - lo_a)


def test_bootstrap_groups_must_match_rows():
    with pytest.raises(ValueError, match="groups has 3 entries"):
        metrics.bootstrap_cis([0, 1, 0, 1], [0.1, 0.9, 0.2, 0.8], {"m": lambda t, p: 0.0}, n=5, groups=[1, 2, 3])


def test_evaluate_with_groups_reports_finite_intervals():
    rng = np.random.default_rng(5)
    groups = np.repeat(np.arange(30), 10)
    y = rng.integers(0, 2, 300)
    p = np.clip(0.3 + 0.4 * y + rng.normal(0, 0.15, 300), 0, 1)
    out = metrics.evaluate(y, p, 0.5, bootstrap_n=100, groups=groups)
    for name in ("deployed_tpr", "deployed_fpr", "auroc"):
        lo, hi = out[f"{name}_ci_low"], out[f"{name}_ci_high"]
        assert np.isfinite(lo) and np.isfinite(hi) and lo <= hi


# --------------------------------------------------------------------------
# risk-coverage
# --------------------------------------------------------------------------

def test_risk_coverage_known_values():
    y = [0, 0, 1, 1]
    p = [0.1, 0.5, 0.55, 0.9]
    rows = {r["half_width"]: r for r in metrics.risk_coverage_curve(y, p, 0.5, widths=(0.0, 0.05, 0.5))}

    # width 0: only the answer exactly at the threshold (0.5) is uncertain
    assert rows[0.0]["coverage"] == pytest.approx(0.75)

    # width 0.05: band [0.45, 0.55] holds 0.5 (a human) and 0.55 (an AI)
    r = rows[0.05]
    assert r["coverage"] == pytest.approx(0.5)
    assert r["human_abstain_rate"] == pytest.approx(0.5)
    assert r["ai_abstain_rate"] == pytest.approx(0.5)
    # what is left, 0.1 (human, cleared) and 0.9 (AI, flagged), is all correct
    assert r["selective_fpr"] == pytest.approx(0.0)
    assert r["selective_recall"] == pytest.approx(1.0)
    assert r["selective_error"] == pytest.approx(0.0)

    # a band wide enough to hold everything leaves nothing answered
    r = rows[0.5]
    assert r["coverage"] == pytest.approx(0.0)
    assert np.isnan(r["selective_error"])


def test_risk_coverage_coverage_never_rises_with_a_wider_band():
    rng = np.random.default_rng(2)
    y = rng.integers(0, 2, 500)
    p = np.clip(0.5 + 0.3 * (y - 0.5) + rng.normal(0, 0.2, 500), 0, 1)
    coverage = [r["coverage"] for r in metrics.risk_coverage_curve(y, p, 0.6)]
    assert coverage == sorted(coverage, reverse=True)


# --------------------------------------------------------------------------
# paired bootstrap: is A really different from B?
# --------------------------------------------------------------------------

def _tpr(y, p, threshold):
    ai = y == 1
    return float(((p >= threshold) & ai).sum() / ai.sum())


def _paired_fixture():
    # 20 questions x 10 answers; the first 5 of each question are AI. A flags all 5 (TPR 1.0), B
    # flags only 2 of them (TPR 0.4). Every question looks the same, so the gap is 0.6 in every draw.
    groups = np.repeat(np.arange(20), 10)
    y = np.tile([1] * 5 + [0] * 5, 20)
    a = np.where(y == 1, 0.9, 0.1)
    b = np.where((y == 1) & (np.arange(200) % 10 < 2), 0.9, 0.1)
    return y, a, b, groups


def test_paired_diff_known_value():
    y, a, b, groups = _paired_fixture()
    out = metrics.paired_bootstrap_diff(y, [a], [b], [0.5], [0.5], groups, _tpr, n=100)
    assert out["diff"] == pytest.approx(0.6)
    assert out["ci_low"] == pytest.approx(0.6) and out["ci_high"] == pytest.approx(0.6)
    assert out["share_a_better"] == pytest.approx(1.0)


def test_paired_diff_of_a_model_with_itself_is_zero():
    y, a, _, groups = _paired_fixture()
    out = metrics.paired_bootstrap_diff(y, [a], [a], [0.5], [0.5], groups, _tpr, n=100)
    assert out["diff"] == 0 and out["ci_low"] == 0 and out["ci_high"] == 0
    assert out["share_a_better"] == 0


def test_paired_diff_averages_the_metric_over_seeds_before_subtracting():
    y, a, b, groups = _paired_fixture()
    # model A: one seed at TPR 1.0 and one at TPR 0.4 -> mean 0.7; model B: both at 0.4 -> 0.4
    out = metrics.paired_bootstrap_diff(y, [a, b], [b, b], [0.5, 0.5], [0.5, 0.5], groups, _tpr, n=50)
    assert out["diff"] == pytest.approx(0.3)
