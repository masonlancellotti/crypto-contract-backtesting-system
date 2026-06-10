"""Position lifecycle runtime: load open paper positions, evaluate lifecycle, report.

Loads OPEN paper positions (reusing :mod:`lock_runtime`), builds a point-in-time
lifecycle input from the latest recorded Kalshi book + the model-validity-gated
calibrated probability, and runs :func:`position_lifecycle.evaluate_lifecycle`.

POST-ENTRY ONLY: it activates solely for positions that already exist. It never
scans flat markets, never opens directional positions, and never submits a live
order. When no open paper positions exist it reports NO_POSITION (never crashes).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from .fees import KalshiFeeModel
# Reuse position loading, latest-book/rows, model-prob gating, and naked settlement.
from .lock_runtime import (
    _calibrated_prob, _latest_books, _rows_by_ticker, _settle_naked,
    load_open_paper_positions,
)
from .position_lifecycle import (
    LOCK_WITH_OPPOSITE_LEG, PARTIAL_LOCK, RIDE, RISK_EXIT, SELL_PARTIAL, SELL_SAME_LEG,
    KalshiPositionState, LifecycleConfig, LifecycleInput, evaluate_lifecycle,
    same_leg_exit_value,
)

# Action -> ledger event type (paper-only; dry-run emits INTENT/EVAL, never a fill).
_EVENT_TYPE = {
    SELL_SAME_LEG: "PAPER_SELL_INTENT",
    SELL_PARTIAL: "PAPER_SELL_INTENT",
    LOCK_WITH_OPPOSITE_LEG: "PAPER_LOCK_INTENT",
    PARTIAL_LOCK: "PAPER_PARTIAL_LOCK",
    RISK_EXIT: "PAPER_RISK_EXIT",
    RIDE: "PAPER_RIDE_DECISION",
    "ALREADY_FULLY_LOCKED": "PAPER_FULLY_LOCKED",
}
_NOTIFY_ACTIONS = {SELL_SAME_LEG, SELL_PARTIAL, LOCK_WITH_OPPOSITE_LEG, PARTIAL_LOCK, RISK_EXIT}


def _input_from_row(config, pos: KalshiPositionState, row: Optional[dict]) -> LifecycleInput:
    held = ("YES" if pos.naked_yes_quantity > 0
            else "NO" if pos.naked_no_quantity > 0 else None)
    if row is None or held is None:
        return LifecycleInput(book_ok=False, source_healthy=True)
    if held == "YES":
        same_bid, same_depth = row.get("yes_bid"), row.get("yes_bid_size")
        opp_ask, opp_depth = row.get("no_ask"), row.get("no_ask_size")
    else:
        same_bid, same_depth = row.get("no_bid"), row.get("no_bid_size")
        opp_ask, opp_depth = row.get("yes_ask"), row.get("yes_ask_size")
    csta, bsta = bool(row.get("coinbase_stale")), bool(row.get("binance_stale"))
    spreads = [s for s in (row.get("yes_spread"), row.get("no_spread")) if isinstance(s, (int, float))]
    spread_cents = (max(spreads) * 100.0) if spreads else None
    p = _calibrated_prob(config, row)
    return LifecycleInput(
        current_ts_ms=row.get("as_of_ts_ms"),
        same_leg_bid=same_bid, same_leg_bid_depth=same_depth,
        opposite_leg_ask=opp_ask, opposite_leg_ask_depth=opp_depth,
        book_ok=bool(row.get("book_ok")), book_age_ms=row.get("book_age_ms"),
        underlying_age_ms=row.get("underlying_age_ms"), underlying_stale=(csta and bsta),
        seconds_to_close=row.get("seconds_to_close"), spread_cents=spread_cents,
        calibrated_p_yes=p, model_valid=(p is not None),
        calibration_status=("calibrated" if p is not None else "uncalibrated"),
        source_healthy=not (csta and bsta))


def _eval(config, pos, row, cfg, fee_model):
    return evaluate_lifecycle(pos, _input_from_row(config, pos, row), config=cfg, fee_model=fee_model)


def _dec_dict(dec) -> dict:
    intent = dec.selected_order_intent
    return {
        "ticker": dec.ticker, "action": dec.action,
        "current_position_side": dec.current_position_side,
        "seconds_to_close": dec.seconds_to_close,
        "same_leg_exit_price": dec.same_leg_exit_price,
        "same_leg_exit_profit_per_contract": dec.same_leg_exit_profit_per_contract,
        "opposite_leg_ask": dec.opposite_leg_ask,
        "max_acceptable_opposite_price": dec.max_acceptable_opposite_price,
        "lock_profit_per_pair": dec.lock_profit_per_pair,
        "total_expected_lock_profit": dec.total_expected_lock_profit,
        "continue_ev_per_contract": dec.continue_ev_per_contract,
        "model_probability_yes": dec.model_probability_yes,
        "naked_quantity_before": dec.naked_quantity_before,
        "naked_quantity_after": dec.naked_quantity_after,
        "locked_pairs_after": dec.locked_pairs_after,
        "order_intent": ({"action": intent.action, "side": intent.side, "quantity": intent.quantity,
                          "limit_price": intent.limit_price, "time_in_force": intent.time_in_force,
                          "max_acceptable_price": intent.max_acceptable_price,
                          "live_submission_allowed": False} if intent else None),
        "reason_codes": dec.reason_codes, "human_summary": dec.human_summary,
        "live_submission_allowed": False}


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #
def run_position_monitor_dry_run(config, *, series="KXBTC15M", ticker=None, limit=0,
                                 include_rejected=True, fmt="table", latest=True) -> dict:
    cfg = LifecycleConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    positions = load_open_paper_positions(config, series=series)
    if ticker:
        positions = [p for p in positions if p.ticker == ticker]
    if limit and limit > 0:
        positions = positions[:limit]
    out = {"series": series, "module_enabled": cfg.enabled, "open_positions": len(positions),
           "paper_only": True, "live_submission_allowed": False, "decisions": []}
    if not positions:
        out["status"] = "NO_POSITION"
        out["message"] = ("no open paper positions found "
                          "(lifecycle manages existing positions only; it never scans flat markets)")
        return out
    books = _latest_books(config, series)
    states: dict = defaultdict(int)
    events: list[dict] = []
    for pos in positions:
        dec = _eval(config, pos, books.get(pos.ticker), cfg, fee_model)
        states[dec.action] += 1
        events.append(lifecycle_event_from_decision(dec, timestamp_ms=_now_ms()))
        if not include_rejected and dec.action == "REJECTED":
            continue
        out["decisions"].append(_dec_dict(dec))
    out["status"] = "OK"
    out["decisions_by_action"] = dict(states)
    if events:
        out["ledger"] = write_lifecycle_ledger(config, events)
    out["reports"] = _write_report(config, "dry_run", out)
    return out


def run_position_monitor_sim(config, *, series="KXBTC15M", limit=100) -> dict:
    """Replay: for each open paper position, find the first actionable lifecycle
    decision over its later book rows and compare paper P&L (ride vs act). Diagnostic."""
    cfg = LifecycleConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    positions = load_open_paper_positions(config, series=series)
    if limit and limit > 0:
        positions = positions[:limit]
    out = {"series": series, "module_enabled": cfg.enabled, "open_positions": len(positions),
           "diagnostic": True, "paper_only": True, "live_submission_allowed": False, "results": []}
    if not positions:
        out["status"] = "NO_POSITION"
        out["message"] = "no open paper positions found"
        return out
    by_ticker = _rows_by_ticker(config, series)
    pnl_ride = pnl_managed = 0.0
    acted = 0
    for pos in positions:
        rows = by_ticker.get(pos.ticker, [])
        label = next((int(r["label_yes_resolved"]) for r in rows
                      if r.get("label_yes_resolved") is not None), None)
        held = "YES" if pos.naked_yes_quantity > 0 else "NO"
        naked = pos.naked_yes_quantity if held == "YES" else pos.naked_no_quantity
        cost = pos.yes_total_cost if held == "YES" else pos.no_total_cost
        triggered = None
        for r in rows:
            dec = _eval(config, pos, r, cfg, fee_model)
            if dec.action in (SELL_SAME_LEG, SELL_PARTIAL, LOCK_WITH_OPPOSITE_LEG,
                              PARTIAL_LOCK, RISK_EXIT):
                triggered = (dec, r)
                break
        ride_pnl = _settle_naked(held, naked, cost, label) if label is not None else None
        managed_pnl = ride_pnl
        if triggered and ride_pnl is not None:
            dec, _r = triggered
            if dec.action in (SELL_SAME_LEG, SELL_PARTIAL, RISK_EXIT):
                # realize the same-leg exit profit on the filled qty; remainder rides
                q = dec.selected_order_intent.quantity if dec.selected_order_intent else naked
                realized = (dec.same_leg_exit_profit_per_contract or 0.0) * q
                managed_pnl = realized + _settle_naked(held, naked - q, cost, label)
            else:  # lock
                q = dec.selected_order_intent.quantity if dec.selected_order_intent else naked
                locked = (dec.lock_profit_per_pair or 0.0) * q
                managed_pnl = locked + _settle_naked(held, naked - q, cost, label)
            acted += 1
        if ride_pnl is not None:
            pnl_ride += ride_pnl
            pnl_managed += (managed_pnl if managed_pnl is not None else ride_pnl)
        out["results"].append({
            "ticker": pos.ticker, "held": held, "naked": naked,
            "action": (triggered[0].action if triggered else "RIDE/WATCH"),
            "ride_pnl": ride_pnl, "managed_pnl": managed_pnl,
            "reason_codes": (triggered[0].reason_codes if triggered else [])})
    out["status"] = "OK"
    out["summary"] = {"positions": len(positions), "positions_acted": acted,
                      "pnl_ride": round(pnl_ride, 6), "pnl_managed": round(pnl_managed, 6)}
    out["reports"] = _write_report(config, "sim", out)
    return out


def run_position_summary(config, *, series="KXBTC15M") -> dict:
    cfg = LifecycleConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    positions = load_open_paper_positions(config, series=series)
    out = {"series": series, "module_enabled": cfg.enabled, "open_positions": len(positions),
           "paper_only": True, "live_submission_allowed": False}
    if not positions:
        out["status"] = "NO_POSITION"
        out["message"] = "no open paper positions found"
        return out
    books = _latest_books(config, series)
    realized = unrealized = 0.0
    naked_yes = naked_no = locked_pairs = 0.0
    sell_opps = lock_opps = ride = 0
    rows_out = []
    for pos in positions:
        row = books.get(pos.ticker)
        dec = _eval(config, pos, row, cfg, fee_model)
        realized += pos.realized_locked_profit
        held = "YES" if pos.naked_yes_quantity > 0 else ("NO" if pos.naked_no_quantity > 0 else None)
        naked_yes += pos.naked_yes_quantity
        naked_no += pos.naked_no_quantity
        locked_pairs += pos.locked_pairs_quantity
        if dec.same_leg_exit_price is not None and held is not None:
            naked = pos.naked_yes_quantity if held == "YES" else pos.naked_no_quantity
            cost = pos.yes_total_cost if held == "YES" else pos.no_total_cost
            unrealized += naked * (dec.same_leg_exit_price - cost)
        if dec.action in (SELL_SAME_LEG, SELL_PARTIAL):
            sell_opps += 1
        elif dec.action in (LOCK_WITH_OPPOSITE_LEG, PARTIAL_LOCK):
            lock_opps += 1
        elif dec.action == RIDE:
            ride += 1
        rows_out.append({"ticker": pos.ticker, "held": held, "action": dec.action,
                         "same_leg_exit_profit_per_contract": dec.same_leg_exit_profit_per_contract,
                         "lock_profit_per_pair": dec.lock_profit_per_pair,
                         "continue_ev_per_contract": dec.continue_ev_per_contract})
    out["status"] = "OK"
    out["exposure"] = {"naked_yes": naked_yes, "naked_no": naked_no, "locked_pairs": locked_pairs}
    out["opportunities"] = {"sell": sell_opps, "lock": lock_opps, "ride": ride}
    out["paper_pnl"] = {"realized_locked": round(realized, 6),
                        "unrealized_mark_to_market": round(unrealized, 6)}
    out["positions"] = rows_out
    return out


# --------------------------------------------------------------------------- #
# Ledger + notifications + low-latency integration
# --------------------------------------------------------------------------- #
def lifecycle_event_from_decision(dec, *, timestamp_ms: int, model_probability_yes=None) -> dict:
    et = _EVENT_TYPE.get(dec.action, "PAPER_POSITION_LIFECYCLE_EVAL")
    intent = dec.selected_order_intent
    side = intent.side if intent else dec.current_position_side
    naked_yes_after = dec.naked_quantity_after if dec.current_position_side == "YES" else 0.0
    naked_no_after = dec.naked_quantity_after if dec.current_position_side == "NO" else 0.0
    return {
        "event_type": et, "venue": "kalshi", "series": "KXBTC15M", "ticker": dec.ticker,
        "timestamp": timestamp_ms, "market_close_ts_ms": None, "action": dec.action,
        "side": side, "quantity": (intent.quantity if intent else 0.0),
        "price": (intent.limit_price if intent else None),
        "fee": (intent.expected_fee if intent else None),
        "same_leg_exit_profit_per_contract": dec.same_leg_exit_profit_per_contract,
        "lock_profit_per_pair": dec.lock_profit_per_pair,
        "continue_ev_per_contract": dec.continue_ev_per_contract,
        "model_probability_yes": (model_probability_yes if model_probability_yes is not None
                                  else dec.model_probability_yes),
        "decision_reason_codes": dec.reason_codes,
        "naked_yes_after": naked_yes_after, "naked_no_after": naked_no_after,
        "locked_pairs_after": dec.locked_pairs_after,
        "realized_paper_pnl": None, "unrealized_paper_pnl": None,
        "live_submission_allowed": False}


def write_lifecycle_ledger(config, events: list[dict]) -> Optional[str]:
    if not events:
        return None
    d = config.data_path() / "paper"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = d / f"kalshi_lifecycle_ledger-{day}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        for e in events:
            e.setdefault("live_submission_allowed", False)
            fh.write(json.dumps(e) + "\n")
    return str(path)


def maybe_notify_lifecycle(config, dec) -> bool:
    """Best-effort notification for high-signal lifecycle actions (Noop-safe; no secrets)."""
    cfg = LifecycleConfig.from_app(config)
    if not cfg.notify or dec.action not in _NOTIFY_ACTIONS:
        return False
    try:
        from ...notifications import build_notifier
        return build_notifier(config).paper_candidate(f"LIFECYCLE {dec.human_summary}")
    except Exception:  # noqa: BLE001 — notifications are best-effort
        return False


def lifecycle_decisions_for_open_positions(config, *, series="KXBTC15M") -> list:
    """Integration entry point for the low-latency runtime / paper loop.

    Activates ONLY for existing open paper positions (never flat). Returns
    (position, decision) pairs; the caller decides whether to enqueue a
    notification (async) or record a paper intent. Never submits a live order.
    """
    cfg = LifecycleConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    positions = load_open_paper_positions(config, series=series)
    if not positions:
        return []
    books = _latest_books(config, series)
    return [(p, _eval(config, p, books.get(p.ticker), cfg, fee_model)) for p in positions]


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _write_report(config, kind: str, out: dict) -> dict:
    d = config.reports_path() / "models"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"kalshi_position_lifecycle_{kind}_{_ts()}.md"
    lines = [f"# Kalshi position lifecycle {kind} — {out['series']}", "",
             f"- module_enabled: {out['module_enabled']}",
             f"- open_paper_positions: {out['open_positions']}",
             f"- status: {out.get('status')}",
             "- POST-ENTRY ONLY (same-leg sell vs opposite-leg lock vs continue EV);"
             " not a flat arb scanner; paper-only; no live orders.", ""]
    if out.get("status") == "NO_POSITION":
        lines.append(f"- {out.get('message')}")
    elif kind == "dry_run":
        lines.append(f"- decisions_by_action: {out.get('decisions_by_action')}")
        for d0 in out.get("decisions", [])[:20]:
            lines.append(f"- [{d0['action']}] {d0['human_summary']}")
    else:
        lines.append(f"- summary: {out.get('summary')}")
    lines += ["", "## Safety",
              "- Activates only with an EXISTING paper position; never scans flat markets.",
              "- Uses executable bids/asks only (never midpoint); fees + freshness + depth gated.",
              "- Decisions use the CURRENT calibrated model probability, not entry-time belief.",
              "- live_submission_allowed=false; no live orders; live trading disabled."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report_md": str(path)}
