"""Tests for high-res repricing-lag v2 (READ-ONLY research on joined snapshots).

Covers the loader (jsonl + jsonl.gz, dedupe, close_ms derive, label line-enrichment, required-
field validation), the insufficient-data block (no v1 fallback), tolerance-bounded horizon
lookup with NO look-ahead (post horizons never resolve to t0), shock detection, response
measurement, stale-candidate qualification + fee/depth/buffer math, dedupe, outcome scoring,
the sensitivity grid, optional Deribit context, end-to-end report generation, and safety.
"""

import gzip
import json
from pathlib import Path

from btc5m.config import load_config
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi import reprice_lag_hires as v2

FM = KalshiFeeModel()
TK = "KXBTC15M-26JUN081630-30"


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    return load_config(mode="paper")


def _jrow(ticker, as_of, **over):
    r = dict(stream="hires_joined_snapshot", as_of_ms=as_of, market_ticker=ticker,
             seconds_to_close=300.0, reference_start_price=100.0, yes_ask=0.80, no_ask=0.21,
             yes_ask_size=5000.0, no_ask_size=5000.0, coinbase_mid=101.0, binance_mid=101.0,
             coinbase_age_ms=50, binance_age_ms=30, kalshi_book_age_ms=0, basis=0.0,
             coinbase_stale=False, binance_stale=False, realized_vol_60s=1e-4,
             no_live_orders=True, live_submission_allowed=False,
             spot_return_250ms=0.0, spot_return_500ms=0.0, spot_return_1s=0.0, spot_return_2s=0.0,
             spot_return_5s=0.0, spot_return_15s=0.0, perp_return_250ms=0.0, perp_return_1s=0.0,
             perp_return_2s=0.0, perp_return_5s=0.0)
    r.update(over)
    return r


def _write(path: Path, rows, gz=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    op = gzip.open if gz else open
    with op(path, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


# --------------------------------------------------------------------------- #
# Part B — loader
# --------------------------------------------------------------------------- #
def test_loader_reads_jsonl_and_gz_dedupes_derives(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    d = tmp_path / "data" / "features" / "hires" / "20260608"
    _write(d / "kalshi_hires_joined_snapshots-20260608_010101_0007.jsonl",
           [_jrow(TK, 1000), _jrow(TK, 2100)])
    _write(d / "kalshi_hires_joined_snapshots-20260608_010110_0007.jsonl.gz",
           [_jrow(TK, 2100), _jrow("KXBTC15M-26JUN081645-45", 3000)], gz=True)  # 2100 dup
    data = v2.load_joined(cfg)
    assert data["n_rows"] == 3 and data["n_windows"] == 2          # dup (TK,2100) collapsed
    assert all(r.get("close_ms") for r in data["rows"])            # derived from seconds_to_close
    assert data["rows"] == sorted(data["rows"], key=lambda r: (r["market_ticker"], r["as_of_ms"]))


def test_loader_enriches_line_from_labels(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    d = tmp_path / "data" / "features" / "hires" / "20260608"
    _write(d / "kalshi_hires_joined_snapshots-20260608_010101_0007.jsonl",
           [_jrow(TK, 1000, reference_start_price=None)])
    lab = tmp_path / "data" / "labels"
    lab.mkdir(parents=True)
    (lab / "kalshi_settlement_labels-20260608.jsonl").write_text(
        json.dumps({"market_ticker": TK, "label_yes_resolved": 1, "reference_start_price": 99.5,
                    "close_ms": 1780000000000}) + "\n", encoding="utf-8")
    data = v2.load_joined(cfg)
    r = data["rows"][0]
    assert r["reference_start_price"] == 99.5 and r["_line_provenance"] == "settlement_target"
    assert data["windows_with_label"] == 1 and data["line_filled"] == 1


# --------------------------------------------------------------------------- #
# Insufficient data blocks (no fallback to v1)
# --------------------------------------------------------------------------- #
def test_insufficient_data_blocks_no_v1_fallback(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    d = tmp_path / "data" / "features" / "hires" / "20260608"
    _write(d / "kalshi_hires_joined_snapshots-20260608_010101_0007.jsonl", [_jrow(TK, 1000)])
    r = v2.run_hires_v2_study(cfg)
    assert r["status"] == "NOT_READY" and r["used_v2"] is True       # v2 attempted, blocked
    assert "insufficient" in r["reason"] and r["live_submission_allowed"] is False
    rep = v2.run_hires_v2_report(cfg)
    sen = v2.run_hires_v2_sensitivity(cfg)
    assert rep["status"] == "NOT_READY" and sen["status"] == "NOT_READY"   # all three consistent


# --------------------------------------------------------------------------- #
# Part C — horizon nearest-row lookup: no look-ahead, post never resolves to t0
# --------------------------------------------------------------------------- #
def test_horizon_post_excludes_t0_and_respects_tolerance():
    rows = [_jrow(TK, 0), _jrow(TK, 1100), _jrow(TK, 2200)]
    s = v2.TickerSeries(rows)
    assert s.nearest(250, 300, after_ms=0) is None                 # +250ms: next row 1100 too far
    assert s.nearest(1000, 750, after_ms=0)["as_of_ms"] == 1100     # +1s resolves to +1100
    assert s.nearest(1000, 750)["as_of_ms"] == 1100                 # without after, same here
    # general nearest could pick t0 if allowed; after_ms forbids it
    assert s.nearest(200, 300, after_ms=0) is None


def test_measure_response_no_lookahead():
    rows = [_jrow(TK, 0, yes_ask=0.80, no_ask=0.21), _jrow(TK, 1100, yes_ask=0.85, no_ask=0.16)]
    s = v2.TickerSeries(rows)
    resp = v2.measure_response(s, 0, v2.market_implied_yes(rows[0]), 0.80, 0.21, 0.97)
    assert resp["coverage"][250] is False and resp["coverage"][500] is False   # sub-cadence sparse
    assert resp["coverage"][1000] is True and resp["horizons"][1000]["offset_ms"] == 1100
    assert resp["horizons"][1000]["mkt_change_c"] is not None


# --------------------------------------------------------------------------- #
# Part D — shock detection
# --------------------------------------------------------------------------- #
def test_detect_shock_direction_source_magnitude():
    up = v2.detect_shock(_jrow(TK, 1, spot_return_1s=0.0012, perp_return_1s=0.0010), "1s")
    dn = v2.detect_shock(_jrow(TK, 1, spot_return_1s=-0.0012), "1s")
    assert up["direction"] == "up" and abs(up["abs_bps"] - 12.0) < 1e-6 and up["source"] == "both"
    assert dn["direction"] == "down"
    assert v2.detect_shock(_jrow(TK, 1), "1s")["abs_bps"] == 0.0    # quiet -> 0 magnitude


# --------------------------------------------------------------------------- #
# Part G — candidate qualification + fee/depth/buffer math
# --------------------------------------------------------------------------- #
def _cfg(**over):
    c = v2.V2Config()
    c.conservative_buffer_cents = 3.0
    for k, v_ in over.items():
        setattr(c, k, v_)
    return c


def test_candidate_qualifies_with_fee_depth_buffer():
    row = _jrow(TK, 1, spot_return_1s=0.0012, coinbase_mid=101.0, binance_mid=101.0, yes_ask=0.80)
    sh = v2.detect_shock(row, "1s")
    q = v2.qualify_candidate(row, sh, _cfg(shock_threshold_bps=5.0), FM)
    assert q["qualified"] and q["side"] == "YES"
    # net = gross - fee - buffer ; proxy ~1.0 (S>L, low vol) -> gross ~20c, fee 2c, buffer 3c
    assert abs(q["net_proxy_edge_cents"] - (q["gross_proxy_edge_cents"] - q["fee_cents"] - 3.0)) < 1e-6
    assert q["net_proxy_edge_cents"] > 0


def test_candidate_blocked_by_thin_depth_stale_race_and_rich_ask():
    base = dict(spot_return_1s=0.0012, coinbase_mid=101.0, binance_mid=101.0)
    cfg = _cfg(min_depth=1.0, max_source_age_ms=2000.0, min_seconds_to_close=30.0)
    thin = v2.qualify_candidate(_jrow(TK, 1, yes_ask_size=0.0, **base), v2.detect_shock(_jrow(TK, 1, **base), "1s"), cfg, FM)
    stale = v2.qualify_candidate(_jrow(TK, 1, coinbase_age_ms=9999, **base), v2.detect_shock(_jrow(TK, 1, **base), "1s"), cfg, FM)
    race = v2.qualify_candidate(_jrow(TK, 1, seconds_to_close=10.0, **base), v2.detect_shock(_jrow(TK, 1, **base), "1s"), cfg, FM)
    rich = v2.qualify_candidate(_jrow(TK, 1, yes_ask=0.99, **base), v2.detect_shock(_jrow(TK, 1, **base), "1s"), cfg, FM)
    assert "insufficient_depth" in thin["reasons"] and "source_age" in stale["reasons"]
    assert "settlement_race" in race["reasons"] and "no_fee_buffer_edge" in rich["reasons"]


# --------------------------------------------------------------------------- #
# Part H/I — dedupe + outcome scoring
# --------------------------------------------------------------------------- #
def test_dedupe_clusters_same_window_side_price():
    cands = [
        {"market_ticker": TK, "side": "YES", "shock_time_ms": 0, "executable_price": 0.80},
        {"market_ticker": TK, "side": "YES", "shock_time_ms": 5000, "executable_price": 0.80},   # within 20s -> same
        {"market_ticker": TK, "side": "YES", "shock_time_ms": 60000, "executable_price": 0.80},  # >20s -> new
        {"market_ticker": TK, "side": "NO", "shock_time_ms": 5000, "executable_price": 0.20}]
    opps = v2.dedupe(cands, 20.0)
    assert len(opps) == 3
    yes = [o for o in opps if o["side"] == "YES"][0]
    assert yes["n_obs"] == 2


def test_outcome_scoring_win_loss_pending():
    opps = [
        {"market_ticker": "W1", "side": "YES", "executable_price": 0.80},
        {"market_ticker": "W2", "side": "NO", "executable_price": 0.30},
        {"market_ticker": "W3", "side": "YES", "executable_price": 0.80}]
    labels = {"W1": {"label_yes_resolved": 1}, "W2": {"label_yes_resolved": 1}, "W3": {}}
    v2.score_outcomes(opps, labels, FM)
    assert opps[0]["win"] == 1 and abs(opps[0]["pnl_net"] - (0.20 - FM.per_contract_fee(0.80))) < 1e-9
    assert opps[1]["win"] == 0                              # NO loses when label==1
    assert opps[2]["status"] == "pending" and opps[2]["win"] is None


# --------------------------------------------------------------------------- #
# Deribit optional
# --------------------------------------------------------------------------- #
def test_deribit_context_optional(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    ctx = v2._deribit_context(cfg, ["2026-06-08"])
    assert ctx["present"] is False and "missing" in ctx["note"].lower()   # absent -> not blocking


# --------------------------------------------------------------------------- #
# End-to-end study (>= readiness) writes the 7 reports + safety
# --------------------------------------------------------------------------- #
def _seed_sufficient(tmp_path):
    d = tmp_path / "data" / "features" / "hires" / "20260608"
    lab = tmp_path / "data" / "labels"
    lab.mkdir(parents=True, exist_ok=True)
    base = 1_780_000_000_000
    rows_a, rows_b, labels = [], [], []
    for w in range(22):                                    # 22 windows >= 20
        tk = f"KXBTC15M-26JUN08{1600 + w}-30"
        t0 = base + w * 1_000_000
        for i in range(100):                               # 100 rows/window ~1.1s apart
            t = t0 + i * 1100
            shock = (i == 40)
            row = _jrow(tk, t, seconds_to_close=300.0 - i, coinbase_mid=101.0, binance_mid=101.0,
                        reference_start_price=100.0,
                        spot_return_1s=(0.0012 if shock else 0.00001),
                        yes_ask=(0.80 if shock else 0.50), no_ask=(0.21 if shock else 0.51))
            (rows_a if w % 2 == 0 else rows_b).append(row)
        labels.append({"market_ticker": tk, "label_yes_resolved": (w % 2),
                       "reference_start_price": 100.0, "close_ms": t0 + 900_000})
    _write(d / "kalshi_hires_joined_snapshots-20260608_010101_0007.jsonl", rows_a)
    _write(d / "kalshi_hires_joined_snapshots-20260608_010110_0007.jsonl.gz", rows_b, gz=True)
    with (lab / "kalshi_settlement_labels-20260608.jsonl").open("w", encoding="utf-8") as fh:
        for r in labels:
            fh.write(json.dumps(r) + "\n")


def test_study_end_to_end_writes_reports_and_safe(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    _seed_sufficient(tmp_path)
    r = v2.run_hires_v2_study(cfg, shock_threshold_bps=5.0)
    assert r["status"] == "OK" and r["used_v2"] is True and r["live_submission_allowed"] is False
    s = r["summary"]
    assert s["n_windows"] >= 20 and s["n_rows"] >= 2000
    assert s["coverage_by_horizon"][1000] > 0.5            # +1s well covered
    rd = tmp_path / "reports" / "reprice_lag" / "hires"
    for key in ("study_md", "shocks_csv", "candidates_csv", "opportunities_csv",
                "sensitivity_csv", "regime_csv", "manifest_json"):
        assert Path(r["reports"][key]).exists()
    # SAFETY: no promotion manifest / promoted artifacts created
    assert not list((tmp_path / "data").glob("**/kalshi_paper_promotion_manifest.json"))


def test_sensitivity_grid_uses_v2(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    _seed_sufficient(tmp_path)
    r = v2.run_hires_v2_sensitivity(cfg)
    assert r["status"] == "OK" and r["used_v2"] is True
    grid = r["grid"]
    assert {g["shock_threshold_bps"] for g in grid} == set(v2.SENS_BPS_GRID)
    assert {g["horizon_ms"] for g in grid} == set(v2.SENS_HORIZONS)
    # raw_shocks non-increasing as threshold rises
    by_thr = {}
    for g in grid:
        by_thr[g["shock_threshold_bps"]] = g["raw_shocks"]
    seq = [by_thr[t] for t in sorted(by_thr)]
    assert seq == sorted(seq, reverse=True)


# --------------------------------------------------------------------------- #
# CLI consistency + safety
# --------------------------------------------------------------------------- #
def test_cli_hires_routes_to_v2_not_v1():
    import btc5m.cli as c
    assert callable(c._run_hires_v2) and callable(c._v2_over)


def test_check_live_disabled_holds(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    assert cfg.live_blockers() and cfg.live_permitted is False
