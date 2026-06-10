"""Tests for the normal-approximation baseline probability model."""

from btc5m.models.baseline import BaselineInputs, BaselineModel, normal_prob_yes
from btc5m.schemas import Comparison


def _inp(S, L, T, sig, cmp=Comparison.GTE):
    return BaselineInputs(reference_price=S, line=L, seconds_to_expiry=T, sigma_per_sqrt_s=sig, comparison=cmp)


def test_above_line_prob_above_half():
    p = normal_prob_yes(_inp(60100, 60000, 120, 0.0005))
    assert 0.5 < p < 1.0


def test_below_line_prob_below_half():
    p = normal_prob_yes(_inp(59900, 60000, 120, 0.0005))
    assert 0.0 < p < 0.5


def test_at_line_is_half():
    p = normal_prob_yes(_inp(60000, 60000, 120, 0.0005))
    assert abs(p - 0.5) < 1e-9


def test_monotonic_in_price():
    base = normal_prob_yes(_inp(60000, 60000, 120, 0.0005))
    higher = normal_prob_yes(_inp(60050, 60000, 120, 0.0005))
    lower = normal_prob_yes(_inp(59950, 60000, 120, 0.0005))
    assert lower < base < higher


def test_more_time_pulls_toward_half():
    near = normal_prob_yes(_inp(60100, 60000, 5, 0.0005))
    far = normal_prob_yes(_inp(60100, 60000, 300, 0.0005))
    assert abs(near - 0.5) > abs(far - 0.5)  # less time => more certain


def test_expired_is_deterministic_gte():
    assert normal_prob_yes(_inp(60000, 60000, 0, 0.0005)) == 1.0   # tie -> Up under GTE
    assert normal_prob_yes(_inp(59999, 60000, 0, 0.0005)) == 0.0
    assert normal_prob_yes(_inp(60001, 60000, -5, 0.0005)) == 1.0


def test_zero_vol_is_deterministic():
    assert normal_prob_yes(_inp(60100, 60000, 120, 0.0)) == 1.0
    assert normal_prob_yes(_inp(59900, 60000, 120, 0.0)) == 0.0


def test_missing_inputs_return_none():
    assert normal_prob_yes(_inp(None, 60000, 120, 0.0005)) is None
    assert normal_prob_yes(_inp(60000, None, 120, 0.0005)) is None


def test_model_output_uncalibrated():
    out = BaselineModel().predict_proba(_inp(60100, 60000, 120, 0.0005))
    assert out.calibration_ts_ms is None          # uncalibrated by design
    assert 0.5 < out.p_yes < 1.0
    assert out.p_yes_lower <= out.p_yes <= out.p_yes_upper
