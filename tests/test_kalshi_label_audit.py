"""Kalshi label audit + orphan compaction (offline).

Orphan official labels (no feature rows) must be detected and excluded from the
gate counts; dedup must prefer OFFICIAL over weaker statuses and the latest row
on ties; MANUAL_REVIEW must never count as a clean training label; compaction
must write a SEPARATE file and never touch the raw label files.
"""

import json

from btc5m.config import load_config
from btc5m.venues.kalshi.labels_audit import audit_labels, compact_labels, dedup_labels


def _lrow(tk, status, yes, created):
    return {"market_ticker": tk, "label_source_status": status,
            "label_yes_resolved": yes, "created_at_ms": created}


def test_orphan_detection_and_gate_counts():
    labels = [
        _lrow("A", "OFFICIAL", 1, 100),   # feature-backed
        _lrow("B", "OFFICIAL", 0, 100),   # ORPHAN (no features)
        _lrow("C", "PROVISIONAL_REFERENCE", 1, 100),
        _lrow("D", "MANUAL_REVIEW", 0, 100),
    ]
    feature_tickers = {"A"}  # only A has feature rows
    r = audit_labels(labels, feature_tickers)
    assert r["official_labels"] == 2
    assert r["official_feature_backed_labels"] == 1     # only A
    assert r["orphan_official_labels"] == 1             # B
    assert r["manual_review_labels"] == 1
    assert r["backtest_gate_count"] == 1               # feature-backed only
    assert r["backtest_allowed"] is False
    assert r["train_allowed"] is False


def test_dedup_prefers_official_then_latest():
    rows = [
        _lrow("A", "PROVISIONAL_REFERENCE", 1, 100),
        _lrow("A", "OFFICIAL", 0, 50),     # OFFICIAL wins despite older ts
        _lrow("B", "OFFICIAL", 1, 100),
        _lrow("B", "OFFICIAL", 0, 200),    # latest wins on equal status
    ]
    deduped = dedup_labels(rows)
    assert deduped["A"]["label_source_status"] == "OFFICIAL"
    assert deduped["A"]["label_yes_resolved"] == 0
    assert deduped["B"]["label_yes_resolved"] == 0       # the created=200 row
    r = audit_labels(rows, {"A", "B"})
    assert r["duplicate_label_rows"] == 2                # 4 rows -> 2 tickers


def test_compact_writes_separate_file_and_preserves_raw(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = load_config(mode="paper")
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir(parents=True)
    raw = labels_dir / "kalshi_settlement_labels-20260601.jsonl"
    rows = [_lrow("A", "OFFICIAL", 1, 100), _lrow("B", "OFFICIAL", 0, 100)]
    raw.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    # feature row only for A
    feats_dir = tmp_path / "features"
    feats_dir.mkdir(parents=True)
    (feats_dir / "kalshi_feature_rows-20260601.jsonl").write_text(
        json.dumps({"market_ticker": "A"}) + "\n", encoding="utf-8")

    report = compact_labels(cfg, write=True)
    assert report["raw_label_files_preserved"] is True
    assert report["orphan_official_labels"] == 1
    # raw untouched
    assert raw.exists() and len(raw.read_text(encoding="utf-8").splitlines()) == 2
    # compacted file written separately, B tagged orphan
    compacted = list(labels_dir.glob("kalshi_settlement_labels_compacted-*.jsonl"))
    assert compacted, "compaction must write a separate compacted file"
    out = {json.loads(l)["market_ticker"]: json.loads(l)
           for l in compacted[0].read_text(encoding="utf-8").splitlines()}
    assert out["B"]["is_orphan"] is True
    assert out["A"]["is_orphan"] is False


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = load_config(mode="paper")
    (tmp_path / "labels").mkdir(parents=True)
    (tmp_path / "labels" / "kalshi_settlement_labels-20260601.jsonl").write_text(
        json.dumps(_lrow("A", "OFFICIAL", 1, 100)) + "\n", encoding="utf-8")
    report = compact_labels(cfg, write=False)
    assert report["compacted_file"] is None
    assert not list((tmp_path / "labels").glob("*compacted*"))
