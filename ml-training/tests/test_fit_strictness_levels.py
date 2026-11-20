"""fit_strictness_levels: the API's verdict rule, the band rule, the level order, and the release names it copies."""

import numpy as np
import pytest

import fit_strictness_levels as fit


def test_verdicts_follow_the_apis_rule():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.10, 0.905, 0.895, 0.99])
    r = fit.verdicts(y, p, threshold=0.9, band=0.01)
    # 0.905 and 0.895 sit within +-0.01 of 0.9, so both are uncertain, not flagged / cleared
    assert r == {"band": 0.01, "humans_flagged": 0.0, "humans_uncertain": 0.5, "ai_flagged": 0.5, "ai_uncertain": 0.5}


def test_verdicts_without_a_band_flag_strictly_above_the_threshold():
    r = fit.verdicts(np.array([0, 1]), np.array([0.9, 0.9]), threshold=0.9, band=0.0)
    assert r["humans_flagged"] == 0.0 and r["humans_uncertain"] == 1.0


def test_choose_band_is_the_widest_within_the_ai_uncertain_budget():
    table = [{"band": b, "ai_uncertain": u} for b, u in ((0.0, 0.0), (0.005, 0.057), (0.01, 0.133))]
    assert fit.choose_band(table) == 0.005


def test_logit_width_of_the_releases_band():
    # +-0.005 around the release's 0.945775: logit(0.950775) - logit(0.940775)
    assert fit.logit_width(0.945775, 0.005) == pytest.approx(0.1955, abs=1e-4)


def test_logit_width_refuses_a_band_that_leaves_zero_one():
    with pytest.raises(ValueError):
        fit.logit_width(0.95, 0.08)


def test_band_for_width_gives_the_reference_band_back_at_the_reference_threshold():
    width = fit.logit_width(0.945775, 0.005)
    assert fit.band_for_width(0.945775, width) == 0.005


def test_the_same_log_odds_width_is_a_wider_probability_band_nearer_one_half():
    width = fit.logit_width(0.945775, 0.005)
    band = fit.band_for_width(0.814079, width)
    assert 0.014 < band < 0.016
    assert fit.logit_width(0.814079, band) == pytest.approx(width, rel=1e-2)


def test_band_for_width_zero_is_no_band():
    assert fit.band_for_width(0.8, 0.0) == 0.0


def _level(threshold, band):
    return {"threshold": threshold, "abstention_band": band}


def test_check_order_accepts_strict_below_standard_below_lenient():
    fit.check_order({"strict": _level(0.81, 0.015), "standard": _level(0.934, 0.006), "lenient": _level(0.946, 0.005)})


def test_check_order_refuses_levels_the_wrong_way_round():
    with pytest.raises(SystemExit, match="not below"):
        fit.check_order({"strict": _level(0.946, 0.005), "standard": _level(0.934, 0.006), "lenient": _level(0.81, 0.01)})


def test_check_order_refuses_a_band_reaching_the_next_threshold():
    with pytest.raises(SystemExit, match="strict's band"):
        fit.check_order({"strict": _level(0.81, 0.13), "standard": _level(0.934, 0.006), "lenient": _level(0.946, 0.005)})


def test_parse_overrides_rejects_unknown_levels():
    assert fit.parse_overrides(["lenient=0.02"]) == {"lenient": 0.02}
    with pytest.raises(SystemExit):
        fit.parse_overrides(["relaxed=0.02"])


def test_lenient_is_the_release_threshold_level_and_strict_flags_the_most():
    assert fit.REFERENCE_LEVEL == "lenient" and fit.LEVELS[fit.REFERENCE_LEVEL] == 0.01
    assert fit.LEVELS["lenient"] < fit.LEVELS["standard"] < fit.LEVELS["strict"]
    assert fit.BY_THRESHOLD == ("strict", "standard", "lenient")


def test_copied_names_match_the_release_script():
    pytest.importorskip("torch")
    try:
        import release_desklib_meld as release
    except (ImportError, AttributeError) as exc:  # it imports the detector's code, which needs Python 3.13
        pytest.skip(f"release_desklib_meld does not import here: {exc}")
    assert (fit.MODEL_VERSION, fit.RUN_NAME, fit.MIN_WORDS) == (release.MODEL_VERSION, release.RUN_NAME, release.MIN_WORDS)
    assert fit.DETECTOR_TARGET == release.DETECTOR_TARGET.resolve()
    assert fit.LEVELS[fit.REFERENCE_LEVEL] == release.TARGET_FPR
