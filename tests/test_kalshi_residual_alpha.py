"""Market-implied residual alpha research (STAGED / report-only).

Covers the residual-target math, the market baseline, no-leakage feature groups, the
detect-signal / reject-no-signal behaviour of the residual model on synthetic fixtures,
p_market+residual clipping, edge-policy integration (buffers intact), the executable
backtest, staged-only artifacts, and the safety invariants. Offline; nothing promoted.
"""

from pathlib import Path

import pytest

from btc5m.config import load_config
from btc5m.venues.kalshi.fees import KalshiFeeModel
from btc5m.venues.kalshi.feature_schema import LEAKAGE_EXCLUDED
from btc5m.venues.kalshi.probability_repair import source_metrics
from btc5m.venues.kalshi import residual_alpha as ra

FM = KalshiFeeModel()


def _synth(signal=True, n_windows=40, per=3):
    """Synthetic residual rows. y alternates per window (both classes everywhere);
    p_market is flat 0.5. With ``signal`` the feature equals the sign of the residual;
    without it the feature is decorrelated from y."""
    rows = []
    for w in range(n_windows):
        y = w % 2
        f = (0.1 if y == 1 else -0.1) if signal else (0.1 if (w % 4) < 2 else -0.1)
        for _ in range(per):
            rows.append({"ticker": f"W{w}", "window_id": f"W{w}", "series": "KXBTC15M",
                         "market_close_ts_ms": 1000 + w, "as_of_ts_ms": 1000 + w,
                         "y": y, "p_market": 0.5, "logit_market": 0.0, "residual": y - 0.5,
                         "yes_ask": 0.5, "no_ask": 0.5, "spot_return_60s": f,
                         "label_yes_resolved": y, "book_ok": True, "seconds_to_close": 300,
                         "reference_start_price": 100.0, "yes_ask_size": 10, "no_ask_size": 10})
    return rows


def _split(rows):
    from btc5m.venues.kalshi.splits import three_way_window_split
    sp = three_way_window_split(rows, embargo_windows=1)
    return sp["train_idx"] + sp["calib_idx"], sp["test_idx"], sp


def _market_metrics(rows, train, test, feats):
    mk = ra._fit_predict("market_only", rows, train, test, feats)
    y = [rows[i]["y"] for i in test]
    tk = [rows[i]["window_id"] for i in test]
    base = sum(y) / len(y)
    return mk, source_metrics(y, mk["p_test"], tk, base)


# --------------------------------------------------------------------------- #
# Part B — residual targets + helpers
# --------------------------------------------------------------------------- #
def test_residual_targets_math():
    t = ra.residual_targets(1, 0.30, 0.70, FM)
    assert t["p_market"] == pytest.approx(0.30)
    assert t["residual"] == pytest.approx(0.70) and t["residual_positive"] == 1
    assert t["edge_realized_yes"] == pytest.approx(1 - 0.30 - FM.per_contract_fee(0.30))
    assert t["edge_realized_no"] == pytest.approx((1 - 1) - 0.70 - FM.per_contract_fee(0.70))
    assert t["candidate_pnl_label"] == 1                      # YES side was profitable ex-post
    t0 = ra.residual_targets(0, 0.30, 0.70, FM)
    assert t0["residual"] == pytest.approx(-0.30)
    assert ra.residual_targets(0, None, 0.7, FM) is None


def test_helpers():
    assert ra._clip(2.0) < 1.0 and ra._clip(-1.0) > 0.0
    assert ra._logit(0.5) == pytest.approx(0.0)
    assert ra._spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert ra._spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert ra._pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)


def test_feature_groups_exclude_leakage():
    groups = ra.feature_groups()
    assert groups["market_only"] == []
    for name, feats in groups.items():
        assert not (set(feats) & LEAKAGE_EXCLUDED)
    assert "label_yes_resolved" not in ra.ALL_FEATS
    assert "reference_start_price" not in ra.ALL_FEATS       # non-stationary level excluded
    assert "yes_ask" in ra.ALL_FEATS                          # executable price IS a feature


# --------------------------------------------------------------------------- #
# Part D/F — detect signal when present, reject when absent
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not ra._SK, reason="sklearn required")
def test_residual_model_detects_planted_signal():
    rows = _synth(signal=True)
    train, test, _ = _split(rows)
    feats = ["spot_return_60s"]
    _mk, mm = _market_metrics(rows, train, test, feats)
    fit = ra._fit_predict("ridge", rows, train, test, feats)
    met = ra._model_metrics(rows, test, fit["p_test"], mm)
    assert met["delta_brier_vs_market"] < 0          # beats market OOS when signal exists
    assert (met["residual_ic_spearman"] or 0) > 0.5  # strong rank correlation
    assert all(0.0 < p < 1.0 for p in fit["p_test"])  # p_repaired clipped to (0,1)


@pytest.mark.skipif(not ra._SK, reason="sklearn required")
def test_residual_model_rejects_no_signal():
    rows = _synth(signal=False)
    train, test, _ = _split(rows)
    feats = ["spot_return_60s"]
    _mk, mm = _market_metrics(rows, train, test, feats)
    fit = ra._fit_predict("ridge", rows, train, test, feats)
    met = ra._model_metrics(rows, test, fit["p_test"], mm)
    # no real signal => does NOT clearly beat market, IC near zero
    assert met["delta_brier_vs_market"] >= -0.01
    assert abs(met["residual_ic_spearman"] or 0.0) < 0.4


# --------------------------------------------------------------------------- #
# Part G — edge-policy integration (buffers intact) + backtest (asks/fees)
# --------------------------------------------------------------------------- #
def test_edge_eval_keeps_buffers(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    rows = _synth(signal=True)
    _train, test, _ = _split(rows)
    p_test = [rows[i]["p_market"] for i in test]
    ev = ra._edge_eval(cfg, rows, test, p_test, unit="window")
    assert "pass_final" in ev and "median_calib_buffer_cents" in ev and "median_model_buffer_cents" in ev
    assert ev["n_rows"] > 0


def test_backtest_uses_asks_and_fees(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    rows = _synth(signal=True)
    _train, test, _ = _split(rows)
    bt = ra._backtest(cfg, rows, test, [rows[i]["p_market"] for i in test])
    assert "net_pnl" in bt and "total_simulated_trades" in bt
    # market-implied prob == price => 0 raw edge => no trades
    assert bt["total_simulated_trades"] == 0


# --------------------------------------------------------------------------- #
# Part J — staged artifacts only
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not ra._SK, reason="sklearn required")
def test_stage_residual_models_staged_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    rows = _synth(signal=True)
    train, test, sp = _split(rows)
    fit = ra._fit_predict("ridge", rows, train, test, ["spot_return_60s"])
    staged = ra._stage_residual_models(cfg, {"ridge": {"metrics": {}}}, {"ridge": fit}, sp,
                                       series="KXBTC15M", dw=40)
    assert len(staged) == 1
    sdir = tmp_path / "data" / "models" / "staged"
    assert Path(staged[0]["artifact_file"]).parent == sdir
    assert staged[0]["tradable_status"] == "DIAGNOSTIC_ONLY"
    import json
    summ = json.loads(Path(staged[0]["summary_file"]).read_text(encoding="utf-8"))
    assert summ["artifact_type"] == "residual_alpha_model" and summ["uses_market_baseline"] is True
    assert summ["is_promoted"] is False and summ["live_approved"] is False
    assert not list((tmp_path / "data").glob("**/kalshi_paper_promotion_manifest.json"))


# --------------------------------------------------------------------------- #
# dataset builder + degradation + safety
# --------------------------------------------------------------------------- #
def test_build_residual_dataset_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    r = ra.run_build_residual_dataset(cfg, series="KXBTC15M")    # empty data -> 0 rows, still OK
    assert r["status"] == "OK" and r["live_submission_allowed"] is False
    assert Path(r["dataset_file"]).exists() and Path(r["metadata_file"]).exists()
    assert r["runtime_unchanged"] is True
    assert not list((tmp_path / "data").glob("**/kalshi_paper_promotion_manifest.json"))


def test_train_degrades_without_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    r = ra.run_train_residual_models(cfg, series="KXBTC15M")
    assert r["status"] != "OK" and r["live_submission_allowed"] is False
    assert r["runtime_unchanged"] is True


def test_cli_commands_registered():
    import btc5m.cli as c
    for name in ("kalshi-build-residual-dataset", "kalshi-train-residual-models",
                 "kalshi-residual-model-report", "kalshi-residual-replay",
                 "kalshi-shadow-compare-residual-models"):
        assert name in c._COMMANDS and callable(c._COMMANDS[name])


def test_check_live_disabled_holds(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    assert cfg.live_blockers() and cfg.live_permitted is False
