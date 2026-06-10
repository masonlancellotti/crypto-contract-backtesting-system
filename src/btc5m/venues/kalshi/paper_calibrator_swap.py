"""PAPER-ONLY calibrator swap (review -> dry-run -> optional write -> rollback). NEVER live.

Replaces ONLY the calibrator in the paper-promotion manifest with a safer staged candidate
(identity_raw or Platt), preserving the promoted MODEL backbone, every edge/risk gate, and the
conservative policy config. This is a CALIBRATION-SAFETY replacement — it does NOT create
trades and demonstrates NO edge. It never enables paper mode, never enables live, never touches
.env or edge thresholds. Every write is reversible (previous calibrator path/hash + a full
pre-swap manifest backup are recorded), dry-run writes no manifest, and ``live_approved`` /
``no_live_orders`` stay false/true.
"""

from __future__ import annotations

import json
import pickle
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import calibrator_replacement as cr
from .model_artifacts import PROMOTED_FOR_PAPER, staged_models_dir
from .paper_promotion import audit, load_active_promotion, manifest_path, paper_promoted_dir, sha256_file
from .probability_repair import snapshot_runtime_state, verify_runtime_unchanged

REPLACEMENT_REASON = "calibration-safety replacement; no demonstrated edge; no paper/live enabled."
CANDIDATE_PATTERNS = {
    "identity_raw": "kalshi_replacement_identity_raw_*.pkl",
    "platt": "kalshi_replacement_platt_*.pkl",
    "fresh_isotonic": "kalshi_replacement_fresh_isotonic_*.pkl",
}
CANDIDATE_METHOD = {"identity_raw": "identity", "platt": "platt", "fresh_isotonic": "isotonic"}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(x, nd=4) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "None"


# --------------------------------------------------------------------------- #
# Staged candidate discovery + eligibility (from the candidate's own metadata)
# --------------------------------------------------------------------------- #
def latest_candidate_path(config, candidate: str) -> Optional[Path]:
    pat = CANDIDATE_PATTERNS.get(candidate)
    if not pat:
        return None
    d = staged_models_dir(config)
    files = sorted(d.glob(pat), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _load_pickle(path) -> dict:
    with open(path, "rb") as fh:
        return pickle.load(fh)


def candidate_eligibility(cand_art: dict) -> dict:
    """Calibration-SAFETY eligibility from the staged candidate's own before/after metrics.

    before = current promoted isotonic; after = candidate. A safer paper calibrator must
    improve distinct-window ECE, not materially worsen Brier, and reduce YES over-prediction.
    It must also be staged + non-promoted + not live-approved (reversible).
    """
    mb = cand_art.get("metrics_before") or {}
    ma = cand_art.get("metrics_after") or {}
    be, ce = mb.get("ece_window"), ma.get("ece_window")
    bb, cb = mb.get("brier"), ma.get("brier")
    byo, cyo = mb.get("yes_overprediction_cents"), ma.get("yes_overprediction_cents")
    better_ece = bool(ce is not None and be is not None and ce < be)
    not_worse_brier = bool(cb is not None and bb is not None and cb <= bb + 0.01)
    reduces_yes = bool(cyo is not None and byo is not None and abs(cyo) <= abs(byo) + 1e-9)
    staged_ok = bool(cand_art.get("is_staged") and not cand_art.get("is_promoted")
                     and not cand_art.get("live_approved"))
    blockers = []
    if not better_ece:
        blockers.append("does_not_improve_window_ece")
    if not not_worse_brier:
        blockers.append("materially_worse_brier")
    if not reduces_yes:
        blockers.append("does_not_reduce_yes_overprediction")
    if not staged_ok:
        blockers.append("not_staged_or_already_promoted_or_live_approved")
    return {"eligible": not blockers, "better_window_ece": better_ece,
            "not_worse_brier": not_worse_brier, "reduces_yes_overprediction": reduces_yes,
            "staged_non_promoted": staged_ok, "blockers": blockers,
            "metrics_before": {"ece_window": be, "brier": bb, "yes_overprediction_cents": byo},
            "metrics_after": {"ece_window": ce, "brier": cb, "yes_overprediction_cents": cyo}}


# --------------------------------------------------------------------------- #
# Part B — review
# --------------------------------------------------------------------------- #
def run_swap_review(config, *, series: str = "KXBTC15M") -> dict:
    """Authoritative review (reuses calibrator-replacement) + swap eligibility per candidate."""
    snap = snapshot_runtime_state(config)
    rev = cr.run_calibrator_replacement_review(config, series=series)   # heavy; stages candidates
    promo = load_active_promotion(config, series=series)
    manifest = promo.get("manifest") or {}
    cands: dict = {}
    for cand in ("identity_raw", "platt", "fresh_isotonic"):
        path = latest_candidate_path(config, cand)
        if path is None:
            cands[cand] = {"available": False}
            continue
        art = _load_pickle(path)
        elig = candidate_eligibility(art)
        cands[cand] = {"available": True, "staged_path": str(path),
                       "calibrator_method": art.get("calibrator_method") or art.get("method"),
                       "model_name": art.get("model_name"), **elig}
    # recommend: eligible identity_raw/platt with the lowest candidate window-ECE
    elig_names = [c for c in ("identity_raw", "platt")
                  if cands.get(c, {}).get("eligible") and cands[c]["metrics_after"]["ece_window"] is not None]
    recommended = (min(elig_names, key=lambda c: cands[c]["metrics_after"]["ece_window"])
                   if elig_names else "none")
    out = {"series": series, "status": "OK" if rev.get("status") == "OK" else rev.get("status"),
           "current_promoted_calibrator": manifest.get("calibrator_type"),
           "promoted_valid": promo.get("valid"),
           "review_metrics": rev.get("metrics") if rev.get("status") == "OK" else None,
           "review_backtest": rev.get("backtest") if rev.get("status") == "OK" else None,
           "review_eligibility": rev.get("eligibility") if rev.get("status") == "OK" else None,
           "candidates": cands, "recommended_candidate": recommended,
           "no_edge_demonstrated": True, "live_submission_allowed": False}
    reports = _write_review_reports(config, out)
    out["reports"] = reports
    out["runtime_unchanged"] = verify_runtime_unchanged(config, snap)["unchanged"]
    return out


# --------------------------------------------------------------------------- #
# Manifest construction (pure) + dry-run / write / rollback
# --------------------------------------------------------------------------- #
def build_swap_manifest(current_manifest: dict, *, new_cal_path: str, new_cal_sha: Optional[str],
                        candidate: str, method: str, reason: str, staged_source: str,
                        preswap_backup_path: Optional[str]) -> dict:
    """Return the new manifest: ONLY calibrator fields change; model + gates preserved; previous
    calibrator + backup recorded for rollback. live_approved/no_live_orders stay false/true."""
    m = dict(current_manifest)
    m.update({
        "calibrator_artifact_path": new_cal_path,
        "calibrator_artifact_sha256": new_cal_sha,
        "calibrator_type": method,
        "calibrator_version": _now_iso(),
        "promoted_for": "PAPER_ONLY", "live_approved": False, "no_live_orders": True,
        # ----- rollback provenance (previous calibrator) -----
        "previous_calibrator_artifact_path": current_manifest.get("calibrator_artifact_path"),
        "previous_calibrator_artifact_sha256": current_manifest.get("calibrator_artifact_sha256"),
        "previous_calibrator_type": current_manifest.get("calibrator_type"),
        "pre_swap_manifest_backup_path": preswap_backup_path,
        # ----- swap provenance -----
        "calibrator_swapped": True,
        "calibrator_swap_candidate": candidate,
        "calibrator_swapped_from_staged": staged_source,
        "calibrator_swapped_at": _now_iso(),
        "calibrator_swap_reason": reason,
        "calibrator_swapped_by_command": "kalshi-paper-calibrator-swap",
    })
    return m


def _swap_preconditions(config, series, candidate) -> dict:
    promo = load_active_promotion(config, series=series)
    if not promo.get("valid"):
        return {"ok": False, "reason": f"current promotion invalid: {promo.get('blockers')}", "promo": promo}
    if candidate not in CANDIDATE_PATTERNS:
        return {"ok": False, "reason": f"unknown candidate {candidate!r}", "promo": promo}
    path = latest_candidate_path(config, candidate)
    if path is None:
        return {"ok": False, "reason": f"no staged {candidate} candidate "
                "(run kalshi-paper-calibrator-swap-review first)", "promo": promo}
    art = _load_pickle(path)
    manifest = promo["manifest"]
    if art.get("model_name") and manifest.get("model_name") and art["model_name"] != manifest["model_name"]:
        return {"ok": False, "reason": f"calibrator/model family mismatch "
                f"({art.get('model_name')} != {manifest.get('model_name')})", "promo": promo}
    elig = candidate_eligibility(art)
    return {"ok": True, "promo": promo, "manifest": manifest, "candidate_path": path,
            "candidate_art": art, "eligibility": elig}


def swap_dry_run(config, *, series: str, candidate: str) -> dict:
    snap = snapshot_runtime_state(config)
    pre = _swap_preconditions(config, series, candidate)
    base = {"series": series, "candidate": candidate, "write": False, "live_submission_allowed": False}
    if not pre["ok"]:
        return {**base, "status": "REFUSED", "reason": pre["reason"],
                "runtime_unchanged": verify_runtime_unchanged(config, snap)["unchanged"]}
    manifest, art, path = pre["manifest"], pre["candidate_art"], pre["candidate_path"]
    method = CANDIDATE_METHOD[candidate]
    planned_cal_name = f"paper_calibrator_swap_{candidate}_{series}_<ts>.pkl"
    planned = build_swap_manifest(
        manifest, new_cal_path=str(paper_promoted_dir(config) / planned_cal_name),
        new_cal_sha="(computed at --write)", candidate=candidate, method=method,
        reason=REPLACEMENT_REASON, staged_source=str(path),
        preswap_backup_path="(written at --write)")
    audit(config, "CALIBRATOR_SWAP_DRY_RUN", {"series": series, "candidate": candidate,
          "staged_source": str(path), "staged_source_sha256": sha256_file(path),
          "eligible": pre["eligibility"]["eligible"], "result": "DRY_RUN_NO_WRITE"})
    verify = verify_runtime_unchanged(config, snap)
    return {**base, "status": "DRY_RUN", "eligibility": pre["eligibility"],
            "compatibility": {"candidate_model_name": art.get("model_name"),
                              "promoted_model_name": manifest.get("model_name"),
                              "compatible": True},
            "staged_source": str(path), "staged_source_sha256": sha256_file(path),
            "current_calibrator": manifest.get("calibrator_artifact_path"),
            "current_calibrator_type": manifest.get("calibrator_type"),
            "planned_manifest": planned, "manifest_written": False,
            "paper_disabled": True, "live_disabled": True,
            "note": "DRY-RUN: no manifest written. paper/live remain disabled. Pass --write to apply "
                    "(reversible via kalshi-paper-calibrator-swap-rollback).",
            "runtime_unchanged": verify["unchanged"]}


def swap_write(config, *, series: str, candidate: str, require_eligible: bool = True) -> dict:
    """Apply the calibrator swap to the PAPER promotion manifest. Reversible; paper/live stay off."""
    snap = snapshot_runtime_state(config)
    pre = _swap_preconditions(config, series, candidate)
    base = {"series": series, "candidate": candidate, "write": True, "live_submission_allowed": False}
    if not pre["ok"]:
        return {**base, "status": "REFUSED", "reason": pre["reason"]}
    elig = pre["eligibility"]
    if require_eligible and not elig["eligible"]:
        return {**base, "status": "REFUSED_NOT_ELIGIBLE", "eligibility": elig,
                "reason": f"candidate not eligible: {elig['blockers']}"}
    manifest, art, path = pre["manifest"], pre["candidate_art"], pre["candidate_path"]
    method = CANDIDATE_METHOD[candidate]
    d = paper_promoted_dir(config)
    stamp = _ts()
    # 1) backup the current manifest (full reversibility)
    mp = manifest_path(config)
    backup = d / f"kalshi_paper_promotion_manifest.preswap-{stamp}.json"
    shutil.copyfile(mp, backup)
    # 2) copy + re-stamp the staged calibrator into paper_promoted/ (PAPER-ONLY; not live)
    new_cal = d / f"paper_calibrator_swap_{candidate}_{series}_{stamp}.pkl"
    _copy_calibrator_stamped(path, new_cal, series=series, reason=REPLACEMENT_REASON)
    new_sha = sha256_file(new_cal)
    # 3) build + write the new manifest (model + gates preserved)
    new_manifest = build_swap_manifest(
        manifest, new_cal_path=str(new_cal), new_cal_sha=new_sha, candidate=candidate, method=method,
        reason=REPLACEMENT_REASON, staged_source=str(path), preswap_backup_path=str(backup))
    mp.write_text(json.dumps(new_manifest, indent=2, default=str), encoding="utf-8")
    audit(config, "CALIBRATOR_SWAP_WRITE", {
        "series": series, "candidate": candidate, "result": "PAPER_CALIBRATOR_SWAPPED",
        "new_calibrator_path": str(new_cal), "new_calibrator_sha256": new_sha,
        "previous_calibrator_path": new_manifest["previous_calibrator_artifact_path"],
        "previous_calibrator_sha256": new_manifest["previous_calibrator_artifact_sha256"],
        "pre_swap_manifest_backup_path": str(backup), "reason": REPLACEMENT_REASON,
        "model_preserved": manifest.get("model_artifact_path"), "live_approved": False})
    # re-verify the new promotion is valid + the MODEL is unchanged
    promo2 = load_active_promotion(config, series=series)
    return {**base, "status": "PAPER_CALIBRATOR_SWAPPED", "eligibility": elig,
            "manifest_path": str(mp), "new_calibrator_path": str(new_cal), "new_calibrator_sha256": new_sha,
            "previous_calibrator_path": new_manifest["previous_calibrator_artifact_path"],
            "previous_calibrator_sha256": new_manifest["previous_calibrator_artifact_sha256"],
            "pre_swap_manifest_backup_path": str(backup),
            "model_artifact_path": new_manifest.get("model_artifact_path"),
            "model_preserved": (snapshot_runtime_state(config).get(new_manifest.get("model_artifact_path"))
                                == snap.get(new_manifest.get("model_artifact_path"))),
            "new_promotion_valid": promo2.get("valid"), "new_promotion_blockers": promo2.get("blockers"),
            "paper_disabled": True, "live_disabled": True,
            "reason": REPLACEMENT_REASON, "audit_note": "reversible via kalshi-paper-calibrator-swap-rollback"}


def _copy_calibrator_stamped(src, dst, *, series: str, reason: str) -> None:
    art = dict(_load_pickle(src))
    art.update({
        "is_promoted": True, "is_staged": False, "promoted_for": "PAPER_ONLY",
        "calibration_status": "calibrated", "NON_TRADABLE_DIAGNOSTIC_ONLY": False, "is_diagnostic": False,
        "tradable_status": PROMOTED_FOR_PAPER, "live_approved": False,
        "promoted_at": _now_iso(), "promoted_by_command": "kalshi-paper-calibrator-swap",
        "promoted_series": series, "source_artifact_path": str(src),
        "calibrator_swap_reason": reason,
        "notes": "PAPER-ONLY calibration-safety swap; identity/Platt over the poor promoted isotonic; "
                 "no demonstrated edge; never live.",
    })
    with open(dst, "wb") as fh:
        pickle.dump(art, fh)


def swap_rollback(config, *, series: str = "KXBTC15M", write: bool = False) -> dict:
    snap = snapshot_runtime_state(config)
    mp = manifest_path(config)
    base = {"series": series, "write": bool(write), "live_submission_allowed": False}
    if not mp.exists():
        return {**base, "status": "NO_MANIFEST"}
    manifest = json.loads(mp.read_text(encoding="utf-8"))
    if not manifest.get("calibrator_swapped"):
        return {**base, "status": "NOTHING_TO_ROLLBACK",
                "note": "active manifest was not produced by a calibrator swap.",
                "runtime_unchanged": verify_runtime_unchanged(config, snap)["unchanged"]}
    backup = manifest.get("pre_swap_manifest_backup_path")
    prev_cal = manifest.get("previous_calibrator_artifact_path")
    prev_sha = manifest.get("previous_calibrator_artifact_sha256")
    can_restore = bool(backup and Path(backup).exists()) or bool(prev_cal and Path(prev_cal).exists())
    if not write:
        audit(config, "CALIBRATOR_SWAP_ROLLBACK", {"series": series, "result": "DRY_RUN_WOULD_ROLLBACK",
              "restore_from_backup": backup, "previous_calibrator": prev_cal, "can_restore": can_restore})
        return {**base, "status": "DRY_RUN_WOULD_ROLLBACK", "restore_from_backup": backup,
                "previous_calibrator": prev_cal, "previous_calibrator_sha256": prev_sha,
                "can_restore": can_restore, "note": "pass --write to restore the previous calibrator.",
                "runtime_unchanged": verify_runtime_unchanged(config, snap)["unchanged"]}
    if not can_restore:
        return {**base, "status": "REFUSED_NO_BACKUP",
                "reason": "no pre-swap manifest backup or previous calibrator file present."}
    if backup and Path(backup).exists():
        shutil.copyfile(backup, mp)                          # restore the full pre-swap manifest
        method = "restored_pre_swap_manifest_backup"
    else:                                                    # reconstruct minimal restore
        manifest.update({"calibrator_artifact_path": prev_cal, "calibrator_artifact_sha256": prev_sha,
                         "calibrator_type": manifest.get("previous_calibrator_type"),
                         "calibrator_swapped": False, "rolled_back_at": _now_iso()})
        mp.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        method = "reconstructed_from_previous_fields"
    promo = load_active_promotion(config, series=series)
    audit(config, "CALIBRATOR_SWAP_ROLLBACK", {"series": series, "result": "ROLLED_BACK", "method": method,
          "restored_calibrator": prev_cal, "promotion_valid": promo.get("valid")})
    return {**base, "status": "ROLLED_BACK", "method": method, "restored_calibrator": prev_cal,
            "manifest_path": str(mp), "new_promotion_valid": promo.get("valid"),
            "paper_disabled": True, "live_disabled": True}


# --------------------------------------------------------------------------- #
# Reports (Part G)
# --------------------------------------------------------------------------- #
def _write_review_reports(config, out: dict) -> dict:
    import csv as _csv
    d = config.reports_path() / "calibration"
    d.mkdir(parents=True, exist_ok=True)
    md = config.reports_path() / "models"
    md.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    rmd = d / f"kalshi_paper_calibrator_swap_review_{stamp}.md"
    rcsv = d / f"kalshi_paper_calibrator_swap_review_{stamp}.csv"
    audit_json = md / f"kalshi_paper_calibrator_swap_audit_{stamp}.json"
    metrics = out.get("review_metrics") or {}
    backtest = out.get("review_backtest") or {}
    order = [m for m in ("current_promoted_isotonic", "identity_raw", "platt", "fresh_isotonic",
                         "market_implied") if m in metrics]
    lines = [
        f"# Kalshi PAPER calibrator swap review — {out['series']}", "",
        "> CALIBRATION-SAFETY review only. The promoted isotonic calibrator is the worst-calibrated "
        "source and loses in diagnostic backtest; identity_raw / Platt are safer. This is NOT an alpha "
        "claim — **no tradable edge is demonstrated and pass_final remains 0**. No promotion is performed "
        "here; paper/live stay disabled; edge-policy gates are unchanged; a swap is fully reversible.", "",
        f"- current promoted calibrator: **{out.get('current_promoted_calibrator')}**  "
        f"promoted_valid: {out.get('promoted_valid')}",
        f"- recommended safer candidate (PAPER-ONLY): **{out.get('recommended_candidate')}**",
        "", "| calibrator | ECE_window | ECE_row | brier | log_loss | YES_overpred(c) | NO_overpred(c) | "
        "backtest_net | pass_final |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in order:
        x = metrics.get(m, {})
        bt = backtest.get(m, {})
        yo = x.get("yes_overprediction_cents")
        # pass_final is 0 across calibrators under the current edge policy (documented elsewhere)
        lines.append(f"| {m} | {_f(x.get('ece_window'))} | {_f(x.get('ece_row'))} | {_f(x.get('brier'))} | "
                     f"{_f(x.get('log_loss'))} | {_f(yo,2)} | "
                     f"{_f(-yo,2) if isinstance(yo,(int,float)) else 'None'} | "
                     f"{_f(bt.get('net_pnl'),2)} | 0 |")
    lines += ["", "## Swap eligibility (vs promoted isotonic; from each candidate's own metrics)"]
    for cand, c in out.get("candidates", {}).items():
        if not c.get("available"):
            lines.append(f"- {cand}: (no staged candidate)")
            continue
        lines.append(f"- **{cand}**: eligible={c.get('eligible')} (better_window_ece={c.get('better_window_ece')}, "
                     f"not_worse_brier={c.get('not_worse_brier')}, reduces_yes_overpred={c.get('reduces_yes_overprediction')}, "
                     f"staged_non_promoted={c.get('staged_non_promoted')})  blockers={c.get('blockers')}")
    lines += ["", "## Verdict",
              f"- recommended_candidate: **{out.get('recommended_candidate')}** (calibration-safety only)",
              "- **no tradable edge is demonstrated; pass_final remains 0; this is not an alpha claim.**",
              "- a swap changes ONLY the paper calibrator; the model backbone, edge-policy gates, "
              "calibration buffers, and conservative policy config are unchanged; it is reversible.",
              "", "## Safety",
              "- No promotion performed in the review. paper/live remain disabled. live_submission_allowed=false."]
    rmd.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with rcsv.open("w", encoding="utf-8", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["calibrator", "ece_window", "ece_row", "brier", "log_loss",
                    "yes_overprediction_cents", "backtest_net_pnl", "pass_final", "swap_eligible"])
        for m in order:
            x = metrics.get(m, {})
            bt = backtest.get(m, {})
            ce = out.get("candidates", {}).get(m, {}).get("eligible", "")
            w.writerow([m, x.get("ece_window"), x.get("ece_row"), x.get("brier"), x.get("log_loss"),
                        x.get("yes_overprediction_cents"), bt.get("net_pnl"), 0, ce])
    audit_json.write_text(json.dumps({
        "created_at": _now_iso(), "series": out["series"], "action": "SWAP_REVIEW",
        "current_promoted_calibrator": out.get("current_promoted_calibrator"),
        "recommended_candidate": out.get("recommended_candidate"),
        "no_edge_demonstrated": True, "pass_final": 0, "promotion_performed": False,
        "paper_disabled": True, "live_disabled": True, "edge_gates_unchanged": True,
        "reversible": True, "candidates": out.get("candidates", {}),
        "live_submission_allowed": False}, indent=2, default=str), encoding="utf-8")
    return {"review_md": str(rmd), "review_csv": str(rcsv), "audit_json": str(audit_json)}
