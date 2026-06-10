"""Offline end-to-end test of the paper decision pipeline + session + backtest."""

import json
from datetime import datetime, timezone

from btc5m.backtest.paper_backtest import run_paper_backtest
from btc5m.config import load_config
from btc5m.paper.pipeline import run_paper_decisions
from btc5m.paper.session import render_session_summary, write_session_summary


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00"))
               .replace(tzinfo=timezone.utc).timestamp() * 1000)


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _seed_dataset(tmp_path):
    start_ms = _ms("2026-05-31T07:30:00Z")
    expiry_ms = _ms("2026-05-31T07:35:00Z")
    as_of = start_ms + 60_000          # 1 min into the window -> ~240s to expiry
    slug = "btc-updown-5m-1780212600"
    cond = "0xcond"
    market = {
        "id": "1", "conditionId": cond, "slug": slug,
        "question": "Bitcoin Up or Down", "endDate": "2026-05-31T07:35:00Z",
        "eventStartTime": "2026-05-31T07:30:00Z",
        "outcomes": '["Up","Down"]', "clobTokenIds": '["yes_tok","no_tok"]',
        "description": "resolve Up if end >= start", "closed": False,
        "orderPriceMinTickSize": 0.01, "orderMinSize": 5,
    }
    _write_jsonl(tmp_path / "raw" / "polymarket_markets-20260531.jsonl",
                 [{"stream": "polymarket_markets", "payload": market}])

    # Cheap YES ask (0.45) with deep book -> positive edge vs model.
    yes_ev = {"slug": slug, "condition_id": cond, "outcome": "YES",
              "ts_ms": as_of, "recv_ms": as_of, "best_bid": 0.44, "best_ask": 0.45,
              "spread": 0.01, "is_crossed": False,
              "bids": [[0.44, 500]], "asks": [[0.45, 500], [0.46, 500]]}
    no_ev = {"slug": slug, "condition_id": cond, "outcome": "NO",
             "ts_ms": as_of, "recv_ms": as_of, "best_bid": 0.54, "best_ask": 0.55,
             "spread": 0.01, "is_crossed": False,
             "bids": [[0.54, 500]], "asks": [[0.55, 500]]}
    _write_jsonl(tmp_path / "normalized" / "polymarket_book-20260531.jsonl",
                 [{"stream": "polymarket_book", "event": yes_ev},
                  {"stream": "polymarket_book", "event": no_ev}])

    # Underlying: reference price 73800 (> line 73750) before as_of.
    und = [{"stream": "underlying_coinbase", "event": {
        "source": "coinbase", "symbol": "BTC-USD", "event_type": "ticker",
        "exchange_ts_ms": as_of - 30_000, "recv_ms": as_of - 30_000,
        "price": 73800.0, "best_bid": 73799.5, "best_ask": 73800.5, "spread": 1.0}}]
    _write_jsonl(tmp_path / "normalized" / "underlying_coinbase-20260531.jsonl", und)

    # Provisional line below reference -> model leans YES.
    line = {"slug": slug, "condition_id": cond, "market_id": "1",
            "window_start_ms": start_ms, "expiry_ms": expiry_ms, "line_price": 73750.0,
            "line_source": "coinbase:BTC-USD", "line_source_status": "PROVISIONAL_REFERENCE",
            "line_captured_at_ms": start_ms, "comparison": "GTE"}
    _write_jsonl(tmp_path / "normalized" / "settlement_lines-20260531.jsonl",
                 [{"stream": "settlement_lines", "event": line}])

    # OFFICIAL label: Up resolved (1) -> known outcome for realized pnl.
    label = {"slug": slug, "condition_id": cond, "window_start_ms": start_ms,
             "expiry_ms": expiry_ms, "line_price": 73750.0, "final_reference_price": 73810.0,
             "settlement_distance": 60.0, "label_yes_resolved": 1, "official_outcome": 1,
             "comparison": "GTE", "reason_code": "OK", "label_source_status": "OFFICIAL",
             "created_at_ms": expiry_ms}
    _write_jsonl(tmp_path / "labels" / "settlement_labels-20260531.jsonl", [label])
    return slug


def _cfg(tmp_path):
    cfg = load_config(mode="paper")
    cfg.data_dir = str(tmp_path)
    cfg.reports_dir = str(tmp_path / "reports")
    return cfg


def test_pipeline_emits_paper_candidate_and_fill(tmp_path):
    _seed_dataset(tmp_path)
    cfg = _cfg(tmp_path)
    entries, stats = run_paper_decisions(
        cfg, asset="BTC", duration="5m", allow_uncalibrated=True,
        sigma_override=0.0003, requested_size=10.0,
    )
    cand = [e for e in entries if e.decision == "PAPER_CANDIDATE"]
    assert cand, f"expected a PAPER_CANDIDATE; got {[e.decision for e in entries]}"
    e = cand[0]
    assert e.side == "BUY_YES"
    assert e.executable_price == 0.45          # YES ask, never midpoint
    assert e.fill_status in ("filled", "simulated")
    assert e.sim_price == 0.45 and e.sim_size == 10.0
    assert e.known_outcome == 1
    assert abs(e.realized_pnl - (1 - 0.45) * 10) < 1e-6   # +5.5 paper
    assert e.is_paper is True


def test_session_summary_renders_and_writes(tmp_path):
    session = {
        "data": {"markets_seen": 1, "book_snapshots": 2, "underlying_events": 1,
                 "line_records": 1, "label_rows": 1, "feature_rows": 2},
        "decisions_by_state": {"PAPER_CANDIDATE": 1}, "paper_candidates": 1,
        "fills": 1, "rejections": 0, "ledger_entries": 1, "ledger_file": "x.jsonl",
        "readiness": {"completed_windows": 1, "official_labels": 1, "provisional_labels": 0,
                      "manual_review": 0, "usable_labeled_rows": 1,
                      "training_allowed": False, "backtest_allowed": False},
        "safety": {"trading_mode": "paper", "live_trading_enabled": False,
                   "kill_switch_enabled": True, "live_permitted": False,
                   "notifier": "NoopNotifier", "chainlink_configured": False},
        "blockers": ["insufficient data"], "next_actions": ["a", "b", "c"],
    }
    text = render_session_summary(session, ref_ms=_ms("2026-05-31T00:00:00Z"))
    assert "paper session summary" in text
    assert "No live orders placed" in text
    assert "PAPER_CANDIDATE" in text
    cfg = _cfg(tmp_path)
    path = write_session_summary(cfg, session, ref_ms=_ms("2026-05-31T00:00:00Z"))
    assert path.exists()


def test_backtest_blocked_on_sparse_data(tmp_path):
    _seed_dataset(tmp_path)
    cfg = _cfg(tmp_path)
    result = run_paper_backtest(cfg, asset="BTC", duration="5m")
    assert result["status"] == "blocked"      # never fabricates P&L
    assert "have_usable_labeled_rows" in result
