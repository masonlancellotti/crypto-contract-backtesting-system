"""Tests for the maker-entry feasibility study (READ-ONLY research).

Covers snapshot loading/filtering, the conservative trade-through fill rule
(strictly-later snapshots only), would-cross handling, settle/fee math,
rest-horizon filtering, double-fill (both-sides quoting) detection, aggregation,
the end-to-end CLI run + report files, and the safety invariants. Offline.
"""

import json

from btc5m.config import load_config
from btc5m.venues.kalshi import maker_entry as me
from btc5m.venues.kalshi.fees import KalshiFeeModel

T1 = "KXBTC15M-26JUN061830-30"
START = 1_000_000
CLOSE = START + 900_000


def _snap(t_ms, yes_bid, yes_ask, no_bid, no_ask, ticker=T1, valid=True, **over):
    e = {
        "venue": "kalshi", "series_ticker": "KXBTC15M", "market_ticker": ticker,
        "window_start_ms": START, "close_ms": CLOSE, "recv_ms": t_ms, "status": "active",
        "yes_bid": yes_bid, "yes_ask": yes_ask, "no_bid": no_bid, "no_ask": no_ask,
        "yes_bid_size": 100.0, "yes_ask_size": 100.0, "no_bid_size": 100.0,
        "no_ask_size": 100.0,
        "book_validity_flags": {
            "yes_side_present": valid, "no_side_present": valid,
            "incomplete_book": not valid, "yes_crossed": False, "no_crossed": False,
            "prices_in_range": True,
        },
    }
    e.update(over)
    return {"stream": "kalshi_orderbook", "event": e}


def _label(ticker=T1, y=1):
    return {
        "venue": "kalshi", "series_ticker": "KXBTC15M", "market_ticker": ticker,
        "window_start_ms": START, "close_ms": CLOSE, "official_result": "yes" if y else "no",
        "label_yes_resolved": y, "label_source_status": "OFFICIAL",
    }


def _write_env(tmp_path, monkeypatch, snaps, labels):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    nd = tmp_path / "data" / "normalized"
    ld = tmp_path / "data" / "labels"
    nd.mkdir(parents=True)
    ld.mkdir(parents=True)
    (nd / "kalshi_orderbook-20260606.jsonl").write_text(
        "\n".join(json.dumps(s) for s in snaps) + "\n", encoding="utf-8")
    (ld / "kalshi_settlement_labels-20260606.jsonl").write_text(
        "\n".join(json.dumps(lb) for lb in labels) + "\n", encoding="utf-8")
    return load_config()


# --------------------------------------------------------------------------- #
# Loading + filtering
# --------------------------------------------------------------------------- #
def test_load_window_snapshots_filters_invalid_prewindow_postclose(tmp_path, monkeypatch):
    snaps = [
        _snap(START - 5_000, 0.50, 0.55, 0.45, 0.50),          # pre-window -> dropped
        _snap(START + 10_000, 0.50, 0.55, 0.45, 0.50),          # kept
        _snap(START + 20_000, 0.50, 0.55, 0.45, 0.50, valid=False),  # invalid book -> dropped
        _snap(CLOSE + 1, 0.50, 0.55, 0.45, 0.50),               # post-close -> dropped
        _snap(START + 30_000, None, 0.55, 0.45, 0.50),          # missing bid -> dropped
    ]
    cfg = _write_env(tmp_path, monkeypatch, snaps, [_label()])
    by_tk = me.load_window_snapshots(cfg)
    assert list(by_tk) == [T1]
    assert [s["recv_ms"] for s in by_tk[T1]] == [START + 10_000]


def test_first_trade_through_strictly_later_and_threshold():
    snaps = [
        {"recv_ms": 0, "yes_ask": 0.50},      # decision row itself (ask == limit) must NOT count
        {"recv_ms": 1_000, "yes_ask": 0.52},
        {"recv_ms": 2_000, "yes_ask": 0.50},  # first touch at/below limit
        {"recv_ms": 3_000, "yes_ask": 0.40},
    ]
    assert me._first_trade_through(snaps, 0, "yes_ask", 0.50) == 2_000
    assert me._first_trade_through(snaps, 0, "yes_ask", 0.30) is None
    # from the last index there is no later snapshot
    assert me._first_trade_through(snaps, 3, "yes_ask", 0.99) is None


# --------------------------------------------------------------------------- #
# Simulation semantics
# --------------------------------------------------------------------------- #
def test_simulate_fill_settle_and_would_cross(tmp_path, monkeypatch):
    # Decision at t+10s: yes 0.50/0.55. Ask trades through 0.50 at t+70s.
    # NO side never trades through. Label YES=1.
    snaps = [
        _snap(START + 10_000, 0.50, 0.55, 0.45, 0.50),
        _snap(START + 70_000, 0.45, 0.50, 0.50, 0.55),
    ]
    cfg = _write_env(tmp_path, monkeypatch, snaps, [_label(y=1)])
    sim = me.simulate_maker_entries(cfg)
    decs = sim["decisions"]
    yes_join = [d for d in decs if d["side"] == "YES" and d["mode"] == "join"]
    assert yes_join[0]["fill_ms"] == START + 70_000 and yes_join[0]["y_side"] == 1
    # improve at bid+1c = 0.51 < ask: eligible; fills too (0.50 <= 0.51)
    yes_imp = [d for d in decs if d["side"] == "YES" and d["mode"] == "improve"][0]
    assert not yes_imp["would_cross"] and yes_imp["fill_ms"] == START + 70_000
    # NO join from the second snapshot: bid 0.50, ask 0.55 -> no later snapshot -> no fill
    no_join_late = [d for d in decs if d["side"] == "NO" and d["mode"] == "join"
                    and d["t0"] == START + 70_000][0]
    assert no_join_late["fill_ms"] is None
    # would_cross: improve from a 1c-spread book
    tight = [
        _snap(START + 10_000, 0.50, 0.51, 0.49, 0.50),
    ]
    cfg2 = _write_env(tmp_path / "b", monkeypatch, tight, [_label(y=1)])
    sim2 = me.simulate_maker_entries(cfg2)
    imp = [d for d in sim2["decisions"] if d["mode"] == "improve" and d["side"] == "YES"][0]
    assert imp["would_cross"] and imp["fill_ms"] is None


def test_maker_ev_math_and_fee_application():
    fee0 = KalshiFeeModel(rate=0.0, status="ASSUMED_ZERO_MAKER_FEE")
    taker = KalshiFeeModel(rate=0.07, status="ASSUMED")
    recs = [
        {"ticker": T1, "t0": 0, "day": "2026-06-06", "side": "YES", "mode": "join",
         "limit": 0.50, "ask0": 0.55, "secs_to_close": 600.0, "y_side": 1,
         "would_cross": False, "fill_ms": 1_000},
        {"ticker": T1, "t0": 60_000, "day": "2026-06-06", "side": "YES", "mode": "join",
         "limit": 0.40, "ask0": 0.45, "secs_to_close": 540.0, "y_side": 0,
         "would_cross": False, "fill_ms": None},
    ]
    a = me._agg(recs, fee0, taker, me.CLOSE_HORIZON)
    assert a["eligible"] == 2 and a["fills"] == 1
    assert abs(a["fill_rate"] - 0.5) < 1e-9
    # filled: y=1, L=0.50, no maker fee -> +50c per fill
    assert abs(a["maker_ev_cents_per_fill"] - 50.0) < 1e-6
    # per decision: 0.50 / 2 eligible -> 25c
    assert abs(a["maker_ev_cents_per_decision"] - 25.0) < 1e-6
    # taker EV: (1 - 0.55 - fee(0.55)) + (0 - 0.45 - fee(0.45)) over 2
    exp_taker = ((1 - 0.55 - taker.per_contract_fee(0.55))
                 + (0 - 0.45 - taker.per_contract_fee(0.45))) / 2 * 100.0
    assert abs(a["taker_ev_cents_per_decision"] - exp_taker) < 1e-6
    assert a["win_rate_given_fill"] == 1.0 and a["win_rate_no_fill"] == 0.0


def test_rest_horizon_filtering():
    rec = {"ticker": T1, "t0": 0, "day": "d", "side": "YES", "mode": "join",
           "limit": 0.5, "ask0": 0.55, "secs_to_close": 600.0, "y_side": 1,
           "would_cross": False, "fill_ms": 61_000}
    assert not me._filled_within(rec, 60)
    assert me._filled_within(rec, 180)
    assert me._filled_within(rec, me.CLOSE_HORIZON)


def test_double_fill_detection_and_locked_net(tmp_path, monkeypatch):
    # Both sides trade through after the first decision point: YES join 0.48 and
    # NO join 0.47 both fill -> locked pair cost 0.95, locked net 0.05 (no maker fee).
    snaps = [
        _snap(START + 10_000, 0.48, 0.55, 0.47, 0.54),
        _snap(START + 65_000, 0.40, 0.48, 0.50, 0.58),   # yes_ask 0.48 <= 0.48 -> YES fill
        _snap(START + 75_000, 0.50, 0.58, 0.40, 0.47),   # no_ask 0.47 <= 0.47 -> NO fill
    ]
    cfg = _write_env(tmp_path, monkeypatch, snaps, [_label(y=1)])
    sim = me.simulate_maker_entries(cfg)
    pairs = sim["double_fill_pairs"]
    assert len(pairs) == 1
    assert abs(pairs[0]["pair_cost"] - 0.95) < 1e-9
    assert abs(pairs[0]["locked_net"] - 0.05) < 1e-9
    an = me.analyze_maker_entries(sim)
    assert an["double_fill"]["n_double_fills"] == 1


# --------------------------------------------------------------------------- #
# End-to-end + CLI + safety
# --------------------------------------------------------------------------- #
def test_run_maker_entry_study_end_to_end(tmp_path, monkeypatch):
    snaps = [
        _snap(START + 10_000, 0.50, 0.55, 0.45, 0.50),
        _snap(START + 70_000, 0.45, 0.50, 0.50, 0.55),
        _snap(START + 130_000, 0.44, 0.49, 0.51, 0.56),
    ]
    cfg = _write_env(tmp_path, monkeypatch, snaps, [_label(y=1)])
    r = me.run_maker_entry_study(cfg)
    assert r["status"] == "OK" and r["n_windows"] == 1
    assert r["live_submission_allowed"] is False
    assert "YES" in r["central_cohorts"] and "NO" in r["central_cohorts"]
    md = (tmp_path / "reports" / "maker")
    assert any(p.suffix == ".md" for p in md.iterdir())
    assert any(p.suffix == ".csv" for p in md.iterdir())
    text = next(p for p in md.iterdir() if p.suffix == ".md").read_text(encoding="utf-8")
    assert "LOWER BOUND" in text and "live disabled" in text


def test_orphan_label_window_excluded(tmp_path, monkeypatch):
    # label exists but no snapshots for that ticker -> not in study; snapshots
    # without a label -> also excluded.
    snaps = [_snap(START + 10_000, 0.50, 0.55, 0.45, 0.50, ticker="KXBTC15M-26JUN061845-45")]
    cfg = _write_env(tmp_path, monkeypatch, snaps, [_label(ticker=T1)])
    sim = me.simulate_maker_entries(cfg)
    assert sim["n_windows_with_label_and_books"] == 0
    assert sim["decisions"] == []


def test_cli_registration():
    from btc5m import cli
    assert "kalshi-maker-entry-study" in cli._COMMANDS
