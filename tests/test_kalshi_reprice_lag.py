"""Tests for the Kalshi repricing-lag / stale-quote event study (READ-ONLY research).

Covers shock detection, de-duplication, no-lookahead, Kalshi response measurement,
executable ask/fee/depth gating, event P&L, distinct-window aggregation, the sensitivity
grid, optional Deribit join, Polymarket comparability, CLI registration + report
generation, and the safety invariants (no paper/live, no promotion, live disabled). Offline.
"""

import json
from pathlib import Path

from btc5m.config import load_config
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi import reprice_lag as rl

FM = KalshiFeeModel()


def _row(ticker, as_of_ms, **over):
    r = {k: None for k in rl._FIELDS}
    r.update(dict(
        market_ticker=ticker, series_ticker="KXBTC15M",
        event_ticker=ticker.rsplit("-", 1)[0], as_of_ms=as_of_ms, seconds_to_close=300.0,
        status="active", yes_bid=0.79, yes_ask=0.80, no_bid=0.20, no_ask=0.21,
        yes_ask_size=5000.0, no_ask_size=5000.0, top_depth=10000.0, depth_imbalance=0.5,
        executable_yes_buy_price=0.80, executable_no_buy_price=0.21, spread_yes=0.01,
        book_age_ms=0.0, quote_age_ms=0.0, mkt_implied_yes_from_ask=0.80,
        reference_price=100.0, reference_start_price=100.0, distance_to_start=0.0,
        distance_to_line_vol_normalized=0.0, has_start_reference=True, has_orderbook=True,
        incomplete_book=False, thin_book=False, feed_health_ok=True,
        spot_sigma_per_sqrt_s=0.0003, spot_return_5s=0.0, spot_return_15s=0.0,
        spot_return_30s=0.0, spot_return_60s=0.0, spot_perp_basis=0.0,
        spot_perp_basis_change_60s=0.0, binance_ofi_best=None, binance_queue_imbalance=0.0,
        perp_cvd_60s=0.0, perp_signed_trade_imbalance_60s=0.0, realized_vol_60s=0.0003,
        realized_vol_180s=0.0003, coinbase_stale=False, binance_stale=False,
        fee_estimate_per_contract=0.02, fee_status="ASSUMED",
        deribit_available=False, deribit_used=False, deribit_stale=True))
    r.update(over)
    return r


TICK = "KXBTC15M-26JUN061830-30"
SCFG = rl.ShockConfig()  # default thresholds; ofi_abs_thr stays None unless populated


# --------------------------------------------------------------------------- #
# Part A — shock detection
# --------------------------------------------------------------------------- #
def test_detect_shock_up_and_down_direction():
    up = rl.detect_shock(_row(TICK, 1000, spot_return_5s=0.0012), SCFG)   # +12 bps
    dn = rl.detect_shock(_row(TICK, 1000, spot_return_5s=-0.0012), SCFG)  # -12 bps
    assert up and up["direction"] == "up" and "ret_5s" in up["signals"]
    assert dn and dn["direction"] == "down"


def test_detect_shock_none_when_quiet():
    # 1 bp move, sigma large enough that vol-normalized < 1 => no shock
    assert rl.detect_shock(_row(TICK, 1000, spot_return_5s=0.0001, spot_sigma_per_sqrt_s=0.001), SCFG) is None


def test_detect_shock_volnorm_path():
    # below 5 bps but tiny sigma => vol-normalized move >= 1 sigma fires
    s = rl.detect_shock(_row(TICK, 1000, spot_return_5s=0.0003, spot_sigma_per_sqrt_s=0.00003), SCFG)
    assert s and any(x.startswith("volnorm") for x in s["signals"]) and s["direction"] == "up"


def test_detect_shock_records_raw_abs_bps_for_sensitivity():
    s = rl.detect_shock(_row(TICK, 1000, spot_return_5s=0.0009, spot_return_30s=0.0020), SCFG)
    assert s["abs_ret_bps"] == max(9.0, 20.0)  # raw max over horizons, threshold-free


# --------------------------------------------------------------------------- #
# Part E — de-duplication
# --------------------------------------------------------------------------- #
def test_dedup_collapses_same_window_side_within_window():
    evs = [{"ticker": TICK, "direction": "up", "as_of_ms": 0},
           {"ticker": TICK, "direction": "up", "as_of_ms": 5000},     # within 20s -> same opp
           {"ticker": TICK, "direction": "up", "as_of_ms": 60000},    # >20s -> new opp
           {"ticker": TICK, "direction": "down", "as_of_ms": 6000},   # other side -> new
           {"ticker": "KXBTC15M-26JUN061845-45", "direction": "up", "as_of_ms": 6000}]  # other window
    opps = rl.dedup_events(evs, window_s=20.0)
    assert len(opps) == 4
    first = [o for o in opps if o["ticker"] == TICK and o["direction"] == "up"][0]
    assert first["n_obs"] == 2


# --------------------------------------------------------------------------- #
# Part B — Kalshi response measurement + no fabrication beyond tolerance
# --------------------------------------------------------------------------- #
def test_measure_response_resolves_coarse_horizons_only():
    # mkt_implied_yes_from_ask=None so the implied prob derives from the (moving) asks
    rows = [_row(TICK, 0, yes_ask=0.80, no_ask=0.21, mkt_implied_yes_from_ask=None),
            _row(TICK, 4000, yes_ask=0.83, no_ask=0.18, mkt_implied_yes_from_ask=None),
            _row(TICK, 8000, yes_ask=0.85, no_ask=0.16, mkt_implied_yes_from_ask=None)]
    series = rl._TickerSeries(rows)
    resp = rl.measure_response(series, rows[0])
    # +5s resolves to the ~+4s row (within 2.5s tol); +30s/+60s do NOT resolve (no rows)
    assert resp["horizons"][5] is not None and resp["horizons"][5]["offset_s"] == 4.0
    assert resp["horizons"][30] is None and resp["horizons"][60] is None
    # +1s/+2s collapse to t0 at this cadence (documented limitation)
    assert resp["horizons"][1]["offset_s"] == 0.0
    # market moved >= 2c by +8s -> time_to_move recorded
    assert resp["time_to_move_s"] in (4.0, 8.0)


def test_ticker_series_nearest_respects_tolerance():
    series = rl._TickerSeries([_row(TICK, 0), _row(TICK, 8000)])
    assert series.nearest(8000, 2500) is not None
    assert series.nearest(4000, 2500) is None   # nothing within +/-2.5s of +4s


# --------------------------------------------------------------------------- #
# Part C — executable opportunity gating (uses ONLY shock-time info)
# --------------------------------------------------------------------------- #
def _study():
    return rl.StudyConfig(min_depth=1.0, min_seconds_to_close=60.0, max_book_age_ms=5000.0,
                          conservative_buffer_cents=3.0, min_opp_edge_cents=0.0)


def test_qualify_opportunity_up_shock_passes():
    shock = {"direction": "up"}
    row = _row(TICK, 1000, reference_price=101.0, reference_start_price=100.0, yes_ask=0.80)
    q = rl.qualify_opportunity(row, shock, SCFG, _study(), FM)
    assert q["qualified"] and q["side"] == "YES" and q["conservative_edge_cents"] > 0
    assert "win" not in q   # qualification never sees outcome (no look-ahead)


def test_qualify_blocks_thin_depth_stale_book_and_race():
    shock = {"direction": "up"}
    base = dict(reference_price=101.0, reference_start_price=100.0, yes_ask=0.80)
    thin = rl.qualify_opportunity(_row(TICK, 1, yes_ask_size=0.0, **base), shock, SCFG, _study(), FM)
    stale = rl.qualify_opportunity(_row(TICK, 1, book_age_ms=99999.0, **base), shock, SCFG, _study(), FM)
    race = rl.qualify_opportunity(_row(TICK, 1, seconds_to_close=10.0, **base), shock, SCFG, _study(), FM)
    assert thin["qualified"] is False and "insufficient_depth" in thin["reasons"]
    assert stale["qualified"] is False and "book_stale" in stale["reasons"]
    assert race["qualified"] is False and "settlement_race" in race["reasons"]


def test_qualify_blocks_when_fee_buffer_eats_edge():
    # ask already rich (0.97) => no fee/buffer-adjusted edge even though baseline ~0.97
    shock = {"direction": "up"}
    row = _row(TICK, 1, reference_price=101.0, reference_start_price=100.0,
               yes_ask=0.97, executable_yes_buy_price=0.97)
    q = rl.qualify_opportunity(row, shock, SCFG, _study(), FM)
    assert q["qualified"] is False and "no_fee_buffer_edge" in q["reasons"]


def test_qualify_blocks_underlying_stale():
    shock = {"direction": "up"}
    row = _row(TICK, 1, reference_price=101.0, reference_start_price=100.0, coinbase_stale=True)
    q = rl.qualify_opportunity(row, shock, SCFG, _study(), FM)
    assert q["qualified"] is False and "underlying_stale" in q["reasons"]


# --------------------------------------------------------------------------- #
# Part F — outcome / P&L (labels used for EVALUATION ONLY)
# --------------------------------------------------------------------------- #
def test_attach_outcomes_win_loss_and_unlabelled():
    opps = [
        {"opp_qualified": True, "opp_side": "YES", "entry_price": 0.80, "settle_label_yes": 1, "ticker": TICK},
        {"opp_qualified": True, "opp_side": "YES", "entry_price": 0.80, "settle_label_yes": 0, "ticker": TICK},
        {"opp_qualified": True, "opp_side": "NO", "entry_price": 0.30, "settle_label_yes": 0, "ticker": TICK},
        {"opp_qualified": True, "opp_side": "YES", "entry_price": 0.80, "settle_label_yes": None, "ticker": TICK},
    ]
    rl._attach_outcomes(opps, FM)
    assert opps[0]["win"] == 1 and abs(opps[0]["pnl_net"] - (0.20 - FM.per_contract_fee(0.80))) < 1e-9
    assert opps[1]["win"] == 0 and abs(opps[1]["pnl_net"] - (-0.80 - FM.per_contract_fee(0.80))) < 1e-9
    assert opps[2]["win"] == 1                     # NO wins when label == 0
    assert opps[3]["win"] is None and opps[3]["pnl_net"] is None


def test_group_stats_counts_distinct_windows():
    opps = [
        {"opp_qualified": True, "opp_side": "YES", "ticker": "W1", "win": 1, "pnl_net": 0.1},
        {"opp_qualified": True, "opp_side": "YES", "ticker": "W1", "win": 0, "pnl_net": -0.2},
        {"opp_qualified": True, "opp_side": "YES", "ticker": "W2", "win": 1, "pnl_net": 0.1},
    ]
    g = rl._group_stats(opps, lambda o: o["opp_side"])["YES"]
    assert g["n"] == 3 and g["windows"] == 2 and g["win"] == 2 and g["loss"] == 1
    assert abs(g["win_rate"] - 2 / 3) < 1e-9


# --------------------------------------------------------------------------- #
# probability helpers
# --------------------------------------------------------------------------- #
def test_market_implied_and_baseline_helpers():
    assert abs(rl.market_implied_yes(_row(TICK, 1, yes_ask=0.60, no_ask=0.40,
                                          mkt_implied_yes_from_ask=None)) - 0.60) < 1e-9
    assert rl.baseline_p_yes(_row(TICK, 1, reference_price=None)) is None
    up = rl.baseline_p_yes(_row(TICK, 1, reference_price=101.0, reference_start_price=100.0))
    assert up is not None and up > 0.5


# --------------------------------------------------------------------------- #
# Part H — Polymarket comparability
# --------------------------------------------------------------------------- #
def test_polymarket_classifier_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    c = rl.classify_polymarket_comparability(cfg)
    assert c["classification"] in ("not_available", "not_comparable")
    assert c["reasons"]   # always explains why it is not directly comparable


# --------------------------------------------------------------------------- #
# Full study on synthetic data: file IO, reports, Deribit-optional, safety
# --------------------------------------------------------------------------- #
def _write_synthetic(tmp_path) -> str:
    day = "20260601"
    feats = tmp_path / "data" / "features"
    labels = tmp_path / "data" / "labels"
    feats.mkdir(parents=True, exist_ok=True)
    labels.mkdir(parents=True, exist_ok=True)
    rows = []
    t0 = 1_780_000_000_000
    # a clear up-shock that qualifies, plus follow-up rows for response horizons
    rows.append(_row(TICK, t0, spot_return_5s=0.0015, reference_price=101.0,
                     reference_start_price=100.0, yes_ask=0.80, no_ask=0.21))
    rows.append(_row(TICK, t0 + 4000, yes_ask=0.84, no_ask=0.17,
                     reference_price=101.2, reference_start_price=100.0))
    rows.append(_row(TICK, t0 + 8000, yes_ask=0.86, no_ask=0.15,
                     reference_price=101.3, reference_start_price=100.0))
    # a quiet row (no shock)
    rows.append(_row(TICK, t0 + 12000, spot_return_5s=0.00001))
    with (feats / f"kalshi_feature_rows-{day}.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    with (labels / f"kalshi_settlement_labels-{day}.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"market_ticker": TICK, "label_yes_resolved": 1,
                             "reference_start_price": 100.0, "close_ms": t0 + 300000}) + "\n")
    return day


def test_run_study_writes_reports_and_is_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    day = _write_synthetic(tmp_path)
    cfg = load_config(mode="paper")
    r = rl.run_reprice_lag_study(cfg, series="KXBTC15M", date=day)
    assert r["status"] == "OK"
    assert r["live_submission_allowed"] is False
    s = r["summary"]
    assert s["raw_shock_rows"] >= 1 and s["qualified_opportunities"] >= 1
    assert s["distinct_windows_with_opps"] >= 1
    # reports written ONLY under reports/reprice_lag
    rd = tmp_path / "reports" / "reprice_lag"
    assert Path(r["reports"]["study_md"]).parent == rd
    assert Path(r["reports"]["events_csv"]).exists() and Path(r["reports"]["opportunities_csv"]).exists()
    # SAFETY: no promotion manifest / promoted artifacts created anywhere
    assert not list((tmp_path / "data").glob("**/kalshi_paper_promotion_manifest.json"))
    pp = tmp_path / "data" / "models" / "paper_promoted"
    assert not (pp.exists() and list(pp.glob("*.pkl")))


def test_run_study_deribit_optional_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    day = _write_synthetic(tmp_path)               # synthetic rows have deribit_available=False
    cfg = load_config(mode="paper")
    r = rl.run_reprice_lag_study(cfg, series="KXBTC15M", date=day, include_deribit=True)
    assert r["status"] == "OK" and r["deribit_present"] is False   # missing Deribit does not block


def test_run_sensitivity_grid_monotone(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    day = _write_synthetic(tmp_path)
    cfg = load_config(mode="paper")
    r = rl.run_sensitivity(cfg, series="KXBTC15M", date=day)
    assert r["status"] == "OK" and len(r["grid"]) == len(rl.SENSITIVITY_BPS_GRID)
    rows_by_thr = [g["raw_shock_rows"] for g in r["grid"]]
    assert rows_by_thr == sorted(rows_by_thr, reverse=True)   # higher threshold => fewer/equal


def test_no_data_returns_clean_status(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    r = rl.run_reprice_lag_study(cfg, series="KXBTC15M", date="20990101")
    assert r["status"] == "NO_DATA" and r["live_submission_allowed"] is False


# --------------------------------------------------------------------------- #
# CLI registration + safety invariants
# --------------------------------------------------------------------------- #
def test_cli_commands_registered():
    import btc5m.cli as c
    for name in ("kalshi-shock-scan", "kalshi-reprice-lag-study",
                 "kalshi-reprice-lag-report", "kalshi-reprice-lag-sensitivity"):
        assert name in c._COMMANDS and callable(c._COMMANDS[name])


def test_check_live_disabled_holds(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    assert cfg.live_blockers()            # non-empty => live NOT permitted
    assert cfg.live_permitted is False
