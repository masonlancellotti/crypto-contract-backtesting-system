"""Paper-ONLY artifact promotion — explicit, auditable, and NEVER live.

Staged ML artifacts (``data/models/staged/``) are inactive: the runtime never loads
them and never loads "newest .pkl by mtime". This module makes promotion an explicit,
reviewable step:

  staged model + calibrator  ->  promotion review  ->  (explicit) promote
  ->  COPY into data/models/paper_promoted/ (stamped is_promoted=true,
      promoted_for=PAPER_ONLY, live_approved=false)
  ->  write kalshi_paper_promotion_manifest.json (with SHA-256 of each copied file)
  ->  runtime (shadow/paper mode) loads ONLY from this manifest.

Safety invariants:
- ``live_approved`` is NEVER set true here; ``no_live_orders=true`` always.
- Promotion COPIES staged artifacts (never overwrites/moves them).
- The promoted dir is a SUBDIR of data/models, so the legacy non-recursive globs
  (``latest_model_artifact_path`` / ``latest_calibrator_path``) never see it.
- Diagnostic-only or uncalibrated artifacts cannot be promoted.
- A calibrator must match the model it was fit on (model_name family).
- The runtime re-verifies SHA + is_promoted + non-diagnostic + calibrated on load.
- Every action (REVIEW / PROMOTE_DRY_RUN / PROMOTE_WRITE / DEMOTE) is audited.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .calibrate import latest_staged_calibrator_path, load_calibrator
from .executable_backtest import latest_staged_model_artifact_path
from .feature_schema import MODEL_SCHEMA_VERSION
from .model_artifacts import (
    DIAGNOSTIC_ONLY, NON_TRADABLE, PROMOTED_FOR_PAPER, TRADABLE, load_artifact,
)

MANIFEST_NAME = "kalshi_paper_promotion_manifest.json"

# Conservative initial PAPER policy (Part G). Stored in the manifest and applied by
# the paper runtime. These are deliberately strict; never loosened to "get trades".
CONSERVATIVE_POLICY_CONFIG = {
    "min_net_edge_cents": 5,
    "min_final_edge_cents": 2,
    "min_raw_edge_cents": 5,
    "max_trades_per_window": 1,
    "max_daily_trades": 10,
    "cooldown_after_entry_seconds": 30,
    "min_seconds_to_close": 10,
    "max_seconds_to_close": 900,
    "max_book_age_ms": 1000,
    "max_underlying_age_ms": 5000,
    "min_depth_contracts": 1,
    "max_spread_cents": 10,
    "require_edge_policy": True,
    "require_confidence_bounds": True,
    "allow_diagnostic_model": False,
    "allow_uncalibrated_model": False,
}


# --------------------------------------------------------------------------- #
# Paths / hashing / audit
# --------------------------------------------------------------------------- #
def paper_promoted_dir(config) -> Path:
    d = config.data_path() / "models" / "paper_promoted"
    d.mkdir(parents=True, exist_ok=True)
    return d


def manifest_path(config) -> Path:
    return paper_promoted_dir(config) / MANIFEST_NAME


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def audit(config, event_type: str, payload: dict) -> str:
    """Append a sanitized audit row. Never stores secrets; live_approved always false."""
    d = config.data_path() / "audit"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = d / f"kalshi_paper_promotion_{day}.jsonl"
    row = {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_initiated": True,
        "live_approved": False,
        "no_live_orders": True,
        **payload,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    return str(path)


# --------------------------------------------------------------------------- #
# Report discovery (eligibility evidence)
# --------------------------------------------------------------------------- #
def _latest(d: Path, pattern: str) -> Optional[str]:
    if not d.exists():
        return None
    files = sorted(d.glob(pattern), key=lambda p: p.stat().st_mtime)
    return str(files[-1]) if files else None


def _evidence_reports(config) -> dict:
    reports = config.reports_path()
    return {
        "calibration_report_path": _latest(reports / "calibration", "kalshi_calibration_report_*.md"),
        "backtest_report_path": _latest(reports / "backtests", "kalshi_baseline_comparison_*.md")
        or _latest(reports / "backtests", "kalshi_executable_backtest_*.md"),
        "edge_policy_report_path": _latest(reports / "edge", "kalshi_edge_policy_report_*.md"),
        "frequency_report_path": _latest(reports / "frequency", "kalshi_frequency_frontier_*.md"),
    }


# --------------------------------------------------------------------------- #
# Resolve staged paths
# --------------------------------------------------------------------------- #
def _resolve_model(config, model: str) -> Optional[str]:
    if model in ("staged", "latest", None, ""):
        return latest_staged_model_artifact_path(config)
    return model


def _resolve_calibrator(config, calibrator: str) -> Optional[str]:
    if calibrator in ("staged", "latest", None, ""):
        return latest_staged_calibrator_path(config)
    return calibrator


def _gate_windows(config) -> int:
    try:
        from .readiness import load_kalshi_readiness
        return int(load_kalshi_readiness(config).get("gate_windows", 0) or 0)
    except Exception:  # noqa: BLE001
        return 0


# --------------------------------------------------------------------------- #
# Review (read-only eligibility)
# --------------------------------------------------------------------------- #
def review_promotion(config, *, series: str = "KXBTC15M", model: str = "staged",
                     calibrator: str = "staged", min_windows: Optional[int] = None) -> dict:
    """Read-only paper-promotion eligibility review. Never promotes, never trades."""
    min_windows = int(min_windows if min_windows is not None
                      else getattr(config.backtest, "calibration_min_windows", 150))
    model_path = _resolve_model(config, model)
    cal_path = _resolve_calibrator(config, calibrator)
    blockers: list[str] = []
    warnings: list[str] = []

    model_art = cal_art = None
    if not model_path:
        blockers.append("NO_STAGED_MODEL")
    else:
        try:
            model_art = load_artifact(model_path)
        except Exception as exc:  # noqa: BLE001
            blockers.append(f"MODEL_LOAD_ERROR:{type(exc).__name__}")
    if not cal_path:
        blockers.append("NO_STAGED_CALIBRATOR")
    else:
        try:
            cal_art = load_calibrator(cal_path)
        except Exception as exc:  # noqa: BLE001
            blockers.append(f"CALIBRATOR_LOAD_ERROR:{type(exc).__name__}")

    gate_windows = _gate_windows(config)
    reports = _evidence_reports(config)

    # ---- model checks ----
    if model_art is not None:
        if model_art.get("is_diagnostic") or model_art.get("tradability") == NON_TRADABLE:
            blockers.append("MODEL_DIAGNOSTIC_ONLY")
        if not (model_art.get("is_staged") or model_art.get("is_promoted")):
            blockers.append("MODEL_NOT_STAGED_OR_PROMOTED")
        if model_art.get("model_schema_version") != MODEL_SCHEMA_VERSION:
            blockers.append("MODEL_SCHEMA_MISMATCH")
        if model_art.get("live_approved"):
            blockers.append("MODEL_LIVE_APPROVED_FORBIDDEN")  # never promote a live-approved artifact here

    # ---- calibrator checks ----
    if cal_art is not None:
        if cal_art.get("calibration_status") != "calibrated" or cal_art.get("NON_TRADABLE_DIAGNOSTIC_ONLY"):
            blockers.append("CALIBRATOR_DIAGNOSTIC_OR_UNCALIBRATED")
        if not (cal_art.get("is_staged") or cal_art.get("is_promoted")):
            blockers.append("CALIBRATOR_NOT_STAGED_OR_PROMOTED")

    # ---- model <-> calibrator compatibility ----
    if model_art is not None and cal_art is not None:
        m_name = model_art.get("model_name")
        c_name = cal_art.get("model_name")
        if c_name and m_name and c_name != m_name:
            blockers.append(f"CALIBRATOR_MODEL_MISMATCH(model={m_name},calibrator_fit_on={c_name})")

    # ---- gate + evidence reports ----
    if gate_windows < min_windows:
        blockers.append(f"GATE_WINDOWS_BELOW_MIN({gate_windows}<{min_windows})")
    for key, label in (("calibration_report_path", "CALIBRATION_REPORT_MISSING"),
                       ("backtest_report_path", "BACKTEST_REPORT_MISSING"),
                       ("edge_policy_report_path", "EDGE_POLICY_REPORT_MISSING"),
                       ("frequency_report_path", "FREQUENCY_REPORT_MISSING")):
        if not reports.get(key):
            blockers.append(label)

    # ---- warnings (do NOT block; edge is allowed to be unproven) ----
    if cal_art is not None and cal_art.get("method") == "isotonic":
        cw = (cal_art.get("calibration_window_count")
              or (cal_art.get("split_metadata") or {}).get("calib_windows"))
        if cw is not None and cw < 60:
            warnings.append(f"ISOTONIC_OVERFIT_RISK(calib_windows={cw}); prefer platt/sigmoid")
    warnings.append("EDGE_UNPROVEN: backtests are diagnostic; market-implied baseline is strong "
                    "(model edge over market is small). Paper promotion is NOT proof of profitability.")
    warnings.append("EDGE_POLICY_CONCENTRATION: confirm EDGE_OK trades are not concentrated in a few "
                    "windows or net-negative before trusting paper candidates.")

    eligible = not blockers
    return {
        "series": series,
        "eligible_for_paper_promotion": eligible,
        "recommended_model_artifact": model_path if eligible else None,
        "recommended_calibrator_artifact": cal_path if eligible else None,
        "model_artifact_path": model_path,
        "calibrator_artifact_path": cal_path,
        "model_meta": _meta(model_art),
        "calibrator_meta": _cal_meta(cal_art),
        "gate_windows": gate_windows,
        "min_windows": min_windows,
        "evidence_reports": reports,
        "recommended_policy_config": dict(CONSERVATIVE_POLICY_CONFIG),
        "blockers": blockers,
        "warnings": warnings,
        "why_no_live": ("Promotion is PAPER_ONLY: live_approved=false, no_live_orders=true, and the "
                        "live adapter refuses unconditionally. Live requires a SEPARATE, explicit "
                        "approval step that is intentionally not implemented here."),
        "live_submission_allowed": False,
    }


def _meta(art: Optional[dict]) -> dict:
    if not art:
        return {}
    return {k: art.get(k) for k in (
        "model_name", "model_type", "model_backend", "tradability", "tradable", "is_diagnostic",
        "is_staged", "is_promoted", "tradable_status", "calibration_status", "model_schema_version",
        "live_approved", "created_at", "created_by_command", "train_window_count", "test_window_count")}


def _cal_meta(art: Optional[dict]) -> dict:
    if not art:
        return {}
    return {k: art.get(k) for k in (
        "model_name", "method", "calibration_status", "tradable", "NON_TRADABLE_DIAGNOSTIC_ONLY",
        "is_staged", "is_promoted", "tradable_status", "live_approved", "calibration_window_count",
        "test_window_count", "gate_windows", "created_at", "metrics_before", "metrics_after")}


# --------------------------------------------------------------------------- #
# Promote (dry-run default; --write copies + writes manifest)
# --------------------------------------------------------------------------- #
def promote(config, *, series: str = "KXBTC15M", model: str = "staged", calibrator: str = "staged",
            write: bool = False, reason: str = "", min_windows: Optional[int] = None,
            created_by_command: str = "kalshi-promote-paper-artifacts") -> dict:
    """Review eligibility then (only with ``write=True`` AND eligible) write the
    PAPER_ONLY promotion manifest after copying the artifacts. Default is dry-run."""
    rv = review_promotion(config, series=series, model=model, calibrator=calibrator,
                          min_windows=min_windows)
    out = {"series": series, "write": bool(write), "eligible": rv["eligible_for_paper_promotion"],
           "blockers": rv["blockers"], "warnings": rv["warnings"],
           "model_artifact_path": rv["model_artifact_path"],
           "calibrator_artifact_path": rv["calibrator_artifact_path"],
           "live_submission_allowed": False}

    if not rv["eligible_for_paper_promotion"]:
        out["status"] = "REFUSED_NOT_ELIGIBLE"
        out["audit_file"] = audit(config, "PROMOTE_DRY_RUN" if not write else "PROMOTE_WRITE", {
            "series": series, "result": "REFUSED_NOT_ELIGIBLE", "blockers": rv["blockers"],
            "warnings": rv["warnings"], "model_path": rv["model_artifact_path"],
            "calibrator_path": rv["calibrator_artifact_path"]})
        return out

    planned = _build_manifest(config, series=series, model_path=rv["model_artifact_path"],
                              calibrator_path=rv["calibrator_artifact_path"], reports=rv["evidence_reports"],
                              gate_windows=rv["gate_windows"], reason=reason,
                              created_by_command=created_by_command, model_meta=rv["model_meta"],
                              cal_meta=rv["calibrator_meta"], copied=False)
    if not write:
        out["status"] = "DRY_RUN"
        out["planned_manifest"] = planned
        out["audit_file"] = audit(config, "PROMOTE_DRY_RUN", {
            "series": series, "result": "DRY_RUN", "model_path": rv["model_artifact_path"],
            "calibrator_path": rv["calibrator_artifact_path"],
            "model_sha256": planned["model_artifact_sha256_source"],
            "calibrator_sha256": planned["calibrator_artifact_sha256_source"]})
        return out

    # ---- WRITE: copy artifacts (stamped promoted) + write manifest ----
    d = paper_promoted_dir(config)
    model_dst = d / f"paper_model_{series}_{_ts()}.pkl"
    cal_dst = d / f"paper_calibrator_{series}_{_ts()}.pkl"
    _copy_stamped(rv["model_artifact_path"], model_dst, series=series, created_by_command=created_by_command)
    _copy_stamped(rv["calibrator_artifact_path"], cal_dst, series=series, created_by_command=created_by_command)

    manifest = _build_manifest(config, series=series, model_path=str(model_dst),
                               calibrator_path=str(cal_dst), reports=rv["evidence_reports"],
                               gate_windows=rv["gate_windows"], reason=reason,
                               created_by_command=created_by_command, model_meta=rv["model_meta"],
                               cal_meta=rv["calibrator_meta"], copied=True,
                               source_model=rv["model_artifact_path"], source_calibrator=rv["calibrator_artifact_path"])
    mp = manifest_path(config)
    mp.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    out["status"] = "PROMOTED_FOR_PAPER"
    out["manifest_path"] = str(mp)
    out["manifest"] = manifest
    out["audit_file"] = audit(config, "PROMOTE_WRITE", {
        "series": series, "result": "PROMOTED_FOR_PAPER", "manifest_path": str(mp),
        "model_path": str(model_dst), "model_sha256": manifest["model_artifact_sha256"],
        "calibrator_path": str(cal_dst), "calibrator_sha256": manifest["calibrator_artifact_sha256"],
        "source_model": rv["model_artifact_path"], "source_calibrator": rv["calibrator_artifact_path"],
        "promotion_reason": reason, "warnings": rv["warnings"]})
    return out


def _copy_stamped(src: str, dst: Path, *, series: str, created_by_command: str) -> None:
    """COPY a staged artifact into the promoted dir, stamping promotion metadata.

    Re-pickles (not move) so the staged source is untouched and the promoted copy
    carries is_promoted=true / PROMOTED_FOR_PAPER / live_approved=false."""
    with open(src, "rb") as fh:
        art = pickle.load(fh)
    art = dict(art)
    art["is_promoted"] = True
    art["is_staged"] = False
    art["promoted_for"] = "PAPER_ONLY"
    art["tradable_status"] = PROMOTED_FOR_PAPER
    art["live_approved"] = False
    art["promoted_at"] = datetime.now(timezone.utc).isoformat()
    art["promoted_by_command"] = created_by_command
    art["promoted_series"] = series
    art["source_artifact_path"] = str(src)
    with dst.open("wb") as fh:
        pickle.dump(art, fh)


def _build_manifest(config, *, series, model_path, calibrator_path, reports, gate_windows,
                    reason, created_by_command, model_meta, cal_meta, copied: bool,
                    source_model: Optional[str] = None, source_calibrator: Optional[str] = None) -> dict:
    sm = (model_meta or {})
    cm = (cal_meta or {})
    schema = _latest(config.data_path() / "models" / "staged", "kalshi_feature_schema_*.json") \
        or str(config.data_path() / "models" / "kalshi_feature_schema.json")
    m = {
        "series": series,
        "promoted_for": "PAPER_ONLY",
        "live_approved": False,
        "is_promoted": True,
        "no_live_orders": True,
        "model_artifact_path": model_path,
        "calibrator_artifact_path": calibrator_path,
        "model_artifact_sha256": (sha256_file(model_path) if copied else None),
        "calibrator_artifact_sha256": (sha256_file(calibrator_path) if copied else None),
        # source (staged) hashes for provenance / dry-run preview
        "model_artifact_sha256_source": sha256_file(source_model or model_path),
        "calibrator_artifact_sha256_source": sha256_file(source_calibrator or calibrator_path),
        "source_model_path": source_model or model_path,
        "source_calibrator_path": source_calibrator or calibrator_path,
        "model_type": sm.get("model_type") or sm.get("model_name"),
        "calibrator_type": cm.get("method"),
        "model_version": sm.get("created_at"),
        "calibrator_version": cm.get("created_at"),
        "model_name": sm.get("model_name"),
        "dataset_path": "(in-memory build_model_dataset at score time)",
        "feature_schema_path": schema,
        "feature_schema_version": sm.get("model_schema_version"),
        "train_windows": sm.get("train_window_count"),
        "calibration_windows": cm.get("calibration_window_count"),
        "test_windows": sm.get("test_window_count") or cm.get("test_window_count"),
        "backtest_report_path": reports.get("backtest_report_path"),
        "calibration_report_path": reports.get("calibration_report_path"),
        "edge_policy_report_path": reports.get("edge_policy_report_path"),
        "frequency_report_path": reports.get("frequency_report_path"),
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "promoted_by_command": created_by_command,
        "promotion_reason": reason or "(none provided)",
        "safety_notes": ("PAPER_ONLY. live_approved=false. Runtime loads ONLY this manifest in "
                         "shadow/paper mode; staged + newest-by-mtime artifacts are never used. "
                         "Promotion is not proof of profitability."),
        "conservative_policy_config": dict(CONSERVATIVE_POLICY_CONFIG),
        "max_daily_trades": CONSERVATIVE_POLICY_CONFIG["max_daily_trades"],
        "max_trades_per_window": CONSERVATIVE_POLICY_CONFIG["max_trades_per_window"],
        "min_net_edge_cents": CONSERVATIVE_POLICY_CONFIG["min_net_edge_cents"],
        "min_final_edge_cents": CONSERVATIVE_POLICY_CONFIG["min_final_edge_cents"],
        "max_book_age_ms": CONSERVATIVE_POLICY_CONFIG["max_book_age_ms"],
        "max_underlying_age_ms": CONSERVATIVE_POLICY_CONFIG["max_underlying_age_ms"],
    }
    return m


# --------------------------------------------------------------------------- #
# Demote (rollback)
# --------------------------------------------------------------------------- #
def demote(config, *, series: str = "KXBTC15M", write: bool = False,
           created_by_command: str = "kalshi-demote-paper-artifacts") -> dict:
    """Disable the active paper promotion (preserves artifacts). Dry-run by default."""
    mp = manifest_path(config)
    exists = mp.exists()
    out = {"series": series, "write": bool(write), "manifest_path": str(mp),
           "manifest_existed": exists, "live_submission_allowed": False}
    if not exists:
        out["status"] = "NO_ACTIVE_PROMOTION"
        out["audit_file"] = audit(config, "DEMOTE", {"series": series, "result": "NO_ACTIVE_PROMOTION"})
        return out
    if not write:
        out["status"] = "DRY_RUN_WOULD_DEMOTE"
        out["audit_file"] = audit(config, "DEMOTE", {"series": series, "result": "DRY_RUN_WOULD_DEMOTE",
                                                     "manifest_path": str(mp)})
        return out
    # Preserve artifacts; rename the manifest so the runtime finds no active promotion.
    disabled = mp.with_name(f"kalshi_paper_promotion_manifest.demoted-{_ts()}.json")
    mp.rename(disabled)
    out["status"] = "DEMOTED"
    out["disabled_manifest_path"] = str(disabled)
    out["audit_file"] = audit(config, "DEMOTE", {"series": series, "result": "DEMOTED",
                                                "disabled_manifest_path": str(disabled)})
    return out


# --------------------------------------------------------------------------- #
# Load active promotion (runtime; verifies SHA + promoted + non-diagnostic)
# --------------------------------------------------------------------------- #
def load_active_promotion(config, *, series: str = "KXBTC15M") -> dict:
    """Load + verify the active paper promotion. Returns a dict with ``valid`` and,
    when valid, the loaded model/calibrator artifacts. Never raises."""
    mp = manifest_path(config)
    if not mp.exists():
        return {"valid": False, "exists": False, "blockers": ["NO_PROMOTED_PAPER_MODEL"], "manifest": None}
    try:
        manifest = json.loads(mp.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"valid": False, "exists": True, "blockers": [f"MANIFEST_PARSE_ERROR:{type(exc).__name__}"],
                "manifest": None}
    blockers: list[str] = []
    if manifest.get("series") != series:
        blockers.append(f"MANIFEST_SERIES_MISMATCH({manifest.get('series')}!={series})")
    if manifest.get("live_approved"):
        blockers.append("MANIFEST_LIVE_APPROVED_FORBIDDEN")
    mpath = manifest.get("model_artifact_path")
    cpath = manifest.get("calibrator_artifact_path")
    model_art = cal_art = None
    if not mpath or not Path(mpath).exists():
        blockers.append("PROMOTED_MODEL_FILE_MISSING")
    elif sha256_file(mpath) != manifest.get("model_artifact_sha256"):
        blockers.append("MODEL_SHA_MISMATCH")
    else:
        try:
            model_art = load_artifact(mpath)
        except Exception as exc:  # noqa: BLE001
            blockers.append(f"MODEL_LOAD_ERROR:{type(exc).__name__}")
    if not cpath or not Path(cpath).exists():
        blockers.append("PROMOTED_CALIBRATOR_FILE_MISSING")
    elif sha256_file(cpath) != manifest.get("calibrator_artifact_sha256"):
        blockers.append("CALIBRATOR_SHA_MISMATCH")
    else:
        try:
            cal_art = load_calibrator(cpath)
        except Exception as exc:  # noqa: BLE001
            blockers.append(f"CALIBRATOR_LOAD_ERROR:{type(exc).__name__}")

    if model_art is not None:
        if not model_art.get("is_promoted"):
            blockers.append("MODEL_NOT_PROMOTED")
        if model_art.get("is_diagnostic") or model_art.get("tradability") == NON_TRADABLE:
            blockers.append("MODEL_DIAGNOSTIC_ONLY")
        if model_art.get("live_approved"):
            blockers.append("MODEL_LIVE_APPROVED_FORBIDDEN")
    if cal_art is not None:
        if not cal_art.get("is_promoted"):
            blockers.append("CALIBRATOR_NOT_PROMOTED")
        if cal_art.get("calibration_status") != "calibrated" or cal_art.get("NON_TRADABLE_DIAGNOSTIC_ONLY"):
            blockers.append("CALIBRATOR_DIAGNOSTIC_OR_UNCALIBRATED")

    return {
        "valid": (not blockers),
        "exists": True,
        "blockers": blockers,
        "manifest": manifest,
        "manifest_path": str(mp),
        "model_artifact": model_art,
        "calibrator_artifact": cal_art,
        "model_path": mpath,
        "calibrator_path": cpath,
    }
