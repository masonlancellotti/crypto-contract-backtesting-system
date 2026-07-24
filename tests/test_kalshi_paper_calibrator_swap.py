"""PAPER-ONLY calibrator swap (review / dry-run / write / rollback).

Covers eligibility, the pure manifest builder (model + gates preserved), dry-run writing no
manifest, write updating only the calibrator + manifest with rollback provenance, rollback
restoring the previous manifest, paper/live flags + edge thresholds unchanged, and the runtime
loading the manifest (not newest-by-mtime). Offline; nothing live.
"""

import json
import pickle
from pathlib import Path


from btc5m.config import load_config
from btc5m.venues.kalshi import paper_calibrator_swap as sw
from btc5m.venues.kalshi.edge_policy import EdgePolicyConfig
from btc5m.venues.kalshi.paper_promotion import load_active_promotion, manifest_path, sha256_file

SERIES = "KXBTC15M"


def _setup_promoted(tmp_path, monkeypatch):
    """Create a tmp paper-promoted model + isotonic calibrator + manifest + a staged identity candidate."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    pp = tmp_path / "data" / "models" / "paper_promoted"
    pp.mkdir(parents=True, exist_ok=True)
    staged = tmp_path / "data" / "models" / "staged"
    staged.mkdir(parents=True, exist_ok=True)

    model_p = pp / "paper_model_KXBTC15M_T.pkl"
    model_p.write_bytes(pickle.dumps({"is_promoted": True, "is_diagnostic": False,
                                      "tradability": "TRADABLE", "live_approved": False,
                                      "model_name": "microstructure_logistic"}))
    cal_p = pp / "paper_calibrator_KXBTC15M_T.pkl"
    cal_p.write_bytes(pickle.dumps({"is_promoted": True, "calibration_status": "calibrated",
                                    "NON_TRADABLE_DIAGNOSTIC_ONLY": False, "model_name": "microstructure_logistic",
                                    "calibrator": {"method": "isotonic", "params": {"thresh": []}}}))
    manifest = {
        "series": SERIES, "promoted_for": "PAPER_ONLY", "live_approved": False, "is_promoted": True,
        "no_live_orders": True, "model_artifact_path": str(model_p),
        "calibrator_artifact_path": str(cal_p),
        "model_artifact_sha256": sha256_file(model_p), "calibrator_artifact_sha256": sha256_file(cal_p),
        "model_type": "microstructure_logistic:sklearn", "calibrator_type": "isotonic",
        "model_name": "microstructure_logistic",
        "conservative_policy_config": {"min_net_edge_cents": 5, "min_final_edge_cents": 2,
                                       "min_raw_edge_cents": 5, "require_edge_policy": True},
        "min_final_edge_cents": 2,
    }
    manifest_path(cfg).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # a staged identity candidate that is clearly safer than the promoted isotonic
    cand = staged / "kalshi_replacement_identity_raw_T.pkl"
    cand.write_bytes(pickle.dumps({
        "artifact_type": "calibrator_replacement", "calibrator": {"method": "identity", "params": {}},
        "method": "identity", "calibrator_method": "identity", "model_name": "microstructure_logistic",
        "is_staged": True, "is_promoted": False, "live_approved": False,
        "metrics_before": {"ece_window": 0.106, "brier": 0.137, "yes_overprediction_cents": 8.4},
        "metrics_after": {"ece_window": 0.051, "brier": 0.126, "yes_overprediction_cents": -1.3}}))
    return cfg, model_p, cal_p


# --------------------------------------------------------------------------- #
# eligibility + pure manifest builder
# --------------------------------------------------------------------------- #
def test_candidate_eligibility():
    safer = {"is_staged": True, "is_promoted": False, "live_approved": False,
             "metrics_before": {"ece_window": 0.106, "brier": 0.137, "yes_overprediction_cents": 8.4},
             "metrics_after": {"ece_window": 0.051, "brier": 0.126, "yes_overprediction_cents": -1.3}}
    e = sw.candidate_eligibility(safer)
    assert e["eligible"] and e["better_window_ece"] and e["reduces_yes_overprediction"] and not e["blockers"]
    worse = {"is_staged": True, "is_promoted": False, "live_approved": False,
             "metrics_before": {"ece_window": 0.04, "brier": 0.10, "yes_overprediction_cents": 0.5},
             "metrics_after": {"ece_window": 0.09, "brier": 0.13, "yes_overprediction_cents": 8.0}}
    e2 = sw.candidate_eligibility(worse)
    assert not e2["eligible"] and "does_not_improve_window_ece" in e2["blockers"]


def test_build_swap_manifest_preserves_model_and_gates():
    cur = {"series": SERIES, "model_artifact_path": "/m.pkl", "model_artifact_sha256": "MODELSHA",
           "calibrator_artifact_path": "/old_cal.pkl", "calibrator_artifact_sha256": "OLDSHA",
           "calibrator_type": "isotonic", "live_approved": False,
           "conservative_policy_config": {"min_final_edge_cents": 2, "require_edge_policy": True}}
    m = sw.build_swap_manifest(cur, new_cal_path="/new_cal.pkl", new_cal_sha="NEWSHA",
                               candidate="identity_raw", method="identity", reason=sw.REPLACEMENT_REASON,
                               staged_source="/staged.pkl", preswap_backup_path="/backup.json")
    # model + gates preserved
    assert m["model_artifact_path"] == "/m.pkl" and m["model_artifact_sha256"] == "MODELSHA"
    assert m["conservative_policy_config"] == cur["conservative_policy_config"]
    # only calibrator changed
    assert m["calibrator_artifact_path"] == "/new_cal.pkl" and m["calibrator_type"] == "identity"
    # rollback provenance + paper-only safety
    assert m["previous_calibrator_artifact_path"] == "/old_cal.pkl" and m["previous_calibrator_artifact_sha256"] == "OLDSHA"
    assert m["pre_swap_manifest_backup_path"] == "/backup.json" and m["calibrator_swapped"] is True
    assert m["live_approved"] is False and m["no_live_orders"] is True
    assert m["calibrator_swap_reason"] == sw.REPLACEMENT_REASON


# --------------------------------------------------------------------------- #
# dry-run writes nothing
# --------------------------------------------------------------------------- #
def test_dry_run_writes_no_manifest(tmp_path, monkeypatch):
    cfg, _model_p, _cal_p = _setup_promoted(tmp_path, monkeypatch)
    before = manifest_path(cfg).read_text(encoding="utf-8")
    r = sw.swap_dry_run(cfg, series=SERIES, candidate="identity_raw")
    assert r["status"] == "DRY_RUN" and r["manifest_written"] is False
    assert r["eligibility"]["eligible"] is True
    assert r["planned_manifest"]["calibrator_type"] == "identity"
    assert r["paper_disabled"] and r["live_disabled"] and r["live_submission_allowed"] is False
    assert manifest_path(cfg).read_text(encoding="utf-8") == before    # unchanged on disk
    assert r["runtime_unchanged"] is True


# --------------------------------------------------------------------------- #
# write updates only the calibrator + manifest; model preserved; reversible
# --------------------------------------------------------------------------- #
def test_write_updates_only_calibrator_and_is_reversible(tmp_path, monkeypatch):
    cfg, model_p, old_cal = _setup_promoted(tmp_path, monkeypatch)
    model_sha_before = sha256_file(model_p)
    old_cal_sha = sha256_file(old_cal)
    # edge-policy + runtime-mode snapshots (must be unchanged by the swap)
    edge_before = EdgePolicyConfig.from_app(cfg).__dict__.copy()
    mode_before = cfg.model_runtime_mode

    r = sw.swap_write(cfg, series=SERIES, candidate="identity_raw")
    assert r["status"] == "PAPER_CALIBRATOR_SWAPPED" and r["live_submission_allowed"] is False
    man = json.loads(manifest_path(cfg).read_text(encoding="utf-8"))
    # calibrator changed, model preserved
    assert man["calibrator_type"] == "identity"
    assert man["model_artifact_path"] == str(model_p) and man["model_artifact_sha256"] == model_sha_before
    assert sha256_file(model_p) == model_sha_before                    # model file untouched
    # gates preserved
    assert man["conservative_policy_config"]["min_final_edge_cents"] == 2
    # rollback provenance recorded
    assert man["previous_calibrator_artifact_path"] == str(old_cal)
    assert man["previous_calibrator_artifact_sha256"] == old_cal_sha
    assert Path(man["pre_swap_manifest_backup_path"]).exists()
    # paper-only safety
    assert man["live_approved"] is False and man["no_live_orders"] is True
    assert r["new_promotion_valid"] is True                            # runtime can load the new manifest
    # the runtime loads from the MANIFEST (not newest-by-mtime): calibrator method == identity
    promo = load_active_promotion(cfg, series=SERIES)
    assert promo["valid"] and (promo["calibrator_artifact"].get("calibrator") or {}).get("method") == "identity"
    # paper/live flags + edge thresholds unchanged
    cfg2 = load_config(mode="paper")
    assert cfg2.model_runtime_mode == mode_before                      # not set to paper
    assert not cfg2.paper_policy.enabled
    assert EdgePolicyConfig.from_app(cfg2).__dict__ == edge_before     # edge gates unchanged

    # rollback restores the previous (isotonic) calibrator
    rb = sw.swap_rollback(cfg, series=SERIES, write=True)
    assert rb["status"] == "ROLLED_BACK"
    man2 = json.loads(manifest_path(cfg).read_text(encoding="utf-8"))
    assert man2["calibrator_type"] == "isotonic" and not man2.get("calibrator_swapped")
    assert man2["calibrator_artifact_path"] == str(old_cal)


def test_rollback_dry_run_and_nothing_to_rollback(tmp_path, monkeypatch):
    cfg, _m, _c = _setup_promoted(tmp_path, monkeypatch)
    r = sw.swap_rollback(cfg, series=SERIES, write=False)             # no swap yet
    assert r["status"] == "NOTHING_TO_ROLLBACK"
    sw.swap_write(cfg, series=SERIES, candidate="identity_raw")
    r2 = sw.swap_rollback(cfg, series=SERIES, write=False)            # dry-run after a swap
    assert r2["status"] == "DRY_RUN_WOULD_ROLLBACK" and r2["can_restore"] is True
    assert json.loads(manifest_path(cfg).read_text())["calibrator_type"] == "identity"  # not yet restored


def test_write_refuses_ineligible(tmp_path, monkeypatch):
    cfg, _m, _c = _setup_promoted(tmp_path, monkeypatch)
    # overwrite the staged candidate with a clearly-worse one
    staged = tmp_path / "data" / "models" / "staged" / "kalshi_replacement_identity_raw_T.pkl"
    staged.write_bytes(pickle.dumps({
        "calibrator": {"method": "identity", "params": {}}, "model_name": "microstructure_logistic",
        "is_staged": True, "is_promoted": False, "live_approved": False,
        "metrics_before": {"ece_window": 0.04, "brier": 0.10, "yes_overprediction_cents": 0.5},
        "metrics_after": {"ece_window": 0.09, "brier": 0.13, "yes_overprediction_cents": 8.0}}))
    before = manifest_path(cfg).read_text(encoding="utf-8")
    r = sw.swap_write(cfg, series=SERIES, candidate="identity_raw")
    assert r["status"] == "REFUSED_NOT_ELIGIBLE"
    assert manifest_path(cfg).read_text(encoding="utf-8") == before    # manifest untouched


def test_cli_commands_registered():
    import btc5m.cli as c
    for name in ("kalshi-paper-calibrator-swap-review", "kalshi-paper-calibrator-swap",
                 "kalshi-paper-calibrator-swap-rollback"):
        assert name in c._COMMANDS and callable(c._COMMANDS[name])


def test_check_live_disabled_holds(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    cfg = load_config(mode="paper")
    assert cfg.live_blockers() and cfg.live_permitted is False
