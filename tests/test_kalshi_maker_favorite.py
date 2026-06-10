"""Tests for maker-entry date filtering (Part A) and the deep-favorite
validation report + verdict tiers (Parts B/C). Offline.
"""

import json

from btc5m.config import load_config
from btc5m.venues.kalshi import maker_entry as me

DAY1_START = 1_780_300_800_000   # 2026-06-01 00:00:00 UTC
DAY2_START = DAY1_START + 86_400_000   # 2026-06-02


def _snap(t_ms, yes_bid, yes_ask, no_bid, no_ask, ticker, window_start, close):
    return {"stream": "kalshi_orderbook", "event": {
        "venue": "kalshi", "series_ticker": "KXBTC15M", "market_ticker": ticker,
        "window_start_ms": window_start, "close_ms": close, "recv_ms": t_ms,
        "status": "active", "yes_bid": yes_bid, "yes_ask": yes_ask,
        "no_bid": no_bid, "no_ask": no_ask, "yes_bid_size": 100.0,
        "yes_ask_size": 100.0, "no_bid_size": 100.0, "no_ask_size": 100.0,
        "book_validity_flags": {"yes_side_present": True, "no_side_present": True,
                                "incomplete_book": False, "yes_crossed": False,
                                "no_crossed": False, "prices_in_range": True}}}


def _label(ticker, window_start, close, y=1):
    return {"venue": "kalshi", "series_ticker": "KXBTC15M", "market_ticker": ticker,
            "window_start_ms": window_start, "close_ms": close,
            "official_result": "yes" if y else "no", "label_yes_resolved": y,
            "label_source_status": "OFFICIAL"}


def _print_row(ts_ms, yes_price, taker_side, ticker, tid):
    return {"stream": "kalshi_trades", "event": {
        "market_ticker": ticker, "trade_id": tid, "created_time_ms": ts_ms,
        "yes_price": yes_price, "no_price": round(1.0 - yes_price, 4),
        "count": 10.0, "taker_side": taker_side}}


def _two_day_env(tmp_path, monkeypatch, *, yes_bid=0.85, yes_ask=0.87):
    """One labeled window per day (June 1 + June 2), each with books + prints."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    nd = tmp_path / "data" / "normalized"
    ld = tmp_path / "data" / "labels"
    nd.mkdir(parents=True)
    ld.mkdir(parents=True)
    snaps, labels, prints = [], [], []
    for i, day_start in enumerate((DAY1_START, DAY2_START)):
        tk = f"KXBTC15M-26JUN0{i + 1}1830-30"
        w0, w1 = day_start + 3_600_000, day_start + 3_600_000 + 900_000
        snaps.append(_snap(w0 + 10_000, yes_bid, yes_ask, round(1 - yes_ask, 2),
                           round(1 - yes_bid, 2), tk, w0, w1))
        labels.append(_label(tk, w0, w1, y=1))
        # tape trades through the YES bid (taker bought NO below the limit)
        prints.append(_print_row(w0 + 30_000, yes_bid - 0.02, "no", tk, f"t{i}"))
    (nd / "kalshi_orderbook-20260601.jsonl").write_text(
        "\n".join(json.dumps(s) for s in snaps) + "\n", encoding="utf-8")
    (ld / "kalshi_settlement_labels-20260601.jsonl").write_text(
        "\n".join(json.dumps(lb) for lb in labels) + "\n", encoding="utf-8")
    (nd / "kalshi_trades-20260601.jsonl").write_text(
        "\n".join(json.dumps(p) for p in prints) + "\n", encoding="utf-8")
    return load_config()


# --------------------------------------------------------------------------- #
# Part A — date filtering
# --------------------------------------------------------------------------- #
def test_date_filters_change_the_sample(tmp_path, monkeypatch):
    cfg = _two_day_env(tmp_path, monkeypatch)
    full = me.simulate_maker_entries(cfg, fill_model="prints-through")
    assert full["date_filter"]["windows_before_filter"] == 2
    assert full["date_filter"]["windows_after_filter"] == 2
    assert full["n_windows_with_label_and_books"] == 2

    fwd = me.simulate_maker_entries(cfg, fill_model="prints-through",
                                    start_date="20260602")
    assert fwd["date_filter"]["windows_before_filter"] == 2
    assert fwd["date_filter"]["windows_after_filter"] == 1
    assert fwd["n_windows_with_label_and_books"] == 1
    assert len(fwd["decisions"]) < len(full["decisions"])

    until = me.simulate_maker_entries(cfg, fill_model="prints-through",
                                      end_date="20260601")
    assert until["date_filter"]["windows_after_filter"] == 1
    only_day = {d["day"] for d in until["decisions"]}
    assert only_day == {"2026-06-01"}


def test_empty_range_blocks_clearly(tmp_path, monkeypatch):
    cfg = _two_day_env(tmp_path, monkeypatch)
    r = me.run_maker_entry_study(cfg, fill_model="prints-through",
                                 start_date="20270101")
    assert r["status"] == "BLOCKED_NO_DATA_IN_RANGE"
    assert r["blockers"]
    assert r["live_submission_allowed"] is False
    assert not (tmp_path / "reports" / "maker").exists()   # no misleading report


def test_run_study_reports_date_range(tmp_path, monkeypatch):
    cfg = _two_day_env(tmp_path, monkeypatch)
    r = me.run_maker_entry_study(cfg, fill_model="prints-through",
                                 start_date="20260601", end_date="20260602")
    assert r["status"] == "OK"
    assert r["date_filter"]["start_date"] == "20260601"
    md = next(p for p in (tmp_path / "reports" / "maker").iterdir()
              if p.suffix == ".md")
    text = md.read_text(encoding="utf-8")
    assert "start=20260601" in text and "end=20260602" in text
    assert "windows before/after filter: 2/2" in text


# --------------------------------------------------------------------------- #
# Part C — verdict tiers
# --------------------------------------------------------------------------- #
def _verdict(**over):
    base = dict(through_full_ev=2.0, front_full_ev=3.0, through_fwd_ev=2.0,
                front_fwd_ev=3.0, through_fwd_ev_stress=0.5, fwd_fills=150,
                fwd_windows=80, fwd_days=6, fwd_positive_days=5,
                top_day_fill_share=0.2, top_window_fill_share=0.05)
    base.update(over)
    return me.favorite_verdict(**base)


def test_verdict_dead_when_both_models_negative():
    assert _verdict(through_full_ev=-1.0, front_full_ev=-0.5)["verdict"] == "dead"


def test_verdict_dead_when_concentrated():
    assert _verdict(top_day_fill_share=0.9)["verdict"] == "dead"
    assert _verdict(top_window_fill_share=0.5)["verdict"] == "dead"


def test_verdict_dead_when_forward_negative_with_adequate_sample():
    assert _verdict(through_fwd_ev=-1.0, front_fwd_ev=-0.5)["verdict"] == "dead"


def test_verdict_needs_more_forward_data_when_sample_small():
    assert _verdict(fwd_fills=10, fwd_days=1, fwd_windows=5)["verdict"] == \
        "needs_more_forward_data"
    # forward not positive yet but front still positive -> wait, not dead
    assert _verdict(through_fwd_ev=-0.2, front_fwd_ev=0.4)["verdict"] == \
        "needs_more_forward_data"


def test_verdict_research_lead_below_shadow_thresholds():
    assert _verdict(fwd_fills=60)["verdict"] == "research_lead"
    assert _verdict(through_fwd_ev_stress=-0.1)["verdict"] == "research_lead"
    assert _verdict(fwd_positive_days=2)["verdict"] == "research_lead"


def test_verdict_shadow_candidate_later_only_when_strong():
    v = _verdict()
    assert v["verdict"] == "shadow_candidate_later"
    # and it must never be a paper/live recommendation
    assert "paper" not in " ".join(v["reasons"]).lower()


# --------------------------------------------------------------------------- #
# Part B — favorite report end-to-end
# --------------------------------------------------------------------------- #
def test_favorite_report_end_to_end(tmp_path, monkeypatch):
    cfg = _two_day_env(tmp_path, monkeypatch, yes_bid=0.85, yes_ask=0.87)
    r = me.run_maker_favorite_report(cfg, start_date="20260602")
    assert r["status"] == "OK"
    assert r["live_submission_allowed"] is False
    b = r["buckets"]["YES/[80c,90c)"]
    full = b["cohorts"]["prints-through|full|fee0.00"]
    fwd = b["cohorts"]["prints-through|forward|fee0.00"]
    assert full["fills"] == 2 and fwd["fills"] == 1     # forward = June 2 only
    # fee stress strictly reduces EV
    stress = b["cohorts"]["prints-through|full|fee0.07"]
    assert stress["maker_ev_cents_per_fill"] < full["maker_ev_cents_per_fill"]
    # tiny sample -> never shadow_candidate_later
    assert b["verdict"]["verdict"] in ("dead", "needs_more_forward_data")
    text = open(r["report_file"], encoding="utf-8").read()
    assert "verdict" in text and "Never recommends paper/live" not in text.lower()
    assert "live_submission_allowed=false" in text


def test_favorite_report_cli_registration():
    from btc5m import cli
    assert "kalshi-maker-favorite-report" in cli._COMMANDS
