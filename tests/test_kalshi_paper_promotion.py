"""Paper-ONLY promotion + shadow/paper runtime — manifest safety, modes, gates.

All offline. Verifies: the runtime never uses newest-by-mtime; staged artifacts are
inactive unless explicitly promoted; diagnostic/uncalibrated/mismatched artifacts are
rejected; promotion is PAPER_ONLY (live_approved=false); SHA mismatch blocks; demote
rolls back; shadow scores but never fills/candidates; paper mode requires the edge
policy and is never live. Nothing trades; live stays disabled.
"""

import json


from btc5m.config import load_config

WIN = 15 * 60 * 1000
DTV = None  # filled at import time below


def _feats():
    from btc5m.venues.kalshi.feature_schema import DISTANCE_TIME_VOL_FEATURES
    return DISTANCE_TIME_VOL_FEATURES


def _frow(tk, *, as_of, close, yes):
    return {"market_ticker": tk, "has_orderbook": True, "has_underlying": True,
            "has_start_reference": True, "book_ok": True,
            "seconds_to_close": (close - as_of) / 1000.0, "as_of_ms": as_of, "close_ms": close,
            "feature_set_version": 3, "yes_ask": 0.42, "no_ask": 0.60,
            "yes_spread": 0.02, "no_spread": 0.02, "top_depth": 100.0,
            "yes_ask_size": 100.0, "no_ask_size": 100.0, "quote_age_ms": 100,
            "reference_start_price": 70000.0, "reference_price": 70010.0,
            "distance_to_start": (50.0 if yes else -50.0), "spot_sigma_per_sqrt_s": 1e-4,
            "realized_vol_60s": 1e-4, "realized_vol_180s": 1e-4,
            "distance_to_line_vol_normalized": (0.5 if yes else -0.5),
            "spot_return_60s": (0.001 if yes else -0.001)}


def _setup(tmp_path, monkeypatch, *, n_windows=4, reports=True):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    feats = tmp_path / "features"; feats.mkdir(parents=True)
    labels = tmp_path / "labels"; labels.mkdir(parents=True)
    base = 1_780_000_000_000
    fr, lr = [], []
    for w in range(n_windows):
        close = base + (w + 1) * WIN
        yes = w % 2
        for i in range(6):
            fr.append(_frow(f"KX-{w}", as_of=close - (200 - i * 10) * 1000, close=close, yes=yes))
        lr.append({"market_ticker": f"KX-{w}", "label_source_status": "OFFICIAL", "label_yes_resolved": yes})
    (feats / "kalshi_feature_rows-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in fr) + "\n", encoding="utf-8")
    (labels / "kalshi_settlement_labels-20260602.jsonl").write_text(
        "\n".join(json.dumps(r) for r in lr) + "\n", encoding="utf-8")
    if reports:
        for sub, name in (("calibration", "kalshi_calibration_report_20260602_000000.md"),
                          ("backtests", "kalshi_baseline_comparison_20260602_000000.md"),
                          ("edge", "kalshi_edge_policy_report_20260602_000000.md"),
                          ("frequency", "kalshi_frequency_frontier_20260602_000000.md")):
            d = tmp_path / "reports" / sub
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text("evidence", encoding="utf-8")


def _make_staged(cfg, *, model_name="microstructure_logistic", tradable=True, calibrated=True,
                 cal_model_name=None, method="isotonic"):
    from btc5m.venues.kalshi.calibrate import Calibrator, build_calibrator_artifact, save_calibrator
    from btc5m.venues.kalshi.feature_schema import MODEL_SCHEMA_VERSION
    from btc5m.venues.kalshi.model_artifacts import build_artifact, save_artifact
    feats = _feats()
    art = build_artifact(
        model_name=model_name, model_obj_dict={"w": [0.0] * len(feats), "b": 0.0},
        feature_names=feats, imputer_dict={"means": [0.0] * len(feats), "stds": [1.0] * len(feats),
                                           "n_features": len(feats)},
        split_metadata={"train_windows": 3, "val_windows": 1}, training_config={"backend": "pure_ml"},
        metrics={}, tradable=tradable, model_schema_version=MODEL_SCHEMA_VERSION,
        calibration_status="uncalibrated", is_diagnostic=(not tradable), is_staged=True,
        series="KXBTC15M", train_window_count=3, test_window_count=1)
    mp = save_artifact(cfg, art, staged=True, stem=f"kalshi_{model_name}_test")
    cal = build_calibrator_artifact(
        calibrator=Calibrator(method="identity", params={}), method=method,
        model_name=(cal_model_name or model_name), split_metadata={"calib_windows": 2},
        metrics_before={"brier": 0.2}, metrics_after={"brier": 0.19}, tradable=calibrated,
        gate_windows=4, is_staged=True, series="KXBTC15M", calibration_window_count=2, test_window_count=1)
    cp = save_calibrator(cfg, cal, staged=True, stem="kalshi_calibrator_test")
    return mp["artifact_file"], cp["calibrator_file"]


# --------------------------------------------------------------------------- #
# Review eligibility
# --------------------------------------------------------------------------- #
def test_review_eligible_with_matching_pair(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg)
    from btc5m.venues.kalshi.paper_promotion import review_promotion
    r = review_promotion(cfg, series="KXBTC15M", model=m, calibrator=c, min_windows=2)
    assert r["eligible_for_paper_promotion"] is True, r["blockers"]
    assert r["recommended_model_artifact"] == m
    assert r["live_submission_allowed"] is False
    # warnings present (edge unproven) but they do NOT block
    assert any("EDGE_UNPROVEN" in w for w in r["warnings"])


def test_review_blocks_when_reports_missing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, reports=False)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg)
    from btc5m.venues.kalshi.paper_promotion import review_promotion
    r = review_promotion(cfg, series="KXBTC15M", model=m, calibrator=c, min_windows=2)
    assert r["eligible_for_paper_promotion"] is False
    assert "EDGE_POLICY_REPORT_MISSING" in r["blockers"]
    assert "FREQUENCY_REPORT_MISSING" in r["blockers"]


def test_review_rejects_diagnostic_model(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg, tradable=False)   # diagnostic
    from btc5m.venues.kalshi.paper_promotion import review_promotion
    r = review_promotion(cfg, series="KXBTC15M", model=m, calibrator=c, min_windows=2)
    assert r["eligible_for_paper_promotion"] is False
    assert "MODEL_DIAGNOSTIC_ONLY" in r["blockers"]


def test_review_rejects_uncalibrated_calibrator(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg, calibrated=False)  # diagnostic calibrator
    from btc5m.venues.kalshi.paper_promotion import review_promotion
    r = review_promotion(cfg, series="KXBTC15M", model=m, calibrator=c, min_windows=2)
    assert r["eligible_for_paper_promotion"] is False
    assert "CALIBRATOR_DIAGNOSTIC_OR_UNCALIBRATED" in r["blockers"]


def test_review_rejects_calibrator_model_mismatch(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg, model_name="microstructure_logistic", cal_model_name="lightgbm_model")
    from btc5m.venues.kalshi.paper_promotion import review_promotion
    r = review_promotion(cfg, series="KXBTC15M", model=m, calibrator=c, min_windows=2)
    assert r["eligible_for_paper_promotion"] is False
    assert any(b.startswith("CALIBRATOR_MODEL_MISMATCH") for b in r["blockers"])


# --------------------------------------------------------------------------- #
# Promote / demote
# --------------------------------------------------------------------------- #
def test_promote_dry_run_writes_no_manifest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg)
    from btc5m.venues.kalshi.paper_promotion import manifest_path, promote
    r = promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=False, min_windows=2)
    assert r["status"] == "DRY_RUN" and r["eligible"] is True
    assert not manifest_path(cfg).exists()             # dry-run writes nothing
    assert r["live_submission_allowed"] is False


def test_promote_write_creates_manifest_paper_only(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg)
    from btc5m.venues.kalshi.model_artifacts import load_artifact
    from btc5m.venues.kalshi.paper_promotion import manifest_path, promote
    r = promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=True, min_windows=2,
                reason="unit test")
    assert r["status"] == "PROMOTED_FOR_PAPER"
    man = json.loads(manifest_path(cfg).read_text(encoding="utf-8"))
    assert man["promoted_for"] == "PAPER_ONLY" and man["live_approved"] is False
    assert man["no_live_orders"] is True and man["is_promoted"] is True
    assert man["model_artifact_sha256"] and man["calibrator_artifact_sha256"]
    # promoted COPIES carry is_promoted=true; staged sources are untouched
    promoted = load_artifact(man["model_artifact_path"])
    assert promoted["is_promoted"] is True and promoted["live_approved"] is False
    assert "/paper_promoted/" in man["model_artifact_path"].replace("\\", "/")
    staged_src = load_artifact(m)
    assert staged_src["is_promoted"] is False           # source not overwritten


def test_runtime_does_not_use_newest_by_mtime(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg)
    from btc5m.venues.kalshi.executable_backtest import latest_model_artifact_path
    from btc5m.venues.kalshi.paper_promotion import promote
    promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=True, min_windows=2)
    # The legacy "active" selector scans data/models/*.pkl (non-recursive): it finds
    # NOTHING here (staged + paper_promoted are subdirs) -> promotion never becomes the
    # newest-by-mtime active artifact.
    assert latest_model_artifact_path(cfg) is None


def test_load_active_promotion_sha_mismatch_blocks(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg)
    from btc5m.venues.kalshi.paper_promotion import load_active_promotion, promote
    r = promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=True, min_windows=2)
    assert load_active_promotion(cfg, series="KXBTC15M")["valid"] is True
    # tamper the promoted model file -> SHA no longer matches the manifest -> blocked
    p = r["manifest"]["model_artifact_path"]
    with open(p, "ab") as fh:
        fh.write(b"x")
    bad = load_active_promotion(cfg, series="KXBTC15M")
    assert bad["valid"] is False and "MODEL_SHA_MISMATCH" in bad["blockers"]


def test_demote_disables_manifest_preserves_artifacts(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg)
    from btc5m.venues.kalshi.paper_promotion import (
        demote, load_active_promotion, manifest_path, promote,
    )
    pr = promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=True, min_windows=2)
    model_copy = pr["manifest"]["model_artifact_path"]
    d = demote(cfg, series="KXBTC15M", write=True)
    assert d["status"] == "DEMOTED"
    assert not manifest_path(cfg).exists()                       # active manifest gone
    from pathlib import Path
    assert Path(model_copy).exists()                             # artifacts preserved
    blocked = load_active_promotion(cfg, series="KXBTC15M")
    assert blocked["valid"] is False and "NO_PROMOTED_PAPER_MODEL" in blocked["blockers"]


# --------------------------------------------------------------------------- #
# Runtime modes
# --------------------------------------------------------------------------- #
def test_runtime_disabled_emits_nothing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg)
    from btc5m.venues.kalshi.paper_promotion import promote
    from btc5m.venues.kalshi.paper_runtime import evaluate_paper_rows
    promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=True, min_windows=2)
    ev = evaluate_paper_rows(cfg, series="KXBTC15M", mode="disabled", limit=10)
    assert ev["status"] == "RUNTIME_DISABLED" and ev["paper_candidates"] == 0
    assert ev["live_submission_allowed"] is False


def test_runtime_shadow_scores_but_never_fills(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg)
    from btc5m.venues.kalshi.paper_promotion import promote
    from btc5m.venues.kalshi.paper_runtime import evaluate_paper_rows
    promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=True, min_windows=2)
    ev = evaluate_paper_rows(cfg, series="KXBTC15M", mode="shadow", limit=10)
    assert ev["status"] == "OK" and ev["paper_candidates"] == 0
    assert ev["decisions"] and all(d["decision_state"] == "SHADOW_DECISION" for d in ev["decisions"])
    assert all(d["live_submission_allowed"] is False for d in ev["decisions"])


def test_runtime_no_manifest_blocks(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    _make_staged(cfg)  # staged exists but NOT promoted
    from btc5m.venues.kalshi.paper_runtime import evaluate_paper_rows
    ev = evaluate_paper_rows(cfg, series="KXBTC15M", mode="shadow", limit=10)
    assert ev["status"] == "NO_PROMOTED_PAPER_MODEL"
    assert "NO_PROMOTED_PAPER_MODEL" in ev["blockers"]


def test_runtime_paper_mode_requires_edge_and_never_live(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg)
    from btc5m.venues.kalshi.paper_promotion import promote
    from btc5m.venues.kalshi.paper_runtime import evaluate_paper_rows
    promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=True, min_windows=2)
    ev = evaluate_paper_rows(cfg, series="KXBTC15M", mode="paper", limit=10)
    assert ev["status"] == "OK" and ev["edge_policy_required"] is True
    # Any PAPER_CANDIDATE must have passed the edge policy (EDGE_OK); none may be live.
    for d in ev["decisions"]:
        assert d["live_submission_allowed"] is False
        if d["decision_state"] == "PAPER_CANDIDATE":
            assert d["edge_policy_state"] == "EDGE_OK"


# --------------------------------------------------------------------------- #
# Audit + safety
# --------------------------------------------------------------------------- #
def test_audit_rows_written_no_live(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg)
    from btc5m.venues.kalshi.paper_promotion import promote
    promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=False, min_windows=2)
    promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=True, min_windows=2)
    audit_files = list((tmp_path / "audit").glob("kalshi_paper_promotion_*.jsonl"))
    assert audit_files
    rows = [json.loads(ln) for ln in audit_files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert rows and all(r["live_approved"] is False and r["user_initiated"] is True for r in rows)
    assert {r["event_type"] for r in rows} >= {"PROMOTE_DRY_RUN", "PROMOTE_WRITE"}


def test_check_live_disabled_passes_with_promotion(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cfg = load_config(mode="paper")
    m, c = _make_staged(cfg)
    from btc5m.cli import main
    from btc5m.venues.kalshi.paper_promotion import promote
    promote(cfg, series="KXBTC15M", model=m, calibrator=c, write=True, min_windows=2)
    assert main(["check-live-disabled"]) == 0   # live still refuses with a promotion active
