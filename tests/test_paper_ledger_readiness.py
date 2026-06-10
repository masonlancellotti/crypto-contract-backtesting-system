"""Tests for the paper ledger and data-readiness gating (offline)."""

from btc5m.backtest.paper_backtest import aggregate_paper_pnl
from btc5m.config import load_config
from btc5m.paper.ledger import LedgerEntry, PaperLedger, load_ledger
from btc5m.paper.readiness import assess_readiness, dedupe_label_rows


def test_ledger_write_and_load(tmp_path):
    cfg = load_config(mode="paper")
    cfg.data_dir = str(tmp_path)
    led = PaperLedger(cfg)
    e = LedgerEntry(
        timestamp_ms=1000, slug="btc-updown-5m-1", condition_id="0xc", side="BUY_YES",
        decision="PAPER_CANDIDATE", model_yes_probability=0.66, executable_price=0.57,
        estimated_costs=0.02, net_edge=0.07, reason_codes=["model_prob_above_yes_ask"],
        line_source_status="OFFICIAL", label_source_status="OFFICIAL",
        fill_status="filled", sim_price=0.57, sim_size=100.0, fees=0.0,
        known_outcome=1, realized_pnl=43.0,
    )
    assert led.write([e], ref_ms=1000) == 1
    loaded = load_ledger(tmp_path / "paper")
    assert len(loaded) == 1
    assert loaded[0]["executable_price"] == 0.57   # ask, never midpoint
    assert loaded[0]["is_paper"] is True
    assert loaded[0]["realized_pnl"] == 43.0


def test_readiness_blocks_when_sparse():
    feats = [
        {"slug": "s1", "line_known": True, "reference_price": 73800.0,
         "feed_health_ok": True, "seconds_to_expiry": 120.0},
        {"slug": "s2", "line_known": False, "reference_price": None,
         "feed_health_ok": True, "seconds_to_expiry": 120.0},
    ]
    labels = [{"slug": "s1", "label_source_status": "OFFICIAL", "official_outcome": 1}]
    r = assess_readiness(feats, labels)
    assert r["usable_rows"] == 1
    assert r["usable_labeled_rows"] == 1
    assert r["missing_fields"].get("no_line") == 1
    assert r["training_allowed"] is False        # 1 << 500
    assert r["backtest_allowed"] is False


def test_readiness_allows_with_enough_official_rows():
    feats = [
        {"slug": f"s{i}", "line_known": True, "reference_price": 1.0,
         "feed_health_ok": True, "seconds_to_expiry": 100.0}
        for i in range(600)
    ]
    labels = [{"slug": f"s{i}", "label_source_status": "OFFICIAL", "official_outcome": i % 2}
              for i in range(600)]
    r = assess_readiness(feats, labels, min_train_rows=500, min_backtest_rows=200)
    assert r["usable_labeled_rows"] == 600
    assert r["training_allowed"] is True
    assert r["backtest_allowed"] is True


def test_dedupe_prefers_official():
    rows = [
        {"slug": "s1", "label_source_status": "UNKNOWN", "created_at_ms": 5},
        {"slug": "s1", "label_source_status": "OFFICIAL", "official_outcome": 1, "created_at_ms": 1},
        {"slug": "s1", "label_source_status": "UNKNOWN", "created_at_ms": 9},
    ]
    out = dedupe_label_rows(rows)
    assert len(out) == 1
    assert out[0]["label_source_status"] == "OFFICIAL"


def test_aggregate_paper_pnl_one_per_slug():
    entries = [
        {"decision": "PAPER_CANDIDATE", "fill_status": "filled", "slug": "s1",
         "realized_pnl": 10.0, "known_outcome": 1, "fees": 0.0},
        {"decision": "PAPER_CANDIDATE", "fill_status": "filled", "slug": "s1",
         "realized_pnl": -5.0, "known_outcome": 1, "fees": 0.0},   # same slug -> ignored
        {"decision": "PAPER_CANDIDATE", "fill_status": "filled", "slug": "s2",
         "realized_pnl": -3.0, "known_outcome": 0, "fees": 0.0},
        {"decision": "WATCH", "fill_status": "not_traded", "slug": "s3"},  # not a fill
    ]
    agg = aggregate_paper_pnl(entries)
    assert agg["paper_simulation"] is True
    assert agg["n_trades"] == 2               # one per slug
    assert agg["net_pnl_paper"] == 7.0
    assert 0.0 <= agg["hit_rate"] <= 1.0


def test_aggregate_paper_pnl_empty():
    assert aggregate_paper_pnl([])["n_trades"] == 0
