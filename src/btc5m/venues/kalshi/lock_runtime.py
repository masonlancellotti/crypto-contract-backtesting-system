"""Lock-profit runtime: load open paper positions, evaluate locks, simulate, report.

Loads OPEN paper positions from the policy paper ledger (+ any prior lock fills),
fetches the current Kalshi book per held ticker, and runs :func:`lock_profit.evaluate_lock`.
It only ever manages EXISTING positions (held YES → monitor NO; held NO → monitor
YES) — it never scans flat markets and never opens directional positions. When no
open paper positions exist it reports NO_POSITION (never crashes). No live orders.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from ...notifications import build_notifier
from .calibrate import Calibrator, latest_calibrator_path, load_calibrator
from .executable_backtest import predict_from_artifact, settle_trade
from .fees import KalshiFeeModel
from .lock_profit import (
    LOCK_FULL, LOCK_PARTIAL, RIDE, KalshiPositionLot, KalshiPositionState, LockConfig,
    evaluate_lock,
)
from .model_artifacts import load_artifact
from .model_dataset import build_model_dataset


def _iter(path) -> list[dict]:
    out = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return out


def load_open_paper_positions(config, *, series: str = "KXBTC15M") -> list[KalshiPositionState]:
    """Build positions from policy paper entries + any recorded lock fills. Never flat-scans."""
    d = config.data_path() / "paper"
    lots: dict[str, list] = defaultdict(list)
    close_ms: dict[str, int] = {}
    if d.exists():
        for p in sorted(d.glob("kalshi_policy_paper_ledger-*.jsonl")):
            for row in _iter(p):
                if row.get("paper_fill_status") == "simulated_filled" and row.get("selected_side"):
                    tk = row.get("ticker")
                    qty = float(row.get("size") or 0)
                    price = row.get("selected_entry_price")
                    if tk and price is not None and qty > 0:
                        fee = float(row.get("expected_fee") or 0.0)
                        lots[tk].append(KalshiPositionLot(side=row["selected_side"], quantity=qty,
                                                          price=float(price), fee_per_contract=(fee / qty)))
                        close_ms[tk] = row.get("market_close_ts_ms")
        for p in sorted(d.glob("kalshi_lock_ledger-*.jsonl")):
            for row in _iter(p):
                if row.get("event_type") in ("PAPER_LOCK_FILLED", "PAPER_LOCK_PARTIAL") and row.get("side"):
                    tk = row.get("ticker")
                    qty = float(row.get("quantity") or 0)
                    price = row.get("price")
                    if tk and price is not None and qty > 0:
                        fee = float(row.get("fee") or 0.0)
                        lots[tk].append(KalshiPositionLot(side=row["side"], quantity=qty,
                                                          price=float(price), fee_per_contract=(fee / qty)))
    return [KalshiPositionState.from_lots(v, series=series, ticker=tk, market_close_ts_ms=close_ms.get(tk))
            for tk, v in lots.items()]


def _latest_books(config, series: str) -> dict[str, dict]:
    rows = build_model_dataset(config, series=series)["rows"]
    latest: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (r.get("as_of_ts_ms") or 0)):
        if r.get("ticker"):
            latest[r["ticker"]] = r
    return latest


def _rows_by_ticker(config, series: str) -> dict[str, list]:
    rows = build_model_dataset(config, series=series)["rows"]
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        if r.get("ticker"):
            by[r["ticker"]].append(r)
    for tk in by:
        by[tk].sort(key=lambda r: (r.get("as_of_ts_ms") or 0))
    return by


def _calibrated_prob(config, row: dict) -> Optional[float]:
    """Calibrated P(YES) for a row, ONLY if a non-diagnostic + valid calibrated model exists."""
    from .policy_runtime import assess_calibration_validity, assess_model_validity
    mv = assess_model_validity(config)
    cv = assess_calibration_validity(config)
    if not (mv.exists and mv.trained and not mv.diagnostic_only and cv.exists and cv.valid):
        return None
    try:
        raw = predict_from_artifact(load_artifact(mv.artifact_path), [row], [0])[0]
        cobj = Calibrator.from_dict(load_calibrator(latest_calibrator_path(config)).get("calibrator", {}))
        return cobj.transform([raw])[0]
    except Exception:  # noqa: BLE001
        return None


def _eval_position(config, pos: KalshiPositionState, row: Optional[dict], lcfg, fee_model,
                   mode, allow_partial):
    held = "YES" if pos.naked_yes_quantity > 0 else ("NO" if pos.naked_no_quantity > 0 else None)
    if row is None or held is None:
        return evaluate_lock(pos, opposite_ask=None, opposite_depth=0.0, book_ok=False,
                             seconds_to_close=None, config=lcfg, fee_model=fee_model, mode=mode,
                             allow_partial=allow_partial)
    opp_ask = row.get("no_ask") if held == "YES" else row.get("yes_ask")
    opp_depth = row.get("no_ask_size") if held == "YES" else row.get("yes_ask_size")
    return evaluate_lock(
        pos, opposite_ask=opp_ask, opposite_depth=opp_depth, book_ok=bool(row.get("book_ok")),
        seconds_to_close=row.get("seconds_to_close"), book_age_ms=row.get("book_age_ms"),
        underlying_age_ms=row.get("underlying_age_ms"),
        underlying_stale=bool(row.get("coinbase_stale") and row.get("binance_stale")),
        calibrated_p_yes=_calibrated_prob(config, row), config=lcfg, fee_model=fee_model,
        mode=mode, allow_partial=allow_partial)


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #
def run_lock_dry_run(config, *, series="KXBTC15M", ticker=None, limit=0, include_rejected=True,
                     fmt="table", mode=None, allow_partial=None) -> dict:
    lcfg = LockConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    positions = load_open_paper_positions(config, series=series)
    if ticker:
        positions = [p for p in positions if p.ticker == ticker]
    if limit and limit > 0:
        positions = positions[:limit]
    out = {"series": series, "module_enabled": lcfg.enabled, "open_positions": len(positions),
           "live_submission_allowed": False, "decisions": []}
    if not positions:
        out["status"] = "NO_POSITION"
        out["message"] = "no open paper positions found (lock module manages existing positions only)"
        return out
    books = _latest_books(config, series)
    states = defaultdict(int)
    for pos in positions:
        dec = _eval_position(config, pos, books.get(pos.ticker), lcfg, fee_model, mode, allow_partial)
        states[dec.decision_state] += 1
        if not include_rejected and dec.decision_state == "REJECTED":
            continue
        out["decisions"].append(_dec_dict(pos, dec))
    out["status"] = "OK"
    out["decisions_by_state"] = dict(states)
    out["reports"] = _write_lock_report(config, "dry_run", out)
    return out


def run_lock_sim(config, *, series="KXBTC15M", limit=100, mode=None, allow_partial=None) -> dict:
    """Replay: for each open paper position, would a lock have triggered later? Diagnostic."""
    lcfg = LockConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    positions = load_open_paper_positions(config, series=series)
    if limit and limit > 0:
        positions = positions[:limit]
    out = {"series": series, "module_enabled": lcfg.enabled, "open_positions": len(positions),
           "diagnostic": True, "live_submission_allowed": False, "results": []}
    if not positions:
        out["status"] = "NO_POSITION"
        out["message"] = "no open paper positions found"
        return out
    by_ticker = _rows_by_ticker(config, series)
    locked_total = naked_total = pnl_with_lock = pnl_no_lock = 0.0
    for pos in positions:
        rows = by_ticker.get(pos.ticker, [])
        label = next((int(r["label_yes_resolved"]) for r in rows if r.get("label_yes_resolved") is not None), None)
        triggered = None
        for r in rows:
            dec = _eval_position(config, pos, r, lcfg, fee_model, mode, allow_partial)
            if dec.decision_state in (LOCK_FULL, LOCK_PARTIAL):
                triggered = dec
                break
        held = "YES" if pos.naked_yes_quantity > 0 else "NO"
        naked = pos.naked_yes_quantity if held == "YES" else pos.naked_no_quantity
        naked_cost = pos.yes_total_cost if held == "YES" else pos.no_total_cost
        # ride P&L (no lock): naked settles vs label
        ride_pnl = _settle_naked(held, naked, naked_cost, label) if label is not None else None
        lock_pnl = ride_pnl
        if triggered and label is not None:
            lock_qty = triggered.lock_quantity
            locked_profit = (triggered.expected_locked_profit_per_pair or 0.0) * lock_qty
            remaining = naked - lock_qty
            lock_pnl = locked_profit + _settle_naked(held, remaining, naked_cost, label)
            locked_total += lock_qty
            naked_total += remaining
        else:
            naked_total += naked
        if ride_pnl is not None:
            pnl_no_lock += ride_pnl
            pnl_with_lock += (lock_pnl if lock_pnl is not None else ride_pnl)
        out["results"].append({
            "ticker": pos.ticker, "held": held, "naked_before": naked,
            "lock_triggered": bool(triggered), "lock_state": (triggered.decision_state if triggered else None),
            "locked_qty": (triggered.lock_quantity if triggered else 0.0),
            "expected_locked_profit": (triggered.expected_total_locked_profit if triggered else None),
            "ride_pnl": ride_pnl, "lock_pnl": lock_pnl})
    out["status"] = "OK"
    out["summary"] = {"positions": len(positions), "locked_contracts": locked_total,
                      "naked_contracts_remaining": naked_total,
                      "pnl_no_lock": round(pnl_no_lock, 6), "pnl_with_lock": round(pnl_with_lock, 6),
                      "risk_reduction_contracts": locked_total}
    out["reports"] = _write_lock_report(config, "sim", out)
    return out


def _settle_naked(held, qty, cost, label) -> float:
    if qty <= 0 or label is None:
        return 0.0
    win = (label == 1) if held == "YES" else (label == 0)
    return qty * ((1.0 - cost) if win else (-cost))


def _dec_dict(pos: KalshiPositionState, dec) -> dict:
    return {
        "ticker": dec.ticker, "decision_state": dec.decision_state,
        "existing_position_side": dec.existing_position_side, "side_to_buy": dec.side_to_buy,
        "lock_quantity": dec.lock_quantity, "current_opposite_ask": dec.current_opposite_ask,
        "max_acceptable_opposite_price": dec.max_acceptable_opposite_price,
        "expected_locked_profit_per_pair": dec.expected_locked_profit_per_pair,
        "expected_total_locked_profit": dec.expected_total_locked_profit,
        "continue_ev_per_contract": dec.continue_ev_per_contract,
        "naked_quantity_before": dec.naked_quantity_before,
        "naked_quantity_after": dec.naked_quantity_after,
        "locked_quantity_after": dec.locked_quantity_after,
        "reason_codes": dec.reason_codes, "ride_vs_lock_reason": dec.ride_vs_lock_reason,
        "human_summary": dec.human_summary, "live_submission_allowed": False}


# --------------------------------------------------------------------------- #
# Ledger + notifications + integration
# --------------------------------------------------------------------------- #
def write_lock_ledger(config, events: list[dict]) -> Optional[str]:
    if not events:
        return None
    d = config.data_path() / "paper"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = d / f"kalshi_lock_ledger-{day}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        for e in events:
            e.setdefault("venue", "kalshi")
            e.setdefault("series", "KXBTC15M")
            e.setdefault("live_submission_allowed", False)
            fh.write(json.dumps(e) + "\n")
    return str(path)


def lock_event_from_decision(dec, *, timestamp_ms: int, model_probability_yes=None) -> dict:
    et = {"LOCK_FULL": "PAPER_LOCK_FILLED", "LOCK_PARTIAL": "PAPER_LOCK_PARTIAL",
          "REJECTED": "PAPER_LOCK_REJECTED", "RIDE": "PAPER_RIDE_DECISION",
          "ALREADY_FULLY_LOCKED": "PAPER_FULLY_LOCKED"}.get(dec.decision_state, "PAPER_LOCK_INTENT")
    intent = dec.order_intent
    return {
        "event_type": et, "ticker": dec.ticker, "timestamp": timestamp_ms,
        "side": dec.side_to_buy, "quantity": dec.lock_quantity,
        "price": (intent.limit_price if intent else dec.current_opposite_ask),
        "fee": (intent.expected_fee if intent else dec.expected_lock_fee),
        "lock_decision_state": dec.decision_state,
        "locked_pairs_after": dec.locked_quantity_after,
        "naked_yes_after": (dec.naked_quantity_after if dec.existing_position_side == "YES" else 0.0),
        "naked_no_after": (dec.naked_quantity_after if dec.existing_position_side == "NO" else 0.0),
        "expected_locked_profit": dec.expected_total_locked_profit,
        "continue_ev_per_contract": dec.continue_ev_per_contract,
        "model_probability_yes": model_probability_yes,
        "reason_codes": dec.reason_codes, "live_submission_allowed": False}


def maybe_notify_lock(config, dec) -> bool:
    lcfg = LockConfig.from_app(config)
    if not lcfg.notify or dec.decision_state not in (LOCK_FULL, LOCK_PARTIAL, RIDE, "ALREADY_FULLY_LOCKED"):
        return False
    try:
        return build_notifier(config).paper_candidate(f"LOCK {dec.human_summary}")
    except Exception:  # noqa: BLE001
        return False


def lock_decisions_for_open_positions(config, *, series="KXBTC15M") -> list:
    """Integration entry point for the low-latency runtime / policy loop.

    Activates ONLY for existing open paper positions (never flat). Returns
    (position, decision) pairs; the caller decides whether to act (paper-only).
    """
    lcfg = LockConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    positions = load_open_paper_positions(config, series=series)
    if not positions:
        return []
    books = _latest_books(config, series)
    return [(p, _eval_position(config, p, books.get(p.ticker), lcfg, fee_model, None, None))
            for p in positions]


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _write_lock_report(config, kind: str, out: dict) -> dict:
    d = config.reports_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"kalshi_lock_{kind}_{_ts()}.md"
    lines = [f"# Kalshi post-entry lock-profit {kind} — {out['series']}", "",
             f"- module_enabled: {out['module_enabled']}",
             f"- open_paper_positions: {out['open_positions']}",
             f"- status: {out.get('status')}",
             "- POST-ENTRY ONLY (not a flat arb scanner); paper-only; no live orders.", ""]
    if out.get("status") == "NO_POSITION":
        lines.append(f"- {out.get('message')}")
    elif kind == "dry_run":
        lines.append(f"- decisions_by_state: {out.get('decisions_by_state')}")
        for d0 in out.get("decisions", [])[:20]:
            lines.append(f"- [{d0['decision_state']}] {d0['human_summary']}")
    else:
        lines.append(f"- summary: {out.get('summary')}")
        for r in out.get("results", [])[:20]:
            lines.append(f"- {r['ticker']}: held {r['held']} lock={r['lock_state']} "
                         f"ride_pnl={r['ride_pnl']} lock_pnl={r['lock_pnl']}")
    lines += ["", "## Safety",
              "- Lock activates only with an EXISTING paper position; never scans flat markets.",
              "- Locked profit is guaranteed only AFTER the opposite leg fills; partials leave naked risk.",
              "- live_submission_allowed=false; no live orders; live trading disabled."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report_md": str(path)}
