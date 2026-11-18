import math

import pytest

import desklib


def test_calibrated_probability_is_a_sigmoid_of_the_logit_over_the_temperature():
    assert desklib.calibrated_probability(0.0, 2.0) == 0.5
    assert desklib.calibrated_probability(4.0, 2.0) == pytest.approx(1 / (1 + math.exp(-2.0)))
    assert desklib.calibrated_probability(-4.0, 2.0) == pytest.approx(1 / (1 + math.exp(2.0)))


def test_calibrated_probability_survives_logits_that_would_overflow_exp():
    assert desklib.calibrated_probability(-5000.0, 1.0) == 0.0
    assert desklib.calibrated_probability(5000.0, 1.0) == 1.0
