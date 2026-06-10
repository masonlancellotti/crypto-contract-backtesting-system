"""Staged calibrator replacement + window-based reliability (report-only).

Covers window-based reliability buckets (distinct-window Wilson, wider than row), the
promoted-backbone context, staged-only replacement candidates with rich metadata, the
promotion-review eligibility logic (mark only), the candidate cohort mapping, the config
reliability_unit flag, and the safety invariants (no promotion, no manifest change,
live/paper disabled). Offline; nothing promoted.
"""

from pathlib import Path

import pytest

from btc5m.config import load_config
from btc5m.venues.kalshi import calibrator_replacement as cr
from btc5m.venues.kalshi.uncertainty import build_calibration_buckets, build_window_calibration_buckets


def _fake_prep():
    """A _prepare_runtime-shaped context: 20 mixed-outcome windows; model over-predicts YES."""
    specs = ([("A", w, 0.50, 1 if w < 5 else 0) for w in range(10)]
             + [("B", w, 0.20, 1 if w < 2 else 0) for w in range(10)])
    rows = []
    for gi, (g, w, mp, label) in enumerate(specs):
        ya, na = mp, round(1.0 - mp, 2)
        for _ in range(3):
            i = len(rows)
            rows.append({"ticker": f"{g}{w}", "as_of_ts_ms": 1000 + i, "label_yes_resolved": label,
                         "model_probability_yes": min(0.99, mp + 0.15),       # raw over-predicts YES
                         "calibrated_probability_yes": min(0.99, mp + 0.25),  # isotonic over-predicts MORE
                         "yes_ask": ya, "no_ask": na, "book_ok": True, "seconds_to_close": 300,
                         "reference_start_price": 100.0, "yes_ask_size": 10, "no_ask_size": 10,
                         "market_close_ts_ms": 900000 + gi, "series": "KXBTC15M", "row_id": f"{g}{w}@{i}"})
    return {"dataset_rows": rows, "buckets": []}


# --------------------------------------------------------------------------- #
# Part C — window-based reliability buckets
# --------------------------------------------------------------------------- #
def test_window_buckets_use_distinct_windows_and_are_wider():
    p = [0.75] * 10
    y = [1] * 8 + [0, 0]
    tickers = ["A"] * 8 + ["B", "C"]            # 3 distinct windows; A dominates rows
    row = build_calibration_buckets(y, p)
    win = build_window_calibration_buckets(y, p, tickers)
    assert len(row) == 1 and len(win) == 1
    assert row[0].count == 10                    # rows
    assert win[0].count == 3                     # DISTINCT windows
    assert win[0].mean_actual == pytest.approx(1 / 3)   # window YES rate (A=1, B=0, C=0)
    # window interval is WIDER (fewer effective samples) -> never looser
    assert (win[0].wilson_high - win[0].wilson_low) > (row[0].wilson_high - row[0].wilson_low)


def test_reliability_table_has_effective_sample_size():
    ctx = cr.build_promoted_context(_fake_prep())
    assert ctx["applied"]
    tbl = cr.reliability_tables(ctx, "identity_raw")
    assert tbl and all("effective_sample_size" in b and "distinct_window_n" in b for b in tbl)
    # Kish effective n never exceeds the row count and is <= distinct windows * something sane
    for b in tbl:
        if b["effective_sample_size"] is not None:
            assert b["effective_sample_size"] <= b["row_n"]


def test_config_reliability_unit_flag(monkeypatch):
    cfg = load_config(mode="paper")
    assert cfg.edge_policy.reliability_unit == "both"    # default
    monkeypatch.setenv("KALSHI_EDGE_RELIABILITY_UNIT", "window")
    assert load_config(mode="paper").edge_policy.reliability_unit == "window"
    monkeypatch.setenv("KALSHI_EDGE_RELIABILITY_UNIT", "bogus")
    assert load_config(mode="paper").edge_policy.reliability_unit == "both"   # invalid -> both


# --------------------------------------------------------------------------- #
# Part B — promoted context + staged candidates
# --------------------------------------------------------------------------- #
def test_build_promoted_context_all_methods():
    ctx = cr.build_promoted_context(_fake_prep())
    assert ctx["applied"]
    assert {"current_promoted_isotonic", "identity_raw", "platt", "fresh_isotonic",
            "market_implied"} <= set(ctx["methods"])
    for a in cr.ALPHAS:
        assert cr._alpha_method(a) in ctx["methods"]
    # both bucket families present per method
    assert set(ctx["row_buckets"]) == set(ctx["methods"]) == set(ctx["win_buckets"])
    assert "platt" in ctx["calibrators"] and "isotonic" in ctx["calibrators"]


def test_stage_replacements_are_staged_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    ctx = cr.build_promoted_context(_fake_prep())
    ctx["series"] = "KXBTC15M"
    staged = cr.stage_replacements(cfg, ctx, series="KXBTC15M")
    assert len(staged) == 3 + len(cr.ALPHAS)        # identity + platt + isotonic + 5 alphas = 8
    sdir = tmp_path / "data" / "models" / "staged"
    for a in staged:
        f = a.get("artifact_file") or a.get("calibrator_file")
        assert Path(f).parent == sdir
        assert a["tradable_status"] in ("STAGED_NON_PROMOTED", "DIAGNOSTIC_ONLY")
    # metadata present on a calibrator candidate summary
    import json
    summ = json.loads(Path(staged[0]["summary_file"]).read_text(encoding="utf-8"))
    assert summ["is_promoted"] is False and summ["live_approved"] is False
    assert summ["promotion_required"] is True and "model_backbone_path" in summ
    # nothing under paper_promoted; no promotion manifest
    assert not list((tmp_path / "data").glob("**/kalshi_paper_promotion_manifest.json"))


# --------------------------------------------------------------------------- #
# Part H — eligibility (mark only)
# --------------------------------------------------------------------------- #
def test_eligibility_marks_safer_calibrator():
    ctx = {"metrics": {
        "current_promoted_isotonic": {"ece_window": 0.106, "brier": 0.123, "yes_overprediction_cents": 8.4},
        "identity_raw": {"ece_window": 0.051, "brier": 0.110, "yes_overprediction_cents": -1.3},
        "platt": {"ece_window": 0.062, "brier": 0.113, "yes_overprediction_cents": -2.4},
        "market_implied": {"ece_window": 0.034},
    }}
    backtest = {"current_promoted_isotonic": {"net_pnl": -7.49}, "identity_raw": {"net_pnl": 0.68},
                "platt": {"net_pnl": 3.20}}
    cohort = {"by_unit": {"row": {"identity_raw": {"distinct_pass_windows": 0},
                                  "platt": {"distinct_pass_windows": 0}}}}
    elig = cr.eligibility(ctx, backtest, cohort)
    assert elig["recommended_replacement_candidate"] == "identity_raw"   # lowest window ECE among safer
    assert elig["replacement_eligible_for_promotion_review"] is True
    assert elig["per_candidate"]["identity_raw"]["staged_shadow_candidate"] is True
    assert elig["per_candidate"]["identity_raw"]["safer_calibrator"] is True
    assert not elig["blockers"]


def test_eligibility_blocks_when_no_calibration_improvement():
    ctx = {"metrics": {
        "current_promoted_isotonic": {"ece_window": 0.04, "brier": 0.10, "yes_overprediction_cents": 0.5},
        "identity_raw": {"ece_window": 0.09, "brier": 0.12, "yes_overprediction_cents": 8.0},
        "platt": {"ece_window": 0.08, "brier": 0.12, "yes_overprediction_cents": 7.0},
        "market_implied": {"ece_window": 0.03},
    }}
    backtest = {"current_promoted_isotonic": {"net_pnl": 1.0}, "identity_raw": {"net_pnl": -2.0},
                "platt": {"net_pnl": -1.0}}
    elig = cr.eligibility(ctx, backtest, {"by_unit": {"row": {}}})
    assert elig["recommended_replacement_candidate"] == "none"
    assert elig["replacement_eligible_for_promotion_review"] is False


# --------------------------------------------------------------------------- #
# cohort mapping + degradation + safety
# --------------------------------------------------------------------------- #
def test_cohort_prob_mapping():
    cals = cr.build_promoted_context(_fake_prep())["calibrators"]
    assert cr._cohort_prob("identity_raw", raw=0.7, promoted=0.8, market=0.6, cals=cals) == 0.7
    assert cr._cohort_prob("current_promoted_isotonic", raw=0.7, promoted=0.8, market=0.6, cals=cals) == 0.8
    assert cr._cohort_prob("market_implied", raw=0.7, promoted=0.8, market=0.6, cals=cals) == 0.6
    assert cr._cohort_prob("market_shrunk_a0.1", raw=0.7, promoted=0.8, market=0.6,
                           cals=cals) == pytest.approx(cr.blend(0.7, 0.6, 0.1))


def test_runners_degrade_without_promotion(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    for fn in (cr.run_calibrator_replacement_review, cr.run_candidate_replacement_impact,
               cr.run_stage_calibrator_replacements):
        r = fn(cfg, series="KXBTC15M")
        assert r["status"] != "OK"
        assert r["live_submission_allowed"] is False
        assert r["runtime_unchanged"] is True
    # preservation manifest written; no promotion manifest created
    assert list((tmp_path / "reports" / "models").glob("pre_calibrator_replacement_preservation_*.json"))
    assert not list((tmp_path / "data").glob("**/kalshi_paper_promotion_manifest.json"))


def test_report_writers_do_not_raise(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    ctx = cr.build_promoted_context(_fake_prep())
    ctx["series"] = "KXBTC15M"
    backtest = cr.replacement_backtest(cfg, ctx)
    cohort = {"ledger": "x", "n_cohort": 0, "by_unit": {"row": {}, "window": {}}}
    elig = cr.eligibility(ctx, backtest, cohort)
    reliab = cr.reliability_tables(ctx, "identity_raw")
    rev = cr._write_review(cfg, ctx, backtest, elig, reliab, "both")
    imp = cr._write_impact(cfg, cohort, ctx)
    bt = cr._write_backtest(cfg, ctx, backtest)
    for d in (rev, imp, bt):
        for v in d.values():
            if isinstance(v, str) and v.endswith((".md", ".csv")):
                assert Path(v).exists()
    assert "any_repaired_pass_row" in imp and "any_repaired_pass_window" in imp


def test_cli_commands_registered():
    import btc5m.cli as c
    for name in ("kalshi-calibrator-replacement-review", "kalshi-candidate-replacement-impact",
                 "kalshi-stage-calibrator-replacements", "kalshi-shadow-compare-calibrators"):
        assert name in c._COMMANDS and callable(c._COMMANDS[name])
    # alias points at the existing shadow-compare engine
    assert (c._COMMANDS["kalshi-shadow-compare-calibrators"]
            is c._COMMANDS["kalshi-shadow-compare-probability-repairs"])


def test_check_live_disabled_holds(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    assert cfg.live_blockers() and cfg.live_permitted is False
