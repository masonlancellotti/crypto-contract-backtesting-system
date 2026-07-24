"""Tests for the high-resolution measurement layer + recorder hardening (READ-ONLY).

Covers normalized schemas, Kalshi normalization + null-source_ts basis, point-in-time
joining (no look-ahead), the threaded/bounded priority-drop writer, queue overflow + high-
priority protection, clean-shutdown drain, file rotation, compression (active-file safe) +
retention, Binance aggTrade enable/sample/rate-cap, status (sizes/rates/queue/v2-ready),
the smoke runner with mocked sources, safe defaults, and check-live-disabled. No network.
"""

import json
import os
import time
from pathlib import Path

from btc5m.config import load_config
from btc5m.venues.kalshi.client import MarketPhase, select_collection_targets
from btc5m.venues.kalshi.hires import (
    HiResConfig, HiResWriter, PriorityDropQueue, BinanceWSSource, stream_priority,
    coinbase_ticker_event, binance_book_ticker_event, binance_trade_event,
    run_hires_compact, run_hires_smoke, run_hires_status,
)
from btc5m.venues.kalshi.hires import collector as cm
from btc5m.venues.kalshi.hires import sources as sm

TICK = "KXBTC15M-26JUN061830-30"


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    return load_config(mode="paper")


# --------------------------------------------------------------------------- #
# Schemas + Kalshi normalization (recv_ms basis on null source_ts)
# --------------------------------------------------------------------------- #
def test_event_builders_carry_safety_flag():
    cb = coinbase_ticker_event({"product_id": "BTC-USD", "best_bid": "100", "best_ask": "100.5",
                                "best_bid_size": "1", "best_ask_size": "2"}, 1000)
    bn = binance_book_ticker_event({"s": "BTCUSDT", "b": "100", "a": "100.5", "u": 1}, 1000)
    tr = binance_trade_event({"e": "aggTrade", "p": "100", "q": "0.5", "m": True, "a": 9}, 1000)
    assert cb["mid"] == 100.25 and bn["mid"] == 100.25 and tr["side"] == "sell"
    for e in (cb, bn, tr):
        assert e["live_submission_allowed"] is False and e["recv_ms"] == 1000


def test_kalshi_book_uses_recv_basis_not_stale(tmp_path, monkeypatch):
    cfg_app = _env(tmp_path, monkeypatch)
    src = sm.KalshiRESTBookSource(cfg_app, HiResConfig(), client=object(), line_lookup=lambda _t: 99.0)
    active = {"ticker": TICK, "event_ticker": "KXBTC15M-26JUN061830", "status": "active",
              "close_time": "2026-06-06T18:30:00Z", "_phase": MarketPhase.CURRENT_IN_WINDOW.value}
    raw = {"orderbook": {"orderbook_fp": {"yes_dollars": [["0.40", "10"]], "no_dollars": [["0.59", "20"]]}}}
    norm = src._normalize_book(active, raw, recv=1_780_000_000_000)
    assert norm["yes_ask"] == 0.41 and norm["source_ts_ms"] is None and norm["quote_age_ms"] is None
    assert norm["book_age_basis"] == "recv_ms" and norm["book_age_ms"] == 0
    assert norm["reference_start_price"] == 99.0 and norm["live_submission_allowed"] is False


def test_active_market_selection_prioritizes_current():
    disc = [{"ticker": "A", "_phase": MarketPhase.CLOSED_PENDING_SETTLE.value, "_close_ms": 1, "_open_ms": 0},
            {"ticker": "B", "_phase": MarketPhase.CURRENT_IN_WINDOW.value, "_close_ms": 5, "_open_ms": 2}]
    assert select_collection_targets(disc, max_markets=1)["targets"][0]["ticker"] == "B"


# --------------------------------------------------------------------------- #
# Part B — priority-drop queue
# --------------------------------------------------------------------------- #
def test_priorities():
    assert stream_priority("normalized", "hires_kalshi_active_book") == 0
    assert stream_priority("joined", "hires_joined_snapshot") == 0
    assert stream_priority("normalized", "hires_binance_book_ticker") == 1
    assert stream_priority("normalized", "hires_binance_trade") == 2
    assert stream_priority("raw", "hires_binance_trade") == 3


def test_queue_drops_low_priority_first_and_protects_high():
    q = PriorityDropQueue(maxsize=2, warn_size=1, drop_policy="drop_low_priority")
    assert q.put((1, "n", "hires_binance_book_ticker", {}, 1, 1)) == "queued"
    assert q.put((2, "n", "hires_binance_trade", {}, 1, 1)) == "queued"     # full now
    assert q.put((2, "n", "hires_binance_trade", {}, 1, 1)) == "dropped"    # low dropped
    # high priority is admitted even when full (loud overflow), never dropped
    assert q.put((0, "n", "hires_kalshi_active_book", {}, 1, 1)) == "queued_high_overflow"
    assert q.high_overflow == 1
    assert q.dropped_by_stream["hires_binance_trade:dropped_full"] == 1


def test_queue_drop_oldest_low_priority_evicts_for_higher():
    q = PriorityDropQueue(maxsize=2, warn_size=1, drop_policy="drop_oldest_low_priority")
    q.put((2, "n", "hires_binance_trade", {"i": 1}, 1, 1))
    q.put((2, "n", "hires_binance_trade", {"i": 2}, 1, 1))                  # full of trades
    assert q.put((1, "n", "hires_binance_book_ticker", {}, 1, 1)) == "queued_evicted"
    assert q.dropped_by_stream["hires_binance_trade:evicted_oldest"] == 1
    assert q.depth() == 2


# --------------------------------------------------------------------------- #
# Threaded writer: enqueue, write, clean-shutdown drain
# --------------------------------------------------------------------------- #
def _cfg(**over):
    c = HiResConfig()
    for k, v in over.items():
        setattr(c, k, v)
    return c


def _read_segment_lines(tmp_path, kind, base):
    d = tmp_path / "data" / kind / "hires"
    files = list(d.rglob(f"{base}-*.jsonl"))
    return [ln for f in files for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()], files


def test_threaded_writer_drains_on_shutdown(tmp_path, monkeypatch):
    cfg_app = _env(tmp_path, monkeypatch)
    w = HiResWriter(cfg_app, _cfg(writer_mode="threaded", compress_closed_files=False))
    w.start()
    for i in range(50):
        w.submit("normalized", "hires_binance_book_ticker",
                 {"stream": "hires_binance_book_ticker", "event": {"i": i, "recv_ms": 1000 + i}}, 1000 + i)
    w.stop(drain_timeout=5.0)
    lines, files = _read_segment_lines(tmp_path, "normalized", "hires_binance_book_ticker")
    assert len(lines) == 50 and files
    assert w.metrics()["rows_written_by_stream"]["hires_binance_book_ticker"] == 50


def test_writer_rotation_opens_new_segment(tmp_path, monkeypatch):
    cfg_app = _env(tmp_path, monkeypatch)
    w = HiResWriter(cfg_app, _cfg(writer_mode="sync", rotate_every_seconds=0, compress_closed_files=False))
    rec = {"stream": "hires_coinbase_ticker", "event": {"recv_ms": 1}}
    w.submit("normalized", "hires_coinbase_ticker", rec, 1)
    time.sleep(0.005)
    w.submit("normalized", "hires_coinbase_ticker", rec, 2)   # rotate_every_seconds=0 -> new segment
    w.stop()
    _lines, files = _read_segment_lines(tmp_path, "normalized", "hires_coinbase_ticker")
    assert len(files) >= 2 and w.metrics()["rotate_count"] >= 1


def test_writer_compresses_closed_segment(tmp_path, monkeypatch):
    cfg_app = _env(tmp_path, monkeypatch)
    w = HiResWriter(cfg_app, _cfg(writer_mode="sync", compress_closed_files=True))
    w.submit("normalized", "hires_coinbase_ticker",
             {"stream": "hires_coinbase_ticker", "event": {"recv_ms": 1}}, 1)
    w.stop()                                          # closes + gzips the segment
    d = tmp_path / "data" / "normalized" / "hires"
    assert list(d.rglob("hires_coinbase_ticker-*.jsonl.gz"))
    assert not list(d.rglob("hires_coinbase_ticker-*.jsonl"))   # original removed
    assert w.metrics()["compression_count"] >= 1


# --------------------------------------------------------------------------- #
# Part D — compaction: active-file safety + retention dry-run/write
# --------------------------------------------------------------------------- #
def _mk(p: Path, mtime_age_s: float):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"x":1}\n', encoding="utf-8")
    t = time.time() - mtime_age_s
    os.utime(p, (t, t))


def test_compaction_skips_active_compresses_closed(tmp_path, monkeypatch):
    cfg_app = _env(tmp_path, monkeypatch)
    base = tmp_path / "data" / "normalized" / "hires"
    _mk(base / "active-now.jsonl", 5)            # recent -> active -> skip
    _mk(base / "closed-old.jsonl", 4000)         # old -> compress
    r = run_hires_compact(cfg_app, write=True)
    assert (base / "active-now.jsonl").exists()           # untouched
    assert (base / "closed-old.jsonl.gz").exists() and not (base / "closed-old.jsonl").exists()
    assert r["compress"]["normalized"]["files_compressed"] == 1


def test_compaction_retention_dryrun_then_write(tmp_path, monkeypatch):
    cfg_app = _env(tmp_path, monkeypatch)
    raw = tmp_path / "data" / "raw" / "hires"
    _mk(raw / "ancient.jsonl.gz", 9 * 86400)     # older than raw retention (7d)
    dry = run_hires_compact(cfg_app, write=False, enforce_retention=True)
    assert dry["retention"]["raw"]["files_over_age"] == 1 and dry["retention"]["raw"]["files_deleted"] == 0
    assert (raw / "ancient.jsonl.gz").exists()
    wet = run_hires_compact(cfg_app, write=True, enforce_retention=True)
    assert wet["retention"]["raw"]["files_deleted"] == 1 and not (raw / "ancient.jsonl.gz").exists()


# --------------------------------------------------------------------------- #
# Part C — Binance aggTrade enable / sample / rate cap (testable handler)
# --------------------------------------------------------------------------- #
def test_aggtrade_disabled_by_default():
    s = BinanceWSSource("BTCUSDT")
    assert s._params() == ["btcusdt@bookTicker"]                     # no aggTrade
    assert s._handle_msg({"e": "aggTrade", "p": "1", "q": "1", "a": 1}, 1) is None
    assert s.stats()["trade_msgs"] == 0


def test_aggtrade_enabled_sampling():
    s = BinanceWSSource("BTCUSDT", aggtrade=True, aggtrade_sample_n=2)
    assert set(s._params()) == {"btcusdt@bookTicker", "btcusdt@aggTrade"}
    emitted = [s._handle_msg({"e": "aggTrade", "p": "1", "q": "1", "a": i}, 1) for i in range(4)]
    assert sum(1 for e in emitted if e) == 2                         # every 2nd kept
    assert s.stats()["trade_msgs"] == 2 and s.stats()["trade_sampled_dropped"] == 2


def test_binance_rate_cap_on_bookticker():
    s = BinanceWSSource("BTCUSDT", max_mps=2)
    kept = [s._handle_msg({"s": "BTCUSDT", "b": "1", "a": "1", "u": i}, 1_000) for i in range(5)]
    assert sum(1 for e in kept if e) == 2 and s.stats()["rate_capped"] == 3   # same 1s window


# --------------------------------------------------------------------------- #
# Part E — joined no-lookahead + status + smoke
# --------------------------------------------------------------------------- #
class _Fake(sm.BaseSource):
    def __init__(self, name, events):
        super().__init__()
        self.name = name
        for raw, norm in events:
            self._emit(raw, norm)

    def run(self):
        pass


def test_joined_point_in_time_no_lookahead(tmp_path, monkeypatch):
    cfg_app = _env(tmp_path, monkeypatch)
    T = 1_780_000_000_000
    cb = _Fake("coinbase", [({}, coinbase_ticker_event({"product_id": "BTC-USD", "best_bid": "100", "best_ask": "100"}, T))])
    bn = _Fake("binance", [
        ({}, binance_book_ticker_event({"s": "BTCUSDT", "b": "101", "a": "101", "u": 1}, T + 10)),
        ({}, binance_book_ticker_event({"s": "BTCUSDT", "b": "999", "a": "999", "u": 2}, T + 100))])
    kb = {"stream": "hires_kalshi_active_book", "source": "kalshi", "recv_ms": T + 50,
          "market_ticker": "KXBTC15M-X", "seconds_to_close": 300.0, "yes_ask": 0.5, "no_ask": 0.5,
          "yes_ask_size": 10.0, "no_ask_size": 10.0, "book_age_ms": 0}
    kal = _Fake("kalshi", [({}, kb)])
    w = HiResWriter(cfg_app, _cfg(writer_mode="sync", compress_closed_files=False))
    coll = cm.HiResCollector(cfg_app, _cfg(writer_mode="sync"), [cb, bn, kal], w, joined=True)
    coll._drain_once()
    w.stop()
    jfiles = list((tmp_path / "data" / "features" / "hires").rglob("kalshi_hires_joined_snapshots-*.jsonl"))
    rows = [json.loads(l) for f in jfiles for l in f.read_text().splitlines() if l.strip()]
    assert len(rows) == 1 and rows[0]["binance_mid"] == 101.0   # NOT 999 (no look-ahead)
    assert rows[0]["coinbase_age_ms"] == 50 and rows[0]["no_live_orders"] is True


def test_run_hires_smoke_with_mocked_sources(tmp_path, monkeypatch):
    cfg_app = _env(tmp_path, monkeypatch)
    T = 1_780_000_000_000

    def factory(config, hcfg, *, line_lookup=None):
        cb = _Fake("coinbase", [({}, coinbase_ticker_event(
            {"product_id": "BTC-USD", "best_bid": "100", "best_ask": "100"}, T))])
        kb = {"stream": "hires_kalshi_active_book", "source": "kalshi", "recv_ms": T + 30,
              "market_ticker": "KXBTC15M-Y", "seconds_to_close": 200.0, "yes_ask": 0.5, "no_ask": 0.5,
              "yes_ask_size": 5.0, "no_ask_size": 5.0, "book_age_ms": 0}
        return [cb, _Fake("kalshi", [({}, kb)]), _Fake("binance", [])], ["mocked"]

    r = run_hires_smoke(cfg_app, series="KXBTC15M", seconds=0.25, sources_factory=factory)
    sm_ = r["smoke"]
    assert r["live_submission_allowed"] is False and sm_["no_orders"] is True
    assert sm_["joined_snapshots"] >= 1 and sm_["active_ticker"] == "KXBTC15M-Y"
    assert sm_["queue_below_warning"] is True and sm_["high_priority_rows_dropped"] is False
    assert sm_["aggtrade_load_manageable"] is True
    assert Path(r["reports"]["session_json"]).exists()


def test_status_reports_sizes_queue_and_v2(tmp_path, monkeypatch):
    cfg_app = _env(tmp_path, monkeypatch)
    # a normalized kalshi segment + a session json with queue/drop metrics
    nb = tmp_path / "data" / "normalized" / "hires" / "20260608"
    nb.mkdir(parents=True)
    (nb / "kalshi_active_book-20260608_010101.jsonl").write_text(
        json.dumps({"stream": "hires_kalshi_active_book",
                    "event": {"recv_ms": 1_780_000_000_000, "market_ticker": "KXBTC15M-Z"}}) + "\n",
        encoding="utf-8")
    rd = tmp_path / "reports" / "hires"
    rd.mkdir(parents=True)
    (rd / "kalshi_hires_session_20260608_010101.json").write_text(json.dumps({"summary": {
        "queue": {"depth_max": 7, "depth_current": 0, "dropped_by_stream": {"hires_binance_trade:dropped_full": 3}},
        "writer": {"writer_errors": 0, "compression_count": 2}}}), encoding="utf-8")
    r = run_hires_status(cfg_app, series="KXBTC15M")
    assert r["files"]["kalshi_active_book"]["present"] and r["files"]["kalshi_active_book"]["total_bytes"] > 0
    assert r["session"]["queue_depth_max"] == 7 and r["session"]["dropped_by_stream"]
    assert r["reprice_lag_v2_ready"] is False and "reprice_lag_v2" in r


# --------------------------------------------------------------------------- #
# Safety + CLI registration
# --------------------------------------------------------------------------- #
def test_safe_defaults_and_env_cannot_enable_orders(monkeypatch):
    monkeypatch.setenv("HIRES_NO_ORDERS", "false")
    monkeypatch.setenv("HIRES_LIVE_SUBMISSION_ALLOWED", "true")
    monkeypatch.setenv("BINANCE_HIRES_AGGTRADE_ENABLED", "true")
    c = HiResConfig.from_env()
    assert c.enabled is False and c.no_orders is True and c.live_submission_allowed is False
    assert c.writer_mode == "threaded" and c.binance_aggtrade_enabled is True   # env can enable aggTrade
    # ... but the default (no env) keeps aggTrade OFF:
    for k in ("HIRES_NO_ORDERS", "HIRES_LIVE_SUBMISSION_ALLOWED", "BINANCE_HIRES_AGGTRADE_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    assert HiResConfig.from_env().binance_aggtrade_enabled is False


def test_cli_hires_commands_registered():
    import btc5m.cli as c
    for name in ("kalshi-hires-record", "kalshi-hires-record-loop", "kalshi-hires-smoke",
                 "kalshi-hires-status", "kalshi-hires-compact"):
        assert name in c._COMMANDS and callable(c._COMMANDS[name])


def test_check_live_disabled_holds(tmp_path, monkeypatch):
    cfg = _env(tmp_path, monkeypatch)
    assert cfg.live_blockers() and cfg.live_permitted is False
