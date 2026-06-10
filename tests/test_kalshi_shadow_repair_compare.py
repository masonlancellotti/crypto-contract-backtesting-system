"""Staged shadow comparison of repaired probabilities (report-only).

Covers per-method probability construction, the shared scoring engine, the accumulator +
verdict, staged-only candidate artifacts, graceful degradation without a promoted model,
and the safety invariants (no promotion, no manifest change, live/paper disabled). Offline.
"""

from pathlib import Path

import pytest

from btc5m.config import load_config
from btc5m.venues.kalshi.edge_policy import EdgePolicyConfig
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.probability_repair import blend, market_implied_yes
from btc5m.venues.kalshi import shadow_repair_compare as sc

ECFG = EdgePolicyConfig()
FM = KalshiFeeModel()


def _fake_prep():
    """A minimal _prepare_runtime-shaped context: mixed-outcome windows, model over-predicts YES."""
    specs = ([("A", w, 0.50, 1 if w < 5 else 0) for w in range(10)]
             + [("B", w, 0.20, 1 if w < 2 else 0) for w in range(10)])
    rows = []
    for gi, (g, w, mp, label) in enumerate(specs):
        ya, na = mp, round(1.0 - mp, 2)
        for _ in range(3):
            i = len(rows)
            rows.append({"ticker": f"{g}{w}", "as_of_ts_ms": 1000 + i, "label_yes_resolved": label,
                         "model_probability_yes": min(0.99, mp + 0.15),       # raw over-predicts YES
                         "calibrated_probability_yes": min(0.99, mp + 0.20),  # isotonic over-predicts more
                         "yes_ask": ya, "no_ask": na, "book_ok": True, "seconds_to_close": 300,
                         "reference_start_price": 100.0, "yes_ask_size": 10, "no_ask_size": 10,
                         "market_close_ts_ms": 900000 + gi})
    return {"dataset_rows": rows, "buckets": []}


# --------------------------------------------------------------------------- #
# per-method construction
# --------------------------------------------------------------------------- #
def test_prepare_methods_builds_all_sources():
    mctx = sc.prepare_methods(_fake_prep(), alphas=[0.0, 0.05, 0.1, 0.2])
    names = set(mctx["method_names"])
    assert {"current_promoted_isotonic", "identity_raw", "platt", "market_implied"} <= names
    for a in (0.0, 0.05, 0.1, 0.2):
        assert sc._alpha_method(a) in names
    assert set(mctx["buckets"]) == names              # a bucket set per source
    assert "platt" in mctx["calibrators"] and "identity" in mctx["calibrators"]


def test_method_prob_mapping():
    mctx = sc.prepare_methods(_fake_prep(), alphas=[0.1])
    raw_p, promoted_p, market = 0.70, 0.78, 0.60
    assert sc._method_prob("identity_raw", raw_p=raw_p, promoted_p=promoted_p, market=market, mctx=mctx) == raw_p
    assert sc._method_prob("current_promoted_isotonic", raw_p=raw_p, promoted_p=promoted_p,
                           market=market, mctx=mctx) == promoted_p
    assert sc._method_prob("market_implied", raw_p=raw_p, promoted_p=promoted_p, market=market, mctx=mctx) == market
    assert sc._method_prob("market_shrunk_a0.1", raw_p=raw_p, promoted_p=promoted_p, market=market,
                           mctx=mctx) == pytest.approx(blend(raw_p, market, 0.1))


def test_score_row_all_methods_structure():
    mctx = sc.prepare_methods(_fake_prep(), alphas=[0.0, 0.1])
    recs = sc.score_row_all_methods(0.65, 0.78, 0.50, 0.50, mctx=mctx, edge_cfg=ECFG, fee_model=FM)
    assert {"current_promoted_isotonic", "identity_raw", "platt", "market_implied"} <= set(recs)
    for name, d in recs.items():
        assert "final_policy_edge_cents" in d and "state" in d and "bucket" in d
    # market-implied probability == market price => ~0 disagreement
    assert abs(recs["market_implied"]["market_disagreement_cents"]) < 1e-6
    # market-implied raw edge ~ 0 (can't beat the market at its own price)
    assert recs["market_implied"]["raw_edge_cents"] == pytest.approx(0.0, abs=1.0)


# --------------------------------------------------------------------------- #
# accumulator + verdict
# --------------------------------------------------------------------------- #
def test_accumulator_and_summary():
    acc = sc._Acc(min_raw_edge_cents=5.0)
    acc.add({"identity_raw": {"p": 0.7, "market": 0.6, "side": "YES", "raw_edge_cents": 8.0,
                              "uncertainty_adjusted_edge_cents": 1.0, "final_policy_edge_cents": -1.0,
                              "calib_buffer_cents": 3.0, "state": "EDGE_BELOW_MIN", "bucket": "[0.7,0.8)",
                              "market_disagreement_cents": 10.0, "reason_codes": ["EDGE_BELOW_MIN"]}})
    acc.add({"identity_raw": {"p": 0.8, "market": 0.7, "side": "YES", "raw_edge_cents": 3.0,
                              "uncertainty_adjusted_edge_cents": 2.5, "final_policy_edge_cents": 2.5,
                              "calib_buffer_cents": 1.0, "state": "EDGE_OK", "bucket": "[0.8,0.9)",
                              "market_disagreement_cents": 10.0, "reason_codes": ["EDGE_OK"]}})
    s = acc.summary()["identity_raw"]
    assert s["n_rows"] == 2 and s["candidate_like_rows"] == 1 and s["pass_final_edge"] == 1
    assert s["best_final_edge_cents"] == 2.5 and s["side_distribution"] == {"YES": 2}


def test_verdict_no_pass_recommends_collection():
    summary = {"current_promoted_isotonic": {"pass_final_edge": 0, "best_final_edge_cents": -1.0},
               "identity_raw": {"pass_final_edge": 0, "best_final_edge_cents": 1.8},
               "platt": {"pass_final_edge": 0, "best_final_edge_cents": 0.4}}
    v = sc._verdict(summary)
    assert v["any_repaired_pass"] is False and v["staged_shadow_candidate"] is None
    assert "COLLECTION" in v["recommendation"].upper()


def test_verdict_pass_marks_staged_shadow_candidate():
    summary = {"current_promoted_isotonic": {"pass_final_edge": 0, "best_final_edge_cents": -1.0},
               "identity_raw": {"pass_final_edge": 3, "best_final_edge_cents": 4.0}}
    v = sc._verdict(summary)
    assert v["any_repaired_pass"] is True and v["staged_shadow_candidate"] == ["identity_raw"]
    assert "STAGED_SHADOW_CANDIDATE" in v["recommendation"]


# --------------------------------------------------------------------------- #
# staged-only artifacts + degradation + safety
# --------------------------------------------------------------------------- #
def test_stage_candidates_are_staged_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    mctx = sc.prepare_methods(_fake_prep(), alphas=[0.0, 0.05, 0.1, 0.2])
    staged = sc.stage_candidates(cfg, mctx, series="KXBTC15M")
    assert len(staged) == 6                          # identity + platt + 4 alphas
    sdir = tmp_path / "data" / "models" / "staged"
    for a in staged:
        f = a.get("artifact_file") or a.get("calibrator_file")
        assert Path(f).parent == sdir
        assert a["tradable_status"] in ("STAGED_NON_PROMOTED", "DIAGNOSTIC_ONLY")
    # nothing under paper_promoted, no promotion manifest
    assert not list((tmp_path / "data").glob("**/kalshi_paper_promotion_manifest.json"))
    pp = tmp_path / "data" / "models" / "paper_promoted"
    assert not (pp.exists() and list(pp.glob("*.pkl")))


def test_run_shadow_compare_degrades_without_promotion(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    r = sc.run_shadow_compare(cfg, series="KXBTC15M", minutes=0)   # no promoted model in tmp
    assert r["status"] != "OK"
    assert r["live_submission_allowed"] is False
    assert r["runtime_unchanged"] is True
    # never created a promotion manifest or promoted artifacts
    assert not list((tmp_path / "data").glob("**/kalshi_paper_promotion_manifest.json"))


def test_cli_command_registered():
    import btc5m.cli as c
    assert "kalshi-shadow-compare-probability-repairs" in c._COMMANDS
    assert callable(c._COMMANDS["kalshi-shadow-compare-probability-repairs"])


def test_check_live_disabled_holds(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    assert cfg.live_blockers()                 # non-empty => live NOT permitted
    assert cfg.live_permitted is False
