"""Continuous, single-process Kalshi collection loop.

Rediscovers KXBTC15M every cycle; records current/upcoming/just-settled
orderbooks + Coinbase/Binance underlying (+ optional Deribit); builds rich
point-in-time feature rows; periodically backfills OFFICIAL settlements and runs
readiness; writes a ledger + session summary each cycle; prints a heartbeat.

Robust by design: every network call is wrapped, transient failures are counted
and skipped, the loop continues until ``max_cycles`` or Ctrl-C, and because all
writes are append-only JSONL, stopping at any point leaves recorded data valid.
NEVER submits live orders.
"""

from __future__ import annotations

import dataclasses
import time
from collections import Counter
from typing import Callable, Optional

from ...data.recorder import Recorder
from ...data.underlying import build_underlying_client
from ...models.baseline import BaselineInputs, BaselineModel
from ...notifications.base import Notification
from ...notifications.queue import Priority, build_notification_queue
from ...schemas import Comparison
from ...timeutils import now_ms
from .client import KalshiClient, classify_market, iso_to_ms, select_collection_targets
from .deribit_features import DeribitState, deribit_feature_fields
from .features import UnderlyingMicrostructureState
from .fees import KalshiFeeModel
from .orderbook import normalize_orderbook
from .paper import (
    KalshiLedgerEntry, build_feature_row, decide_kalshi, decision_window_skip_reason,
    write_kalshi_ledger, write_kalshi_session_summary,
)
from .readiness import load_kalshi_readiness
from .settlement import build_label_row, comparison_from_rules
from .start_reference import StartReferenceResolver


def _sigma(samples: list[tuple[int, float]]) -> Optional[float]:
    import math
    rets = []
    for (t0, p0), (t1, p1) in zip(samples, samples[1:]):
        if p0 and p1 and p0 > 0 and p1 > 0 and t1 > t0:
            dt = (t1 - t0) / 1000.0
            if dt > 0:
                rets.append(math.log(p1 / p0) / math.sqrt(dt))
    if len(rets) < 3:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) if var > 0 else None


def _poll_underlying_once(rec, und_clients, micro_state) -> tuple[int, int]:
    """Poll + record + ingest the underlying feeds once. Returns (events, errors).

    Records raw + normalized and feeds the in-memory microstructure buffer. Kept tiny
    so it can be called on a TIGHT decision-freshness interval, decoupled from the
    slower Kalshi book loop."""
    events = errors = 0
    for uc in und_clients:
        try:
            for raw_ev, ev in uc.poll():
                rec.record_raw(f"underlying_{uc.source}", raw_ev)
                ev_dict = dataclasses.asdict(ev)
                rec.record_normalized(f"underlying_{uc.source}", ev_dict)
                micro_state.ingest(ev_dict)
                events += 1
        except Exception:  # noqa: BLE001
            errors += 1
    return events, errors


class _TradePoller:
    """Polls PUBLIC Kalshi trade prints (no auth) and records normalized rows.

    Trade prints are the missing input for honest maker-fill modeling (see
    RESEARCH_LEDGER.md legs 13/14): ``taker_side`` says which side aggressed, so
    the resting (maker) side of every print is known. One bounded HTTP call per
    poll covers ALL series tickers via a min_ts watermark + trade_id dedupe.
    Failures never disturb the book loop."""

    def __init__(self, client, series: str, poll_interval_s: float = 5.0):
        self.client = client
        self.series = series
        self.poll_interval_s = poll_interval_s
        self._last_poll_mono = 0.0
        self._watermark_s: Optional[int] = None
        self._seen: dict[str, None] = {}   # insertion-ordered bounded id cache

    def poll(self, rec, *, mono_now: float, recv_ms: int) -> tuple[int, int]:
        if mono_now - self._last_poll_mono < self.poll_interval_s:
            return 0, 0
        self._last_poll_mono = mono_now
        get_trades = getattr(self.client, "get_trades", None)
        if get_trades is None:
            return 0, 0
        try:
            trades = get_trades(min_ts=self._watermark_s, limit=200, max_pages=3)
        except Exception:  # noqa: BLE001
            return 0, 1
        wrote = 0
        max_ts_s = self._watermark_s or 0
        for t in trades:
            tk = t.get("ticker") or ""
            tid = t.get("trade_id")
            if not tk.startswith(self.series) or not tid or tid in self._seen:
                continue
            created_ms = iso_to_ms(t.get("created_time"))
            row = {
                "venue": "kalshi", "series_ticker": self.series, "market_ticker": tk,
                "trade_id": tid, "created_time_ms": created_ms, "recv_ms": recv_ms,
                "yes_price": _fnum(t.get("yes_price_dollars", t.get("yes_price"))),
                "no_price": _fnum(t.get("no_price_dollars", t.get("no_price"))),
                "count": _fnum(t.get("count_fp", t.get("count"))),
                "taker_side": t.get("taker_side"),
                "is_block_trade": bool(t.get("is_block_trade")),
            }
            rec.record_normalized("kalshi_trades", row)
            self._seen[tid] = None
            wrote += 1
            if created_ms:
                max_ts_s = max(max_ts_s, created_ms // 1000)
        # watermark backs off 2s to tolerate same-second arrivals (dedupe absorbs
        # the overlap) but never regresses below its current value
        if max_ts_s:
            self._watermark_s = max(self._watermark_s or 0, max_ts_s - 2)
        while len(self._seen) > 5000:
            self._seen.pop(next(iter(self._seen)))
        return wrote, 0


def _fnum(x) -> Optional[float]:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def run_continuous(
    cfg,
    *,
    series: str = "KXBTC15M",
    sources: str = "coinbase,binance",
    line_source: str = "coinbase",
    seconds_per_cycle: float = 900.0,
    interval: float = 1.0,
    max_markets: int = 4,
    readiness_every: int = 1,
    backfill_every: int = 1,
    max_cycles: int = 0,
    size: float = 10.0,
    allow_uncalibrated: bool = False,
    paper_policy_enabled: bool = False,
    emit: Callable[[str], None] = print,
) -> dict:
    """Run the continuous collector. Returns a final summary dict.

    ``paper_policy_enabled`` (off by default) additionally evaluates the SHADOW/PAPER
    runtime per cycle from the PROMOTED paper manifest (never newest-by-mtime), writing
    decision rows. It still records-only and submits NO orders; shadow mode never fills.
    The runtime mode comes from ``KALSHI_MODEL_RUNTIME_MODE`` (disabled|shadow|paper).
    """
    client = KalshiClient(cfg)
    trade_poller = _TradePoller(client, series)
    trade_events = 0
    fee_model = KalshiFeeModel.from_config(cfg)
    model = BaselineModel(cfg)
    runtime_mode = getattr(cfg, "model_runtime_mode", "disabled")
    if paper_policy_enabled:
        eff_mode = runtime_mode if runtime_mode in ("shadow", "paper") else "shadow"
        emit(f"[paper-runtime] paper_policy_enabled=True mode={eff_mode} — evaluating the PROMOTED "
             "paper manifest per cycle (manifest-based; never newest-by-mtime). No live orders; "
             "shadow mode never fills.")
    # Latency-safe async notifications: the loop ENQUEUES (non-blocking) and a
    # background worker sends. Defaults to Noop unless Pushover is configured.
    notify_q = build_notification_queue(cfg)

    src_names = [s.strip() for s in (sources or "").split(",") if s.strip()]
    deribit_enabled = bool(getattr(getattr(cfg, "deribit", None), "enabled", False))
    und_clients = []
    for name in src_names:
        if name.lower().startswith("deribit"):
            continue  # handled separately below
        try:
            und_clients.append(build_underlying_client(name, cfg))
        except ValueError as exc:
            emit(f"[warn] {exc}")
    # Deribit is slow-moving context: poll it on its own (loose) interval and join
    # the cached latest snapshot point-in-time. The Kalshi loop never blocks on it.
    _de = getattr(cfg, "deribit", None)
    deribit_poll_interval_s = float(getattr(_de, "poll_interval_seconds", 30) or 30)
    deribit_stale_ms = int(getattr(_de, "stale_threshold_seconds", 180) or 180) * 1000
    deribit_state = DeribitState()
    last_deribit_poll = 0.0
    # DECISION-path underlying freshness: re-poll Coinbase/Binance on a tight interval
    # (independent of the slower Kalshi book loop) so the underlying used for features +
    # recorded for source-health stays decision-fresh (<= a few seconds), not 30-60s stale.
    und_decision_poll_interval_s = max(1.0, min(2.0, float(interval)))
    last_und_poll = 0.0
    deribit_client = None
    if any(s.lower().startswith("deribit") for s in src_names):
        if deribit_enabled:
            from ...data.deribit_client import DeribitClient
            deribit_client = DeribitClient(cfg)
            emit("[deribit] enabled — polling public snapshots on a loose interval "
                 f"({deribit_poll_interval_s:.0f}s) and joining point-in-time into feature rows; "
                 "the Kalshi book loop never blocks on it.")
        else:
            emit("[blocker] 'deribit' was requested in --sources but DERIBIT_ENABLED=false. "
                 "Deribit is OPTIONAL — skipping it and continuing with the other sources. "
                 "Set DERIBIT_ENABLED=true to collect + join it (no separate command needed).")
    try:
        spot_client = build_underlying_client(line_source, cfg)
    except ValueError:
        spot_client = None

    micro_state = UnderlyingMicrostructureState()
    start_ref_resolver = StartReferenceResolver()
    spot_samples: list[tuple[int, float]] = []
    seen_tickers: set[str] = set()
    totals = Counter()
    cycle = 0
    stopped_reason = "max_cycles"

    emit(f"=== kalshi-collect-continuous: series={series} sources={src_names} "
         f"cycle={seconds_per_cycle}s interval={interval}s max_markets={max_markets} "
         f"readiness_every={readiness_every} backfill_every={backfill_every} "
         f"max_cycles={max_cycles or 'unbounded'} ===")
    emit("safety: record-only; live trading disabled; no orders placed. Stop with Ctrl-C.")

    with Recorder(cfg) as rec:
        try:
            while True:
                cycle += 1
                errors = 0
                # ---- rediscover ----
                try:
                    discovered = client.discover(
                        series_ticker=series, statuses=("open", "unopened", "settled"))
                except Exception as exc:  # noqa: BLE001
                    emit(f"[cycle {cycle}] discovery failed: {type(exc).__name__}: {exc}")
                    discovered = []
                    errors += 1
                # PHASE-PRIORITIZED target selection: the active CURRENT_IN_WINDOW market is
                # always collected first (never displaced by an upcoming/just-closed market,
                # esp. with --max-markets 1). Upcoming are recorded for backfill but not scored.
                sel = select_collection_targets(discovered, max_markets=max_markets)
                targets = sel["targets"]
                for m in targets:
                    if m.get("ticker"):
                        seen_tickers.add(m["ticker"])
                phase_counts = Counter(m.get("_phase") for m in discovered)
                # selected target tickers by phase (for heartbeat/session visibility)
                selected = {
                    "current": [m.get("ticker") for m in targets
                                if m.get("_phase") == "CURRENT_IN_WINDOW" and m.get("ticker")],
                    "upcoming": [m.get("ticker") for m in targets
                                 if m.get("_phase") in ("UPCOMING", "UPCOMING_PRE_WINDOW") and m.get("ticker")],
                    "closed": [m.get("ticker") for m in targets
                               if m.get("_phase") == "CLOSED_PENDING_SETTLE" and m.get("ticker")],
                }

                raw_ob = norm_ob = und_events = feat_rows = 0
                decisions: Counter = Counter()
                last_decision: dict[str, dict] = {}
                last_feature: dict[str, dict] = {}

                # ---- record loop for this cycle ----
                # End the cycle when the ACTIVE market closes (so the next cycle rediscovers and
                # follows the new window) — bounded by seconds_per_cycle. Without this, a cycle that
                # started mid-window keeps recording its now-closed CURRENT target for the rest of
                # the cycle while the new active market goes unrecorded (the 'active ticker never
                # recorded' symptom). A few seconds of grace lets the close settle before re-select.
                cycle_deadline = _cycle_deadline(
                    targets, seconds_per_cycle=seconds_per_cycle,
                    mono_now=time.monotonic(), now=now_ms())
                first = True
                while targets and (first or time.monotonic() < cycle_deadline):
                    first = False
                    iter_rows: list[dict] = []   # feature rows built THIS iteration (flushed below)
                    ref_price = None
                    if spot_client is not None:
                        try:
                            price, _src, _raw = spot_client.reference_price_now()
                            if price:
                                ref_price = float(price)
                                spot_samples.append((now_ms(), ref_price))
                        except Exception:  # noqa: BLE001
                            errors += 1
                    sigma = _sigma(spot_samples)
                    _ue, _err = _poll_underlying_once(rec, und_clients, micro_state)
                    und_events += _ue
                    errors += _err
                    last_und_poll = time.monotonic()
                    _tw, _terr = trade_poller.poll(rec, mono_now=time.monotonic(),
                                                   recv_ms=now_ms())
                    trade_events += _tw
                    errors += _terr
                    if deribit_client is not None:
                        nowm = time.monotonic()
                        if nowm - last_deribit_poll >= deribit_poll_interval_s:
                            last_deribit_poll = nowm
                            try:
                                for raw_d, norm_d in deribit_client.poll():
                                    # Persist per DERIBIT_RECORD_RAW/NORMALIZED toggles;
                                    # always ingest into the in-memory join cache.
                                    if getattr(_de, "record_raw", True):
                                        rec.record_raw("deribit_btc", raw_d)
                                    if getattr(_de, "record_normalized", True):
                                        rec.record_normalized("deribit_btc", norm_d)
                                    deribit_state.ingest(norm_d)
                            except Exception:  # noqa: BLE001
                                errors += 1
                    for m in targets:
                        tk = m.get("ticker")
                        rec.record_raw("kalshi_markets", m)
                        try:
                            ob = client.get_orderbook(tk)
                        except Exception:  # noqa: BLE001
                            errors += 1
                            continue
                        rec.record_raw("kalshi_orderbook", {"ticker": tk, "recv_ms": now_ms(), "payload": ob})
                        raw_ob += 1
                        norm = normalize_orderbook(
                            ob, market_ticker=tk, series_ticker=(tk.split("-")[0] if tk else None),
                            event_ticker=m.get("event_ticker"), status=m.get("status"),
                            window_start_ms=iso_to_ms(m.get("open_time")),
                            close_ms=iso_to_ms(m.get("close_time")), recv_ms=now_ms(),
                            fee_status=cfg.kalshi.fee_status,
                        )
                        rec.record_normalized("kalshi_orderbook", norm)
                        norm_ob += 1
                        # DECISION freshness: re-poll the underlying on a tight interval right
                        # before building the feature row so the within-row source ages (and the
                        # recorded rows source-health reads) stay decision-fresh — decoupled from
                        # the slower per-market Kalshi book fetches.
                        nowm = time.monotonic()
                        if nowm - last_und_poll >= und_decision_poll_interval_s:
                            _ue2, _err2 = _poll_underlying_once(rec, und_clients, micro_state)
                            und_events += _ue2
                            errors += _err2
                            last_und_poll = nowm
                            rec.flush()   # make the fresh underlying visible to readers immediately
                        as_of = now_ms()
                        und_extra = micro_state.features(
                            as_of_ms=as_of, window_start_ms=iso_to_ms(m.get("open_time")))
                        start_ref_info = start_ref_resolver.resolve(
                            m, as_of_ms=as_of, micro_state=micro_state)
                        start_ref = start_ref_info.price
                        deribit_extra = deribit_feature_fields(
                            snapshot=deribit_state.latest_at_or_before(as_of), as_of_ms=as_of,
                            enabled=deribit_enabled, stale_threshold_ms=deribit_stale_ms,
                            realized_vol_60s=und_extra.get("realized_vol_60s"),
                            realized_vol_180s=und_extra.get("realized_vol_180s"))
                        row = build_feature_row(
                            norm, as_of_ms=as_of, reference_price=ref_price,
                            sigma_per_sqrt_s=sigma, start_reference=start_ref,
                            fee_model=fee_model, underlying_extra=und_extra,
                            deribit_extra=deribit_extra,
                            start_reference_provenance=start_ref_info.feature_fields(as_of))
                        iter_rows.append(row)
                        last_feature[tk] = row
                        cmp_ = comparison_from_rules(m.get("rules_primary"))
                        # Separate COLLECTION targets from PAPER-DECISION targets.
                        # Books/features above are recorded for every discovered
                        # market (open/upcoming/closed) for labels + backfill, but
                        # the model/policy only runs on markets that are OPEN and
                        # inside their active window. Closed / pre-open / out-of-
                        # window markets are SKIPPED here without being scored.
                        market_secs = getattr(
                            getattr(cfg, "low_latency", None), "market_duration_seconds", 900)
                        skip_reason = decision_window_skip_reason(
                            row, market_duration_seconds=market_secs)
                        if skip_reason is None:
                            out = model.predict_proba(BaselineInputs(
                                reference_price=ref_price, line=start_ref,
                                seconds_to_expiry=row.get("seconds_to_close"), sigma_per_sqrt_s=sigma,
                                comparison=Comparison.GTE if cmp_ != "GT" else Comparison.GT))
                            model_p_yes, calibrated = out.p_yes, out.calibration_ts_ms is not None
                        else:
                            model_p_yes, calibrated = None, False
                        dec = decide_kalshi(
                            row, model_p_yes=model_p_yes, calibrated=calibrated,
                            fee_model=fee_model, min_net_edge_cents=cfg.execution.min_net_edge_cents,
                            order_size=size, allow_uncalibrated_candidates=allow_uncalibrated,
                            market_duration_seconds=market_secs)
                        decisions[dec["decision_state"]] += 1
                        last_decision[tk] = dec
                    # INCREMENTAL feature flush: write THIS iteration's rows + flush the recorder
                    # now (not once per 15m cycle) so the paper/shadow runtime + source-health read
                    # FRESH feature rows, never 14m-stale batched ones.
                    if iter_rows:
                        feat_rows += _write_features(cfg, iter_rows)
                    rec.flush()
                    if time.monotonic() < cycle_deadline:
                        time.sleep(max(0.0, float(interval)))

                totals["raw_orderbook_rows"] += raw_ob
                totals["normalized_orderbook_rows"] += norm_ob
                totals["underlying_events"] += und_events
                totals["feature_rows"] += feat_rows
                totals["trade_prints"] = totals.get("trade_prints", 0) + trade_events
                trade_events = 0

                # ---- periodic backfill ----
                labels_written = 0
                if backfill_every and cycle % backfill_every == 0:
                    labels_written = _backfill(cfg, client, seen_tickers)
                    totals["labels_backfilled"] += labels_written

                # ---- ledger + session summary ----
                entries = []
                sim_fills = 0
                for tk, dec in last_decision.items():
                    if dec.get("fill_status") == "simulated_filled":
                        sim_fills += 1
                    frow = last_feature.get(tk, {})
                    reasons = dec.get("reason_codes", [])
                    entries.append(KalshiLedgerEntry(
                        created_at_ms=now_ms(), venue="kalshi",
                        series_ticker=(tk.split("-")[0] if tk else None), market_ticker=tk,
                        side=dec.get("side"), decision_state=dec["decision_state"],
                        model_probability=dec.get("model_probability"),
                        market_implied_probability=dec.get("market_implied_probability"),
                        executable_price=dec.get("executable_price"),
                        fee_estimate=dec.get("fee_estimate"), fee_status=fee_model.status,
                        spread_cost=frow.get("yes_spread"),
                        slippage_estimate=None, net_edge=dec.get("net_edge"),
                        order_size=dec.get("order_size"), fill_status=dec.get("fill_status"),
                        simulated_fill_price=dec.get("simulated_fill_price"),
                        simulated_fill_size=dec.get("simulated_fill_size"),
                        reason_codes=reasons, book_status=dec.get("book_status", "unknown"),
                        market_close_time_ms=frow.get("close_ms"),
                        seconds_to_close=frow.get("seconds_to_close"),
                        feature_set_version=frow.get("feature_set_version", 2),
                        calibration_status=("uncalibrated" if "UNCALIBRATED_MODEL" in reasons else "calibrated"),
                        executable_yes_price=frow.get("executable_yes_buy_price"),
                        executable_no_price=frow.get("executable_no_buy_price"),
                        raw_edge=dec.get("raw_edge"),
                        liquidity_blocker=bool(dec.get("liquidity_blocker")),
                        staleness_blocker=bool(dec.get("staleness_blocker")),
                        source_health_summary=("spot+perp" if frow.get("has_underlying") else "no-underlying")))
                if entries:
                    write_kalshi_ledger(cfg, entries)

                # ---- periodic readiness ----
                readiness = None
                if readiness_every and cycle % readiness_every == 0:
                    readiness = load_kalshi_readiness(cfg)

                _write_session(cfg, cycle, phase_counts, raw_ob, norm_ob, und_events,
                               feat_rows, labels_written, decisions, sim_fills, fee_model,
                               readiness, deribit_enabled, selected)
                # Best-effort async notifications at the cycle boundary (never per-tick).
                _notify_cycle(notify_q, series, last_decision, norm_ob, errors)
                rec.flush()

                # ---- OPTIONAL paper/shadow runtime (manifest-based; never live) ----
                if paper_policy_enabled:
                    _paper_runtime_cycle(cfg, series, emit)

                # ---- heartbeat ----
                _heartbeat(emit, cycle, len(discovered), phase_counts, raw_ob, norm_ob,
                           und_events, feat_rows, labels_written, decisions, readiness,
                           errors, seconds_per_cycle, deribit_enabled, selected)

                if max_cycles and cycle >= max_cycles:
                    stopped_reason = "max_cycles"
                    break
        except KeyboardInterrupt:
            stopped_reason = "ctrl_c"
            emit("\n[kalshi-collect-continuous] Ctrl-C - stopping cleanly. "
                 "All recorded data is valid (append-only). No orders placed.")
        finally:
            rec.flush()
            try:
                notify_q.close()
            except Exception:  # noqa: BLE001 — shutdown is best-effort
                pass

    final = load_kalshi_readiness(cfg)
    emit(f"--- collector stopped ({stopped_reason}) after {cycle} cycle(s) ---")
    emit(f"totals: {dict(totals)}")
    emit(f"readiness: official_binary_labels={final['official_binary_labels']} "
         f"feature_backed_official_windows={final['feature_backed_official_windows']} "
         f"orphan_labels={final['orphan_labels']} backtest_allowed={final['backtest_allowed']}")
    emit("safety: live trading disabled; record-only; no orders placed.")
    return {"cycles": cycle, "stopped_reason": stopped_reason,
            "totals": dict(totals), "readiness": final}


def _paper_runtime_cycle(cfg, series, emit) -> None:
    """Per-cycle SHADOW/PAPER evaluation from the PROMOTED manifest. Fully guarded:
    a failure here can NEVER affect collection. Never submits orders; shadow never fills."""
    try:
        from .paper_runtime import evaluate_paper_rows, _write_shadow_ledger
        mode = getattr(cfg, "model_runtime_mode", "disabled")
        eff = mode if mode in ("shadow", "paper") else "shadow"
        # Enforce wall-clock feature-row freshness so a stale stored row can never drive a
        # candidate; threshold is the underlying decision window (a "this row is current" bound).
        ftr_thr = int(getattr(getattr(cfg, "freshness", None), "coinbase_decision_max_age_ms", 5000) or 5000)
        ev = evaluate_paper_rows(cfg, series=series, mode=eff, limit=10,
                                 enforce_feature_row_age=True, feature_row_max_age_ms=ftr_thr)
        if ev.get("status") != "OK":
            emit(f"[paper-runtime] {ev.get('status')} blockers={ev.get('blockers')}")
            return
        if ev.get("decisions"):
            _write_shadow_ledger(cfg, ev["decisions"])
        emit(f"[paper-runtime mode={eff}] decisions={ev.get('decisions_by_state')} "
             f"paper_candidates={ev.get('paper_candidates')} "
             f"freshest_feature_row_age_ms={ev.get('freshest_feature_row_age_ms')} "
             f"(live_submission_allowed=False)")
    except Exception as exc:  # noqa: BLE001 — paper runtime is best-effort, never fatal
        emit(f"[paper-runtime] skipped: {type(exc).__name__}: {exc}")


def _notify_cycle(notify_q, series, last_decision, norm_ob, errors) -> None:
    """Enqueue best-effort async notifications at the CYCLE boundary.

    Enqueue-and-continue only: a full queue or a notifier failure can never affect
    collection. Per-tick decisions are NEVER pushed (avoids spam + latency); only
    high-signal cycle outcomes (paper candidates, collector-stale) are enqueued.
    The actual send + explanation generation happen in the background worker.
    """
    try:
        for tk, dec in (last_decision or {}).items():
            if dec.get("decision_state") != "PAPER_CANDIDATE":
                continue
            side = {"BUY_YES": "BUY YES", "BUY_NO": "BUY NO"}.get(dec.get("side"), dec.get("side") or "")
            price, p, net = dec.get("executable_price"), dec.get("model_probability"), dec.get("net_edge")
            if isinstance(p, (int, float)) and isinstance(net, (int, float)):
                body = f"{series} {side} @ {price} | model {p:.2f} | net {net * 100:+.1f}c"
            else:
                body = f"{series} {side} @ {price}"
            notify_q.enqueue(
                Notification("PAPER_CANDIDATE", "BTC 15m PAPER_CANDIDATE", body),
                priority=Priority.HIGH,
                explanation_input={**dec, "ticker": tk, "series": series,
                                   "live_submission_allowed": False})
        if not norm_ob:
            notify_q.enqueue(
                Notification("COLLECTOR_STALE", "BTC 15m COLLECTOR",
                             f"{series}: recorded 0 order books this cycle (errors={errors})"),
                priority=Priority.HIGH)
    except Exception:  # noqa: BLE001 — notifications are best-effort, never fatal
        pass


def _write_features(cfg, rows: list[dict]) -> int:
    if not rows:
        return 0
    import json
    from datetime import datetime, timezone
    d = cfg.data_path() / "features"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    with (d / f"kalshi_feature_rows-{day}.jsonl").open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return len(rows)


def _backfill(cfg, client, tickers: set[str]) -> int:
    rows = []
    for tk in sorted(tickers):
        try:
            m = client.get_market(tk)
        except Exception:  # noqa: BLE001
            continue
        if not m:
            continue
        if classify_market(m, now_ms=now_ms()).value in ("SETTLED", "CLOSED_PENDING_SETTLE"):
            rows.append(build_label_row(m))
    if not rows:
        return 0
    import json
    from datetime import datetime, timezone
    d = cfg.data_path() / "labels"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    with (d / f"kalshi_settlement_labels-{day}.jsonl").open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return len(rows)


def _cycle_deadline(targets, *, seconds_per_cycle, mono_now, now, grace_s: float = 3.0) -> float:
    """Monotonic deadline for the record loop: ``seconds_per_cycle``, but capped so the cycle ENDS
    shortly after the active (CURRENT_IN_WINDOW) market closes. This makes the next cycle rediscover
    at the window boundary and follow the new active market, instead of recording a now-closed market
    for the rest of a misaligned 900s cycle. With no current target (cur=0) the full ``seconds_per_cycle``
    applies (an upcoming target is recorded for backfill until it opens / the cycle ends)."""
    deadline = mono_now + max(0.0, float(seconds_per_cycle))
    cur_close = min((m.get("_close_ms") for m in targets
                     if m.get("_phase") == "CURRENT_IN_WINDOW" and m.get("_close_ms") is not None),
                    default=None)
    if cur_close is not None:
        secs_to_close = (cur_close - now) / 1000.0
        if secs_to_close > 0:
            deadline = min(deadline, mono_now + secs_to_close + float(grace_s))
    return deadline


def _write_session(cfg, cycle, phase_counts, raw_ob, norm_ob, und_events, feat_rows,
                   labels_written, decisions, sim_fills, fee_model, readiness, deribit_enabled,
                   selected=None):
    blockers = []
    if readiness:
        blockers = (readiness.get("reasons_backtest_blocked") or [])[:3]
    selected = selected or {}
    session = {
        "run_duration_s": None,
        "data": {
            "markets_discovered": sum(phase_counts.values()),
            "open_markets": phase_counts.get("CURRENT_IN_WINDOW", 0),
            "upcoming_markets": phase_counts.get("UPCOMING", 0) + phase_counts.get("UPCOMING_PRE_WINDOW", 0),
            "closed_markets": phase_counts.get("CLOSED_PENDING_SETTLE", 0),
            "settled_markets": phase_counts.get("SETTLED", 0),
            "raw_orderbook_rows": raw_ob, "normalized_orderbook_rows": norm_ob,
            "underlying_events": und_events, "labels_backfilled": labels_written,
            "feature_rows_built": feat_rows,
            # which target tickers were SELECTED for collection this cycle, by phase
            "selected_current_tickers": list(selected.get("current", [])),
            "selected_upcoming_tickers": list(selected.get("upcoming", [])),
            "selected_closed_tickers": list(selected.get("closed", [])),
        },
        "decisions_by_state": dict(decisions),
        "paper_candidates": decisions.get("PAPER_CANDIDATE", 0),
        "simulated_fills": sim_fills,
        "fee_assumptions": fee_model.describe(),
        "blockers": blockers,
        "safety": "live trading disabled by default; record-only; no orders placed.",
        "next_actions": [
            "Keep the collector running across many 15m windows.",
            "Watch kalshi-data-readiness feature_backed_official_windows toward 60/150.",
            "When backtest_allowed, fit + calibrate before trusting any PAPER_CANDIDATE.",
        ],
    }
    write_kalshi_session_summary(cfg, session)


def _heartbeat(emit, cycle, n_disc, phase_counts, raw_ob, norm_ob, und_events, feat_rows,
               labels, decisions, readiness, errors, seconds_per_cycle, deribit_enabled,
               selected=None):
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    fb = readiness["feature_backed_official_windows"] if readiness else "?"
    bt = readiness["backtest_allowed"] if readiness else "?"
    blocker = "?"
    if readiness:
        rb = readiness.get("reasons_backtest_blocked") or []
        blocker = rb[0] if rb else "none"
    selected = selected or {}
    emit(
        f"[hb {ts}] cycle={cycle} disc={n_disc} "
        f"cur={phase_counts.get('CURRENT_IN_WINDOW',0)} "
        f"up={phase_counts.get('UPCOMING',0)+phase_counts.get('UPCOMING_PRE_WINDOW',0)} "
        f"closed={phase_counts.get('CLOSED_PENDING_SETTLE',0)} "
        f"settled={phase_counts.get('SETTLED',0)} | "
        f"ob_raw={raw_ob} ob_norm={norm_ob} und={und_events} feat={feat_rows} labels={labels} | "
        f"decisions={dict(decisions)} | feat_backed_windows={fb} backtest_allowed={bt} | "
        f"errors={errors} deribit={'on' if deribit_enabled else 'off'} | "
        f"next rediscover in ~{int(seconds_per_cycle)}s | safety=record-only/live-disabled")
    # explicit SELECTED target tickers by phase (so it's obvious the active market is collected)
    emit(f"        selected_current_tickers={selected.get('current', [])} "
         f"selected_upcoming_tickers={selected.get('upcoming', [])} "
         f"selected_closed_tickers={selected.get('closed', [])}")
    if not selected.get("current") and phase_counts.get("CURRENT_IN_WINDOW", 0):
        emit("        WARNING: a CURRENT_IN_WINDOW market exists but none selected — check --max-markets.")
    if blocker not in ("?", "none"):
        emit(f"        main blocker: {blocker}")
