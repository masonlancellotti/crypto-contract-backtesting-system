"""Kalshi training dry-run (offline): joins, purge/embargo, reports, REFUSES.

Must block below the distinct-window threshold, never train, never use
underlying-only rows as executable examples, and report column missingness.
"""

import json

from btc5m.config import load_config
from btc5m.venues.kalshi.train_prep import train_dry_run


def _write(tmp_path, feature_rows, label_rows):
    feats = tmp_path / "features"
    labels = tmp_path / "labels"
    feats.mkdir(parents=True)
    labels.mkdir(parents=True)
    (feats / "kalshi_feature_rows-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in feature_rows) + "\n", encoding="utf-8")
    (labels / "kalshi_settlement_labels-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in label_rows) + "\n", encoding="utf-8")


def _frow(tk, *, as_of, close, ob=True, und=True, secs=120, book_ok=True, **extra):
    row = {"market_ticker": tk, "has_orderbook": ob, "has_underlying": und,
           "has_start_reference": True, "seconds_to_close": secs, "book_ok": book_ok,
           "reference_price": 100.0, "as_of_ms": as_of, "close_ms": close,
           "yes_ask": 0.42, "no_ask": 0.60}
    row.update(extra)
    return row


def _label(tk, yes=1):
    return {"market_ticker": tk, "label_source_status": "OFFICIAL", "label_yes_resolved": yes}


def test_dry_run_blocks_below_threshold_and_does_not_train(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    base = 1_780_000_000_000
    feats = []
    for w in range(3):  # 3 windows, far below the 60/150 gates
        close = base + w * 15 * 60 * 1000 + 15 * 60 * 1000
        for i in range(5):
            feats.append(_frow(f"KX-{w}", as_of=close - (300 - i) * 1000, close=close))
    labels = [_label(f"KX-{w}", yes=w % 2) for w in range(3)]
    _write(tmp_path, feats, labels)
    cfg = load_config(mode="paper")

    r = train_dry_run(cfg, series="KXBTC15M")
    assert r["trained"] is False
    assert r["train_allowed"] is False
    assert r["backtest_allowed"] is False
    assert r["gate_windows"] == 3
    assert r["training_eligible_rows"] == 15
    assert any("threshold" in b for b in r["blockers"])
    assert "yes_ask" in r["column_missingness"]
    assert r["purge_embargo"]["applied"] is True
    assert "YES" in r["label_balance"] or "NO" in r["label_balance"]


def test_dry_run_excludes_underlying_only_and_unusable_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    base = 1_780_000_000_000
    close = base + 15 * 60 * 1000
    feats = [
        _frow("KX-A", as_of=close - 100_000, close=close),          # usable
        _frow("KX-A", as_of=close - 50_000, close=close),           # usable
        _frow("KX-A", as_of=close + 10_000, close=close, secs=-5),  # post-close -> excluded
        _frow("KX-A", as_of=close - 40_000, close=close, ob=False), # underlying-only -> excluded
    ]
    _write(tmp_path, feats, [_label("KX-A")])
    cfg = load_config(mode="paper")
    r = train_dry_run(cfg, series="KXBTC15M")
    assert r["gate_windows"] == 1
    assert r["training_eligible_rows"] == 2   # only the two usable executable rows


def test_dry_run_via_cli_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_MODE", "paper")
    _write(tmp_path, [_frow("KX-A", as_of=1, close=2)], [_label("KX-A")])
    from btc5m.cli import main
    assert main(["kalshi-train-dry-run", "--series", "KXBTC15M"]) == 0
