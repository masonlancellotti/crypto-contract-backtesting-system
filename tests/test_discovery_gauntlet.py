"""Tests for the overfitting gauntlet: PSR, expected-max-Sharpe, DSR, PBO, plateau, verdict."""

import numpy as np

from btc5m.discovery import gauntlet, metrics


def test_psr_at_zero_sharpe_is_half():
    # a Sharpe of exactly 0 vs benchmark 0 is 50/50
    p = gauntlet.probabilistic_sharpe_ratio(0.0, 500, 0.0, 3.0, sr_benchmark=0.0)
    assert abs(p - 0.5) < 1e-6


def test_psr_monotonic_in_sharpe():
    lo = gauntlet.probabilistic_sharpe_ratio(0.1, 400, 0.0, 3.0)
    hi = gauntlet.probabilistic_sharpe_ratio(0.4, 400, 0.0, 3.0)
    assert hi > lo > 0.5


def test_expected_max_sharpe_grows_with_trials():
    v = 0.04
    assert gauntlet.expected_max_sharpe(1, v) == 0.0
    e10 = gauntlet.expected_max_sharpe(10, v)
    e1000 = gauntlet.expected_max_sharpe(1000, v)
    assert 0.0 < e10 < e1000
    # zero selection variance => no inflation
    assert gauntlet.expected_max_sharpe(1000, 0.0) == 0.0


def test_dsr_rejects_lone_lucky_sharpe_under_many_trials():
    # a modest Sharpe that is the best of MANY trials should not clear DSR
    rng = np.random.default_rng(1)
    rets = rng.standard_normal(300) * 1.0 + 0.12  # sharpe ~0.12
    res = gauntlet.deflated_sharpe_ratio(rets, n_trials=1000, sr_variance=0.0036)
    assert not res["significant"]
    assert res["deflated_sharpe_ratio"] < 0.95


def test_dsr_accepts_strong_edge_even_deflated():
    rng = np.random.default_rng(2)
    rets = rng.standard_normal(500) * 1.0 + 0.45  # strong sharpe ~0.45
    res = gauntlet.deflated_sharpe_ratio(rets, n_trials=300, sr_variance=0.004)
    assert res["significant"]
    assert res["deflated_sharpe_ratio"] > 0.95


def test_pbo_noise_matrix_is_high():
    rng = np.random.default_rng(3)
    M = rng.standard_normal((400, 60))           # all noise
    r = gauntlet.pbo_cscv(M, n_partitions=8)
    assert 0.0 <= r.pbo <= 1.0
    assert r.pbo > 0.3                            # no real OOS persistence


def test_pbo_true_edge_matrix_is_low():
    rng = np.random.default_rng(4)
    M = rng.standard_normal((400, 60))
    M[:, 30] += 0.4                              # one genuine edge
    r = gauntlet.pbo_cscv(M, n_partitions=8)
    assert r.pbo < 0.2


def test_parameter_plateau_detects_spike_vs_plateau():
    spike = gauntlet.parameter_plateau({1: 0.1, 2: 0.1, 3: 1.0, 4: 0.1, 5: 0.1})
    assert spike["is_spike"] is True
    plateau = gauntlet.parameter_plateau({1: 0.8, 2: 0.95, 3: 1.0, 4: 0.96, 5: 0.85})
    assert plateau["is_spike"] is False


def test_verdict_requires_all_gates():
    good_dsr = {"significant": True, "deflated_sharpe_ratio": 0.99, "expected_max_sharpe": 0.1}
    bad_dsr = {"significant": False, "deflated_sharpe_ratio": 0.4, "expected_max_sharpe": 0.1}
    pbo_ok = gauntlet.PBOResult(pbo=0.1, n_splits=10, n_trials=5)
    pbo_bad = gauntlet.PBOResult(pbo=0.7, n_splits=10, n_trials=5)
    assert gauntlet.verdict(good_dsr, pbo_ok, replication_assets=4)["passed"]
    assert not gauntlet.verdict(bad_dsr, pbo_ok)["passed"]
    assert not gauntlet.verdict(good_dsr, pbo_bad)["passed"]
    assert not gauntlet.verdict(good_dsr, pbo_ok, replication_assets=1)["passed"]


def test_sharpe_and_tstat_consistency():
    rets = [0.1, -0.2, 0.3, 0.0, 0.15, -0.05]
    sr = metrics.sharpe(rets)
    t = metrics.tstat(rets)
    assert abs(t - sr * (len(rets) ** 0.5)) < 1e-9
