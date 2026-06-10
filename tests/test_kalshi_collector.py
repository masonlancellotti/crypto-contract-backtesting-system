"""Continuous Kalshi collector — offline, network fully mocked.

Verifies: the command is registered; one cycle records books + underlying, builds
features, writes a ledger + session summary; an uncalibrated baseline never emits
a PAPER_CANDIDATE; requesting the disabled optional Deribit source does not crash;
and a Ctrl-C mid-cycle stops cleanly leaving recorded data valid.
"""

from datetime import datetime, timedelta, timezone

from btc5m.cli import _COMMANDS
from btc5m.config import load_config
from btc5m.schemas import UnderlyingEvent
from btc5m.timeutils import now_ms
from btc5m.venues.kalshi import collector as collector_mod
from btc5m.venues.kalshi.client import KalshiClient


def _market():
    now = datetime.now(timezone.utc)
    return {
        "ticker": "KXBTC15M-26JUN010345-45", "event_ticker": "KXBTC15M-26JUN010345",
        "title": "BTC price up in next 15 mins?", "yes_sub_title": "Target Price: $72,901.10",
        "status": "active", "result": "",
        "open_time": (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "close_time": (now + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiration_time": (now + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rules_primary": "If the simple average ... is at least the simple average ...",
        "updated_time": "2026-06-01T07:31:00Z", "_phase": "CURRENT_IN_WINDOW",
    }


class _FakeUnd:
    def __init__(self, source):
        self.source = source

    def poll(self):
        ts = now_ms()
        ev = UnderlyingEvent(source=self.source, symbol="BTC-USD", event_type="ticker",
                             exchange_ts_ms=ts, recv_ms=ts, price=72000.0,
                             best_bid=71999.5, best_ask=72000.5, spread=1.0)
        return [({"price": 72000.0}, ev)]

    def reference_price_now(self):
        return 72000.0, f"{self.source}:BTC", {"price": 72000.0}


class _FakeUndAt:
    def __init__(self, source, ts, price=72000.0):
        self.source = source
        self.ts = ts
        self.price = price

    def poll(self):
        ev = UnderlyingEvent(source=self.source, symbol="BTC-USD", event_type="ticker",
                             exchange_ts_ms=self.ts, recv_ms=self.ts, price=self.price,
                             best_bid=self.price - 0.5, best_ask=self.price + 0.5, spread=1.0)
        return [({"price": self.price}, ev)]

    def reference_price_now(self):
        return self.price, f"{self.source}:BTC", {"price": self.price}


def _patch_clients(monkeypatch):
    market = _market()
    raw_ob = {"orderbook_fp": {"yes_dollars": [["0.40", "500"]], "no_dollars": [["0.58", "500"]]}}
    monkeypatch.setattr(KalshiClient, "discover", lambda self, **kw: [market])
    monkeypatch.setattr(KalshiClient, "get_orderbook", lambda self, t, **kw: raw_ob)
    monkeypatch.setattr(KalshiClient, "get_market", lambda self, t: market)
    monkeypatch.setattr(collector_mod, "build_underlying_client",
                        lambda name, cfg: _FakeUnd(name))


def _upcoming_market():
    now = datetime.now(timezone.utc)
    return {
        "ticker": "KXBTC15M-26JUN010400-00", "event_ticker": "KXBTC15M-26JUN010400",
        "title": "BTC price up in next 15 mins?", "yes_sub_title": "Target Price: $73,000.00",
        "status": "initialized", "result": "",
        "open_time": (now + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "close_time": (now + timedelta(minutes=25)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiration_time": (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rules_primary": "...", "updated_time": "2026-06-01T07:31:00Z", "_phase": "UPCOMING",
        "_open_ms": now_ms() + 600_000, "_close_ms": now_ms() + 1_500_000,
    }


def test_command_registered():
    assert "kalshi-collect-continuous" in _COMMANDS


def test_max_markets_1_collects_active_and_shadow_sees_executable_row(tmp_path, monkeypatch):
    # The collector must record the ACTIVE market (not an upcoming one) with one slot, and the
    # shadow data path must then see an executable active row. Guards the 'active ticker never
    # recorded -> shadow active_window=0/book_backed=0' failure.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("TRADING_MODE", "paper")
    cur = _market()
    cur["_open_ms"] = now_ms() - 300_000
    cur["_close_ms"] = now_ms() + 600_000
    up = _upcoming_market()
    raw_ob = {"orderbook_fp": {"yes_dollars": [["0.40", "500"]], "no_dollars": [["0.58", "500"]]}}
    # discover lists the UPCOMING market FIRST; with max_markets=1 the collector must still pick CURRENT
    monkeypatch.setattr(KalshiClient, "discover", lambda self, **kw: [up, cur])
    monkeypatch.setattr(KalshiClient, "get_orderbook", lambda self, t, **kw: raw_ob)
    monkeypatch.setattr(KalshiClient, "get_market", lambda self, t: cur)
    monkeypatch.setattr(collector_mod, "build_underlying_client", lambda name, cfg: _FakeUnd(name))
    cfg = load_config(mode="paper")

    msgs: list[str] = []
    collector_mod.run_continuous(
        cfg, series="KXBTC15M", sources="coinbase", seconds_per_cycle=0.0, interval=0.0,
        max_markets=1, readiness_every=0, backfill_every=0, max_cycles=1, emit=msgs.append)

    import json
    tk, up_tk = cur["ticker"], up["ticker"]
    norm = list((tmp_path / "normalized").glob("kalshi_orderbook-*.jsonl"))
    feats = list((tmp_path / "features").glob("kalshi_feature_rows-*.jsonl"))
    assert norm and feats, "collector must write normalized orderbooks + feature rows"
    for p in norm + feats:  # recorded data must be valid JSONL
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)
    norm_text = "".join(p.read_text(encoding="utf-8") for p in norm)
    feat_text = "".join(p.read_text(encoding="utf-8") for p in feats)
    assert tk in norm_text and tk in feat_text          # ACTIVE market IS recorded
    assert up_tk not in feat_text                        # the upcoming one is NOT (only 1 slot)
    # heartbeat exposes the selected current ticker
    assert any("selected_current_tickers" in m and tk in m for m in msgs)
    # the shadow data path reads it as an executable ACTIVE row
    from btc5m.venues.kalshi.paper_runtime import _decision_eligibility, latest_feature_rows
    rows = latest_feature_rows(cfg, series="KXBTC15M", lines=500)
    active = [r for r in rows if r.get("ticker") == tk]
    assert active, "collector-written active row must be visible to the shadow data path"
    pc = cfg.paper_policy
    md = int(getattr(getattr(cfg, "low_latency", None), "market_duration_seconds", 900))
    ok, reasons, flags = _decision_eligibility(active[-1], pc=pc, market_duration_seconds=md,
                                               feature_row_max_age_ms=10_000, now=now_ms())
    assert flags["active_window"] and flags["book_backed"] and flags["start_reference"]


def test_collector_captures_tbd_start_reference_from_underlying_near_open(tmp_path, monkeypatch):
    # Active KXBTC15M payloads can carry "Target price: TBD"; in that case the collector
    # should use a recorded point-in-time underlying sample near window_start, mark it
    # provisional, and make the row executable if the book is otherwise valid.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("TRADING_MODE", "paper")
    now = now_ms()
    open_ms = now - 1_000
    close_ms = now + 899_000

    def _iso(ms):
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    market = {
        "ticker": "KXBTC15M-26JUN041500-00",
        "event_ticker": "KXBTC15M-26JUN041500",
        "title": "BTC price up in next 15 mins?",
        "yes_sub_title": "Target price: TBD",
        "no_sub_title": "Target price: TBD",
        "status": "active",
        "result": "",
        "open_time": _iso(open_ms),
        "close_time": _iso(close_ms),
        "rules_primary": "If the simple average is at least the simple average, then Yes.",
        "_phase": "CURRENT_IN_WINDOW",
        "_open_ms": open_ms,
        "_close_ms": close_ms,
    }
    raw_ob = {"orderbook_fp": {"yes_dollars": [["0.40", "500"]], "no_dollars": [["0.58", "500"]]}}
    monkeypatch.setattr(KalshiClient, "discover", lambda self, **kw: [market])
    monkeypatch.setattr(KalshiClient, "get_orderbook", lambda self, t, **kw: raw_ob)
    monkeypatch.setattr(KalshiClient, "get_market", lambda self, t: market)
    monkeypatch.setattr(collector_mod, "build_underlying_client",
                        lambda name, cfg: _FakeUndAt(name, open_ms + 250, price=72000.0))
    cfg = load_config(mode="paper")

    collector_mod.run_continuous(
        cfg, series="KXBTC15M", sources="coinbase", seconds_per_cycle=0.0, interval=0.0,
        max_markets=1, readiness_every=0, backfill_every=0, max_cycles=1, emit=lambda *_: None)

    import json
    feats = list((tmp_path / "features").glob("kalshi_feature_rows-*.jsonl"))
    rows = [json.loads(l) for p in feats for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    row = next(r for r in rows if r["market_ticker"] == market["ticker"])
    assert row["has_start_reference"] is True
    assert row["reference_start_price"] == 72000.0
    assert row["reference_start_price_source_status"] == "PROVISIONAL_REFERENCE"
    assert row["reference_start_price_method"] == "underlying_nearest_window_start_proxy"
    assert row["reference_start_price_source"].startswith("coinbase")
    assert row["reference_missing_reason"] is None
    assert row["distance_to_start"] == 0.0


def test_one_cycle_writes_ledger_and_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("TRADING_MODE", "paper")
    _patch_clients(monkeypatch)
    cfg = load_config(mode="paper")

    msgs: list[str] = []
    # request deribit too -> must not crash (it is disabled/optional)
    result = collector_mod.run_continuous(
        cfg, series="KXBTC15M", sources="coinbase,binance,deribit",
        seconds_per_cycle=0.0, interval=0.0, max_markets=2,
        readiness_every=1, backfill_every=1, max_cycles=1, emit=msgs.append)

    assert result["cycles"] == 1
    assert result["stopped_reason"] == "max_cycles"
    ledger = list((tmp_path / "paper").glob("kalshi_paper_ledger-*.jsonl"))
    summary = list((tmp_path / "reports" / "paper").glob("kalshi_session_summary-*.md"))
    assert ledger, "collector must write a ledger"
    assert summary, "collector must write a session summary"
    import json
    rows = [json.loads(l) for l in ledger[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert rows and all(r["decision_state"] != "PAPER_CANDIDATE" for r in rows)
    assert all(r["is_paper"] is True for r in rows)
    # rich ledger fields present
    assert "feature_set_version" in rows[0] and "calibration_status" in rows[0]
    # a heartbeat with the safety posture was emitted
    assert any("record-only" in m or "live-disabled" in m for m in msgs)


def test_ctrl_c_stops_cleanly_and_keeps_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    _patch_clients(monkeypatch)

    def _boom(*_a, **_k):
        raise KeyboardInterrupt()

    # force the in-cycle sleep to raise, simulating Ctrl-C mid-collection
    monkeypatch.setattr(collector_mod.time, "sleep", _boom)
    cfg = load_config(mode="paper")
    result = collector_mod.run_continuous(
        cfg, series="KXBTC15M", sources="coinbase",
        seconds_per_cycle=600.0, interval=0.01, max_markets=1,
        readiness_every=0, backfill_every=0, max_cycles=0, emit=lambda *_: None)
    assert result["stopped_reason"] == "ctrl_c"
    # the orderbook recorded before the interrupt is valid JSONL
    norm = list((tmp_path / "normalized").glob("kalshi_orderbook-*.jsonl"))
    assert norm, "data recorded before Ctrl-C must be persisted"
    import json
    for line in norm[0].read_text(encoding="utf-8").splitlines():
        if line.strip():
            json.loads(line)  # must not raise
