"""Trade-frequency frontier / overtrading analysis (research-only).

Covers scenario grid bounding, the marginal trade curve, time-to-close bucketing,
within-window concentration/overtrading, cap/cooldown/daily enforcement, economics
(fees + executable prices, no midpoint), and safety (no live, no promotion). Offline.
"""

import pytest

from btc5m.config import load_config
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.trade_frequency import (
    FrequencyConfig, FrequencyScenario, build_scenario_grid, calibration_buckets,
    extract_candidates, marginal_trade_curve, prob_bucket, simulate_frequency_policy,
    time_to_close_analysis, ttc_bucket, within_window_analysis,
)

FM = KalshiFeeModel()


def _cand(ticker="W1", ts=0, secs=300, side="YES", entry=0.30, net=0.05, label=1,
          p=0.62, book_age=None, spread_c=None, depth=None):
    return {"ticker": ticker, "as_of_ts_ms": ts, "day": "20260601", "seconds_to_close": secs,
            "side": side, "entry_price": entry, "net_edge": net, "raw_edge": net + 0.02,
            "fee_per_contract": 0.02, "p_yes": p, "label_yes": label, "book_age_ms": book_age,
            "spread_cents": spread_c, "depth": depth, "deribit_regime": None,
            "coinbase_stale": False, "binance_stale": False, "yes_ask": entry, "no_ask": 1 - entry}


# --------------------------------------------------------------------------- #
# Definitions / buckets
# --------------------------------------------------------------------------- #
def test_ttc_bucketing():
    assert ttc_bucket(700) == "15m-10m"
    assert ttc_bucket(450) == "10m-5m"
    assert ttc_bucket(3) == "<5s"
    assert ttc_bucket(None) == "na"
    assert ttc_bucket(1200) == ">=15m"


def test_prob_bucketing():
    assert prob_bucket(0.62) == "60-65%"
    assert prob_bucket(0.95) == "90-100%"
    assert prob_bucket(None) == "na"


# --------------------------------------------------------------------------- #
# Scenario grid is bounded (no combinatorial explosion)
# --------------------------------------------------------------------------- #
def test_scenario_grid_bounded():
    cfg = FrequencyConfig()  # full grid would be 6*4*5*5 = 600
    full = build_scenario_grid(cfg, max_scenarios=10_000)
    assert len(full) == 6 * 4 * 5 * 5
    assert len(build_scenario_grid(cfg, max_scenarios=10)) == 10
    assert len(build_scenario_grid(cfg)) <= cfg.default_max_scenarios   # default cap (250)


# --------------------------------------------------------------------------- #
# Overtrading: caps, cooldowns, daily limits
# --------------------------------------------------------------------------- #
def test_max_trades_per_window_enforced():
    cands = [_cand(ts=i * 1000) for i in range(5)]   # 5 candidates, same window
    r = simulate_frequency_policy(cands, FrequencyScenario(max_trades_per_window=1), FM)
    assert r.trades == 1 and r.distinct_windows == 1


def test_cooldown_after_entry_enforced():
    cands = [_cand(ts=0), _cand(ts=10_000)]  # 10s apart, same window
    sc = FrequencyScenario(max_trades_per_window=2, max_entries_per_window=2,
                           allow_multiple_entries_same_window=True, cooldown_after_entry_seconds=30)
    assert simulate_frequency_policy(cands, sc, FM).trades == 1   # 2nd within 30s cooldown
    sc2 = FrequencyScenario(max_trades_per_window=2, max_entries_per_window=2,
                            allow_multiple_entries_same_window=True, cooldown_after_entry_seconds=5)
    assert simulate_frequency_policy(cands, sc2, FM).trades == 2  # 10s >= 5s cooldown


def test_max_daily_trades_enforced():
    cands = [_cand(ticker=f"W{i}", ts=i * 1000) for i in range(5)]  # 5 windows, same day
    r = simulate_frequency_policy(cands, FrequencyScenario(max_daily_trades=2), FM)
    assert r.trades == 2


def test_min_net_edge_gate():
    cands = [_cand(net=0.01)]  # 1c edge
    assert simulate_frequency_policy(cands, FrequencyScenario(min_net_edge_cents=2), FM).trades == 0
    assert simulate_frequency_policy(cands, FrequencyScenario(min_net_edge_cents=1), FM).trades == 1


# --------------------------------------------------------------------------- #
# Economics: fees + executable prices, net P&L (no midpoint)
# --------------------------------------------------------------------------- #
def test_economics_net_pnl_includes_fees():
    win = simulate_frequency_policy([_cand(side="YES", entry=0.30, label=1)],
                                    FrequencyScenario(min_net_edge_cents=1), FM)
    # gross = 1*(1-0.30)=0.70 ; fee = taker_fee(0.30,1)=0.02 ; net = 0.68
    assert win.net_pnl == pytest.approx(0.68, abs=1e-9)
    loss = simulate_frequency_policy([_cand(side="YES", entry=0.30, label=0)],
                                     FrequencyScenario(min_net_edge_cents=1), FM)
    assert loss.net_pnl == pytest.approx(-0.32, abs=1e-9)


def test_extract_candidates_uses_executable_and_requires_label():
    rows = [
        {"ticker": "W1", "as_of_ts_ms": 1, "seconds_to_close": 300, "yes_ask": 0.40, "no_ask": 0.62,
         "yes_ask_size": 50, "no_ask_size": 50, "book_ok": True, "label_yes_resolved": 1,
         "reference_start_price": 100.0, "model_probability_yes": 0.70},
        {"ticker": "W2", "as_of_ts_ms": 2, "seconds_to_close": 300, "yes_ask": 0.40, "no_ask": 0.62,
         "yes_ask_size": 50, "no_ask_size": 50, "book_ok": True, "label_yes_resolved": None,  # no label
         "reference_start_price": 100.0, "model_probability_yes": 0.70},
    ]
    cands = extract_candidates(rows, FM)
    assert len(cands) == 1 and cands[0]["ticker"] == "W1"
    # executable: edge uses the YES ask (0.40), not a midpoint
    assert cands[0]["entry_price"] == 0.40 and cands[0]["net_edge"] is not None


# --------------------------------------------------------------------------- #
# Marginal trade curve
# --------------------------------------------------------------------------- #
def test_marginal_curve_ranks_and_detects_peak():
    # one clearly-good trade then several bad ones -> peak after the good one
    cands = [_cand(ticker="A", net=0.10, entry=0.30, label=1)]
    cands += [_cand(ticker=f"B{i}", net=0.03, entry=0.60, label=0) for i in range(5)]
    curve = marginal_trade_curve(cands, FM, top_ns=(1, 3, 5), edge_thresholds_cents=(1,))
    assert curve.total_candidates == 6
    assert curve.peak_at_rank == 1 and curve.peak_cumulative_net_pnl > 0
    assert any("peaks at rank" in w for w in curve.warnings)


def test_marginal_curve_handles_empty():
    curve = marginal_trade_curve([], FM)
    assert curve.total_candidates == 0 and curve.peak_at_rank == 0


# --------------------------------------------------------------------------- #
# Within-window concentration / overtrading
# --------------------------------------------------------------------------- #
def test_within_window_detects_concentration():
    # 10 eligible candidates all in ONE window -> concentration warnings
    cands = [_cand(ticker="ONLY", ts=i * 1000, net=0.05) for i in range(10)]
    res = within_window_analysis(cands, FM, min_net_edge_cents=1)
    assert res["distinct_windows"] == 1 and res["eligible_candidates"] == 10
    codes = {w["code"] for w in res["warnings"]}
    assert "CONCENTRATION" in codes
    # max-1/window collapses 10 correlated entries to a single independent sample
    assert res["policies"]["max_1_entries_per_window"]["trades"] == 1


def test_within_window_distinct_windows_are_independent():
    cands = [_cand(ticker=f"W{i}", ts=i * 1000, net=0.05) for i in range(8)]
    res = within_window_analysis(cands, FM, min_net_edge_cents=1)
    assert res["distinct_windows"] == 8


# --------------------------------------------------------------------------- #
# Time-to-close analysis
# --------------------------------------------------------------------------- #
def test_time_to_close_buckets_and_excludes_closed():
    rows = []
    for i, secs in enumerate([700, 450, 90, -5]):  # last is post-close -> excluded
        rows.append({"ticker": f"W{i}", "as_of_ts_ms": i, "seconds_to_close": secs,
                     "yes_ask": 0.40, "no_ask": 0.62, "yes_ask_size": 50, "no_ask_size": 50,
                     "book_ok": True, "label_yes_resolved": 1, "reference_start_price": 100.0,
                     "model_probability_yes": 0.70})
    buckets = {b.bucket: b for b in time_to_close_analysis(rows, FM, min_net_edge_cents=1)}
    assert "15m-10m" in buckets and "10m-5m" in buckets and "2m-60s" in buckets
    # post-close row produced no candidate in any reported bucket
    assert sum(b.candidates for b in buckets.values()) == 3


# --------------------------------------------------------------------------- #
# Calibration buckets
# --------------------------------------------------------------------------- #
def test_calibration_buckets_realized_rate():
    cands = [_cand(p=0.62, label=1), _cand(p=0.63, label=0)]
    out = {b["prob_bucket"]: b for b in calibration_buckets(cands, FM)}
    assert "60-65%" in out and out["60-65%"]["candidates"] == 2
    assert out["60-65%"]["realized_yes_rate"] == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #
def test_no_promotion_no_flat_scanner_no_live():
    import btc5m.venues.kalshi.trade_frequency as tf
    import btc5m.venues.kalshi.trade_frequency_runtime as tfr
    # no flat-position arb scanner
    assert not any("scan" in n.lower() or "arb" in n.lower() for n in dir(tf))
    # staged suggestion is never promoted
    sug = tfr._conservative_suggestion({"diagnostic": True},
                                       type("C", (), {"peak_at_rank": 0, "total_candidates": 0})(),
                                       {"warnings": []})
    assert sug["promoted"] is False and sug["requires_manual_review"] is True
    assert sug["live_submission_allowed"] is False


def test_cli_blocked_when_no_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    from btc5m.venues.kalshi.trade_frequency_runtime import run_frequency_sweep
    r = run_frequency_sweep(cfg, series="KXBTC15M")
    assert r["status"] == "BLOCKED" and r["diagnostic"] is True
    assert r["tradable"] is False and r["promoted"] is False and r["blockers"]
