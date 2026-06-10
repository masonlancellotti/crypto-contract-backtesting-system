"""Probability repair + market-shrinkage (STAGED / report-only).

Covers market-implied probability, the blend formula + alpha grid, distinct-window
reliability, Platt/isotonic/identity/market comparison on a fixture, the candidate-cohort
repair mapping, executable backtest structure, staged-only artifact outputs, runtime-state
preservation, and the safety invariants (no promotion, no manifest change, live disabled).
Offline; no orders; nothing promoted.
"""

import json
from pathlib import Path

import pytest

from btc5m.config import load_config
from btc5m.venues.kalshi.calibrate import fit_calibrator
from btc5m.venues.kalshi import probability_repair as pr

CALIB = pr.CALIB_METHODS


def _synth_ctx():
    """A hand-built repair context where the MARKET is calibrated and the model OVER-predicts.

    Two predicted-probability bins, each holding a MIX of YES/NO windows so window-level
    reliability is meaningful: bin A (market 0.50, 10 windows, 5 YES) and bin B (market 0.20,
    10 windows, 2 YES). The model adds +0.15 everywhere (systematic YES over-prediction).
    """
    specs = ([("A", w, 0.50, 1 if w < 5 else 0) for w in range(10)]
             + [("B", w, 0.20, 1 if w < 2 else 0) for w in range(10)])
    rows, raw, mkt, platt, iso, y, tk = [], [], [], [], [], [], []
    for gi, (g, w, mp, label) in enumerate(specs):
        tkr, ya, na = f"{g}{w}", mp, round(1.0 - mp, 2)
        for _ in range(2):                              # 2 rows per window
            i = len(rows)
            rows.append({"ticker": tkr, "as_of_ts_ms": 1000 + i, "label_yes_resolved": label,
                         "yes_ask": ya, "no_ask": na, "book_ok": True, "seconds_to_close": 300,
                         "reference_start_price": 100.0, "yes_ask_size": 10, "no_ask_size": 10,
                         "market_close_ts_ms": 900000 + gi, "series": "KXBTC15M", "row_id": f"{tkr}@{i}"})
            y.append(label); tk.append(tkr)
            mkt.append(pr.market_implied_yes(ya, na))    # == mp -> calibrated to the bin's YES rate
            raw.append(min(0.99, mp + 0.15))             # over-predicts YES by 15c
            platt.append(min(0.99, mp + 0.07))
            iso.append(min(0.99, mp + 0.05))
    cal = {m: fit_calibrator(m, raw, y).to_dict() for m in CALIB}
    return {"series": "KXBTC15M", "applied": True, "gate_windows": 20,
            "split": {"n_windows": 20, "train_windows": 10, "calib_windows": 5, "test_windows": 5,
                      "embargo_windows": 1},
            "rows": rows, "test_idx": list(range(len(rows))), "y_test": y, "tickers": tk,
            "base_rate": sum(y) / len(y), "calibrators": cal,
            "sources": {"raw_model": raw, "identity": list(raw), "staged_platt": platt,
                        "staged_isotonic": iso, "market_implied": mkt}}


# --------------------------------------------------------------------------- #
# market-implied + blend + alpha grid
# --------------------------------------------------------------------------- #
def test_market_implied_yes():
    assert pr.market_implied_yes(0.30, 0.70) == pytest.approx(0.30)
    assert pr.market_implied_yes(0.62, 0.40) == pytest.approx(0.62 / 1.02)
    assert pr.market_implied_yes(None, 0.5) is None
    assert 0.0 <= pr.market_implied_yes(0.9, 0.9) <= 1.0


def test_blend_formula_and_alpha_grid():
    assert pr.blend(0.8, 0.6, 0.5) == pytest.approx(0.7)
    assert pr.blend(0.8, 0.6, 1.0) == pytest.approx(0.8)   # pure model
    assert pr.blend(0.8, 0.6, 0.0) == pytest.approx(0.6)   # pure market
    assert pr.blend(2.0, 2.0, 1.0) == 1.0 and pr.blend(-1.0, -1.0, 1.0) == 0.0  # clamped
    assert pr.ALPHA_GRID[0] == 0.0 and pr.ALPHA_GRID[-1] == 1.0 and len(pr.ALPHA_GRID) == 11


# --------------------------------------------------------------------------- #
# distinct-window reliability + per-source metrics
# --------------------------------------------------------------------------- #
def test_source_metrics_window_reliability():
    ctx = _synth_ctx()
    m = pr.source_metrics(ctx["y_test"], ctx["sources"]["market_implied"], ctx["tickers"], ctx["base_rate"])
    assert m["n"] == 40
    assert m["ece_window"] is not None and m["reliability_window"]
    assert all("distinct_window_n" in b for b in m["reliability_window"])
    # market is calibrated to base rate => ~no YES over-prediction
    assert abs(m["yes_overprediction_cents"]) < 1.0


def test_compare_sources_market_beats_overpredicting_model():
    ctx = _synth_ctx()
    cmp = pr.compare_sources(ctx)
    assert set(("raw_model", "identity", "staged_platt", "staged_isotonic", "market_implied")) <= set(cmp)
    # the over-predicting raw model has WORSE window ECE than the calibrated market
    assert cmp["market_implied"]["ece_window"] <= cmp["raw_model"]["ece_window"]
    # raw model over-predicts YES (positive cents), market ~0
    assert cmp["raw_model"]["yes_overprediction_cents"] > cmp["market_implied"]["yes_overprediction_cents"]


# --------------------------------------------------------------------------- #
# market-shrink alpha sweep
# --------------------------------------------------------------------------- #
def test_market_shrink_sweep_grid_and_recommendation():
    ctx = _synth_ctx()
    sweep = pr.market_shrink_sweep(ctx)
    assert set(sweep["grid"]) == {"raw", "platt", "isotonic"}
    for base, rows_alpha in sweep["grid"].items():
        assert [r["alpha"] for r in rows_alpha] == pr.ALPHA_GRID    # full 0..1 grid
    rec = sweep["recommendation"]
    assert rec["recommended_alpha"] in pr.ALPHA_GRID
    assert "ece_window" in sweep["market_baseline"]


def test_apply_stability_picks_more_conservative_alpha():
    sweep = {"recommendation": {"recommended_alpha": 0.4, "recommended_base": "platt"}}
    pr._apply_stability(sweep, {"alpha_values": [0.0, 0.1, 0.0], "stable": True})
    # conservative alpha = min(main, walk-forward median) => shrink harder toward market
    assert sweep["recommendation"]["conservative_alpha"] == 0.0
    assert "noise" in sweep["recommendation"]["conservative_note"].lower()


# --------------------------------------------------------------------------- #
# repaired-probability mapping (candidate cohort)
# --------------------------------------------------------------------------- #
def test_repaired_prob_mapping():
    ctx = _synth_ctx()
    cals = ctx["calibrators"]
    raw, market = 0.80, 0.60
    assert pr._repaired_prob("raw_model", raw=raw, promoted=0.9, market=market,
                             calibrators=cals, alpha=0.5, base="raw") == raw
    assert pr._repaired_prob("identity", raw=raw, promoted=0.9, market=market,
                             calibrators=cals, alpha=0.5, base="raw") == raw
    assert pr._repaired_prob("current_promoted_calibrator", raw=raw, promoted=0.9, market=market,
                             calibrators=cals, alpha=0.5, base="raw") == 0.9
    assert pr._repaired_prob("market_implied", raw=raw, promoted=0.9, market=market,
                             calibrators=cals, alpha=0.5, base="raw") == market
    blended = pr._repaired_prob("market_shrunk", raw=raw, promoted=0.9, market=market,
                                calibrators=cals, alpha=0.5, base="raw")
    assert blended == pytest.approx(pr.blend(raw, market, 0.5))
    # platt source transforms the raw probability through the fitted calibrator
    from btc5m.venues.kalshi.calibrate import Calibrator
    expect = Calibrator.from_dict(cals["platt"]).transform([raw])[0]
    assert pr._repaired_prob("staged_platt", raw=raw, promoted=0.9, market=market,
                             calibrators=cals, alpha=0.5, base="raw") == pytest.approx(expect)


# --------------------------------------------------------------------------- #
# executable backtest (asks/fees/gates) — market-implied can't beat itself
# --------------------------------------------------------------------------- #
def test_repair_backtest_structure(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    ctx = _synth_ctx()
    bt = pr.repair_backtest(cfg, ctx, shrink_base="raw", shrink_alpha=0.5)
    assert "market_implied" in bt and "raw_model" in bt and "market_shrunk" in bt
    assert bt["market_implied"]["total_simulated_trades"] == 0   # implied prob == price => no edge
    assert bt["raw_model"]["total_simulated_trades"] > 0


# --------------------------------------------------------------------------- #
# staged-only artifacts (never under paper_promoted; never promoted)
# --------------------------------------------------------------------------- #
def test_staged_artifacts_go_to_staged_dir_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    ctx = _synth_ctx()
    sweep = pr.market_shrink_sweep(ctx)
    blender = pr.stage_market_shrink_blender(cfg, ctx, sweep, series="KXBTC15M")
    platt = pr.stage_platt_calibrator(cfg, ctx, series="KXBTC15M")
    staged = tmp_path / "data" / "models" / "staged"
    assert Path(blender["artifact_file"]).parent == staged
    assert Path(platt["calibrator_file"]).parent == staged
    assert blender["tradable_status"] == "DIAGNOSTIC_ONLY"
    assert platt["tradable_status"] == "STAGED_NON_PROMOTED"
    # the blender summary stamps non-promoted / not-live
    summ = json.loads(Path(blender["summary_file"]).read_text(encoding="utf-8"))
    assert summ["is_promoted"] is False and summ["live_approved"] is False
    # NOTHING written under paper_promoted, no promotion manifest created
    assert not list((tmp_path / "data").glob("**/kalshi_paper_promotion_manifest.json"))
    pp = tmp_path / "data" / "models" / "paper_promoted"
    assert not (pp.exists() and list(pp.glob("*.pkl")))


# --------------------------------------------------------------------------- #
# runtime-state preservation (Part A)
# --------------------------------------------------------------------------- #
def test_snapshot_and_verify_runtime_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    md = tmp_path / "data" / "models"
    md.mkdir(parents=True, exist_ok=True)
    f = md / "kalshi_thing.pkl"
    f.write_bytes(b"v1")
    snap = pr.snapshot_runtime_state(cfg)
    assert str(f) in snap
    assert pr.verify_runtime_unchanged(cfg, snap)["unchanged"] is True
    f.write_bytes(b"v2-changed")
    diff = pr.verify_runtime_unchanged(cfg, snap)
    assert diff["unchanged"] is False and str(f) in diff["changed"]


# --------------------------------------------------------------------------- #
# graceful degradation + safety
# --------------------------------------------------------------------------- #
def test_candidate_repair_no_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    r = pr.candidate_repair_audit(cfg, series="KXBTC15M")
    assert r["status"] == "NO_LEDGER" and r["live_submission_allowed"] is False


def test_cli_commands_registered():
    import btc5m.cli as c
    for name in ("kalshi-calibration-compare", "kalshi-probability-repair",
                 "kalshi-market-shrink-sweep", "kalshi-candidate-repair-audit"):
        assert name in c._COMMANDS and callable(c._COMMANDS[name])


def test_check_live_disabled_holds(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    assert cfg.live_blockers()                  # non-empty => live NOT permitted
    assert cfg.live_submission_allowed is False if hasattr(cfg, "live_submission_allowed") else True
