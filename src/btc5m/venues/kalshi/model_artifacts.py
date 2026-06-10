"""Kalshi model artifact save/load + tradability gating + model card.

An artifact bundles the fitted model params, the feature schema, the imputer/
standardizer, split metadata, training config, and metrics. Artifacts trained
below the gate or in diagnostic mode are stamped
``NON_TRADABLE_DIAGNOSTIC_ONLY`` and :func:`is_tradable` returns False — the
paper/live policy must call :func:`is_tradable` and refuse non-tradable models.
Even a TRADABLE-stamped artifact is still uncalibrated until a separate
calibration step runs, so PAPER_CANDIDATE stays blocked here regardless.
"""

from __future__ import annotations

import json
import pickle
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

TRADABLE = "TRADABLE"
NON_TRADABLE = "NON_TRADABLE_DIAGNOSTIC_ONLY"

# Artifact lifecycle states (see PART L). New artifacts are STAGED_NON_PROMOTED or
# DIAGNOSTIC_ONLY; PROMOTED_FOR_PAPER requires a SEPARATE, explicit promotion step
# (not performed here). Live is never approved by training/calibration.
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
STAGED_NON_PROMOTED = "STAGED_NON_PROMOTED"
PROMOTED_FOR_PAPER = "PROMOTED_FOR_PAPER"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def models_dir(config) -> Path:
    """The ACTIVE models dir the runtime scans (data/models, NON-recursive)."""
    d = config.data_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def staged_models_dir(config) -> Path:
    """Staging dir for NON-PROMOTED artifacts.

    The runtime (policy_runtime / lock_runtime / executable_backtest) globs
    ``data/models/*.pkl`` NON-recursively, so artifacts written here are INVISIBLE
    to runtime auto-selection until an explicit (future) promotion moves them. This
    is the safety boundary: training/calibration write here by default.
    """
    d = config.data_path() / "models" / "staged"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _git_info() -> dict:
    """Best-effort, non-fatal git status (repo may not be a git repo)."""
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=3)
        if rev.returncode != 0:
            return {"git": "not_a_git_repo_or_unavailable"}
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                               text=True, timeout=3)
        return {"git_commit": rev.stdout.strip(), "git_dirty": bool(dirty.stdout.strip())}
    except Exception:  # noqa: BLE001
        return {"git": "unavailable"}


def tradable_status_for(*, is_diagnostic: bool, is_staged: bool, is_promoted: bool) -> str:
    if is_diagnostic:
        return DIAGNOSTIC_ONLY
    if is_promoted:
        return PROMOTED_FOR_PAPER
    return STAGED_NON_PROMOTED


def build_artifact(
    *, model_name: str, model_obj_dict: Optional[dict], feature_names: list[str],
    imputer_dict: Optional[dict], split_metadata: dict, training_config: dict,
    metrics: dict, tradable: bool, model_schema_version: int,
    calibration_status: str = "uncalibrated", notes: str = "",
    artifact_type: str = "model", model_type: Optional[str] = None,
    series: Optional[str] = None, dataset_path: Optional[str] = None,
    feature_schema_path: Optional[str] = None, train_window_count: Optional[int] = None,
    calibration_window_count: Optional[int] = None, test_window_count: Optional[int] = None,
    is_diagnostic: Optional[bool] = None, is_staged: bool = True,
    created_by_command: Optional[str] = None,
) -> dict:
    is_diag = (not tradable) if is_diagnostic is None else bool(is_diagnostic)
    is_promoted = False  # promotion is a SEPARATE explicit step, never done here
    return {
        "model_name": model_name,
        "artifact_type": artifact_type,
        "model_type": model_type or model_name,
        "tradability": TRADABLE if tradable else NON_TRADABLE,
        "tradable": bool(tradable),
        "calibration_status": calibration_status,
        # ----- lifecycle / staging safety (PART L) -----
        "is_diagnostic": is_diag,
        "is_staged": bool(is_staged),
        "is_promoted": is_promoted,
        "promotion_required": True,
        "tradable_status": tradable_status_for(is_diagnostic=is_diag, is_staged=is_staged,
                                               is_promoted=is_promoted),
        "live_approved": False,
        "created_by_command": created_by_command,
        "series": series,
        "dataset_path": dataset_path,
        "feature_schema_path": feature_schema_path,
        "train_window_count": train_window_count,
        "calibration_window_count": calibration_window_count,
        "test_window_count": test_window_count,
        # ----- model payload + provenance -----
        "model": model_obj_dict,
        "feature_names": feature_names,
        "imputer": imputer_dict,
        "split_metadata": split_metadata,
        "training_config": training_config,
        "metrics": metrics,
        "model_schema_version": model_schema_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
        **_git_info(),
        "notes": notes,
    }


def save_artifact(config, artifact: dict, *, stem: Optional[str] = None,
                  staged: bool = False) -> dict:
    """Persist the artifact (.pkl) + a sidecar JSON summary. Returns paths.

    ``staged=True`` writes to ``data/models/staged/`` (INVISIBLE to runtime
    auto-selection) — the safe default for training in this build.
    """
    d = staged_models_dir(config) if staged else models_dir(config)
    stamp = _ts()
    stem = stem or f"kalshi_{artifact['model_name']}_{stamp}"
    artifact = {**artifact, "is_staged": bool(staged),
                "tradable_status": tradable_status_for(
                    is_diagnostic=bool(artifact.get("is_diagnostic", not artifact.get("tradable"))),
                    is_staged=bool(staged), is_promoted=bool(artifact.get("is_promoted", False)))}
    pkl_path = d / f"{stem}.pkl"
    with pkl_path.open("wb") as fh:
        pickle.dump(artifact, fh)
    summary = {k: v for k, v in artifact.items()
               if k not in ("model", "imputer", "sklearn_pipeline")}
    json_path = d / f"{stem}.json"
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
    return {"artifact_file": str(pkl_path), "summary_file": str(json_path),
            "staged": bool(staged), "tradable_status": artifact["tradable_status"]}


def load_artifact(path: str | Path) -> dict:
    with open(path, "rb") as fh:
        return pickle.load(fh)


def is_tradable(artifact: dict) -> bool:
    """A model is tradable ONLY if explicitly stamped TRADABLE *and* calibrated.

    Diagnostic/insufficient-data artifacts and any uncalibrated artifact return
    False, so paper/live decisioning can never promote them to PAPER_CANDIDATE.
    """
    return bool(artifact.get("tradable")
                and artifact.get("tradability") == TRADABLE
                and artifact.get("calibration_status") == "calibrated")


def write_model_card(config, artifact: dict, *, stem: Optional[str] = None) -> str:
    d = config.reports_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    stem = stem or f"kalshi_model_card_{stamp}"
    path = d / f"{stem}.md"
    m = artifact.get("metrics", {})
    sm = artifact.get("split_metadata", {})
    lines = [
        f"# Kalshi model card — {artifact['model_name']}", "",
        f"- tradability: **{artifact['tradability']}**",
        f"- tradable (usable by paper/live policy): **{artifact['tradable'] and is_tradable(artifact)}**",
        f"- lifecycle: **{artifact.get('tradable_status')}**  "
        f"(is_staged={artifact.get('is_staged')} is_promoted={artifact.get('is_promoted')} "
        f"promotion_required={artifact.get('promotion_required')} live_approved={artifact.get('live_approved')})",
        f"- model_backend: {artifact.get('model_backend', artifact.get('training_config', {}).get('backend'))}",
        f"- created_by_command: {artifact.get('created_by_command')}",
        f"- calibration_status: {artifact.get('calibration_status')}",
        f"- created_at: {artifact.get('created_at')}  created_at_ms: {artifact.get('created_at_ms')}",
        f"- model_schema_version: {artifact.get('model_schema_version')}",
        "", "## Intended use",
        "- Estimate P(YES resolves to 1) for Kalshi BTC 15m markets.",
        "- Output is a PROBABILITY. A hard Up/Down class is a DIAGNOSTIC only and",
        "  must never trigger a trade. Trading needs probability + executable EV +",
        "  calibration + gates. This artifact is NOT calibrated, so it cannot emit",
        "  PAPER_CANDIDATE and cannot be used live.",
        "", "## Training data",
        f"- train_windows: {sm.get('train_windows')}  val_windows: {sm.get('val_windows')}",
        f"- train_rows: {sm.get('train_rows')}  val_rows: {sm.get('val_rows')}",
        f"- embargo_windows: {sm.get('embargo_windows')}  no_leak: {sm.get('no_leak')}",
        f"- gate_windows: {sm.get('gate_windows')}  training_ready: {sm.get('training_ready')}",
        "", "## Validation metrics (diagnostic; NOT a profitability claim)",
    ]
    for k in ("accuracy", "roc_auc", "brier", "log_loss"):
        lines.append(f"- {k}: {m.get(k)}")
    cm = m.get("confusion_matrix")
    if cm:
        lines.append(f"- confusion_matrix: {cm}")
    lines += ["", "## Features", f"- {', '.join(artifact.get('feature_names', []))}",
              "", "## Limitations / safety",
              "- Uncalibrated; diagnostic-only artifacts are NON_TRADABLE.",
              "- No P&L/backtest here; executable backtest + calibration are later steps.",
              f"- STAGING: {artifact.get('tradable_status')} — written to data/models/staged/ when staged; "
              "the runtime (policy/lock) only scans data/models/ (non-recursive), so staged artifacts are "
              "NEVER auto-selected. Promotion is a SEPARATE explicit step (not performed here).",
              "- Live trading disabled; live_approved=false; PAPER_CANDIDATE blocked."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)
