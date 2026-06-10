"""Kalshi paper decision layer, ledger, and session summary (record-only).

No midpoint fills: a BUY uses the executable ask (derived from the opposite
side's best bid) and pays the configured/assumed Kalshi fee. Edge is always
net of fees. An UNCALIBRATED model can never produce a PAPER_CANDIDATE — it is
capped at WATCH/MANUAL_REVIEW. Live trading is never reachable here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .book_freshness import effective_book_age
from .deribit_features import deribit_feature_fields
from .features import FEATURE_SET_VERSION
from .fees import KalshiFeeModel

LEDGER_STREAM = "kalshi_paper_ledger"
SESSION_PREFIX = "kalshi_session_summary"


def _imbalance(a, b):
    """(a - b) / (a + b) in [-1, 1], or None if not derivable."""
    if a is None or b is None:
        return None
    denom = a + b
    return ((a - b) / denom) if denom > 0 else None


def build_feature_row(
    norm_ob: dict,
    *,
    as_of_ms: int,
    reference_price: Optional[float],
    sigma_per_sqrt_s: Optional[float],
    start_reference: Optional[float],
    fee_model: KalshiFeeModel,
    underlying_extra: Optional[dict] = None,
    deribit_extra: Optional[dict] = None,
    start_reference_provenance: Optional[dict] = None,
) -> dict:
    """Assemble a point-in-time Kalshi feature row (no look-ahead).

    Keyed by (venue, series, ticker, as_of_ms). Carries Kalshi contract
    microstructure, the BTC reference, the richer external-crypto microstructure
    (merged from ``underlying_extra``; see :mod:`.features`), the OPTIONAL
    point-in-time Deribit vol/options context (merged from ``deribit_extra``; see
    :mod:`.deribit_features` — present-but-flagged when disabled/stale/missing,
    never blocking), availability/provenance flags, a fee estimate with status,
    and ``feature_set_version``.

    Anything not derivable from recorded data is ``None`` with a missingness flag
    — never invented.
    """
    close_ms = norm_ob.get("close_ms")
    secs = (close_ms - as_of_ms) / 1000.0 if close_ms else None
    flags = norm_ob.get("book_validity_flags") or {}
    yes_ask = norm_ob.get("yes_ask")
    yes_bid_size = norm_ob.get("yes_bid_size")
    no_bid_size = norm_ob.get("no_bid_size")
    dist = (reference_price - start_reference) if (reference_price is not None and start_reference is not None) else None
    # Vol-normalized distance to the line: distance standardized by the expected
    # move over the remaining time (sigma * sqrt(seconds_left)). Diagnostic only.
    dist_vol_norm = None
    if dist is not None and sigma_per_sqrt_s and secs is not None and secs > 0 and start_reference:
        expected_move = start_reference * sigma_per_sqrt_s * (secs ** 0.5)
        if expected_move > 0:
            dist_vol_norm = dist / expected_move
    book_ok = bool(not flags.get("incomplete_book") and not flags.get("yes_crossed")
                   and not flags.get("no_crossed") and flags.get("prices_in_range", True))
    book_age = effective_book_age(norm_ob, as_of_ms=as_of_ms)
    row = {
        "venue": "kalshi",
        "feature_set_version": FEATURE_SET_VERSION,
        "market_ticker": norm_ob.get("market_ticker"),
        "series_ticker": norm_ob.get("series_ticker"),
        "event_ticker": norm_ob.get("event_ticker"),
        "as_of_ms": as_of_ms,
        "recv_ms": norm_ob.get("recv_ms"),
        "source_ts_ms": norm_ob.get("source_ts_ms"),
        "close_ms": close_ms,
        "seconds_to_close": secs,
        "status": norm_ob.get("status"),
        "settlement_status": norm_ob.get("status"),
        # ----- Kalshi contract microstructure -----
        "yes_bid": norm_ob.get("yes_bid"),
        "yes_ask": yes_ask,
        "no_bid": norm_ob.get("no_bid"),
        "no_ask": norm_ob.get("no_ask"),
        "yes_spread": norm_ob.get("spread_yes"),
        "no_spread": norm_ob.get("spread_no"),
        "spread_yes": norm_ob.get("spread_yes"),   # back-compat alias
        "yes_bid_size": yes_bid_size,
        "no_bid_size": no_bid_size,
        "yes_ask_size": norm_ob.get("yes_ask_size"),
        "no_ask_size": norm_ob.get("no_ask_size"),
        "yes_depth_levels": norm_ob.get("yes_depth_levels"),
        "no_depth_levels": norm_ob.get("no_depth_levels"),
        "top_depth": (norm_ob.get("yes_ask_size") or 0.0) + (norm_ob.get("no_ask_size") or 0.0),
        "depth_imbalance": _imbalance(yes_bid_size, no_bid_size),
        "mid_yes_diagnostic": norm_ob.get("mid_yes"),   # diagnostics only; never a fill
        "executable_yes_buy_price": norm_ob.get("executable_yes_buy_price"),
        "executable_no_buy_price": norm_ob.get("executable_no_buy_price"),
        "mkt_implied_yes_from_ask": yes_ask,   # executable, not midpoint
        "quote_age_ms": norm_ob.get("quote_age_ms"),
        "book_age_ms": book_age.get("book_age_ms"),
        "book_age_basis": book_age.get("book_age_basis"),
        "book_age_method": book_age.get("book_age_method"),
        "book_age_source": book_age.get("book_age_source"),
        "book_age_confidence": book_age.get("book_age_confidence"),
        "book_recv_ms": book_age.get("book_recv_ms"),
        "book_source_ts_ms": book_age.get("book_source_ts_ms"),
        "yes_crossed": bool(flags.get("yes_crossed")),
        "no_crossed": bool(flags.get("no_crossed")),
        "incomplete_book": bool(flags.get("incomplete_book")),
        # ----- BTC reference -----
        "reference_price": reference_price,
        "reference_start_price": start_reference,
        "distance_to_start": dist,
        "distance_to_line_vol_normalized": dist_vol_norm,
        "spot_sigma_per_sqrt_s": sigma_per_sqrt_s,
        # ----- fees -----
        "fee_estimate_per_contract": fee_model.per_contract_fee(yes_ask or 0.5),
        "fee_status": fee_model.status,
        # ----- availability / health / provenance flags -----
        "has_orderbook": bool(flags.get("yes_side_present") or flags.get("no_side_present")),
        "has_underlying": reference_price is not None,
        "has_start_reference": start_reference is not None,
        "book_ok": book_ok,
        "thin_book": bool(flags.get("thin_yes") or flags.get("thin_no")),
        "feed_health_ok": bool(not flags.get("incomplete_book")),
    }
    prov = start_reference_provenance or {}
    row.update({
        "reference_start_price_source": prov.get("reference_start_price_source"),
        "reference_start_price_ts_ms": prov.get("reference_start_price_ts_ms"),
        "reference_start_price_age_ms": prov.get("reference_start_price_age_ms"),
        "reference_start_price_method": prov.get("reference_start_price_method"),
        "reference_start_price_confidence": prov.get("reference_start_price_confidence"),
        "reference_start_price_source_status": prov.get("reference_start_price_source_status"),
        "reference_missing_reason": (
            None if start_reference is not None
            else prov.get("reference_missing_reason", "START_REFERENCE_MISSING")
        ),
        "reference_start_price_detail": prov.get("reference_start_price_detail"),
        "reference_start_price_sample_count": prov.get("reference_start_price_sample_count"),
        "reference_start_price_window_offset_ms": prov.get("reference_start_price_window_offset_ms"),
    })
    if underlying_extra:
        row.update(underlying_extra)
        # Roll underlying source-health into the row-level provenance flags.
        uflags = underlying_extra.get("underlying_feature_flags") or {}
        row["has_spot_feed"] = bool(uflags.get("has_spot"))
        row["has_perp_feed"] = bool(uflags.get("has_perp"))
    # OPTIONAL Deribit context — always present (disabled/flagged when absent) so
    # the v3 schema is stable; never blocks the row.
    if deribit_extra is None:
        deribit_extra = deribit_feature_fields(snapshot=None, as_of_ms=as_of_ms, enabled=False)
    row.update(deribit_extra)
    return row


# Decision states.
NO_ACTION = "NO_ACTION"
WATCH = "WATCH"
MANUAL_REVIEW = "MANUAL_REVIEW"
PAPER_CANDIDATE = "PAPER_CANDIDATE"
REJECTED = "REJECTED"
SKIPPED = "SKIPPED"   # not a valid paper-decision target right now (collection-only)

# Reason codes for the active-window / status gate (paper-decision targets only).
MARKET_NOT_OPEN = "MARKET_NOT_OPEN"
MARKET_CLOSED = "MARKET_CLOSED"
OUTSIDE_DECISION_WINDOW = "OUTSIDE_DECISION_WINDOW"
EMPTY_OR_INCOMPLETE_BOOK = "EMPTY_OR_INCOMPLETE_BOOK"

# Kalshi market status strings (lower-cased). Recorded snapshots frequently omit
# ``status`` (None); the time-based window gate is then authoritative.
_OPEN_STATUSES = frozenset({"open", "active"})
_CLOSED_STATUSES = frozenset(
    {"closed", "settled", "finalized", "determined", "resolved", "expired"})


def decision_window_skip_reason(
    row: dict,
    *,
    market_duration_seconds: int = 900,
    accept_upcoming: bool = False,
) -> Optional[str]:
    """Return a skip reason code if ``row``'s market is NOT a valid paper-decision
    target *right now*, else ``None``.

    Pure and deterministic. A paper-decision target must be OPEN and inside its
    active trading window. Closed, pre-open / out-of-window, and not-open /
    not-accepting markets are *collection* targets only (books/labels/backfill)
    and must never be run through the model or policy.

    Gating is primarily time-based: for a fixed-duration market the only way
    ``seconds_to_close`` can exceed ``market_duration_seconds`` is that the active
    window has not started yet (pre-open). Explicit ``status`` / ``accepting_orders``
    signals are honoured when present (recorded data often omits them).
    """
    status = (row.get("status") or "").strip().lower()
    if status in _CLOSED_STATUSES:
        return MARKET_CLOSED
    if row.get("accepting_orders") is False:
        return MARKET_NOT_OPEN
    if status and status not in _OPEN_STATUSES:
        return MARKET_NOT_OPEN
    secs = row.get("seconds_to_close")
    if secs is None:
        return MARKET_NOT_OPEN
    if secs <= 0:
        return MARKET_CLOSED
    if not accept_upcoming and secs > market_duration_seconds:
        return OUTSIDE_DECISION_WINDOW
    return None


def decide_kalshi(
    row: dict,
    *,
    model_p_yes: Optional[float],
    calibrated: bool,
    fee_model: KalshiFeeModel,
    min_net_edge_cents: float = 2.0,
    max_quote_age_ms: int = 2000,
    order_size: float = 5.0,
    allow_uncalibrated_candidates: bool = False,
    market_duration_seconds: int = 900,
    accept_upcoming: bool = False,
) -> dict:
    """Compare the model probability to executable Kalshi asks after fees.

    Picks the better of BUY YES / BUY NO. Emits SKIPPED / NO_ACTION / WATCH /
    MANUAL_REVIEW / PAPER_CANDIDATE / REJECTED. Markets that are not valid
    decision targets right now (closed / pre-open / out-of-window / not-open) are
    SKIPPED *before* any scoring. Uncalibrated models are capped at MANUAL_REVIEW
    unless explicitly allowed for paper diagnostics.
    """
    reasons: list[str] = []
    yes_ask = row.get("yes_ask")
    no_ask = row.get("no_ask")
    book_ok = bool(row.get("book_ok"))
    age = row.get("quote_age_ms")

    # Active-window / status gate FIRST: never score a non-decision target. This
    # precedes the book check so a post-close empty book is reported as
    # MARKET_CLOSED rather than mislabeled as an incomplete-book problem.
    skip = decision_window_skip_reason(
        row, market_duration_seconds=market_duration_seconds, accept_upcoming=accept_upcoming)
    if skip is not None:
        return _result(SKIPPED, None, None, None, None, fee_model, [skip], book_ok)

    if model_p_yes is None:
        return _result(WATCH, None, None, None, None, fee_model, ["NO_MODEL_PROB"], book_ok)
    if not book_ok or yes_ask is None or no_ask is None:
        return _result(REJECTED, None, None, model_p_yes, None, fee_model,
                       [EMPTY_OR_INCOMPLETE_BOOK], book_ok)
    if age is not None and age > max_quote_age_ms:
        reasons.append("STALE_QUOTE")

    # Edge for each executable buy, net of fees (in probability cents).
    fee_yes = fee_model.per_contract_fee(yes_ask)
    fee_no = fee_model.per_contract_fee(no_ask)
    edge_yes = (model_p_yes - yes_ask) - fee_yes
    edge_no = ((1.0 - model_p_yes) - no_ask) - fee_no

    if edge_yes >= edge_no:
        side, exec_price, implied, net_edge, fee = "BUY_YES", yes_ask, yes_ask, edge_yes, fee_yes
    else:
        side, exec_price, implied, net_edge, fee = "BUY_NO", no_ask, no_ask, edge_no, fee_no

    if row.get("thin_book"):
        reasons.append("THIN_BOOK")

    net_edge_cents = net_edge * 100.0
    if net_edge_cents < min_net_edge_cents:
        reasons.append(f"EDGE_BELOW_MIN({net_edge_cents:.1f}c<{min_net_edge_cents:.1f}c)")
        return _result(NO_ACTION if net_edge_cents <= 0 else WATCH, side, exec_price,
                       model_p_yes, implied, fee_model, reasons, book_ok, net_edge=net_edge, fee=fee)

    if "STALE_QUOTE" in reasons:
        return _result(WATCH, side, exec_price, model_p_yes, implied, fee_model, reasons,
                       book_ok, net_edge=net_edge, fee=fee)

    if not calibrated and not allow_uncalibrated_candidates:
        reasons.append("UNCALIBRATED_MODEL")
        return _result(MANUAL_REVIEW, side, exec_price, model_p_yes, implied, fee_model, reasons,
                       book_ok, net_edge=net_edge, fee=fee, order_size=order_size)

    reasons.append("NET_EDGE_OK")
    return _result(PAPER_CANDIDATE, side, exec_price, model_p_yes, implied, fee_model, reasons,
                   book_ok, net_edge=net_edge, fee=fee, order_size=order_size, simulate=True, row=row)


def _result(state, side, exec_price, model_p, implied, fee_model, reasons, book_ok,
            *, net_edge=None, fee=None, order_size=0.0, simulate=False, row=None) -> dict:
    sim_price = sim_size = None
    fill_status = "not_traded"
    if simulate and exec_price is not None and row is not None:
        # No midpoint: fill at the executable ask, size-capped by available ask depth.
        ask_size = row.get("yes_ask_size") if side == "BUY_YES" else row.get("no_ask_size")
        sim_size = min(order_size, ask_size) if ask_size is not None else order_size
        sim_price = exec_price
        fill_status = "simulated_filled" if sim_size and sim_size > 0 else "no_depth"
    raw_edge = (net_edge + fee) if (net_edge is not None and fee is not None) else None
    return {
        "decision_state": state,
        "side": side,
        "executable_price": exec_price,
        "model_probability": model_p,
        "market_implied_probability": implied,
        "fee_estimate": fee,
        "fee_status": fee_model.status,
        "raw_edge": raw_edge,
        "net_edge": net_edge,
        "net_edge_cents": (net_edge * 100.0) if net_edge is not None else None,
        "order_size": order_size,
        "fill_status": fill_status,
        "simulated_fill_price": sim_price,
        "simulated_fill_size": sim_size,
        "reason_codes": reasons,
        "liquidity_blocker": bool("THIN_BOOK" in reasons or not book_ok),
        "staleness_blocker": bool("STALE_QUOTE" in reasons),
        "book_status": "ok" if book_ok else "invalid",
    }


@dataclass
class KalshiLedgerEntry:
    created_at_ms: int
    venue: str
    series_ticker: Optional[str]
    market_ticker: Optional[str]
    side: Optional[str]
    decision_state: str
    model_probability: Optional[float]
    market_implied_probability: Optional[float]
    executable_price: Optional[float]
    fee_estimate: Optional[float]
    fee_status: str
    spread_cost: Optional[float]
    slippage_estimate: Optional[float]
    net_edge: Optional[float]
    order_size: Optional[float]
    fill_status: str
    simulated_fill_price: Optional[float]
    simulated_fill_size: Optional[float]
    reason_codes: list = field(default_factory=list)
    book_status: str = "unknown"
    label_source_status: str = "UNKNOWN"
    known_outcome: Optional[int] = None
    paper_pnl: Optional[float] = None
    is_paper: bool = True
    # ----- richer context (Phase H) -----
    market_close_time_ms: Optional[int] = None
    seconds_to_close: Optional[float] = None
    model_version: str = "baseline"
    feature_set_version: int = FEATURE_SET_VERSION
    calibration_status: str = "uncalibrated"
    executable_yes_price: Optional[float] = None
    executable_no_price: Optional[float] = None
    raw_edge: Optional[float] = None
    liquidity_blocker: bool = False
    staleness_blocker: bool = False
    source_health_summary: Optional[str] = None
    settlement_outcome_when_known: Optional[int] = None
    paper_pnl_when_known: Optional[float] = None


def write_kalshi_ledger(config, entries, *, ref_ms: Optional[int] = None) -> tuple[int, Path]:
    d = config.data_path() / "paper"
    d.mkdir(parents=True, exist_ok=True)
    ts = ref_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y%m%d")
    path = d / f"{LEDGER_STREAM}-{day}.jsonl"
    n = 0
    with path.open("a", encoding="utf-8") as fh:
        for e in entries:
            rec = asdict(e) if isinstance(e, KalshiLedgerEntry) else e
            fh.write(json.dumps(rec) + "\n")
            n += 1
    return n, path


def write_kalshi_session_summary(config, session: dict, *, ref_ms: Optional[int] = None) -> Path:
    d = config.reports_path() / "paper"
    d.mkdir(parents=True, exist_ok=True)
    ts = ref_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y%m%d")
    path = d / f"{SESSION_PREFIX}-{day}.md"
    data = session.get("data", {})
    dec = session.get("decisions_by_state", {})
    fees = session.get("fee_assumptions", {})
    lines = [
        f"# Kalshi BTC 15m — paper session summary ({day})",
        "",
        f"- run_duration_s: {session.get('run_duration_s')}",
        f"- markets_discovered: {data.get('markets_discovered')}",
        f"- open/current: {data.get('open_markets')}  upcoming: {data.get('upcoming_markets')}  "
        f"closed: {data.get('closed_markets')}  settled: {data.get('settled_markets')}",
        f"- raw_orderbook_rows: {data.get('raw_orderbook_rows')}",
        f"- normalized_orderbook_rows: {data.get('normalized_orderbook_rows')}",
        f"- underlying_events: {data.get('underlying_events')}",
        f"- labels_backfilled: {data.get('labels_backfilled')}",
        f"- feature_rows_built: {data.get('feature_rows_built')}",
        "",
        "## Decisions by state",
    ]
    for k in (NO_ACTION, WATCH, MANUAL_REVIEW, PAPER_CANDIDATE, REJECTED):
        lines.append(f"- {k}: {dec.get(k, 0)}")
    lines += [
        "",
        f"- paper_candidates: {session.get('paper_candidates', 0)}",
        f"- simulated_fills: {session.get('simulated_fills', 0)}",
        f"- rejections: {dec.get(REJECTED, 0)}",
        "",
        "## Fee assumptions",
        f"- fee_status: {fees.get('fee_status')}  rate: {fees.get('fee_rate')}",
        f"- formula: {fees.get('fee_formula')}",
        "",
        "## Blockers",
    ]
    for b in session.get("blockers", []) or ["(none)"]:
        lines.append(f"- {b}")
    lines += [
        "",
        "## Safety",
        f"- {session.get('safety', 'live trading disabled by default; record-only; no orders placed')}",
        "",
        "## Next 3 actions",
    ]
    for i, a in enumerate(session.get("next_actions", [])[:3], 1):
        lines.append(f"{i}. {a}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
