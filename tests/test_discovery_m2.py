"""Tests for the M2 mining layer: feature factory, panel, and after-cost strategy search."""

import numpy as np

from btc5m.discovery import feature_factory, panel, search
from btc5m.discovery.panel import Observation
from btc5m.venues.kalshi.fees import KalshiFeeModel


def test_feature_factory_versioned_and_extracts():
    v1 = feature_factory.version()
    assert v1.startswith("ff1:") and feature_factory.version() == v1   # deterministic
    names = feature_factory.feature_names()
    assert "spot_return_60s" in names and "ret_accel_5_30" in names
    feats = feature_factory.extract({"spot_return_5s": 0.001, "spot_return_30s": 0.0003,
                                     "realized_vol_30s": 2.0, "realized_vol_180s": 4.0})
    assert abs(feats["ret_accel_5_30"] - 0.0007) < 1e-9
    assert abs(feats["vol_term_30_180"] - 0.5) < 1e-9
    assert feats["binance_ofi_best"] is None                          # missing -> None


def test_build_panel_picks_decision_row_and_derives_market_prob():
    rows = [
        {"ticker": "W1", "market_close_ts_ms": 9000, "label_yes_resolved": 1,
         "seconds_to_close": 600, "yes_ask": 0.70, "no_ask": 0.31,
         "executable_yes_buy_price": 0.70, "executable_no_buy_price": 0.31,
         "spot_return_60s": 0.002},
        {"ticker": "W1", "market_close_ts_ms": 9000, "label_yes_resolved": 1,
         "seconds_to_close": 180, "yes_ask": 0.66, "no_ask": 0.35,
         "executable_yes_buy_price": 0.66, "executable_no_buy_price": 0.35,
         "spot_return_60s": 0.0015},
        # execution snapshot ~3s later (177s to close): the repriced quote the fill should use
        {"ticker": "W1", "market_close_ts_ms": 9000, "label_yes_resolved": 1,
         "seconds_to_close": 177, "yes_ask": 0.72, "no_ask": 0.29,
         "executable_yes_buy_price": 0.72, "executable_no_buy_price": 0.29,
         "spot_return_60s": 0.0011},
    ]
    pn = panel.build_panel(rows, asset="KXBTC15M", lead_seconds=180.0, exec_lag_seconds=3.0)
    assert len(pn) == 1
    o = pn[0]
    assert o.ticker == "W1" and o.y == 1
    # features + market prob from the DECISION row (180s): mkt_p = mid(0.66, 0.65) = 0.655
    assert abs(o.mkt_p - 0.655) < 1e-9
    assert o.feats["spot_return_60s"] == 0.0015
    # but the fill is PRICED at the lagged execution row (177s): exec_yes=0.72, exec_no=0.29
    assert o.exec_yes == 0.72 and o.exec_no == 0.29 and o.exec_lagged is True


def test_build_panel_same_instant_when_lag_zero():
    rows = [
        {"ticker": "W1", "market_close_ts_ms": 9000, "label_yes_resolved": 1,
         "seconds_to_close": 180, "yes_ask": 0.66, "no_ask": 0.35,
         "executable_yes_buy_price": 0.66, "executable_no_buy_price": 0.35},
    ]
    pn = panel.build_panel(rows, asset="KXBTC15M", lead_seconds=180.0, exec_lag_seconds=0.0)
    assert len(pn) == 1 and pn[0].exec_yes == 0.66 and pn[0].exec_lagged is False


def _obs(i, y, sig):
    return Observation(ticker=f"W{i}", asset="KXBTC15M", close_ms=1000 + i, y=y,
                       mkt_p=0.5, exec_yes=0.5, exec_no=0.5, feats={"sig": sig})


def test_search_recovers_planted_edge():
    # feature 'sig' high -> YES tends to win; a 'hi-tail -> YES' rule should top the ranking
    rng = np.random.default_rng(0)
    obs = []
    for i in range(300):
        sig = float(rng.standard_normal())
        # outcome correlated with sig: high sig => YES more likely
        y = 1 if rng.random() < 1 / (1 + np.exp(-1.5 * sig)) else 0
        obs.append(_obs(i, y, sig))
    fee = KalshiFeeModel(rate=0.0, status="ASSUMED_ZERO_MAKER_FEE")
    res = search.generate_trials(obs, ["sig"], fee, min_trades=10)
    assert res["n_trials"] > 0
    assert res["matrix"].shape[0] == len(obs)
    ranked = search.rank_trials(res)
    best = ranked[0]
    # planted: high sig -> YES. Recoverable equivalently as (hi-tail, YES) or (lo-tail, NO).
    assert best["per_trade_mean_c"] > 0
    assert (best["tail"], best["side"]) in {("hi", "YES"), ("lo", "NO")}


def test_search_noise_has_no_positive_edge_trial_of_note():
    rng = np.random.default_rng(1)
    obs = [_obs(i, int(rng.random() < 0.5), float(rng.standard_normal())) for i in range(300)]
    fee = KalshiFeeModel.from_config(None)        # default ~0.07 taker
    res = search.generate_trials(obs, ["sig"], fee, min_trades=10)
    ranked = search.rank_trials(res)
    # after a real fee, pure noise should not produce a strongly significant per-trade t
    assert all(abs(s["per_trade_t"]) < 4 for s in ranked)
