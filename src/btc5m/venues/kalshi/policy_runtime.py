"""Policy runtime: assemble validity + inputs from disk and run the policy engine.

Loads the latest model artifact, calibrator, and backtest evidence; builds the
model-ready dataset; computes raw + calibrated probabilities; evaluates the strict
:func:`policy.evaluate_policy` over recent rows; and powers the dry-run / report /
paper-simulation CLIs. It NEVER submits a live order; paper simulation only settles
candidates against the OFFICIAL label and writes a paper ledger. Below the gate (or
without a trained+calibrated+backtested model) it blocks honestly with reason codes.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from ...notifications import build_notifier
from .calibrate import Calibrator, latest_calibrator_path, load_calibrator
from .executable_backtest import (
    latest_model_artifact_path, predict_from_artifact, settle_trade,
)
from .fees import KalshiFeeModel
from .model_artifacts import NON_TRADABLE, is_tradable, load_artifact
from .model_dataset import build_model_dataset
from .paper import MANUAL_REVIEW, PAPER_CANDIDATE, REJECTED, WATCH
from .policy import (
    BacktestValidity, CalibrationValidity, ExecutablePrices, ModelValidity, PolicyInput,
    SourceFreshness, evaluate_policy,
)
from .readiness import load_kalshi_readiness


# --------------------------------------------------------------------------- #
# Validity assessment (from disk)
# --------------------------------------------------------------------------- #
def assess_model_validity(config) -> ModelValidity:
    path = latest_model_artifact_path(config)
    if not path:
        return ModelValidity(exists=False)
    try:
        art = load_artifact(path)
    except Exception:  # noqa: BLE001
        return ModelValidity(exists=False, artifact_path=path)
    return ModelValidity(
        exists=True, trained=bool(art.get("model")),
        diagnostic_only=(art.get("tradability") == NON_TRADABLE),
        tradable_stamp=bool(art.get("tradable")), version=art.get("model_name"),
        artifact_path=path, feature_schema_version=art.get("model_schema_version"))


def assess_calibration_validity(config) -> CalibrationValidity:
    path = latest_calibrator_path(config)
    if not path:
        return CalibrationValidity(exists=False)
    try:
        art = load_calibrator(path)
    except Exception:  # noqa: BLE001
        return CalibrationValidity(exists=False, version=path)
    return CalibrationValidity(
        exists=True,
        valid=bool(art.get("tradable") and art.get("calibration_status") == "calibrated"),
        diagnostic_only=bool(art.get("NON_TRADABLE_DIAGNOSTIC_ONLY", True)), version=path)


def assess_backtest_validity(config) -> BacktestValidity:
    d = config.reports_path() / "backtests"
    files = sorted(d.glob("kalshi_baseline_comparison_*.json")) if d.exists() else []
    gate_windows = 0
    try:
        gate_windows = load_kalshi_readiness(config).get("gate_windows", 0)
    except Exception:  # noqa: BLE001
        gate_windows = 0
    non_diag = False
    for f in files:
        try:
            meta = json.loads(f.read_text(encoding="utf-8")).get("meta", {})
            if meta.get("gate_met") and not meta.get("diagnostic"):
                non_diag = True
        except Exception:  # noqa: BLE001
            continue
    return BacktestValidity(
        exists=bool(files),
        valid=bool(non_diag and gate_windows >= config.paper_policy.min_backtest_windows),
        windows=gate_windows, version=(str(files[-1]) if files else None))


def _calibrated_probs(config, rows, idx, mv: ModelValidity, cv: CalibrationValidity):
    """Return (raw_probs, calibrated_probs) for rows[idx]; ([],[]) if no model."""
    if not mv.exists or not idx:
        return [None] * len(idx), [None] * len(idx)
    try:
        raw = predict_from_artifact(load_artifact(mv.artifact_path), rows, idx)
    except Exception:  # noqa: BLE001
        return [None] * len(idx), [None] * len(idx)
    cal = list(raw)
    if cv.exists:
        try:
            cobj = Calibrator.from_dict(load_calibrator(latest_calibrator_path(config)).get("calibrator", {}))
            cal = cobj.transform(raw)
        except Exception:  # noqa: BLE001
            cal = list(raw)
    return raw, cal


def assess_validity(config):
    """Assess (model, calibration, backtest) validity once (for hot-path reuse)."""
    return (assess_model_validity(config), assess_calibration_validity(config),
            assess_backtest_validity(config))


def policy_decision_for_hotpath(config, row: dict, *, series: str, p_raw=None, p_cal=None,
                                validity=None):
    """Evaluate the policy on a live hot-path feature row (no label needed). Never trades."""
    mv, cv, bv = validity or assess_validity(config)
    r = dict(row)
    r.setdefault("ticker", row.get("market_ticker"))
    r["book_age_ms"] = row.get("hotpath_book_age_ms", row.get("book_age_ms"))
    r["underlying_age_ms"] = row.get("hotpath_underlying_age_ms", row.get("underlying_age_ms"))
    r["model_schema_version"] = None   # hot-path feature_set_version != model_schema_version; skip check
    pi = _policy_input(r, series=series, p_raw=p_raw, p_cal=p_cal, mv=mv, cv=cv, bv=bv)
    return evaluate_policy(pi, config.paper_policy, fee_model=KalshiFeeModel.from_config(config))


def _policy_input(row, *, series, p_raw, p_cal, mv, cv, bv, open_positions=0, trades_window=0) -> PolicyInput:
    prices = ExecutablePrices(
        yes_bid=row.get("yes_bid"), yes_ask=row.get("yes_ask"), no_bid=row.get("no_bid"),
        no_ask=row.get("no_ask"), yes_depth=row.get("yes_ask_size"), no_depth=row.get("no_ask_size"),
        yes_spread=row.get("yes_spread"), no_spread=row.get("no_spread"))
    fr = SourceFreshness(
        book_age_ms=row.get("book_age_ms"), underlying_age_ms=row.get("underlying_age_ms"),
        deribit_age_ms=row.get("deribit_age_ms"), coinbase_stale=bool(row.get("coinbase_stale")),
        binance_stale=bool(row.get("binance_stale")))
    return PolicyInput(
        series=series, ticker=row.get("ticker"), as_of_ts_ms=row.get("as_of_ts_ms"),
        market_open_ts_ms=row.get("market_open_ts_ms"), market_close_ts_ms=row.get("market_close_ts_ms"),
        seconds_to_close=row.get("seconds_to_close"), calibrated_probability_yes=p_cal,
        model_probability_yes=p_raw, feature_schema_version=row.get("model_schema_version"),
        book_ok=bool(row.get("book_ok")), has_underlying=bool(row.get("has_underlying")),
        reference_start_price=row.get("reference_start_price"), prices=prices, freshness=fr,
        model_validity=mv, calibration_validity=cv, backtest_validity=bv, feature_snapshot=row,
        current_open_positions=open_positions, trades_this_window=trades_window)


def _evaluate_rows(config, *, series, limit, ticker=None):
    """Build dataset, validity, probs, and evaluate the policy over the last `limit` rows."""
    pc = config.paper_policy
    ds = build_model_dataset(config, series=series)
    rows = ds["rows"]
    if ticker:
        rows = [r for r in rows if r.get("ticker") == ticker]
    rows = sorted(rows, key=lambda r: (r.get("as_of_ts_ms") or 0))
    if limit and limit > 0:
        rows = rows[-limit:]
    mv = assess_model_validity(config)
    cv = assess_calibration_validity(config)
    bv = assess_backtest_validity(config)
    idx = list(range(len(rows)))
    raw, cal = _calibrated_probs(config, rows, idx, mv, cv)
    fee_model = KalshiFeeModel.from_config(config)
    decisions = []
    for j, r in enumerate(rows):
        pi = _policy_input(r, series=series, p_raw=raw[j], p_cal=cal[j], mv=mv, cv=cv, bv=bv)
        decisions.append((r, evaluate_policy(pi, pc, fee_model=fee_model)))
    return {"dataset_gate_windows": ds["distinct_windows"], "rows": rows, "decisions": decisions,
            "model_validity": mv, "calibration_validity": cv, "backtest_validity": bv,
            "n_rows": len(rows)}


def _can_emit(mv, cv, bv, pc) -> tuple[bool, list]:
    blockers = []
    if not pc.enabled:
        blockers.append("POLICY_DISABLED")
    if pc.require_trained_model and not (mv.exists and mv.trained):
        blockers.append("MODEL_NOT_TRAINED")
    if pc.require_non_diagnostic_model and (not mv.exists or mv.diagnostic_only):
        blockers.append("MODEL_DIAGNOSTIC_ONLY")
    if pc.require_calibrated_model and not (cv.exists and cv.valid and not cv.diagnostic_only):
        blockers.append("CALIBRATOR_INVALID")
    if pc.require_backtest_evidence and not bv.valid:
        blockers.append("BACKTEST_INSUFFICIENT")
    return (not blockers), blockers


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #
def run_policy_dry_run(config, *, series="KXBTC15M", ticker=None, limit=20,
                       include_rejected=True, fmt="table") -> dict:
    pc = config.paper_policy
    ev = _evaluate_rows(config, series=series, limit=limit, ticker=ticker)
    can, blockers = _can_emit(ev["model_validity"], ev["calibration_validity"],
                              ev["backtest_validity"], pc)
    states = Counter(d.decision_state for _r, d in ev["decisions"])
    out = {"series": series, "policy_enabled": pc.enabled, "can_emit_paper_candidate": can,
           "blockers": blockers, "gate_windows": ev["dataset_gate_windows"],
           "n_rows": ev["n_rows"], "decisions_by_state": dict(states),
           "model_validity": ev["model_validity"].__dict__,
           "calibration_validity": ev["calibration_validity"].__dict__,
           "backtest_validity": ev["backtest_validity"].__dict__,
           "decisions": []}
    for r, d in ev["decisions"]:
        if not include_rejected and d.decision_state == REJECTED:
            continue
        out["decisions"].append({
            "ticker": d.selected_side and r.get("ticker") or r.get("ticker"),
            "as_of_ts_ms": r.get("as_of_ts_ms"), "decision_state": d.decision_state,
            "selected_side": d.selected_side, "model_probability_yes": d.model_probability_yes,
            "calibrated_probability_yes": d.calibrated_probability_yes,
            "executable_yes_price": d.executable_yes_price, "executable_no_price": d.executable_no_price,
            "selected_net_edge": d.selected_net_edge, "reason_codes": d.reason_codes,
            "human_summary": d.human_summary})
    return out


def run_policy_report(config, *, series="KXBTC15M", limit=0) -> dict:
    pc = config.paper_policy
    ev = _evaluate_rows(config, series=series, limit=limit or 0)
    can, blockers = _can_emit(ev["model_validity"], ev["calibration_validity"],
                              ev["backtest_validity"], pc)
    states = Counter(d.decision_state for _r, d in ev["decisions"])
    reasons = Counter(rc for _r, d in ev["decisions"] for rc in d.reason_codes)
    nets = [d.selected_net_edge for _r, d in ev["decisions"] if d.selected_net_edge is not None]
    candidates = [d for _r, d in ev["decisions"] if d.decision_state == PAPER_CANDIDATE]
    sh = _source_health_summary(config)
    report = {
        "series": series, "policy_enabled": pc.enabled, "can_emit_paper_candidate": can,
        "blockers": blockers, "gate_windows": ev["dataset_gate_windows"], "n_rows": ev["n_rows"],
        "decisions_by_state": dict(states), "reason_counts": dict(reasons),
        "edge_distribution": {
            "n_with_edge": len(nets),
            "min_net_edge": min(nets) if nets else None,
            "max_net_edge": max(nets) if nets else None,
            "mean_net_edge": (sum(nets) / len(nets)) if nets else None},
        "candidate_examples": [d.human_summary for d in candidates[:5]],
        "model_validity": ev["model_validity"].__dict__,
        "calibration_validity": ev["calibration_validity"].__dict__,
        "backtest_validity": ev["backtest_validity"].__dict__,
        "source_health": sh}
    report["reports"] = _write_policy_report(config, report)
    return report


def run_paper_policy_sim(config, *, series="KXBTC15M", limit=100, diagnostic_only=False) -> dict:
    pc = config.paper_policy
    ev = _evaluate_rows(config, series=series, limit=limit)
    can, blockers = _can_emit(ev["model_validity"], ev["calibration_validity"],
                              ev["backtest_validity"], pc)
    fee_model = KalshiFeeModel.from_config(config)
    candidates, ledger_rows = 0, []
    states = Counter()
    seen_windows: set = set()
    for r, d in ev["decisions"]:
        states[d.decision_state] += 1
        if d.decision_state != PAPER_CANDIDATE or not d.order_intent:
            continue
        if r.get("ticker") in seen_windows:   # one paper position per window
            continue
        seen_windows.add(r.get("ticker"))
        intent = d.order_intent
        entry = intent.limit_price
        fee_total = fee_model.taker_fee(entry, intent.size)
        s = settle_trade(intent.side, entry, intent.size, int(r.get("label_yes_resolved")), fee_total)
        candidates += 1
        ledger_rows.append({
            "venue": "kalshi", "series": series, "ticker": r.get("ticker"),
            "market_close_ts_ms": r.get("market_close_ts_ms"), "as_of_ts_ms": r.get("as_of_ts_ms"),
            "seconds_to_close": r.get("seconds_to_close"), "decision_state": d.decision_state,
            "selected_side": d.selected_side, "model_probability_yes": d.model_probability_yes,
            "calibrated_probability_yes": d.calibrated_probability_yes,
            "executable_yes_price": d.executable_yes_price, "executable_no_price": d.executable_no_price,
            "selected_entry_price": entry, "opposite_side_ask": intent.opposite_side_ask,
            "raw_edge": d.selected_raw_edge, "net_edge": d.selected_net_edge,
            "expected_fee": fee_total, "size": intent.size, "reason_codes": d.reason_codes,
            "model_version": ev["model_validity"].version,
            "calibration_version": ev["calibration_validity"].version,
            "backtest_version": ev["backtest_validity"].version,
            "feature_schema_version": r.get("model_schema_version"),
            "source_health_summary": ("spot+perp" if r.get("has_underlying") else "no-underlying"),
            "paper_fill_status": "simulated_filled", "paper_net_pnl": s["net_pnl"],
            "settlement_label": int(r.get("label_yes_resolved")),
            "is_paper": True, "live_submission_allowed": False})
    path = _write_paper_ledger(config, ledger_rows) if ledger_rows else None
    return {"series": series, "policy_enabled": pc.enabled, "can_emit_paper_candidate": can,
            "blockers": blockers, "n_rows": ev["n_rows"], "decisions_by_state": dict(states),
            "paper_candidates": candidates, "ledger_rows": len(ledger_rows),
            "ledger_file": path, "live_submission_allowed": False}


def _source_health_summary(config) -> dict:
    try:
        from .source_health import assess_source_health
        h = assess_source_health(config)
        by = {s["source"]: s for s in h["sources"]}
        u = h["underlying"]
        return {
            # LIVENESS (collector alive?) vs DECISION freshness (trade-fresh?) — separate.
            "underlying_liveness_ok": u["underlying_ok"],
            "underlying_decision_ok": u["underlying_decision_ok"],
            "underlying_reference_source": u["reference_source"],
            "underlying_fallback_used": u["fallback_used"],
            "kalshi_liveness_stale": by.get("kalshi", {}).get("liveness_stale"),
            "kalshi_decision_stale": by.get("kalshi", {}).get("decision_stale"),
            "coinbase_liveness_stale": by.get("coinbase", {}).get("liveness_stale"),
            "coinbase_decision_stale": by.get("coinbase", {}).get("decision_stale"),
            "binance_liveness_stale": by.get("binance", {}).get("liveness_stale"),
            "binance_decision_stale": by.get("binance", {}).get("decision_stale"),
            # back-compat aliases (liveness-based "stale")
            "underlying_ok": u["underlying_ok"],
            "kalshi_stale": by.get("kalshi", {}).get("stale"),
            "coinbase_stale": by.get("coinbase", {}).get("stale"),
            "binance_stale": by.get("binance", {}).get("stale"),
            "deribit_enabled": by.get("deribit", {}).get("enabled")}
    except Exception:  # noqa: BLE001
        return {}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _write_policy_report(config, report: dict) -> dict:
    d = config.reports_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"kalshi_policy_report_{_ts()}.md"
    mv, cv, bv = report["model_validity"], report["calibration_validity"], report["backtest_validity"]
    lines = [
        f"# Kalshi paper-candidate policy report — {report['series']}", "",
        f"- policy_enabled: {report['policy_enabled']}",
        f"- **can_emit_PAPER_CANDIDATE: {report['can_emit_paper_candidate']}**  blockers: {report['blockers']}",
        f"- gate_windows: {report['gate_windows']}  rows_evaluated: {report['n_rows']}",
        "", "## Validity",
        f"- model: exists={mv['exists']} trained={mv['trained']} diagnostic_only={mv['diagnostic_only']} "
        f"version={mv['version']}",
        f"- calibrator: exists={cv['exists']} valid={cv['valid']} diagnostic_only={cv['diagnostic_only']}",
        f"- backtest: exists={bv['exists']} valid={bv['valid']} windows={bv['windows']}",
        "", "## Decisions by state", f"- {report['decisions_by_state']}",
        "", "## Reason counts", f"- {report['reason_counts']}",
        "", "## Edge distribution", f"- {report['edge_distribution']}",
        "", "## Source health", f"- {report['source_health']}",
        "", "## Candidate examples", *(f"- {c}" for c in report["candidate_examples"] or ["(none)"]),
        "", "## Safety",
        "- PAPER_CANDIDATE requires trained + calibrated + non-diagnostic + backtested model.",
        "- Decisions use calibrated probability + executable ASK EV (never midpoint).",
        "- No live orders; live_submission_allowed=false; hard Up/Down is diagnostic only."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report_md": str(path)}


def _write_paper_ledger(config, rows: list[dict]) -> str:
    d = config.data_path() / "paper"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = d / f"kalshi_policy_paper_ledger-{day}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return str(path)


def maybe_notify(config, decision) -> bool:
    """Optionally notify on a PAPER_CANDIDATE (Noop fallback; never raises)."""
    pc = config.paper_policy
    if not pc.notify_paper_candidates or decision.decision_state != PAPER_CANDIDATE:
        return False
    try:
        return build_notifier(config).paper_candidate(decision.human_summary)
    except Exception:  # noqa: BLE001
        return False
