"""Refined source-health staleness + compacted-label orphan exclusion (offline).

- A stale Coinbase feed is reported clearly (stale flag + reason + threshold) and
  Binance is offered as the spot fallback.
- The compacted training-labels file contains ONLY gate-eligible official labels
  (orphans excluded); raw files are never touched; Deribit disabled is harmless.
"""

import json

from btc5m.config import load_config
from btc5m.timeutils import now_ms
from btc5m.venues.kalshi.labels_audit import compact_labels
from btc5m.venues.kalshi.source_health import assess_source_health


def _norm(prefix, tmp_path, recv_ms, **fields):
    d = tmp_path / "normalized"
    d.mkdir(parents=True, exist_ok=True)
    ev = {"source": prefix.replace("underlying_", ""), "recv_ms": recv_ms, **fields}
    (d / f"{prefix}-20260602.jsonl").write_text(
        json.dumps({"stream": prefix, "event": ev}) + "\n", encoding="utf-8")


def test_stale_coinbase_reported_and_binance_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    now = now_ms()
    _norm("underlying_coinbase", tmp_path, now - 90_000, price=70000.0)   # 90s old -> stale
    _norm("underlying_binance_futures", tmp_path, now - 1_000, best_bid=70010.0)  # fresh
    cfg = load_config(mode="paper")
    h = assess_source_health(cfg)
    by = {s["source"]: s for s in h["sources"]}
    # LIVENESS: coinbase 90s old -> liveness-stale (>60s); binance fresh.
    assert by["coinbase"]["stale"] is True and by["coinbase"]["liveness_stale"] is True
    assert "liveness_threshold" in (by["coinbase"]["stale_reason"] or "")
    assert by["coinbase"]["stale_threshold_ms"] == 60_000
    assert by["binance"]["stale"] is False and by["binance"]["liveness_stale"] is False
    assert by["binance"]["can_serve_as_spot_fallback"] is True
    # DECISION freshness: coinbase decision-stale; binance decision-fresh -> fallback.
    assert by["coinbase"]["decision_stale"] is True and by["coinbase"]["fresh_for_paper_candidate"] is False
    assert by["binance"]["decision_stale"] is False and by["binance"]["fresh_for_paper_candidate"] is True
    u = h["underlying"]
    assert u["underlying_ok"] is True                      # liveness group (binance alive)
    assert u["underlying_decision_ok"] is True             # decision-fresh via fallback
    assert u["fallback_used"] is True and u["reference_source"] == "binance"
    assert "Binance" in u["recommendation"]


def test_kalshi_required_for_features():
    cfg = load_config(mode="paper")
    h = assess_source_health(cfg)
    by = {s["source"]: s for s in h["sources"]}
    assert by["kalshi"]["required_for_feature_generation"] is True
    assert by["coinbase"]["required_for_feature_generation"] is False
    assert by["deribit"]["enabled"] is False  # disabled does not break assessment


def test_compacted_training_file_excludes_orphans(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    labels = tmp_path / "labels"
    feats = tmp_path / "features"
    labels.mkdir(parents=True)
    feats.mkdir(parents=True)
    # A = gate-eligible (usable feature row); B = orphan official (no features)
    label_rows = [
        {"market_ticker": "A", "label_source_status": "OFFICIAL", "label_yes_resolved": 1},
        {"market_ticker": "B", "label_source_status": "OFFICIAL", "label_yes_resolved": 0},
    ]
    (labels / "kalshi_settlement_labels-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in label_rows) + "\n", encoding="utf-8")
    (feats / "kalshi_feature_rows-20260602.jsonl").write_text(
        json.dumps({"market_ticker": "A", "has_orderbook": True, "has_underlying": True,
                    "seconds_to_close": 120, "book_ok": True}) + "\n", encoding="utf-8")
    cfg = load_config(mode="paper")
    r = compact_labels(cfg, write=True)

    assert r["gate_windows"] == 1
    assert r["orphan_official_labels"] == 1
    assert r["raw_label_files_preserved"] is True
    # raw untouched
    raw = labels / "kalshi_settlement_labels-20260602.jsonl"
    assert len(raw.read_text(encoding="utf-8").splitlines()) == 2
    # training-labels file holds ONLY the gate-eligible A (orphan B excluded)
    training = labels / r["training_labels_file"].split("\\")[-1].split("/")[-1]
    tickers = [json.loads(l)["market_ticker"]
               for l in training.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert tickers == ["A"]
    # full compacted file has both, with gate_eligible flags
    compacted = labels / r["compacted_file"].split("\\")[-1].split("/")[-1]
    rows = {json.loads(l)["market_ticker"]: json.loads(l)
            for l in compacted.read_text(encoding="utf-8").splitlines() if l.strip()}
    assert rows["A"]["gate_eligible"] is True
    assert rows["B"]["gate_eligible"] is False and rows["B"]["is_orphan"] is True
