"""Tests for maker-entry v2: REAL trade-print fill models + the trade backfill loader.

Kalshi matching semantics under test: a taker buying NO consumes resting YES
bids (taker_side="no" prints fill YES makers) and vice versa. "through" requires
the tape to trade strictly below the limit (certain fill); "front" fills at the
level (front-of-queue optimism). Offline.
"""

import json

from btc5m.config import load_config
from btc5m.venues.kalshi import maker_entry as me
from btc5m.venues.kalshi.backfill_trades import load_trade_prints

T1 = "KXBTC15M-26JUN061830-30"
START = 1_000_000
CLOSE = START + 900_000


def _print(ts_ms, yes_price, taker_side, ticker=T1, tid=None):
    return {"market_ticker": ticker, "trade_id": tid or f"t{ts_ms}-{taker_side}",
            "created_time_ms": ts_ms, "yes_price": yes_price,
            "no_price": round(1.0 - yes_price, 4), "count": 10.0,
            "taker_side": taker_side}


# --------------------------------------------------------------------------- #
# _first_print_fill semantics
# --------------------------------------------------------------------------- #
def test_yes_maker_filled_by_no_taker_prints_only():
    prints = [
        _print(START + 5_000, 0.48, "yes"),   # taker bought YES -> fills NO makers, not us
        _print(START + 6_000, 0.49, "no"),    # taker bought NO at yes_price 0.49 < 0.50 -> through
    ]
    # resting YES buy at 0.50
    assert me._first_print_fill(prints, START, CLOSE, "YES", 0.50, queue="through") == START + 6_000
    # the taker_side="yes" print alone never fills a YES maker
    assert me._first_print_fill(prints[:1], START, CLOSE, "YES", 0.50, queue="through") is None


def test_through_vs_front_queue_assumptions():
    prints = [_print(START + 5_000, 0.50, "no")]   # tape traded AT 0.50, not through
    assert me._first_print_fill(prints, START, CLOSE, "YES", 0.50, queue="through") is None
    assert me._first_print_fill(prints, START, CLOSE, "YES", 0.50, queue="front") == START + 5_000


def test_print_fill_respects_t0_and_close():
    prints = [
        _print(START + 1_000, 0.40, "no"),     # before decision -> ignored
        _print(CLOSE + 1, 0.40, "no"),         # after close -> ignored
    ]
    assert me._first_print_fill(prints, START + 2_000, CLOSE, "YES", 0.50, queue="front") is None


def test_no_maker_filled_by_yes_taker_at_no_price():
    # resting NO buy at 0.45; taker bought YES -> hits NO bids; print no_price 0.44 < 0.45
    prints = [_print(START + 7_000, 0.56, "yes")]   # no_price = 0.44
    assert me._first_print_fill(prints, START, CLOSE, "NO", 0.45, queue="through") == START + 7_000
    assert me._first_print_fill(prints, START, CLOSE, "NO", 0.43, queue="through") is None


# --------------------------------------------------------------------------- #
# end-to-end with prints on disk
# --------------------------------------------------------------------------- #
def _snap(t_ms, yes_bid, yes_ask, no_bid, no_ask, ticker=T1):
    return {"stream": "kalshi_orderbook", "event": {
        "venue": "kalshi", "series_ticker": "KXBTC15M", "market_ticker": ticker,
        "window_start_ms": START, "close_ms": CLOSE, "recv_ms": t_ms, "status": "active",
        "yes_bid": yes_bid, "yes_ask": yes_ask, "no_bid": no_bid, "no_ask": no_ask,
        "yes_bid_size": 100.0, "yes_ask_size": 100.0, "no_bid_size": 100.0,
        "no_ask_size": 100.0,
        "book_validity_flags": {"yes_side_present": True, "no_side_present": True,
                                "incomplete_book": False, "yes_crossed": False,
                                "no_crossed": False, "prices_in_range": True}}}


def _label(ticker=T1, y=1):
    return {"venue": "kalshi", "series_ticker": "KXBTC15M", "market_ticker": ticker,
            "window_start_ms": START, "close_ms": CLOSE, "official_result": "yes" if y else "no",
            "label_yes_resolved": y, "label_source_status": "OFFICIAL"}


def test_simulate_with_prints_fill_model(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    nd = tmp_path / "data" / "normalized"
    ld = tmp_path / "data" / "labels"
    nd.mkdir(parents=True)
    ld.mkdir(parents=True)
    (nd / "kalshi_orderbook-20260606.jsonl").write_text(
        json.dumps(_snap(START + 10_000, 0.50, 0.55, 0.45, 0.50)) + "\n", encoding="utf-8")
    (ld / "kalshi_settlement_labels-20260606.jsonl").write_text(
        json.dumps(_label(y=1)) + "\n", encoding="utf-8")
    # tape: trades through the YES 0.50 level at t+30s (taker bought NO)
    prints = [
        {"stream": "kalshi_trades", "event": _print(START + 30_000, 0.49, "no", tid="a")},
        {"stream": "kalshi_trades", "event": _print(START + 31_000, 0.49, "no", tid="a")},  # dup id
    ]
    (nd / "kalshi_trades-20260606.jsonl").write_text(
        "\n".join(json.dumps(p) for p in prints) + "\n", encoding="utf-8")

    cfg = load_config()
    by_tk = load_trade_prints(cfg)
    assert len(by_tk[T1]) == 1   # deduped by trade_id

    sim = me.simulate_maker_entries(cfg, fill_model="prints-through")
    yes_join = [d for d in sim["decisions"] if d["side"] == "YES" and d["mode"] == "join"][0]
    assert yes_join["fill_ms"] == START + 30_000
    # NO side: no taker_side="yes" prints -> never filled
    no_join = [d for d in sim["decisions"] if d["side"] == "NO" and d["mode"] == "join"][0]
    assert no_join["fill_ms"] is None
    assert sim["fill_model"] == "prints-through"


def test_windows_without_prints_are_excluded_in_print_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    nd = tmp_path / "data" / "normalized"
    ld = tmp_path / "data" / "labels"
    nd.mkdir(parents=True)
    ld.mkdir(parents=True)
    (nd / "kalshi_orderbook-20260606.jsonl").write_text(
        json.dumps(_snap(START + 10_000, 0.50, 0.55, 0.45, 0.50)) + "\n", encoding="utf-8")
    (ld / "kalshi_settlement_labels-20260606.jsonl").write_text(
        json.dumps(_label(y=1)) + "\n", encoding="utf-8")
    cfg = load_config()
    sim = me.simulate_maker_entries(cfg, fill_model="prints-through")
    assert sim["n_windows_with_label_and_books"] == 0   # no tape -> excluded
    sim_q = me.simulate_maker_entries(cfg, fill_model="quote")
    assert sim_q["n_windows_with_label_and_books"] == 1  # quote mode unaffected


def test_cli_registration_backfill_and_fill_model():
    from btc5m import cli
    assert "kalshi-backfill-trades" in cli._COMMANDS
