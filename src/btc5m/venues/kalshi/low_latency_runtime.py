"""Low-latency Kalshi runtime: event-driven scoring loop + offline benchmark.

Pipeline per update (all in-memory; no file reads / pandas / model load per tick):
  fresh book/underlying -> HotPathState -> feature snapshot -> preloaded scorer
  -> executable EV + gates -> WATCH / MANUAL_REVIEW / REJECTED (never a live order;
  never PAPER_CANDIDATE from an uncalibrated model).

WebSocket is optional and needs auth; this build always falls back to REST polling
(reported via :class:`KalshiWSClient`). The smoke is resilient: if discovery / book
fetch is unavailable (e.g. offline), it runs on SYNTHETIC ticks so the architecture
and latency path are still exercised — clearly labelled, never written as real data.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ...timeutils import now_ms
from .fees import KalshiFeeModel
from .hotpath_state import HotPathState
from .latency import LatencyTracker
from .order_planner import plan_order
from .paper import MANUAL_REVIEW, NO_ACTION, PAPER_CANDIDATE, REJECTED, WATCH
from .scorer import KalshiScorer
from .ws_client import KalshiWSClient


# --------------------------------------------------------------------------- #
# Executable EV (hot path)
# --------------------------------------------------------------------------- #
def evaluate_ev(row: dict, score: Any, *, fee_model: Any, cfg: Any,
                latency: Optional[LatencyTracker] = None) -> dict:
    """Compute executable per-side edges + a gated decision state (no midpoint).

    Hard rejects: invalid/incomplete book, window closed/closing, stale book,
    stale underlying, missing start reference, insufficient depth. Uncalibrated
    models are capped at MANUAL_REVIEW (never PAPER_CANDIDATE). Returns a flat dict.
    """
    ll = cfg.low_latency
    reasons: list[str] = []
    p = score.p_yes
    yes_ask = row.get("yes_ask")
    no_ask = row.get("no_ask")
    book_ok = bool(row.get("book_ok"))
    secs = row.get("seconds_to_close")
    book_age = row.get("hotpath_book_age_ms")
    und_age = row.get("hotpath_underlying_age_ms")
    start_ref = row.get("reference_start_price")
    top_depth = row.get("top_depth") or 0.0

    raw_yes = (p - yes_ask) if (p is not None and yes_ask is not None) else None
    raw_no = ((1.0 - p) - no_ask) if (p is not None and no_ask is not None) else None
    fee_yes = fee_model.per_contract_fee(yes_ask) if yes_ask is not None else None
    fee_no = fee_model.per_contract_fee(no_ask) if no_ask is not None else None
    buf = (ll.uncertainty_buffer_cents or 0.0) / 100.0
    net_yes = (raw_yes - fee_yes - buf) if (raw_yes is not None and fee_yes is not None) else None
    net_no = (raw_no - fee_no - buf) if (raw_no is not None and fee_no is not None) else None

    def out(state: str, side: Optional[str] = None) -> dict:
        sel_net = net_yes if side == "BUY_YES" else net_no if side == "BUY_NO" else None
        sel_price = yes_ask if side == "BUY_YES" else no_ask if side == "BUY_NO" else None
        if latency is not None and state == REJECTED and reasons:
            latency.reject(reasons[-1])
        return {
            "decision_state": state,
            "side": side,
            "selected_side": side,
            "reason_codes": reasons,
            "model_probability_yes": p,
            "executable_yes_price": yes_ask,
            "executable_no_price": no_ask,
            "raw_edge_yes": raw_yes,
            "raw_edge_no": raw_no,
            "net_edge_yes": net_yes,
            "net_edge_no": net_no,
            "net_edge": sel_net,
            "net_edge_cents": (sel_net * 100.0) if sel_net is not None else None,
            "executable_price": sel_price,
            "fee_estimate": (fee_yes if side == "BUY_YES" else fee_no if side == "BUY_NO" else None),
            "order_size": ll.min_depth,
            "calibration_status": score.calibration_status,
        }

    if p is None:
        reasons.append("NO_MODEL_PROB")
        return out(WATCH)
    if not book_ok:
        reasons.append("INVALID_OR_INCOMPLETE_BOOK")
        return out(REJECTED)
    if yes_ask is None or no_ask is None:
        reasons.append("NO_EXECUTABLE_ASK")
        return out(REJECTED)
    if secs is not None and secs <= 0:
        reasons.append("WINDOW_CLOSED")
        return out(REJECTED)
    if secs is not None and secs < ll.min_seconds_to_close:
        reasons.append("WINDOW_CLOSING")
        return out(REJECTED)
    if book_age is None or book_age > ll.max_book_age_ms:
        reasons.append("STALE_BOOK")
        return out(REJECTED)
    if und_age is None or und_age > ll.max_underlying_age_ms:
        reasons.append("STALE_UNDERLYING")
        return out(REJECTED)
    if start_ref is None:
        reasons.append("MISSING_START_REFERENCE")
        return out(REJECTED)
    if top_depth < ll.min_depth:
        reasons.append("INSUFFICIENT_DEPTH")
        return out(REJECTED)

    side = "BUY_YES" if (net_yes is not None and (net_no is None or net_yes >= net_no)) else "BUY_NO"
    sel_net = net_yes if side == "BUY_YES" else net_no
    net_cents = (sel_net or 0.0) * 100.0
    if net_cents < ll.min_net_edge_cents:
        reasons.append(f"EDGE_BELOW_MIN({net_cents:.1f}c<{ll.min_net_edge_cents:.1f}c)")
        return out(NO_ACTION if net_cents <= 0 else WATCH, side)
    if not score.calibrated:
        reasons.append("UNCALIBRATED_MODEL")
        return out(MANUAL_REVIEW, side)
    reasons.append("NET_EDGE_OK")
    return out(PAPER_CANDIDATE, side)


def build_decision_event(row: dict, ev: dict, score: Any, *, series: str,
                         feature_ms: float, score_ms: float, decision_ms: float,
                         end_to_end_ms: float) -> dict:
    """Assemble the structured paper decision event (no live order submitted)."""
    return {
        "timestamp_ms": now_ms(),
        "ticker": row.get("market_ticker"),
        "series": series,
        "score_latency_ms": round(score_ms, 4),
        "feature_latency_ms": round(feature_ms, 4),
        "decision_latency_ms": round(decision_ms, 4),
        "end_to_end_latency_ms": round(end_to_end_ms, 4),
        "book_age_ms": row.get("hotpath_book_age_ms"),
        "underlying_age_ms": row.get("hotpath_underlying_age_ms"),
        "deribit_age_ms": row.get("deribit_age_ms"),
        "model_version": score.model_version,
        "feature_schema_version": score.feature_schema_version,
        "calibration_status": score.calibration_status,
        "decision_state": ev["decision_state"],
        "reason_codes": ev["reason_codes"],
        "model_probability_yes": ev["model_probability_yes"],
        "executable_yes_price": ev["executable_yes_price"],
        "executable_no_price": ev["executable_no_price"],
        "raw_edge_yes": ev["raw_edge_yes"],
        "raw_edge_no": ev["raw_edge_no"],
        "net_edge_yes": ev["net_edge_yes"],
        "net_edge_no": ev["net_edge_no"],
        "selected_side": ev["selected_side"],
        "live_order_submitted": False,
    }


# --------------------------------------------------------------------------- #
# Synthetic fixtures (offline smoke / benchmark only — never written as real data)
# --------------------------------------------------------------------------- #
def _synthetic_market(series: str, now: int, duration_s: int = 900) -> dict:
    open_ms = now - 120_000
    close_ms = now + max(60_000, duration_s * 1000 - 120_000)

    def _iso(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "ticker": f"{series}-SYNTH", "event_ticker": f"{series}-SYNTH",
        "series_ticker": series, "status": "active",
        "yes_sub_title": "Target Price: $70,000.00",
        "open_time": _iso(open_ms), "close_time": _iso(close_ms),
        "rules_primary": "If the simple average ... is at least the simple average ...",
        "_phase": "CURRENT_IN_WINDOW", "_synthetic": True,
    }


def _synthetic_book(i: int = 0) -> dict:
    # yes bid 0.40 / no bid 0.58 -> yes_ask 0.42, no_ask 0.60; ample depth.
    return {"orderbook_fp": {"yes_dollars": [["0.39", "400"], ["0.40", "500"]],
                             "no_dollars": [["0.57", "400"], ["0.58", "500"]]}}


def _synthetic_spot(ts: int, base: float = 70_010.0, i: int = 0) -> dict:
    wig = 0.5 if i % 2 == 0 else -0.5
    px = base + 0.02 * i + wig
    return {"source": "coinbase", "symbol": "BTC-USD", "event_type": "ticker",
            "recv_ms": ts, "exchange_ts_ms": ts, "price": px,
            "best_bid": px - 0.5, "best_ask": px + 0.5}


def _synthetic_perp(ts: int, base: float = 70_012.0, i: int = 0) -> dict:
    px = base + 0.02 * i
    return {"source": "binance_futures", "event_type": "book", "recv_ms": ts,
            "best_bid": px - 1.0, "best_ask": px + 1.0, "bid_size": 12.0, "ask_size": 8.0}


# --------------------------------------------------------------------------- #
# Smoke loop
# --------------------------------------------------------------------------- #
def run_hotpath_smoke(
    cfg: Any, *, series: str = "KXBTC15M", seconds: float = 10.0, max_markets: int = 1,
    sources: str = "coinbase,binance", emit: Callable[[str], None] = print,
    client: Any = None, underlying_clients: Any = None, synthetic: bool = False,
) -> dict:
    """Run a short, safe, paper-only hot-path smoke. Never submits orders."""
    ll = cfg.low_latency
    fee_model = KalshiFeeModel.from_config(cfg)
    scorer = KalshiScorer(cfg)
    src_names = [s.strip().lower() for s in (sources or "").split(",") if s.strip()]
    deribit_enabled = bool(getattr(getattr(cfg, "deribit", None), "enabled", False)
                           and any(s.startswith("deribit") for s in src_names))
    state = HotPathState(cfg, fee_model=fee_model, deribit_enabled=deribit_enabled,
                         max_book_age_ms=ll.max_book_age_ms,
                         max_underlying_age_ms=ll.max_underlying_age_ms,
                         max_deribit_age_ms=ll.max_deribit_age_ms)
    latency = LatencyTracker()

    emit(f"=== kalshi-hotpath-smoke: series={series} seconds={seconds} max_markets={max_markets} "
         f"sources={src_names} score_interval={ll.hotpath_score_interval_ms}ms ===")
    emit("safety: PAPER-ONLY hot path; live trading disabled; NO orders placed. "
         "Uncalibrated model -> no PAPER_CANDIDATE.")
    ws_status = KalshiWSClient(cfg).availability()
    emit(f"websocket: available={ws_status['available']} ({ws_status['reason']})")

    # ---- resolve data sources (degrade to synthetic if unavailable) ----
    use_synth = synthetic
    targets: list[dict] = []
    if not use_synth:
        if client is None:
            from .client import KalshiClient
            client = KalshiClient(cfg)
        try:
            discovered = client.discover(series_ticker=series,
                                         statuses=("open", "unopened", "settled"))
            keep = [m for m in discovered if m.get("_phase") in
                    ("CURRENT_IN_WINDOW", "UPCOMING_PRE_WINDOW", "UPCOMING")]
            targets = (keep or discovered)[:max_markets]
        except Exception as exc:  # noqa: BLE001
            emit(f"[fallback] discovery unavailable ({type(exc).__name__}); using SYNTHETIC smoke.")
            use_synth = True
    if not targets and not use_synth:
        emit("[fallback] no current/upcoming markets; using SYNTHETIC smoke.")
        use_synth = True
    if use_synth:
        targets = [_synthetic_market(series, now_ms(), ll.market_duration_seconds)]

    if underlying_clients is None and not use_synth:
        from ...data.underlying import build_underlying_client
        underlying_clients = []
        for name in src_names:
            if name.startswith("deribit"):
                continue
            try:
                underlying_clients.append(build_underlying_client(name, cfg))
            except ValueError as exc:
                emit(f"[warn] {exc}")
    underlying_clients = underlying_clients or []

    for m in targets[:max_markets]:
        state.set_market(m)
    # Seed underlying so returns/vol exist immediately (synthetic warmup is offline).
    if use_synth:
        base = now_ms() - 60_000
        for i in range(61):
            state.ingest_underlying(_synthetic_spot(base + i * 1000, i=i))
        state.ingest_underlying(_synthetic_perp(now_ms(), i=1))

    # Optional paper-candidate POLICY integration (off by default; never live).
    policy_validity = None
    if getattr(getattr(cfg, "paper_policy", None), "enabled", False):
        try:
            from .policy_runtime import assess_validity
            policy_validity = assess_validity(cfg)
            emit("policy: ENABLED — evaluating paper-candidate gates per row (no orders).")
        except Exception:  # noqa: BLE001
            policy_validity = None

    events: list[dict] = []
    plans = 0
    deadline = time.monotonic() + max(0.0, float(seconds))
    first = True
    i = 0
    while first or time.monotonic() < deadline:
        first = False
        i += 1
        # ---- underlying update ----
        if use_synth:
            state.ingest_underlying(_synthetic_spot(now_ms(), i=i))
            state.ingest_underlying(_synthetic_perp(now_ms(), i=i))
        else:
            for uc in underlying_clients:
                try:
                    import dataclasses
                    for _raw, ev in uc.poll():
                        state.ingest_underlying(dataclasses.asdict(ev))
                except Exception:  # noqa: BLE001
                    pass
        # ---- per-market book -> snapshot -> score -> EV ----
        for m in targets[:max_markets]:
            tk = m.get("ticker")
            t0 = time.perf_counter()
            recv = now_ms()
            try:
                raw = _synthetic_book(i) if use_synth else client.get_orderbook(tk)
            except Exception:  # noqa: BLE001
                continue
            state.update_book(tk, raw, recv_ms=recv, source_ts_ms=recv)
            as_of = now_ms()
            with latency.stopwatch("feature") as sw_f:
                row = state.feature_snapshot(tk, as_of)
            if row is None:
                continue
            with latency.stopwatch("score") as sw_s:
                sr = scorer.score(row)
            with latency.stopwatch("decision") as sw_d:
                ev = evaluate_ev(row, sr, fee_model=fee_model, cfg=cfg, latency=latency)
            end_to_end = (time.perf_counter() - t0) * 1000.0
            latency.record("end_to_end", end_to_end)
            event = build_decision_event(row, ev, sr, series=series, feature_ms=sw_f.ms,
                                         score_ms=sw_s.ms, decision_ms=sw_d.ms,
                                         end_to_end_ms=end_to_end)
            if policy_validity is not None:
                try:
                    from .policy_runtime import policy_decision_for_hotpath
                    pdec = policy_decision_for_hotpath(
                        cfg, row, series=series, p_raw=sr.p_yes,
                        p_cal=(sr.p_yes if sr.calibrated else None), validity=policy_validity)
                    event["policy_decision_state"] = pdec.decision_state
                    event["policy_reason_codes"] = pdec.reason_codes
                    event["policy_is_paper_candidate"] = pdec.is_paper_candidate
                    event["live_order_submitted"] = False
                except Exception:  # noqa: BLE001
                    pass
            events.append(event)
            if ll.order_planning_enabled and ev.get("side"):
                if plan_order(decision=ev, row=row, fee_model=fee_model, config=cfg,
                              mode="paper_fok_sim") is not None:
                    plans += 1
            if i == 1 or (ll.log_every_n and i % ll.log_every_n == 0):
                emit(f"[{event['ticker']}] {event['decision_state']} "
                     f"p_yes={_fmt(event['model_probability_yes'])} "
                     f"yes_ask={_fmt(event['executable_yes_price'])} "
                     f"no_ask={_fmt(event['executable_no_price'])} "
                     f"e2e={event['end_to_end_latency_ms']}ms reasons={event['reason_codes']}")
        if time.monotonic() < deadline:
            time.sleep(max(0.0, ll.hotpath_score_interval_ms / 1000.0))

    written = _write_decisions(cfg, events)
    summ = latency.summary()
    emit("--- hotpath smoke summary ---")
    emit(f"decisions emitted: {len(events)}  (synthetic={use_synth})  order_plans_simulated: {plans}")
    from collections import Counter as _C
    emit(f"decisions_by_state: {dict(_C(e['decision_state'] for e in events))}")
    for phase in ("feature", "score", "decision", "end_to_end"):
        s = summ.get(phase)
        if s:
            emit(f"  {phase:9s} p50={_ms(s['p50'])} p90={_ms(s['p90'])} "
                 f"p99={_ms(s['p99'])} max={_ms(s['max'])} n={s['count']}")
    if latency.rejections:
        emit(f"rejections_by_reason: {dict(latency.rejections)}")
    if written:
        emit(f"decision events -> {written[0]} ({written[1]} rows)")
    emit("safety: NO live orders submitted; live trading disabled.")
    return {"decisions": len(events), "synthetic": use_synth,
            "latency": summ, "rejections": dict(latency.rejections),
            "decisions_by_state": dict(_C(e["decision_state"] for e in events))}


# --------------------------------------------------------------------------- #
# Offline latency benchmark
# --------------------------------------------------------------------------- #
def run_latency_benchmark(cfg: Any, *, series: str = "KXBTC15M", samples: int = 1000,
                          emit: Callable[[str], None] = print) -> dict:
    """Fully offline/synthetic latency benchmark. No network, no creds, no orders."""
    fee_model = KalshiFeeModel.from_config(cfg)
    scorer = KalshiScorer(cfg)
    state = HotPathState(cfg, fee_model=fee_model, deribit_enabled=False,
                         max_book_age_ms=cfg.low_latency.max_book_age_ms,
                         max_underlying_age_ms=cfg.low_latency.max_underlying_age_ms)
    latency = LatencyTracker()

    emit(f"=== kalshi-latency-benchmark: series={series} samples={samples} "
         f"(offline/synthetic; no network; no orders) ===")
    market = _synthetic_market(series, now_ms(), cfg.low_latency.market_duration_seconds)
    state.set_market(market)
    tk = market["ticker"]
    base = now_ms() - 60_000
    for i in range(61):
        state.ingest_underlying(_synthetic_spot(base + i * 1000, i=i))
    state.ingest_underlying(_synthetic_perp(now_ms(), i=1))

    n = max(1, int(samples))
    for i in range(n):
        ts = now_ms()
        state.ingest_underlying(_synthetic_spot(ts, i=i))
        state.update_book(tk, _synthetic_book(i), recv_ms=ts, source_ts_ms=ts)
        as_of = now_ms()
        with latency.stopwatch("feature"):
            row = state.feature_snapshot(tk, as_of)
        with latency.stopwatch("score"):
            sr = scorer.score(row)
        with latency.stopwatch("decision"):
            evaluate_ev(row, sr, fee_model=fee_model, cfg=cfg, latency=latency)

    # ---- notification enqueue overhead -------------------------------------- #
    # Enqueuing is the ONLY notification work the hot path would ever do; the send
    # itself runs in a background worker. Measured on a Noop-bound queue with the
    # worker disabled to isolate the pure enqueue cost added to the decision path.
    try:
        from ...notifications.base import Notification
        from ...notifications.noop import NoopNotifier
        from ...notifications.queue import NotificationQueue, Priority
        nq = NotificationQueue(NoopNotifier(cfg), async_enabled=True, maxsize=n + 16,
                               coalesce_low=False, start_worker=False)
        for _j in range(n):
            with latency.stopwatch("notify_enqueue"):
                nq.enqueue(Notification("WATCH", "bench", "probe"), priority=Priority.LOW)
        nq.close()
    except Exception:  # noqa: BLE001 — benchmark add-on is best-effort
        pass

    summ = latency.summary()
    emit("--- latency benchmark (ms) ---")
    for phase in ("feature", "score", "decision", "notify_enqueue"):
        s = summ.get(phase) or {}
        emit(f"  {phase:14s} p50={_ms(s.get('p50'))} p90={_ms(s.get('p90'))} "
             f"p99={_ms(s.get('p99'))} max={_ms(s.get('max'))} mean={_ms(s.get('mean'))} n={s.get('count')}")
    # crude hot-spot hint: phase with the highest p99 (decision-path phases only)
    hot = max(("feature", "score", "decision"),
              key=lambda p: (summ.get(p, {}).get("p99") or 0.0))
    emit(f"slowest_phase_by_p99: {hot}")
    enq_p99 = (summ.get("notify_enqueue") or {}).get("p99")
    dec_p50 = (summ.get("decision") or {}).get("p50")
    if isinstance(enq_p99, (int, float)):
        verdict = "negligible" if enq_p99 < 0.05 else "small" if enq_p99 < 0.25 else "NON-NEGLIGIBLE"
        emit(f"notification_enqueue_overhead: p99={_ms(enq_p99)} -> {verdict} "
             f"(decision p50={_ms(dec_p50)}); the send runs off-path in a background worker.")
    if latency.rejections:
        emit(f"rejections_by_reason: {dict(latency.rejections)}")
    emit("safety: offline benchmark; no network; no orders; live trading disabled.")
    return {"samples": n, "latency": summ, "slowest_phase_by_p99": hot,
            "notify_enqueue_overhead_p99_ms": enq_p99,
            "rejections": dict(latency.rejections)}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _write_decisions(cfg: Any, events: list[dict]):
    if not events:
        return None
    d = cfg.data_path() / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = d / f"kalshi_hotpath_decisions-{day}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
    return path, len(events)


def _fmt(x: Optional[float]) -> str:
    return f"{x:.3f}" if isinstance(x, (int, float)) else "None"


def _ms(x: Optional[float]) -> str:
    return f"{x:.3f}" if isinstance(x, (int, float)) else "None"
