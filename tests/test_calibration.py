"""Tests for isotonic calibration + calibration metrics."""

from btc5m.backtest.metrics import (
    expected_calibration_error,
    log_loss,
    reliability_table,
)
from btc5m.models.calibration import IsotonicCalibrator, reliability_report


def test_isotonic_is_monotonic():
    # Scores correlated with outcomes; calibrated map must be non-decreasing.
    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    outcomes = [0, 0, 0, 0, 1, 0, 1, 1, 1]
    cal = IsotonicCalibrator().fit(scores, outcomes)
    mapped = cal.transform(scores)
    assert all(mapped[i] <= mapped[i + 1] + 1e-9 for i in range(len(mapped) - 1))
    assert all(0.0 <= m <= 1.0 for m in mapped)


def test_isotonic_recovers_rough_frequency():
    scores = [0.0] * 10 + [1.0] * 10
    outcomes = [0] * 10 + [1] * 10
    cal = IsotonicCalibrator().fit(scores, outcomes)
    assert cal.transform_one(0.0) < 0.1
    assert cal.transform_one(1.0) > 0.9
    assert cal.fitted_ts_ms is not None


def test_log_loss_and_brier_directions():
    good = log_loss([0.9, 0.1], [1, 0])
    bad = log_loss([0.1, 0.9], [1, 0])
    assert good < bad


def test_reliability_table_buckets():
    probs = [0.05, 0.15, 0.85, 0.95]
    outcomes = [0, 0, 1, 1]
    table = reliability_table(probs, outcomes, n_bins=10)
    assert all("mean_pred" in r and "frac_pos" in r and "count" in r for r in table)
    assert sum(r["count"] for r in table) == 4


def test_ece_zero_when_perfectly_calibrated():
    # 50 at p=0 all negative, 50 at p=1 all positive -> ECE ~ 0
    probs = [0.0] * 50 + [1.0] * 50
    outcomes = [0] * 50 + [1] * 50
    assert expected_calibration_error(probs, outcomes, n_bins=10) < 1e-9


def test_reliability_report_keys():
    rep = reliability_report([0.2, 0.8, 0.6, 0.4], [0, 1, 1, 0])
    assert set(rep) >= {"n", "brier", "log_loss", "ece", "reliability"}
    assert rep["n"] == 4
