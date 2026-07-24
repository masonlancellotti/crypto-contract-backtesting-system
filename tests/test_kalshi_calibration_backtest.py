"""Kalshi calibration + executable backtest + threshold sweep — pure-stdlib, offline.

Verifies executable ask pricing (never midpoint), fee/depth/staleness gates, binary
P&L settlement, gate enforcement, diagnostic non-tradability, walk-forward/3-way
window splits, and that nothing emits PAPER_CANDIDATE or a live order.
"""

import json


from btc5m.config import load_config
from btc5m.venues.kalshi import calibrate, calibration_report as crep
from btc5m.venues.kalshi.executable_backtest import (
    BacktestParams, evaluate_row, run_backtest_baselines, settle_trade, simulate_backtest,
)
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.splits import three_way_window_split, walk_forward_indices
from btc5m.venues.kalshi.threshold_sweep import run_threshold_sweep

WIN = 15 * 60 * 1000


# --------------------------------------------------------------------------- #
# Engine: evaluate_row / settle / simulate
# --------------------------------------------------------------------------- #
def _row(**o):
    r = {"row_id": "KX@1", "market_ticker": "KX", "ticker": "KX", "series": "KXBTC15M",
         "book_ok": True, "yes_ask": 0.42, "no_ask": 0.60, "yes_spread": 0.02, "no_spread": 0.02,
         "top_depth": 100.0, "yes_ask_size": 100.0, "no_ask_size": 100.0, "seconds_to_close": 300.0,
         "book_age_ms": 100, "underlying_age_ms": 100, "reference_start_price": 70000.0,
         "label_yes_resolved": 1, "as_of_ts_ms": 1000, "market_close_ts_ms": 2000}
    r.update(o)
    return r


def test_evaluate_uses_executable_ask_not_midpoint():
    p = BacktestParams()
    fm = KalshiFeeModel()
    dec = evaluate_row(_row(), 0.60, p, fm)
    assert dec["side"] == "YES" and dec["entry_price"] == 0.42      # YES ask, not midpoint
    assert abs(dec["raw_edge"] - (0.60 - 0.42)) < 1e-9
    assert dec["net_edge"] < dec["raw_edge"]                        # fee included
    assert dec["tradeable"] is True
    dec_no = evaluate_row(_row(), 0.30, p, fm)
    assert dec_no["side"] == "NO" and dec_no["entry_price"] == 0.60  # NO ask


def test_gates_reject():
    p = BacktestParams()
    fm = KalshiFeeModel()
    assert "STALE_BOOK" in evaluate_row(_row(book_age_ms=5000), 0.6, p, fm)["reasons"]
    assert "STALE_UNDERLYING" in evaluate_row(_row(underlying_age_ms=9000), 0.6, p, fm)["reasons"]
    assert "INSUFFICIENT_DEPTH" in evaluate_row(_row(top_depth=0.0), 0.6, p, fm)["reasons"]
    assert "INVALID_OR_INCOMPLETE_BOOK" in evaluate_row(_row(book_ok=False), 0.6, p, fm)["reasons"]
    assert "MISSING_LABEL" in evaluate_row(_row(label_yes_resolved=None), 0.6, p, fm)["reasons"]
    assert "MISSING_START_REFERENCE" in evaluate_row(_row(reference_start_price=None), 0.6, p, fm)["reasons"]


def test_no_trade_below_threshold():
    dec = evaluate_row(_row(), 0.43, BacktestParams(), KalshiFeeModel())  # ~1c edge < 2c
    assert dec["tradeable"] is False and "EDGE_BELOW_MIN" in dec["reasons"]


def test_settle_pnl_binary():
    # YES win: gross = size*(1 - entry); net subtracts fee
    s = settle_trade("YES", 0.42, 1.0, label_yes=1, fee_total=0.02)
    assert s["win"] is True and abs(s["gross_pnl"] - 0.58) < 1e-9 and abs(s["net_pnl"] - 0.56) < 1e-9
    s = settle_trade("YES", 0.42, 1.0, label_yes=0, fee_total=0.02)
    assert s["win"] is False and abs(s["gross_pnl"] + 0.42) < 1e-9
    # NO win when label==0
    s = settle_trade("NO", 0.60, 1.0, label_yes=0, fee_total=0.0)
    assert s["win"] is True and abs(s["gross_pnl"] - 0.40) < 1e-9


def test_simulate_one_position_per_window():
    rows = []
    for w in range(2):
        for i in range(3):
            rows.append(_row(ticker=f"W{w}", as_of_ts_ms=w * WIN + i,
                             model_probability_yes=0.70, calibrated_probability_yes=0.70))
    agg = simulate_backtest(rows, params=BacktestParams(), fee_model=KalshiFeeModel(), diagnostic=True)
    assert agg["total_simulated_trades"] == 2          # one per window
    assert agg["windows_touched"] == 2


# --------------------------------------------------------------------------- #
# Calibration metrics + calibrators
# --------------------------------------------------------------------------- #
def test_isotonic_monotone_and_bounded():
    th = calibrate.isotonic_fit([0.1, 0.2, 0.3, 0.9], [0.0, 1.0, 0.0, 1.0])
    vals = [calibrate.isotonic_predict(th, x) for x in (0.0, 0.15, 0.5, 1.0)]
    assert all(0.0 <= v <= 1.0 for v in vals)
    assert vals == sorted(vals)  # non-decreasing


def test_calibrators_transform_bounded():
    for method in ("identity", "platt", "isotonic"):
        c = calibrate.fit_calibrator(method, [0.2, 0.4, 0.6, 0.8], [0, 0, 1, 1])
        out = c.transform([0.1, 0.5, 0.95])
        assert all(0.0 <= v <= 1.0 for v in out)


def test_calibration_summary_metrics():
    y = [0, 0, 1, 1]
    p = [0.1, 0.2, 0.8, 0.9]
    s = crep.calibration_summary(y, p)
    assert s["brier"] is not None and s["log_loss"] is not None and s["ece"] is not None
    assert 0.0 <= s["ece"] <= 1.0


# --------------------------------------------------------------------------- #
# Splits
# --------------------------------------------------------------------------- #
def _win_rows(n_windows, rows_per=4):
    rows = []
    for w in range(n_windows):
        for i in range(rows_per):
            rows.append({"ticker": f"W{w}", "market_close_ts_ms": (w + 1) * WIN,
                         "label_yes_resolved": w % 2})
    return rows


def test_three_way_split_disjoint():
    sp = three_way_window_split(_win_rows(8), embargo_windows=1)
    assert sp["applied"] is True
    tr = {_win_rows(8)[i]["ticker"] for i in sp["train_idx"]}
    ca = {_win_rows(8)[i]["ticker"] for i in sp["calib_idx"]}
    te = {_win_rows(8)[i]["ticker"] for i in sp["test_idx"]}
    assert tr and ca and te
    assert tr.isdisjoint(ca) and ca.isdisjoint(te) and tr.isdisjoint(te)


def test_walk_forward_indices_by_window():
    rows = _win_rows(10)
    folds = walk_forward_indices(rows, n_splits=3, embargo_windows=1)
    assert folds
    for tr, vl in folds:
        trw = {rows[i]["ticker"] for i in tr}
        vlw = {rows[i]["ticker"] for i in vl}
        assert trw.isdisjoint(vlw)   # no window leaks across the split


# --------------------------------------------------------------------------- #
# Runner fixtures (feature rows + labels under tmp DATA_DIR)
# --------------------------------------------------------------------------- #
def _frow(tk, *, as_of, close, yes):
    return {"market_ticker": tk, "series_ticker": "KXBTC15M", "has_orderbook": True,
            "has_underlying": True, "has_start_reference": True, "book_ok": True,
            "seconds_to_close": (close - as_of) / 1000.0, "as_of_ms": as_of, "close_ms": close,
            "feature_set_version": 2, "yes_ask": 0.42, "no_ask": 0.60,
            "yes_spread": 0.02, "no_spread": 0.02, "top_depth": 100.0,
            "yes_ask_size": 100.0, "no_ask_size": 100.0, "quote_age_ms": 100,
            "reference_start_price": 70000.0, "reference_price": 70010.0,
            "distance_to_start": (50.0 if yes else -50.0), "spot_sigma_per_sqrt_s": 1e-4,
            "realized_vol_60s": 1e-4, "realized_vol_180s": 1e-4,
            "distance_to_line_vol_normalized": (0.5 if yes else -0.5),
            "spot_return_60s": (0.001 if yes else -0.001)}


def _write_fixture(tmp_path, n_windows=8, rows_per=6):
    feats = (tmp_path / "features"); feats.mkdir(parents=True)
    labels = (tmp_path / "labels"); labels.mkdir(parents=True)
    base = 1_780_000_000_000
    fr, lr = [], []
    for w in range(n_windows):
        close = base + (w + 1) * WIN
        yes = w % 2
        for i in range(rows_per):
            fr.append(_frow(f"KX-{w}", as_of=close - (200 - i * 10) * 1000, close=close, yes=yes))
        lr.append({"market_ticker": f"KX-{w}", "label_source_status": "OFFICIAL",
                   "label_yes_resolved": yes})
    (feats / "kalshi_feature_rows-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in fr) + "\n", encoding="utf-8")
    (labels / "kalshi_settlement_labels-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in lr) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Gate + diagnostic behavior
# --------------------------------------------------------------------------- #
def test_calibrate_refuses_below_gate_then_diagnostic_non_tradable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=8)
    cfg = load_config(mode="paper")
    r = crep.run_calibrate_model(cfg, series="KXBTC15M", method="isotonic", diagnostic_only=False)
    assert r.get("refused") is True                       # 8 << 150
    r2 = crep.run_calibrate_model(cfg, series="KXBTC15M", method="isotonic", diagnostic_only=True)
    assert r2.get("refused") is not True and "artifact" in r2
    assert r2["artifact"]["NON_TRADABLE_DIAGNOSTIC_ONLY"] is True
    art = calibrate.load_calibrator(r2["artifact"]["calibrator_file"])
    assert art["tradable"] is False and art["calibration_status"] == "diagnostic"


def test_backtest_baselines_diagnostic_runs_and_no_trade_floor(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=8)
    r = run_backtest_baselines(load_config(mode="paper"), series="KXBTC15M", diagnostic_only=True)
    assert r["diagnostic"] is True and "results" in r
    assert r["results"]["no_trade"]["net_pnl"] == 0.0
    assert "market_implied" in r["results"] and "microstructure" in r["results"]
    # every simulated trade is flagged non-tradable in diagnostic mode
    for t in r["results"]["microstructure"].get("trades", []):
        assert t["tradable"] is False


def test_backtest_refuses_below_gate_without_diagnostic(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=8)
    r = run_backtest_baselines(load_config(mode="paper"), series="KXBTC15M", diagnostic_only=False)
    assert r.get("refused") is True


def test_threshold_sweep_reports_without_autoselect(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=8)
    r = run_threshold_sweep(load_config(mode="paper"), series="KXBTC15M", diagnostic_only=True)
    assert len(r["configs"]) == 120
    assert "recommended_config" not in r and "selected_config" not in r   # never auto-selects
    c0 = r["configs"][0]
    assert "trades" in c0 and "net_pnl" in c0 and "reject_rate" in c0


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #
def test_no_paper_candidate_and_live_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _write_fixture(tmp_path, n_windows=8)
    r = run_backtest_baselines(load_config(mode="paper"), series="KXBTC15M", diagnostic_only=True)
    trades = r["results"]["microstructure"].get("trades", [])
    for t in trades:
        assert "PAPER_CANDIDATE" not in str(t.get("reason_codes", []))
        assert "live_order_submitted" not in t      # backtest never references live orders
    from btc5m.cli import main
    assert main(["check-live-disabled"]) == 0
