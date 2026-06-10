"""Tests for the gated decision layer."""

from btc5m.decision import Decision, DecisionConfig, candidate_message, evaluate_candidate


def _row(**kw):
    base = {
        "as_of_ms": 1000, "slug": "btc-updown-5m-1", "condition_id": "0xc",
        "yes_ask": 0.57, "yes_bid": 0.55, "no_ask": 0.45, "no_bid": 0.43,
        "seconds_to_expiry": 120.0, "yes_spread": 0.02, "yes_depth_ask": 500.0,
        "yes_is_crossed": False, "stale_yes_quote": False, "missing_yes_book": False,
        "thin_yes_book": False, "wide_yes_spread": False, "feed_health_ok": True,
        "line_known": True, "line_source_status": "OFFICIAL",
        "distance_from_line": 50.0, "spot_cvd_60s": 1.0,
    }
    base.update(kw)
    return base


def test_paper_candidate_when_edge_fresh_calibrated():
    c = evaluate_candidate(_row(), p_yes=0.66, calibrated=True,
                           line_source_status="OFFICIAL", label_source_status="OFFICIAL")
    # raw edge 0.66-0.57=0.09; net 0.09-0.02=0.07 >= 0.03
    assert c["decision"] == Decision.PAPER_CANDIDATE.value
    assert c["side"] == "BUY_YES"
    assert c["net_edge"] > 0.03
    assert "PAPER_CANDIDATE" in candidate_message(c)


def test_no_action_when_edge_too_small():
    c = evaluate_candidate(_row(), p_yes=0.58, calibrated=True)
    # raw 0.01; net negative -> NO_ACTION
    assert c["decision"] in (Decision.NO_ACTION.value, Decision.WATCH.value)


def test_watch_when_stale():
    c = evaluate_candidate(_row(stale_yes_quote=True, feed_health_ok=False),
                           p_yes=0.66, calibrated=True)
    assert c["decision"] == Decision.WATCH.value
    assert "stale_quote_or_bad_feed" in c["reason_codes"]


def test_watch_when_uncalibrated():
    c = evaluate_candidate(_row(), p_yes=0.66, calibrated=False)
    assert c["decision"] == Decision.WATCH.value
    assert "model_uncalibrated" in c["reason_codes"]


def test_manual_review_when_line_unknown():
    c = evaluate_candidate(_row(line_known=False, line_source_status="UNKNOWN"),
                           p_yes=0.66, calibrated=True, line_source_status="UNKNOWN")
    assert c["decision"] == Decision.MANUAL_REVIEW.value
    assert "line_unknown" in c["reason_codes"]


def test_no_action_when_no_price():
    c = evaluate_candidate(_row(yes_ask=None, no_ask=None), p_yes=0.66, calibrated=True)
    assert c["decision"] == Decision.NO_ACTION.value
    assert "no_executable_price" in c["reason_codes"]


def test_never_live_by_default():
    # Even a perfect setup never yields LIVE unless allow_live=True.
    c = evaluate_candidate(_row(), p_yes=0.80, calibrated=True, line_source_status="OFFICIAL")
    assert c["decision"] != Decision.LIVE_CANDIDATE.value


def test_live_candidate_only_when_explicitly_allowed():
    cfg = DecisionConfig(allow_live=True)
    c = evaluate_candidate(_row(), p_yes=0.80, calibrated=True,
                           line_source_status="OFFICIAL", cfg=cfg)
    assert c["decision"] == Decision.LIVE_CANDIDATE.value
    # but provisional line must NOT reach live
    c2 = evaluate_candidate(_row(line_source_status="PROVISIONAL_REFERENCE"),
                            p_yes=0.80, calibrated=True,
                            line_source_status="PROVISIONAL_REFERENCE", cfg=cfg)
    assert c2["decision"] != Decision.LIVE_CANDIDATE.value


def test_provisional_line_flagged_but_paper_ok():
    c = evaluate_candidate(_row(line_source_status="PROVISIONAL_REFERENCE"),
                           p_yes=0.66, calibrated=True,
                           line_source_status="PROVISIONAL_REFERENCE")
    assert "provisional_line" in c["reason_codes"]
    assert c["decision"] == Decision.PAPER_CANDIDATE.value  # paper allowed
