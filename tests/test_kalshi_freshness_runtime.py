"""Source-freshness runtime: smoke command, liveness-vs-decision, Binance fallback.

Offline. Verifies the decision-fresh smoke fraction; that feeds can be LIVENESS-fresh
yet DECISION-stale (blocking candidates); and that a fresh Coinbase OR fresh Binance
fallback makes the underlying DECISION-ok. Never enables/loosens anything.
"""

import json
from datetime import datetime, timezone

from btc5m.config import load_config


def _norm(prefix, tmp_path, age_ms, **fields):
    """Write a today-dated normalized row `age_ms` old (recv_ms = now - age_ms)."""
    from btc5m.timeutils import now_ms
    d = tmp_path / "normalized"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    ev = {"source": prefix.replace("underlying_", ""), "recv_ms": now_ms() - age_ms, **fields}
    (d / f"{prefix}-{day}.jsonl").write_text(
        json.dumps({"stream": prefix, "event": ev}) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Smoke command
# --------------------------------------------------------------------------- #
def test_source_freshness_smoke_alive_but_decision_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _norm("kalshi_orderbook", tmp_path, 7_000)              # alive(60s) decision-stale(1s)
    _norm("underlying_coinbase", tmp_path, 33_000, price=70000.0)   # alive decision-stale(5s)
    _norm("underlying_binance_futures", tmp_path, 40_000, best_bid=70010.0)
    from btc5m.venues.kalshi.source_health import source_freshness_smoke
    r = source_freshness_smoke(load_config(mode="paper"), series="KXBTC15M",
                               seconds=0.0, sleep=lambda *_: None)
    assert r["samples"] >= 1
    cb = r["per_source"]["coinbase"]
    assert cb["liveness_fresh_fraction"] == 1.0 and cb["decision_fresh_fraction"] == 0.0
    assert r["underlying_decision_fresh_fraction"] == 0.0
    assert r["verdict"] == "ALIVE_BUT_DECISION_STALE"
    assert "every 1-2s" in r["recommendation"]


def test_source_freshness_smoke_decision_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _norm("kalshi_orderbook", tmp_path, 300)
    _norm("underlying_coinbase", tmp_path, 1_000, price=70000.0)
    _norm("underlying_binance_futures", tmp_path, 1_000, best_bid=70010.0)
    from btc5m.venues.kalshi.source_health import source_freshness_smoke
    r = source_freshness_smoke(load_config(mode="paper"), series="KXBTC15M",
                               seconds=0.0, sleep=lambda *_: None)
    assert r["per_source"]["coinbase"]["decision_fresh_fraction"] == 1.0
    assert r["underlying_decision_fresh_fraction"] == 1.0 and r["verdict"] == "DECISION_FRESH"


# --------------------------------------------------------------------------- #
# Liveness-fresh but decision-stale blocks the decision
# --------------------------------------------------------------------------- #
def test_liveness_fresh_but_decision_stale_blocks_underlying(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _norm("underlying_coinbase", tmp_path, 30_000, price=70000.0)   # 30s: alive, decision-stale
    _norm("underlying_binance_futures", tmp_path, 35_000, best_bid=70010.0)
    from btc5m.venues.kalshi.source_health import assess_source_health
    h = assess_source_health(load_config(mode="paper"))
    by = {s["source"]: s for s in h["sources"]}
    assert by["coinbase"]["liveness_stale"] is False and by["coinbase"]["decision_stale"] is True
    u = h["underlying"]
    assert u["underlying_liveness_ok"] is True              # alive
    assert u["underlying_decision_ok"] is False             # but NOT trade-fresh
    assert u["both_decision_stale"] is True
    # the strict gate (within-row ages = the same) blocks a candidate
    from btc5m.venues.kalshi.freshness import paper_candidate_freshness
    g = paper_candidate_freshness(book_age_ms=300, coinbase_age_ms=30_000,
                                  binance_age_ms=35_000, fcfg=load_config(mode="paper").freshness)
    assert g["ok"] is False and "UNDERLYING_BOTH_STALE" in g["reasons"]


# --------------------------------------------------------------------------- #
# Fresh Coinbase OR Binance fallback -> underlying_decision_ok
# --------------------------------------------------------------------------- #
def test_fresh_coinbase_primary_underlying_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _norm("underlying_coinbase", tmp_path, 1_000, price=70000.0)    # primary fresh
    _norm("underlying_binance_futures", tmp_path, 40_000, best_bid=70010.0)  # stale
    from btc5m.venues.kalshi.source_health import assess_source_health
    u = assess_source_health(load_config(mode="paper"))["underlying"]
    assert u["underlying_decision_ok"] is True
    assert u["reference_source"] == "coinbase" and u["fallback_used"] is False


def test_stale_coinbase_fresh_binance_fallback_underlying_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _norm("underlying_coinbase", tmp_path, 33_000, price=70000.0)   # primary stale
    _norm("underlying_binance_futures", tmp_path, 1_000, best_bid=70010.0)  # fallback fresh
    from btc5m.venues.kalshi.source_health import assess_source_health
    u = assess_source_health(load_config(mode="paper"))["underlying"]
    assert u["underlying_decision_ok"] is True
    assert u["reference_source"] == "binance" and u["fallback_used"] is True


def test_fallback_disabled_stale_coinbase_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("UNDERLYING_ALLOW_BINANCE_FALLBACK", "false")
    _norm("underlying_coinbase", tmp_path, 33_000, price=70000.0)
    _norm("underlying_binance_futures", tmp_path, 1_000, best_bid=70010.0)
    from btc5m.venues.kalshi.source_health import assess_source_health
    u = assess_source_health(load_config(mode="paper"))["underlying"]
    assert u["underlying_decision_ok"] is False and u["fallback_used"] is False
