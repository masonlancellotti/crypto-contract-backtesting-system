"""btc5m command-line interface.

Safe, secret-free entrypoints for setup, discovery, recording, and smoke testing:

    init                 validate config + create data/report directories
    status               print resolved config + safety status
    smoke                run a dummy candidate through risk + paper adapter
    check-live-disabled  confirm the live adapter refuses orders by default
    notify-test          send a test notification (Noop unless Pushover present)
    discover-markets     list current/upcoming Polymarket BTC 5m up/down markets (public)
    debug-discovery      explain discovery: routes, window classification, UI mismatch
    inspect-market       inspect one market by --slug/--url (metadata + both books)
    record               poll + record real CLOB books (+ provisional line) to data/
    record-market        record one explicit market by --slug/--url (manual override)
    collect-continuous   rolling rediscovery + continuous book/underlying collection
    record-underlying    poll + record Coinbase/Binance BTC feeds to data/
    backfill-settlements label completed recorded windows to data/labels/
    backfill-official-chainlink  capture OFFICIAL Chainlink lines (gated; needs creds)
    build-features       replay recorded data into point-in-time feature rows
    decide               features -> baseline model -> gated decision candidates
    data-readiness       report whether training/backtest is allowed (gated)
    paper-backtest       gated minimum backtest (blocked until enough data)
    run-paper-pipeline   full record-only/paper loop + ledger + session summary
    label-status         summarize label rows on disk
    paper                paper entrypoint (use run-paper-pipeline for the loop)
    eod                  build + send an end-of-day summary

Run `python -m btc5m.cli <command> [options]`.

Examples:
    python -m btc5m.cli discover-markets --asset BTC --duration 5m
    python -m btc5m.cli record --asset BTC --duration 5m --seconds 60
    python -m btc5m.cli record-underlying --seconds 60 --sources coinbase,binance
    python -m btc5m.cli backfill-settlements --asset BTC --duration 5m
    python -m btc5m.cli label-status
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error

from .config import AppConfig, load_config
from .data.recorder import Recorder
from .data.underlying import CoinbaseSpotClient, build_underlying_client
from .execution.risk import RiskContext, RiskManager
from .notifications import build_notifier
from .schemas import (
    BookLevel,
    ContractMeta,
    Order,
    OrderBook,
    OrderSide,
    Outcome,
    RiskDecision,
)
from .timeutils import age_ms, now_ms

DATA_SUBDIRS = ["raw", "normalized", "features", "labels", "models"]
REPORT_SUBDIRS = ["calibration", "backtests", "paper"]


# --------------------------------------------------------------------------- #
# Dummy fixtures (for smoke tests only)
# --------------------------------------------------------------------------- #
def _dummy_book(contract_id: str = "BTC-5M-DUMMY") -> OrderBook:
    now = now_ms()
    return OrderBook(
        contract_id=contract_id,
        outcome=Outcome.YES,
        bids=[BookLevel(0.55, 200), BookLevel(0.54, 400)],
        asks=[BookLevel(0.57, 150), BookLevel(0.58, 500)],
        ts_ms=now,
        recv_ms=now,
    )


def _dummy_meta(contract_id: str = "BTC-5M-DUMMY") -> ContractMeta:
    return ContractMeta(
        contract_id=contract_id,
        title="BTC above 60000 at 00:35 UTC",
        asset="BTC",
        line=60000.0,
        expiry_ms=now_ms() + 300_000,
        resolution_source="dummy-index",
        yes_token_id="yes-dummy",
        no_token_id="no-dummy",
    )


def _dummy_order(contract_id: str = "BTC-5M-DUMMY") -> Order:
    return Order(
        contract_id=contract_id,
        outcome=Outcome.YES,
        side=OrderSide.BUY,
        price=0.57,
        size=100,
        client_order_id="smoke-1",
    )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_init(cfg: AppConfig, args: argparse.Namespace) -> int:
    data = cfg.data_path()
    reports = cfg.reports_path()
    for sub in DATA_SUBDIRS:
        (data / sub).mkdir(parents=True, exist_ok=True)
    for sub in REPORT_SUBDIRS:
        (reports / sub).mkdir(parents=True, exist_ok=True)
    print(f"OK  data dir:    {data}")
    print(f"OK  reports dir: {reports}")
    print(f"OK  config loaded; trading_mode={cfg.trading_mode}, live_permitted={cfg.live_permitted}")
    return 0


def cmd_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    print("=== btc5m status ===")
    print(f"trading_mode               : {cfg.trading_mode}")
    print(f"live_trading_enabled       : {cfg.live_trading_enabled}")
    print(f"kill_switch_enabled        : {cfg.kill_switch_enabled}")
    print(f"require_manual_confirmation: {cfg.require_manual_confirmation}")
    print(f"live_permitted             : {cfg.live_permitted}")
    if not cfg.live_permitted:
        print("live blockers:")
        for b in cfg.live_blockers():
            print(f"  - {b}")
    print(f"timezone                   : {cfg.timezone}  (EOD {cfg.eod_summary_time})")
    print(f"paper_starting_bankroll    : {cfg.paper_starting_bankroll}")
    print("--- subsystems ---")
    print(f"notify_provider            : {cfg.notifications.provider}")
    print(f"pushover_configured        : {cfg.notifications.pushover_configured}")
    print("--- venues / data feeds ---")
    print(f"  PRIMARY venue              : {cfg.primary_venue}  (Kalshi BTC 15m KXBTC15M)")
    print("  kalshi   public REST market data : IMPLEMENTED (no auth needed)")
    print("  coinbase spot   (REST polling)   : IMPLEMENTED")
    print("  binance  USDT-M (REST polling)   : IMPLEMENTED")
    de = getattr(cfg, "deribit", None)
    der_status = "IMPLEMENTED (public REST)" if (de and de.enabled) else "OPTIONAL / DISABLED"
    print(f"  deribit  vol/options (optional)  : {der_status}")
    print("  websocket streams                : scaffold (REST polling used)")
    ll = getattr(cfg, "low_latency", None)
    if ll is not None:
        ws = "on" if ll.use_websocket else "off(REST fallback)"
        print("--- low-latency hot path (paper-only; never live) ---")
        print(f"  enabled={ll.enabled}  websocket={ws}  paper_only={ll.paper_only}  "
              f"order_planning={ll.order_planning_enabled}  live_submission_allowed={ll.live_submission_allowed}")
        print(f"  score_interval={ll.hotpath_score_interval_ms}ms  max_book_age={ll.max_book_age_ms}ms  "
              f"max_underlying_age={ll.max_underlying_age_ms}ms  market_duration={ll.market_duration_seconds}s")
    pp = getattr(cfg, "paper_policy", None)
    if pp is not None:
        print("--- paper-candidate policy (never live) ---")
        print(f"  enabled={pp.enabled}  require_trained={pp.require_trained_model}  "
              f"require_calibrated={pp.require_calibrated_model}  require_backtest={pp.require_backtest_evidence}  "
              f"require_non_diagnostic={pp.require_non_diagnostic_model}")
        print(f"  min_net_edge={pp.min_net_edge_cents}c  min_raw_edge={pp.min_raw_edge_cents}c  "
              f"uncertainty_buffer={pp.uncertainty_buffer_cents}c  live_submission_allowed={pp.live_submission_allowed}")
    lk = getattr(cfg, "lock", None)
    if lk is not None:
        print("--- post-entry lock-profit (paper-only; post-entry only; never live) ---")
        print(f"  enabled={lk.enabled}  paper_only={lk.paper_only}  default_mode={lk.default_mode}  "
              f"allow_partial={lk.allow_partial}  live_submission_allowed={lk.live_submission_allowed}")
        print(f"  min_profit={lk.min_profit_cents}c  hard_profit={lk.hard_profit_cents}c  "
              f"ride_min_edge={lk.ride_min_edge_cents}c")
    lr = getattr(cfg, "live_readiness", None)
    if lr is not None:
        print("--- live-readiness (DRY-RUN ONLY; never submits) ---")
        print(f"  readiness_enabled={lr.enabled}  dry_run_only={lr.dry_run_only}  "
              f"submit_enabled={lr.submit_enabled}  allow_market_orders={lr.allow_market_orders}  "
              f"live_submission_allowed={lr.live_submission_allowed}")
        print(f"  requires: approved_model={lr.require_approved_model} calibrator={lr.require_valid_calibrator} "
              f"backtest={lr.require_valid_backtest} paper_evidence={lr.require_paper_evidence}  "
              f"max_live_order_size={lr.max_live_order_size} max_live_notional={lr.max_live_notional}")
    return 0


def cmd_smoke(cfg: AppConfig, args: argparse.Namespace) -> int:
    print("=== smoke: dummy candidate through risk + paper adapter ===")
    book, meta, order = _dummy_book(), _dummy_meta(), _dummy_order()

    rm = RiskManager(cfg)
    rctx = RiskContext(
        book=book,
        meta=meta,
        calibration_ts_ms=now_ms(),  # pretend freshly calibrated
        clock_skew_ms=0,
        last_feed_event_ms=now_ms(),
    )
    decision = rm.evaluate(order, rctx)
    print(f"risk decision (real gates): approved={decision.approved}")
    for r in decision.reasons:
        print(f"  - blocked: {r}")
    print("  (kill switch + unset limits SHOULD block by default — that is correct)")

    print("  (the live Kalshi adapter additionally refuses every order: see check-live-disabled)")
    return 0


def cmd_check_live_disabled(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .execution.live_kalshi import LiveKalshiExecutionAdapter

    print("=== check-live-disabled ===")
    order = _dummy_order()

    kalshi = LiveKalshiExecutionAdapter(cfg)
    k_block = kalshi.preflight(order, None)
    k_fill = kalshi.submit(order, None)
    k_ok = bool(k_block) and k_fill.get("status") == "rejected"
    print(f"KALSHI live adapter refused: {k_ok}. Blockers:")
    for b in k_block:
        print(f"  - {b}")

    if k_ok:
        print("LIVE DISABLED — the Kalshi live adapter refused the order.")
        return 0
    print("ERROR: the live adapter did NOT refuse with default config!")
    return 1


def cmd_notify_test(cfg: AppConfig, args: argparse.Namespace) -> int:
    notifier = build_notifier(cfg)
    kind = type(notifier).__name__
    ok = notifier.rejection(
        "model edge +4.0c rejected: stale quote / thin depth (test notification)"
    )
    print(f"notifier={kind} sent={ok}")
    return 0 if ok else 1


def cmd_notification_health(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Notification queue + provider health (offline self-test; no network, no secrets)."""
    from .notifications.base import Notification
    from .notifications.noop import NoopNotifier
    from .notifications.queue import NotificationQueue, Priority

    n = cfg.notifications
    real_provider = type(build_notifier(cfg)).__name__  # never constructs/sends a request
    # Self-test on a Noop-bound queue so the health check never hits the network.
    q = NotificationQueue(
        NoopNotifier(cfg),
        async_enabled=getattr(n, "async_enabled", True),
        maxsize=getattr(n, "queue_maxsize", 500),
        send_timeout_ms=getattr(n, "send_timeout_ms", 750),
        drop_low_priority_when_full=getattr(n, "drop_low_priority_when_full", True),
        coalesce_low=getattr(n, "coalesce_watch", True),
    )
    samples = int(getattr(args, "samples", None) or 500)
    for i in range(samples):
        high = (i % 50 == 0)
        q.enqueue(Notification("PAPER_CANDIDATE" if high else "WATCH", "health", f"probe {i}"),
                  priority=Priority.HIGH if high else Priority.LOW)
    q.flush(timeout=3.0)
    h = q.health()
    q.close()

    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps({"real_provider": real_provider,
                           "pushover_configured": n.pushover_configured, **h}, default=str))
        return 0
    eq, sl = h["enqueue_latency_ms"], h["send_latency_ms"]
    print("=== notification-health ===")
    print(f"  provider           : {real_provider}  (pushover_configured={n.pushover_configured})")
    print(f"  async_enabled      : {h['async_enabled']}")
    print(f"  queue              : depth={h['queue_depth']}/{h['queue_maxsize']}  max_seen={h['max_depth_seen']}")
    print(f"  send_timeout_ms    : {h['send_timeout_ms']}")
    print(f"  coalesce / drop_low: {h['coalesce_low']} / {h['drop_low_priority_when_full']}")
    print(f"  sent / failed      : {h['sent']} / {h['failed']}")
    print(f"  dropped            : {h['dropped']}  by_reason={h['dropped_by_reason']}")
    print(f"  coalesced          : {h['coalesced']}")
    print(f"  blocking_prevented : {h['blocking_sends_prevented']}")
    print(f"  enqueue latency ms : p50={_f3(eq['p50'])} p95={_f3(eq['p95'])} max={_f3(eq['max'])} n={eq['n']}")
    print(f"  send latency ms    : p50={_f3(sl['p50'])} p95={_f3(sl['p95'])} max={_f3(sl['max'])} "
          f"n={sl['n']} latest={_f3(h['latest_send_latency_ms'])}")
    print(f"  last_error         : {h['last_error']}")
    print("  safety: offline self-test (Noop-bound); no network; no secrets printed; live disabled.")
    return 0






def cmd_record_underlying(cfg: AppConfig, args: argparse.Namespace) -> int:
    import dataclasses

    sources = [s for s in (args.sources or "coinbase,binance").split(",") if s.strip()]
    print(f"=== record-underlying: sources={sources} seconds={args.seconds} interval={args.interval}s ===")
    clients = []
    for name in sources:
        try:
            clients.append(build_underlying_client(name, cfg, series=getattr(args, 'series', None)))
        except ValueError as exc:
            print(f"  warn: {exc}")
    if not clients:
        print("BLOCKER: no valid sources (use coinbase|binance).")
        return 1

    raw_events = norm_events = errors = 0
    with Recorder(cfg) as rec:
        deadline = time.monotonic() + max(0.0, float(args.seconds))
        first = True
        while first or time.monotonic() < deadline:
            first = False
            for client in clients:
                stream = f"underlying_{client.source}"
                try:
                    for raw, event in client.poll():
                        rec.record_raw(stream, raw)
                        rec.record_normalized(stream, dataclasses.asdict(event))
                        raw_events += 1
                        norm_events += 1
                except urllib.error.URLError as exc:
                    errors += 1
                    print(f"  warn: {client.source}: network error: {exc}")
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    print(f"  warn: {client.source}: {type(exc).__name__}: {exc}")
            if time.monotonic() < deadline:
                time.sleep(max(0.0, float(args.interval)))

    print("--- record-underlying summary ---")
    print(f"raw events recorded       : {raw_events}")
    print(f"normalized events recorded: {norm_events}")
    print(f"errors                    : {errors}")
    print(f"raw dir       : {cfg.data_path() / 'raw'}")
    print(f"normalized dir: {cfg.data_path() / 'normalized'}")
    if raw_events == 0:
        print("BLOCKER: recorded 0 underlying events — check connectivity.")
        return 1
    return 0


















def _safety_snapshot(cfg: AppConfig) -> dict:
    return {
        "trading_mode": cfg.trading_mode,
        "live_trading_enabled": cfg.live_trading_enabled,
        "kill_switch_enabled": cfg.kill_switch_enabled,
        "live_permitted": cfg.live_permitted,
        "notifier": type(build_notifier(cfg)).__name__,
    }




def _count_norm(cfg: AppConfig, glob: str) -> int:
    n = 0
    d = cfg.data_path() / "normalized"
    for p in d.glob(glob) if d.exists() else []:
        try:
            with p.open("r", encoding="utf-8") as fh:
                n += sum(1 for line in fh if line.strip())
        except OSError:
            pass
    return n




# --------------------------------------------------------------------------- #
# Discovery diagnostics + manual override + continuous collection
# --------------------------------------------------------------------------- #
def _iso(ms: int | None) -> str:
    from datetime import datetime, timezone
    if not ms:
        return "n/a"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_slug(args: argparse.Namespace) -> str | None:
    """Resolve a market slug from --slug or --url (parses Polymarket URLs)."""
    from .discovery import parse_market_url, parse_slug

    if getattr(args, "slug", None):
        return args.slug.strip()
    if getattr(args, "url", None):
        slug = parse_market_url(args.url)
        if slug and not parse_slug(slug):
            # Parsed a non-Up/Down slug (e.g. an event landing page); still return
            # it so the caller can try to fetch + report a precise blocker.
            return slug
        return slug
    return None






def _poll_books_once(client, rec, markets, *, errors_label: bool = True) -> tuple[int, int, int]:
    """Poll + record YES/NO books for each market once. Returns (raw, norm, errors)."""
    raw_books = norm_events = errors = 0
    for m in markets:
        for outcome, token in ((Outcome.YES, m.yes_token_id), (Outcome.NO, m.no_token_id)):
            if not token:
                continue
            try:
                raw = client.get_raw_book(token)
                rec.record_raw(
                    "polymarket_book",
                    {"slug": m.slug, "outcome": outcome.value, "token_id": token,
                     "recv_ms": now_ms(), "payload": raw},
                )
                raw_books += 1
                book = client.get_book(m.contract_id, outcome, token)
                rec.record_normalized("polymarket_book", _normalized_event(m, outcome, token, book))
                norm_events += 1
            except Exception as exc:  # noqa: BLE001 - keep going, count errors
                errors += 1
                if errors_label:
                    print(f"  warn: {m.slug} {outcome.value}: {type(exc).__name__}: {exc}")
    return raw_books, norm_events, errors






# --------------------------------------------------------------------------- #
# Kalshi BTC 15m (PRIMARY venue)
# --------------------------------------------------------------------------- #
def _kalshi_dollars(m: dict, key: str):
    v = m.get(key)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _resolve_kalshi_ticker(args: argparse.Namespace) -> str | None:
    from .venues.kalshi.client import parse_market_url
    if getattr(args, "ticker", None):
        return args.ticker.strip().upper()
    if getattr(args, "url", None):
        return parse_market_url(args.url)
    return None


def _sigma_from_prices(samples: list[tuple[int, float]]) -> float | None:
    """Per-sqrt-second log-return stdev from (ts_ms, price) samples (past-only)."""
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


def _kalshi_select_targets(client, cfg, args):
    """Discover + select current/upcoming markets (or an explicit ticker)."""
    ticker = _resolve_kalshi_ticker(args)
    if ticker:
        m = client.get_market(ticker)
        return ([m] if m else []), ticker
    markets = client.discover(series_ticker=args.series, statuses=("open", "unopened"))
    keep = [m for m in markets if m.get("_phase") in ("CURRENT_IN_WINDOW", "UPCOMING_PRE_WINDOW", "UPCOMING")]
    keep = keep or markets
    return _take(keep, args.max_markets), None


def _write_kalshi_labels(cfg: AppConfig, rows: list[dict]) -> int:
    if not rows:
        return 0
    from datetime import datetime, timezone
    d = cfg.data_path() / "labels"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = d / f"kalshi_settlement_labels-{day}.jsonl"
    import json as _json
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(_json.dumps(r) + "\n")
    return len(rows)


def _write_kalshi_features(cfg: AppConfig, rows: list[dict]) -> int:
    if not rows:
        return 0
    from datetime import datetime, timezone
    d = cfg.data_path() / "features"
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = d / f"kalshi_feature_rows-{day}.jsonl"
    import json as _json
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(_json.dumps(r) + "\n")
    return len(rows)


def cmd_kalshi_discover(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.client import KalshiClient

    print(f"=== kalshi-discover: series={args.series} status={args.status} "
          f"lookahead={args.lookahead_minutes}m ===")
    client = KalshiClient(cfg)
    now = now_ms()
    print(f"local UTC now : {_iso(now)}")
    print(f"kalshi server : {client.server_date_header() or 'unavailable'}")
    try:
        statuses = (args.status,) if args.status and args.status != "all" else ("open", "unopened", "settled")
        markets = client.discover(series_ticker=args.series, statuses=statuses, now_ms=now)
    except urllib.error.HTTPError as exc:
        print(f"BLOCKER: HTTP {exc.code} from Kalshi: {exc.read().decode('utf-8','replace')[:200]}")
        return 1
    except urllib.error.URLError as exc:
        print(f"BLOCKER: network error reaching Kalshi API ({client.base}): {exc}")
        return 1
    if not markets:
        print(f"No KXBTC15M markets for filters status={statuses}. "
              f"Endpoint={client.base}/markets?series_ticker={args.series}")
        return 0
    from collections import Counter
    phases = Counter(m.get("_phase") for m in markets)
    print(f"found {len(markets)} market(s): {dict(phases)}")
    shown = _take(markets, args.max_markets)
    for m in shown:
        print(
            f"  {m.get('ticker')}  [{m.get('_phase')}]\n"
            f"    event/title : {m.get('event_ticker')} | {m.get('title')}\n"
            f"    start ref   : {m.get('yes_sub_title')}\n"
            f"    window      : {m.get('open_time')} -> {m.get('close_time')} (status={m.get('status')})\n"
            f"    YES bid/ask : {_kalshi_dollars(m,'yes_bid_dollars')} / {_kalshi_dollars(m,'yes_ask_dollars')}  "
            f"NO bid/ask: {_kalshi_dollars(m,'no_bid_dollars')} / {_kalshi_dollars(m,'no_ask_dollars')}\n"
            f"    last/vol/OI : {_kalshi_dollars(m,'last_price_dollars')} / {m.get('volume_fp')} / {m.get('open_interest_fp')}"
        )
    if len(markets) > len(shown):
        print(f"  ... and {len(markets)-len(shown)} more (use --max-markets 0)")
    return 0


def cmd_kalshi_nearest_markets(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY: print the nearest CURRENT/UPCOMING KXBTC15M markets with open/close times,
    seconds-to-open/close, status, and classified phase vs current UTC. Diagnoses 'cur=0'
    (no active market discovered) by showing exactly what Kalshi returns and how it classifies."""
    from collections import Counter

    from .venues.kalshi.client import KalshiClient

    def _rel(secs):
        if secs is None:
            return "n/a"
        return f"in {secs:.0f}s" if secs >= 0 else f"{-secs:.0f}s ago"

    client = KalshiClient(cfg)
    now = now_ms()
    print(f"=== kalshi-nearest-markets: series={args.series} ===")
    print(f"current UTC   : {_iso(now)}  (now_ms={now})")
    print(f"kalshi server : {client.server_date_header() or 'unavailable'}")
    try:
        markets = client.discover(series_ticker=args.series, statuses=("open", "unopened"), now_ms=now)
    except urllib.error.HTTPError as exc:
        print(f"BLOCKER: HTTP {exc.code} from Kalshi: {exc.read().decode('utf-8', 'replace')[:200]}")
        return 1
    except urllib.error.URLError as exc:
        print(f"BLOCKER: network error reaching Kalshi API ({client.base}): {exc}")
        return 1
    phases = Counter(m.get("_phase") for m in markets)
    cur = phases.get("CURRENT_IN_WINDOW", 0)
    print(f"phase counts  : cur={cur} up={phases.get('UPCOMING', 0)} "
          f"closed={phases.get('CLOSED_PENDING_SETTLE', 0)} settled={phases.get('SETTLED', 0)} "
          f"unknown={phases.get('UNKNOWN', 0)}  (total {len(markets)})")
    if cur == 0:
        print("  WARNING: cur=0 — no CURRENT_IN_WINDOW market discovered. Check status/open/close below.")
    rows = sorted(markets, key=lambda m: m.get("_close_ms") or 0)
    candidates = [m for m in rows if m.get("_phase") in ("CURRENT_IN_WINDOW", "UPCOMING")]
    shown = _take(candidates, args.max_markets if (args.max_markets and args.max_markets > 0) else 8)
    print(f"nearest current/upcoming ({len(shown)} of {len(candidates)} shown):")
    for m in shown:
        mark = ">>" if m.get("_phase") == "CURRENT_IN_WINDOW" else "  "
        s_open = None if m.get("_open_ms") is None else round((m["_open_ms"] - now) / 1000.0, 1)
        s_close = None if m.get("_close_ms") is None else round((m["_close_ms"] - now) / 1000.0, 1)
        print(f"  {mark} {m.get('ticker')}  [{m.get('_phase')}]  status={m.get('status')!r}")
        print(f"       open={m.get('open_time')} ({_rel(s_open)})   "
              f"close={m.get('close_time')} ({_rel(s_close)})")
    print("  safety: read-only public market data; no orders; live disabled.")
    return 0


def cmd_kalshi_collector_targets(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY: show exactly what kalshi-collect-continuous would SELECT to collect this cycle,
    phase-prioritized (active CURRENT first), and why. Mirrors the collector's rediscover +
    select_collection_targets path so target selection can be audited without running the collector."""
    from collections import Counter

    from .venues.kalshi.client import KalshiClient, select_collection_targets

    client = KalshiClient(cfg)
    now = now_ms()
    mm = args.max_markets
    print(f"=== kalshi-collector-targets: series={args.series} "
          f"max_markets={mm if (mm and mm > 0) else 'all'} ===")
    print(f"current UTC   : {_iso(now)}")
    print(f"kalshi server : {client.server_date_header() or 'unavailable'}")
    try:
        # SAME statuses the collector's rediscover uses
        discovered = client.discover(series_ticker=args.series,
                                     statuses=("open", "unopened", "settled"), now_ms=now)
    except urllib.error.HTTPError as exc:
        print(f"BLOCKER: HTTP {exc.code} from Kalshi: {exc.read().decode('utf-8', 'replace')[:200]}")
        return 1
    except urllib.error.URLError as exc:
        print(f"BLOCKER: network error reaching Kalshi API ({client.base}): {exc}")
        return 1
    phases = Counter(m.get("_phase") for m in discovered)
    print(f"discovered    : {len(discovered)}  phases={dict(phases)}")
    sel = select_collection_targets(discovered, max_markets=mm)
    targets = sel["targets"]
    cur = phases.get("CURRENT_IN_WINDOW", 0)
    sel_cur = [m.get("ticker") for m in targets if m.get("_phase") == "CURRENT_IN_WINDOW"]
    if cur and not sel_cur:
        print("  BUG: a CURRENT market exists but is NOT in the selection!")
    elif cur:
        print(f"  OK: active CURRENT market selected FIRST -> {sel_cur[0]}")
    else:
        print("  note: cur=0 — no active market; collecting nearest UPCOMING for backfill (NOT scored).")

    def _close_in(m):
        c = m.get("_close_ms")
        return "n/a" if c is None else f"{round((c - now) / 1000.0)}s"

    print(f"SELECTED targets ({len(targets)}) — the tickers this cycle would record:")
    for i, m in enumerate(targets):
        print(f"  {i + 1}. {m.get('ticker')}  [{m.get('_phase')}]  status={m.get('status')!r}  "
              f"close_in={_close_in(m)}  window={m.get('open_time')} -> {m.get('close_time')}")
    print(f"available by phase: current={len(sel['current'])} upcoming={len(sel['upcoming'])} "
          f"closed={len(sel['closed'])}  (SETTLED excluded from collection)")
    print("  safety: read-only public market data; no orders; live disabled.")
    return 0


def cmd_kalshi_inspect(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.client import KalshiClient, classify_market
    from .venues.kalshi.orderbook import normalize_orderbook
    from .venues.kalshi.settlement import comparison_from_rules, parse_target_price

    ticker = _resolve_kalshi_ticker(args)
    if not ticker:
        print("BLOCKER: provide --ticker or --url.")
        return 1
    print(f"=== kalshi-inspect: ticker={ticker} ===")
    client = KalshiClient(cfg)
    try:
        m = client.get_market(ticker)
    except urllib.error.URLError as exc:
        print(f"BLOCKER: network error reaching Kalshi API: {exc}")
        return 1
    if not m:
        print(f"BLOCKER: market not found by ticker '{ticker}'.")
        return 1
    now = now_ms()
    from .venues.kalshi.client import iso_to_ms
    print(f"  title        : {m.get('title')}")
    print(f"  event/series : {m.get('event_ticker')} / {ticker.split('-')[0]}")
    print(f"  status/phase : {m.get('status')} / {classify_market(m, now_ms=now).value}")
    print(f"  window       : {m.get('open_time')} -> {m.get('close_time')} (exp {m.get('expiration_time')})")
    print(f"  start ref    : {m.get('yes_sub_title')}  (parsed: {parse_target_price(m.get('yes_sub_title'))})")
    print(f"  comparison   : {comparison_from_rules(m.get('rules_primary'))} (from rules; never title)")
    print(f"  result       : {m.get('result') or '(unsettled)'}")
    print(f"  YES bid/ask  : {_kalshi_dollars(m,'yes_bid_dollars')} / {_kalshi_dollars(m,'yes_ask_dollars')}")
    print(f"  rules        : {(m.get('rules_primary') or '')[:200]}")
    try:
        raw_ob = client.get_orderbook(ticker)
        norm = normalize_orderbook(
            raw_ob, market_ticker=ticker, series_ticker=ticker.split("-")[0],
            event_ticker=m.get("event_ticker"), status=m.get("status"),
            window_start_ms=iso_to_ms(m.get("open_time")), close_ms=iso_to_ms(m.get("close_time")),
            recv_ms=now_ms(), fee_status=cfg.kalshi.fee_status,
        )
        print("  --- normalized orderbook (executable; derived from yes/no bids) ---")
        print(f"    YES bid={norm['yes_bid']} ask={norm['yes_ask']} (ask_size={norm['yes_ask_size']})")
        print(f"    NO  bid={norm['no_bid']} ask={norm['no_ask']} (ask_size={norm['no_ask_size']})")
        print(f"    depth levels yes/no = {norm['yes_depth_levels']}/{norm['no_depth_levels']}  "
              f"validity={norm['book_validity_flags']}")
    except Exception as exc:  # noqa: BLE001
        print(f"  BLOCKER fetching/normalizing orderbook: {type(exc).__name__}: {exc}")
        return 1
    return 0


def cmd_kalshi_record(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.client import KalshiClient, iso_to_ms
    from .venues.kalshi.orderbook import normalize_orderbook

    print(f"=== kalshi-record: series={args.series} seconds={args.seconds} "
          f"interval={args.interval}s max_markets={args.max_markets} ===")
    print("safety: record-only; live trading disabled; no orders placed.")
    client = KalshiClient(cfg)
    try:
        targets, explicit = _kalshi_select_targets(client, cfg, args)
    except urllib.error.URLError as exc:
        print(f"BLOCKER: network error reaching Kalshi API: {exc}")
        return 1
    if not targets:
        print("BLOCKER: no current/upcoming KXBTC15M markets to record (and no --ticker/--url).")
        return 0
    print(f"recording {len(targets)} market(s): {[m.get('ticker') for m in targets]}")

    raw_ob = norm_ob = errors = stale = thin = invalid = 0
    seen_versions: dict[str, str] = {}
    with Recorder(cfg) as rec:
        deadline = time.monotonic() + max(0.0, float(args.seconds))
        first = True
        while first or time.monotonic() < deadline:
            first = False
            for m in targets:
                tk = m.get("ticker")
                ver = str(m.get("updated_time") or "")
                if seen_versions.get(tk) != ver:
                    rec.record_raw("kalshi_markets", m)
                    seen_versions[tk] = ver
                try:
                    ob = client.get_orderbook(tk)
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
                    f = norm["book_validity_flags"]
                    invalid += int(bool(f.get("incomplete_book") or f.get("yes_crossed") or f.get("no_crossed")))
                    thin += int(bool(f.get("thin_yes") or f.get("thin_no")))
                    print(f"  {tk}: YES {norm['yes_bid']}/{norm['yes_ask']}  NO {norm['no_bid']}/{norm['no_ask']}")
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    print(f"  warn: {tk}: {type(exc).__name__}: {exc}")
            if time.monotonic() < deadline:
                time.sleep(max(0.0, float(args.interval)))

    print("--- kalshi-record summary ---")
    print(f"raw orderbook snapshots : {raw_ob}")
    print(f"normalized snapshots    : {norm_ob}")
    print(f"invalid/thin/errors     : {invalid}/{thin}/{errors}")
    if raw_ob == 0:
        print("BLOCKER: recorded 0 orderbooks — check connectivity / market availability.")
        return 1
    return 0


def cmd_kalshi_backfill_settlements(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.client import KalshiClient, classify_market
    from .venues.kalshi.settlement import build_label_row

    print(f"=== kalshi-backfill-settlements: series={args.series} ===")
    client = KalshiClient(cfg)
    # Recorded markets (so we label what we actually saw), refreshed to latest state.
    raw_dir = cfg.data_path() / "raw"
    tickers: set[str] = set()
    import json as _json
    for p in sorted(raw_dir.glob("kalshi_markets-*.jsonl")) if raw_dir.exists() else []:
        for line in _iter_jsonl_safe(p):
            payload = line.get("payload") if isinstance(line, dict) else None
            mk = payload if isinstance(payload, dict) else line
            if isinstance(mk, dict) and mk.get("ticker"):
                tickers.add(mk["ticker"])
    # Also include freshly-settled markets from discovery.
    try:
        for m in client.discover(series_ticker=args.series, statuses=("settled",)):
            if m.get("ticker"):
                tickers.add(m["ticker"])
    except Exception as exc:  # noqa: BLE001
        print(f"  warn: settled discovery failed: {type(exc).__name__}: {exc}")
    if not tickers:
        print("note: no recorded/known markets to backfill — run kalshi-record first.")
        return 0

    now = now_ms()
    rows = []
    from collections import Counter
    counts = Counter()
    for tk in sorted(tickers):
        try:
            m = client.get_market(tk)
        except Exception:  # noqa: BLE001
            continue
        if not m:
            continue
        phase = classify_market(m, now_ms=now)
        if phase.value not in ("SETTLED", "CLOSED_PENDING_SETTLE"):
            continue
        row = build_label_row(m)  # official result only; BTC end-ref left None (provisional join is optional)
        rows.append(row)
        counts[row["label_source_status"]] += 1
    written = _write_kalshi_labels(cfg, rows)
    print(f"completed/settled markets labeled: {len(rows)}  by_status={dict(counts)}  written={written}")
    for r in rows[:6]:
        print(f"  {r['market_ticker']}: {r['label_source_status']} result={r['official_result']} "
              f"yes_resolved={r['label_yes_resolved']} reason={r['reason_code']}")
    return 0


def cmd_kalshi_data_readiness(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.readiness import load_kalshi_readiness

    print("=== kalshi-data-readiness ===")
    r = load_kalshi_readiness(cfg)
    groups = [
        ("markets", ["markets_seen", "open_markets", "upcoming_markets",
                     "closed_markets", "settled_markets"]),
        ("recorded rows", ["raw_orderbook_rows", "normalized_orderbook_rows", "underlying_rows"]),
        ("labels", ["official_binary_labels", "feature_backed_official_windows",
                    "feature_backed_unusable_windows", "orphan_labels", "orphan_official_labels",
                    "provisional_reference_rows", "manual_review_rows", "unknown_label_rows"]),
        ("feature-row categories", ["feature_rows_total", "feature_rows_underlying_only",
                                    "feature_rows_book_backed", "feature_rows_with_start_reference",
                                    "feature_rows_without_start_reference"]),
        ("rows rejected", ["rows_rejected_missing_book", "rows_rejected_missing_underlying",
                           "rows_rejected_window_closed_or_bad_book", "rows_rejected_no_official_label"]),
        ("eligibility", ["usable_rows_for_binary_model", "usable_rows_for_line_distance_model",
                         "training_eligible_rows"]),
    ]
    for title, keys in groups:
        print(f"  -- {title} --")
        for k in keys:
            print(f"     {k}: {r[k]}")
    print("  == AUTHORITATIVE GATE ==")
    print(f"     gate_windows (authoritative): {r['gate_windows']}")
    print(f"     gate_basis: {r['gate_basis']}")
    print(f"     backtest_gate: {r['gate_windows']}/{r['backtest_gate_threshold']}  "
          f"allowed={r['backtest_allowed']}")
    print(f"     train_gate   : {r['gate_windows']}/{r['train_gate_threshold']} windows "
          f"AND {r['training_eligible_rows']}/{r['train_gate_min_rows']} rows  "
          f"allowed={r['training_allowed_binary_model']}")
    if r["feature_backed_unusable_windows"]:
        print(f"     note: feature_backed_official_windows={r['feature_backed_official_windows']} "
              f"but {r['feature_backed_unusable_windows']} have no usable executable row -> "
              f"authoritative gate_windows={r['gate_windows']}.")
    for b in r["reasons_training_blocked"]:
        print(f"  training blocked: {b}")
    for b in r["reasons_backtest_blocked"]:
        print(f"  backtest blocked: {b}")
    print(f"  note: {r['note']}")
    print(f"  recommended_next_command: {r['recommended_next_command']}")
    return 0


def cmd_kalshi_auth_smoke(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .execution.live_kalshi import kalshi_auth_smoke

    print("=== kalshi-auth-smoke (no secrets printed, no orders) ===")
    info = kalshi_auth_smoke(cfg)
    for k, v in info.items():
        print(f"  {k}: {v}")
    if not info["auth_configured"]:
        print("  -> public REST market data works without auth. Set KALSHI_KEY_ID + "
              "KALSHI_PRIVATE_KEY_PATH (env-only) to enable authenticated WS/account later.")
    return 0


def cmd_run_kalshi_paper_pipeline(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Safe Kalshi paper pipeline: discover -> record books + underlying ->
    features -> baseline model -> decisions -> ledger -> session summary.
    Never trades. Every step fails safe and reports precise blockers."""
    import dataclasses
    from collections import Counter

    from .models.baseline import BaselineInputs, BaselineModel
    from .schemas import Comparison
    from .venues.kalshi.client import KalshiClient, classify_market, iso_to_ms
    from .venues.kalshi.features import UnderlyingMicrostructureState
    from .venues.kalshi.fees import KalshiFeeModel
    from .venues.kalshi.orderbook import normalize_orderbook
    from .venues.kalshi.paper import (
        KalshiLedgerEntry, build_feature_row, decide_kalshi,
        write_kalshi_ledger, write_kalshi_session_summary,
    )
    from .venues.kalshi.readiness import load_kalshi_readiness
    from .venues.kalshi.settlement import build_label_row, comparison_from_rules
    from .venues.kalshi.start_reference import StartReferenceResolver

    t0 = time.monotonic()
    print(f"=== run-kalshi-paper-pipeline: series={args.series} seconds={args.seconds} "
          f"sources={args.sources} ===")
    print("safety: record-only; live disabled; no orders placed.")
    blockers: list[str] = []
    client = KalshiClient(cfg)
    fee_model = KalshiFeeModel.from_config(cfg)
    model = BaselineModel(cfg)

    try:
        targets, _ = _kalshi_select_targets(client, cfg, args)
    except Exception as exc:  # noqa: BLE001
        print(f"BLOCKER: discovery failed: {type(exc).__name__}: {exc}")
        targets = []
        blockers.append(f"discovery: {type(exc).__name__}: {exc}")

    src_names = [s for s in (args.sources or "coinbase,binance").split(",") if s.strip()]
    deribit_enabled = bool(getattr(getattr(cfg, "deribit", None), "enabled", False))
    und_clients = []
    for name in src_names:
        if name.lower().startswith("deribit"):
            continue  # optional auxiliary source handled separately (point-in-time join)
        try:
            und_clients.append(build_underlying_client(name, cfg, series=getattr(args, 'series', None)))
        except ValueError as exc:
            blockers.append(str(exc))
    deribit_client = None
    if any(s.lower().startswith("deribit") for s in src_names):
        if deribit_enabled:
            from .data.deribit_client import DeribitClient
            deribit_client = DeribitClient(cfg)
        else:
            blockers.append("deribit requested but DERIBIT_ENABLED=false — skipped (optional, non-fatal).")
    from .venues.kalshi.deribit_features import DeribitState, deribit_feature_fields
    _de = getattr(cfg, "deribit", None)
    deribit_poll_interval_s = float(getattr(_de, "poll_interval_seconds", 30) or 30)
    deribit_stale_ms = int(getattr(_de, "stale_threshold_seconds", 180) or 180) * 1000
    deribit_state = DeribitState()
    last_deribit_poll = 0.0
    try:
        spot_client = build_underlying_client(args.line_source, cfg, series=getattr(args, 'series', None))
    except ValueError:
        spot_client = None

    raw_ob = norm_ob = und_events = 0
    spot_samples: list[tuple[int, float]] = []
    micro_state = UnderlyingMicrostructureState()
    start_ref_resolver = StartReferenceResolver()
    decisions = Counter()
    last_decision: dict[str, dict] = {}
    last_feature: dict[str, dict] = {}
    market_meta: dict[str, dict] = {tk: m for m in targets if (tk := m.get("ticker"))}
    feature_rows: list[dict] = []

    with Recorder(cfg) as rec:
        deadline = time.monotonic() + max(0.0, float(args.seconds))
        first = True
        while targets and (first or time.monotonic() < deadline):
            first = False
            # current spot + sigma (past-only)
            ref_price = None
            if spot_client is not None:
                try:
                    price, _src, _raw = spot_client.reference_price_now()
                    if price:
                        ref_price = float(price)
                        spot_samples.append((now_ms(), ref_price))
                except Exception:  # noqa: BLE001
                    pass
            sigma = _sigma_from_prices(spot_samples)
            # underlying recording (+ ingest into the microstructure state)
            for uc in und_clients:
                try:
                    for raw_ev, ev in uc.poll():
                        rec.record_raw(f"underlying_{uc.source}", raw_ev)
                        ev_dict = dataclasses.asdict(ev)
                        rec.record_normalized(f"underlying_{uc.source}", ev_dict)
                        micro_state.ingest(ev_dict)
                        und_events += 1
                except Exception:  # noqa: BLE001
                    pass
            # optional Deribit context (throttled; never blocks the Kalshi loop)
            if deribit_client is not None:
                nowm = time.monotonic()
                if nowm - last_deribit_poll >= deribit_poll_interval_s:
                    last_deribit_poll = nowm
                    try:
                        for raw_d, norm_d in deribit_client.poll():
                            rec.record_raw("deribit_btc", raw_d)
                            rec.record_normalized("deribit_btc", norm_d)
                            deribit_state.ingest(norm_d)
                    except Exception:  # noqa: BLE001
                        pass
            # kalshi books + features + decisions
            for m in targets:
                tk = m.get("ticker")
                rec.record_raw("kalshi_markets", m)
                try:
                    ob = client.get_orderbook(tk)
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
                        sigma_per_sqrt_s=sigma, start_reference=start_ref, fee_model=fee_model,
                        underlying_extra=und_extra, deribit_extra=deribit_extra,
                        start_reference_provenance=start_ref_info.feature_fields(as_of),
                    )
                    feature_rows.append(row)
                    last_feature[tk] = row
                    cmp_ = comparison_from_rules(m.get("rules_primary"))
                    if start_ref is not None:
                        out = model.predict_proba(BaselineInputs(
                            reference_price=ref_price, line=start_ref,
                            seconds_to_expiry=row.get("seconds_to_close"), sigma_per_sqrt_s=sigma,
                            comparison=Comparison.GTE if cmp_ != "GT" else Comparison.GT,
                        ))
                        model_p_yes, calibrated = out.p_yes, out.calibration_ts_ms is not None
                    else:
                        model_p_yes, calibrated = None, False
                    dec = decide_kalshi(
                        row, model_p_yes=model_p_yes, calibrated=calibrated,
                        fee_model=fee_model, min_net_edge_cents=cfg.execution.min_net_edge_cents,
                        order_size=args.size, allow_uncalibrated_candidates=args.allow_uncalibrated,
                    )
                    decisions[dec["decision_state"]] += 1
                    last_decision[tk] = dec
                except Exception as exc:  # noqa: BLE001
                    print(f"  warn: {tk}: {type(exc).__name__}: {exc}")
            if time.monotonic() < deadline:
                time.sleep(max(0.0, float(args.interval)))

    feat_written = _write_kalshi_features(cfg, feature_rows)

    # Settlement backfill (best-effort) for any settled targets.
    label_rows = []
    for tk, m in market_meta.items():
        try:
            fresh = client.get_market(tk) or m
        except Exception:  # noqa: BLE001
            fresh = m
        if classify_market(fresh, now_ms=now_ms()).value in ("SETTLED", "CLOSED_PENDING_SETTLE"):
            label_rows.append(build_label_row(fresh))
    labels_written = _write_kalshi_labels(cfg, label_rows)

    # Ledger: last decision per market.
    notifier = build_notifier(cfg)
    entries = []
    sim_fills = 0
    for tk, dec in last_decision.items():
        if dec.get("fill_status") == "simulated_filled":
            sim_fills += 1
        frow = last_feature.get(tk, {})
        reasons = dec.get("reason_codes", [])
        entries.append(KalshiLedgerEntry(
            created_at_ms=now_ms(), venue="kalshi", series_ticker=(tk.split("-")[0] if tk else None),
            market_ticker=tk, side=dec.get("side"), decision_state=dec["decision_state"],
            model_probability=dec.get("model_probability"),
            market_implied_probability=dec.get("market_implied_probability"),
            executable_price=dec.get("executable_price"), fee_estimate=dec.get("fee_estimate"),
            fee_status=fee_model.status, spread_cost=frow.get("yes_spread"),
            slippage_estimate=None, net_edge=dec.get("net_edge"), order_size=dec.get("order_size"),
            fill_status=dec.get("fill_status"), simulated_fill_price=dec.get("simulated_fill_price"),
            simulated_fill_size=dec.get("simulated_fill_size"), reason_codes=reasons,
            book_status=dec.get("book_status", "unknown"),
            market_close_time_ms=frow.get("close_ms"), seconds_to_close=frow.get("seconds_to_close"),
            feature_set_version=frow.get("feature_set_version", 2),
            calibration_status=("uncalibrated" if "UNCALIBRATED_MODEL" in reasons else "calibrated"),
            executable_yes_price=frow.get("executable_yes_buy_price"),
            executable_no_price=frow.get("executable_no_buy_price"),
            raw_edge=dec.get("raw_edge"), liquidity_blocker=bool(dec.get("liquidity_blocker")),
            staleness_blocker=bool(dec.get("staleness_blocker")),
            source_health_summary=("spot+perp" if frow.get("has_underlying") else "no-underlying"),
        ))
        if dec["decision_state"] == "PAPER_CANDIDATE":
            notifier.paper_candidate(
                f"BTC 15m KALSHI PAPER: {dec['side']} @ {dec['executable_price']} | "
                f"model {dec['model_probability']:.2f} | net {dec.get('net_edge_cents',0):+.1f}c | {tk}")
    ledger_written, ledger_path = write_kalshi_ledger(cfg, entries)

    readiness = load_kalshi_readiness(cfg)
    from collections import Counter as _C
    phase_counts = _C(m.get("_phase") for m in targets)
    session = {
        "run_duration_s": round(time.monotonic() - t0, 1),
        "data": {
            "markets_discovered": len(market_meta),
            "open_markets": phase_counts.get("CURRENT_IN_WINDOW", 0),
            "upcoming_markets": phase_counts.get("UPCOMING", 0) + phase_counts.get("UPCOMING_PRE_WINDOW", 0),
            "closed_markets": phase_counts.get("CLOSED_PENDING_SETTLE", 0),
            "settled_markets": phase_counts.get("SETTLED", 0),
            "raw_orderbook_rows": raw_ob, "normalized_orderbook_rows": norm_ob,
            "underlying_events": und_events, "labels_backfilled": labels_written,
            "feature_rows_built": feat_written,
        },
        "decisions_by_state": dict(decisions),
        "paper_candidates": decisions.get("PAPER_CANDIDATE", 0),
        "simulated_fills": sim_fills,
        "fee_assumptions": fee_model.describe(),
        "blockers": blockers,
        "safety": "live trading disabled by default; record-only; no orders placed.",
        "next_actions": [
            "Run again across many 15m windows; watch kalshi-data-readiness distinct_settled_windows.",
            "After windows settle, run kalshi-backfill-settlements to attach OFFICIAL results.",
            "When backtest_allowed, fit + calibrate a model before any PAPER_CANDIDATE is trusted.",
        ],
    }
    summary_path = write_kalshi_session_summary(cfg, session)

    print("--- pipeline summary ---")
    print(f"decisions: {dict(decisions)} | paper_candidates: {session['paper_candidates']} | "
          f"sim_fills: {sim_fills}")
    print(f"raw_ob={raw_ob} norm_ob={norm_ob} underlying={und_events} features={feat_written} "
          f"labels={labels_written}")
    print(f"ledger : {ledger_path} ({ledger_written} entries)")
    print(f"summary: {summary_path}")
    print(f"readiness: official_labels={readiness['official_binary_labels']} "
          f"distinct_settled_windows={readiness['distinct_settled_windows']} "
          f"backtest_allowed={readiness['backtest_allowed']}")
    if blockers:
        print("blockers:")
        for b in blockers:
            print(f"  - {b}")
    if not targets:
        print("note: no current/upcoming markets this run — try again near a 15m boundary, or "
              "use --ticker. Underlying/labels steps still ran where possible.")
    print("safety: no orders placed; live trading disabled by default.")
    return 0


def cmd_kalshi_label_audit(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.labels_audit import audit_labels, load_feature_tickers, load_label_rows

    from .venues.kalshi.labels_audit import load_usable_feature_tickers

    print(f"=== kalshi-label-audit: series={args.series} ===")
    rows = load_label_rows(cfg)
    feats = load_feature_tickers(cfg)
    usable = load_usable_feature_tickers(cfg)
    r = audit_labels(rows, feats, usable)
    order = [
        "total_label_rows", "deduped_labels", "duplicate_label_rows",
        "official_labels", "provisional_labels", "manual_review_labels", "unknown_labels",
        "labels_with_feature_rows", "orphan_labels", "orphan_official_labels",
        "official_feature_backed_labels", "feature_backed_unusable_windows",
        "labels_rejected_no_feature_rows", "labels_rejected_unusable_features",
    ]
    for k in order:
        print(f"  {k}: {r[k]}")
    print("  == AUTHORITATIVE GATE (matches kalshi-data-readiness) ==")
    print(f"     gate_windows: {r['gate_windows']}")
    print(f"     backtest_gate: {r['backtest_gate_count']}/{r['backtest_gate_threshold']}  "
          f"allowed={r['backtest_allowed']}")
    print(f"     train_gate   : {r['train_gate_count']}/{r['train_gate_threshold']}  "
          f"allowed={r['train_allowed']}")
    if r["feature_backed_unusable_windows"]:
        print(f"  note: official_feature_backed_labels={r['official_feature_backed_labels']} (presence) "
              f"but {r['feature_backed_unusable_windows']} have no usable executable row -> "
              f"authoritative gate_windows={r['gate_windows']}.")
    if r["orphan_official_labels"]:
        print(f"  note: {r['orphan_official_labels']} OFFICIAL labels have NO feature rows "
              f"(orphans). Excluded from gates. Use kalshi-clean-orphan-labels --write.")
    print("  safety: read-only; no labels deleted; no orders placed.")
    return 0


def cmd_kalshi_clean_orphan_labels(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.labels_audit import compact_labels

    write = bool(getattr(args, "write", False))
    mode = "WRITE compacted file" if write else "DRY-RUN (no files written)"
    print(f"=== kalshi-clean-orphan-labels: series={args.series} [{mode}] ===")
    print("safety: raw label files are NEVER modified or deleted.")
    r = compact_labels(cfg, write=write)
    print(f"  total_label_rows: {r['total_label_rows']}")
    print(f"  deduped_labels: {r['deduped_labels']}  (duplicates collapsed: {r['duplicate_label_rows']})")
    print(f"  official_feature_backed_labels (presence): {r['official_feature_backed_labels']}")
    print(f"  gate_windows (authoritative, usable)     : {r['gate_windows']}")
    print(f"  orphan_official_labels (excluded by gates): {r['orphan_official_labels']}")
    print(f"  raw_label_files_preserved: {r['raw_label_files_preserved']}")
    if write:
        print(f"  compacted_file (all deduped, is_orphan/gate_eligible tagged): {r['compacted_file']}")
        print(f"  training_labels_file (gate-eligible official only, orphans EXCLUDED): "
              f"{r['training_labels_file']}")
    else:
        print("  (dry-run) re-run with --write to emit: (1) a deduped compacted file with "
              "is_orphan/gate_eligible tags, and (2) a clean training-labels file containing "
              "ONLY gate-eligible official labels (orphans excluded). Raw files untouched.")
    return 0


def cmd_source_health(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.source_health import assess_source_health

    print(f"=== source-health: series={args.series} ===")
    h = assess_source_health(cfg)
    for s in h["sources"]:
        req = "REQUIRED-for-features" if s["required_for_feature_generation"] else "optional-for-features"
        used = "used-in-features" if s["used_in_kalshi_feature_builder"] else "not-in-features"
        age = f"{s['data_age_ms']}ms" if s["data_age_ms"] is not None else "n/a"
        print(f"  [{s['source']}] enabled={s['enabled']} {s['status']} {req} {used}")
        print(f"      rows_today raw/norm={s['rows_today_raw']}/{s['rows_today_normalized']}  "
              f"latest_ts={s['latest_normalized_ts_ms']}  age={age}  latest_price={s['latest_price']}")
        # LIVENESS (alive?) vs DECISION freshness (trade-fresh?) — explicitly separate.
        print(f"      LIVENESS: stale={s['liveness_stale']} (threshold={s['liveness_threshold_ms']}ms)   "
              f"DECISION: stale={s['decision_stale']} (threshold={s['decision_threshold_ms']}ms)")
        print(f"      fresh_for: collection={s['fresh_for_collection']} decision={s['fresh_for_decision']} "
              f"training={s['fresh_for_training']} paper_candidate={s['fresh_for_paper_candidate']}")
        if s["stale_reason"]:
            print(f"      liveness_stale_reason: {s['stale_reason']}")
        if s.get("decision_stale_reason"):
            print(f"      decision_stale_reason: {s['decision_stale_reason']}")
        print(f"      feature_role: {s['feature_role']}")
        if s["can_serve_as_spot_fallback"]:
            print("      can_serve_as_spot_fallback: True")
        if s.get("latest_values"):
            vals = "  ".join(f"{k}={v}" for k, v in s["latest_values"].items())
            print(f"      latest_values: {vals}")
        if s["source"] == "deribit":
            print(f"      enabled_by_config={s.get('enabled_by_config')}  implemented={s['implemented']}  "
                  f"optional={s.get('optional')}  include_in_model_features={s.get('include_in_model_features')}  "
                  f"selected_for_model_features={s.get('selected_for_model_features')}")
            print(f"      historical_rows_present={s.get('historical_rows_present')}  "
                  f"disabled_by_config_but_rows_present={s.get('disabled_by_config_but_rows_present')}  "
                  f"joined_into_feature_rows={s.get('joined_into_feature_rows')}  "
                  f"feature_columns_present={s.get('feature_columns_present')}")
        if s.get("missing_reason"):
            print(f"      missing_reason: {s['missing_reason']}")
        if s.get("recommendation"):
            print(f"      recommendation: {s['recommendation']}")
    u = h["underlying"]
    print("  -- underlying group: LIVENESS (alive?) vs DECISION freshness (trade-fresh?) --")
    print(f"     LIVENESS: primary={u['spot_primary']}(stale={u['spot_primary_liveness_stale']})  "
          f"fallback={u['spot_fallback']}(stale={u['spot_fallback_liveness_stale']})  "
          f"underlying_liveness_ok={u['underlying_liveness_ok']}")
    print(f"     DECISION: coinbase_stale={u['coinbase_decision_stale']}  binance_stale={u['binance_decision_stale']}  "
          f"both_stale={u['both_decision_stale']}  reference={u['reference_source']}  "
          f"fallback_used={u['fallback_used']}")
    print(f"     underlying_decision_ok={u['underlying_decision_ok']}  "
          f"fresh_for_paper_candidate={u['fresh_for_paper_candidate']}  (allow_fallback={u['allow_binance_fallback']}, "
          f"require_primary={u['require_primary_for_entry']})")
    print(f"     recommendation: {u['recommendation']}")
    print(f"     note: {u['note']}")
    nt = h["notifier"]
    print(f"  [notifications] provider={nt['provider']} pushover_enabled={nt['pushover_enabled']} "
          f"configured={nt['pushover_configured']}")
    print("  safety: read-only; no secrets printed; no orders placed.")
    return 0


def cmd_kalshi_source_freshness_smoke(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Sample source-health over N seconds; report DECISION-fresh fraction per source. READ-ONLY."""
    from .venues.kalshi.source_health import source_freshness_smoke

    seconds = float(getattr(args, "seconds", None) or 60.0)
    interval = float(getattr(args, "interval", None) or 1.0)
    print(f"=== kalshi-source-freshness-smoke: series={args.series} seconds={seconds} interval={interval} ===")
    print("  sampling latest recorded rows (read-only; no extra network)...")
    r = source_freshness_smoke(cfg, series=args.series, seconds=seconds, interval=interval)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str))
        return 0
    print(f"  samples: {r['samples']}")
    for src, p in r["per_source"].items():
        a = p["age"]
        print(f"  [{src}] liveness_fresh={p['liveness_fresh_fraction']} (thr={p['liveness_threshold_ms']}ms)  "
              f"DECISION_fresh={p['decision_fresh_fraction']} (thr={p['decision_threshold_ms']}ms)  "
              f"age_ms[min/mean/max]={a['min_ms']}/{a['mean_ms']}/{a['max_ms']}")
    print(f"  underlying_decision_fresh_fraction: {r['underlying_decision_fresh_fraction']}  "
          f"fallback_used_fraction: {r['underlying_fallback_used_fraction']}")
    print(f"  VERDICT: {r['verdict']}")
    print(f"  recommendation: {r['recommendation']}")
    print(f"  note: {r['note']}")
    print("  safety: read-only; no orders; live disabled.")
    return 0


def cmd_record_deribit(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .data.deribit_client import DeribitClient

    currency = getattr(args, "currency", "BTC")
    print(f"=== record-deribit: currency={currency} seconds={args.seconds} ===")
    print("safety: record-only; optional auxiliary vol/options source; no orders placed.")
    client = DeribitClient(cfg, currency=currency)
    if not client.enabled:
        print("BLOCKER: Deribit is DISABLED (DERIBIT_ENABLED=false). It is OPTIONAL and not "
              "required for the Kalshi MVP. Enable locally with DERIBIT_ENABLED=true to record "
              "public DVOL/index/historical-vol/options summaries (no credentials needed).")
        return 0
    de_cfg = cfg.deribit
    print(f"  record_raw={de_cfg.record_raw}  record_normalized={de_cfg.record_normalized}  "
          f"(DERIBIT_RECORD_RAW / DERIBIT_RECORD_NORMALIZED)")
    recorded = 0
    last_norm = None
    with Recorder(cfg) as rec:
        deadline = time.monotonic() + max(0.0, float(args.seconds))
        first = True
        while first or time.monotonic() < deadline:
            first = False
            try:
                for raw_d, norm_d in client.poll():
                    if de_cfg.record_raw:
                        rec.record_raw("deribit_btc", raw_d)
                    if de_cfg.record_normalized:
                        rec.record_normalized("deribit_btc", norm_d)
                    last_norm = norm_d
                    recorded += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  warn: {type(exc).__name__}: {exc}")
            if time.monotonic() < deadline:
                time.sleep(max(1.0, float(args.interval)))
    print(f"--- record-deribit summary --- snapshots fetched: {recorded}")
    if last_norm:
        print(f"  index_price={last_norm.get('deribit_index_price')} "
              f"DVOL={last_norm.get('deribit_dvol')} "
              f"hist_vol={last_norm.get('deribit_historical_vol')} "
              f"near_iv={last_norm.get('deribit_near_expiry_iv')} "
              f"atm_iv={last_norm.get('deribit_atm_iv')}")
        print(f"  OI_total={last_norm.get('deribit_options_open_interest_total')} "
              f"put/call_OI={last_norm.get('deribit_put_call_oi_ratio')} "
              f"put/call_vol={last_norm.get('deribit_put_call_volume_ratio')} "
              f"skew={last_norm.get('deribit_skew_proxy')}")
        if last_norm.get("deribit_missing_reason"):
            print(f"  missing_reason: {last_norm['deribit_missing_reason']}")
    if recorded == 0:
        print("BLOCKER: fetched 0 Deribit snapshots — check connectivity / DERIBIT_API_URL.")
        return 1
    return 0


def cmd_kalshi_collect_continuous(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.collector import run_continuous

    # Optional in-process runtime mode (shadow|paper|disabled) WITHOUT editing .env.
    # "live" is never accepted; live submission is impossible regardless.
    rt_mode = getattr(args, "runtime_mode", None)
    paper_on = bool(getattr(args, "paper_policy_enabled", False))
    if rt_mode in ("disabled", "shadow", "paper"):
        cfg.model_runtime_mode = rt_mode
        if rt_mode in ("shadow", "paper"):
            paper_on = True
        print(f"  [runtime-mode] in-process model_runtime_mode={rt_mode} (paper_policy_enabled={paper_on}); "
              "never submits live orders.")
    run_continuous(
        cfg, series=args.series, sources=args.sources, line_source=args.line_source,
        seconds_per_cycle=float(args.seconds_per_cycle), interval=float(args.interval),
        max_markets=int(args.max_markets), readiness_every=int(args.readiness_every),
        backfill_every=int(args.backfill_every), max_cycles=int(args.max_cycles),
        size=float(args.size), allow_uncalibrated=bool(args.allow_uncalibrated),
        paper_policy_enabled=paper_on,
    )
    return 0


def cmd_kalshi_train_dry_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Training-prep DRY-RUN: join features+labels, purge/embargo, report, then REFUSE."""
    from .venues.kalshi.train_prep import train_dry_run

    print(f"=== kalshi-train-dry-run: series={args.series} (DRY-RUN; no training, no orders) ===")
    r = train_dry_run(cfg, series=args.series, embargo_windows=int(getattr(args, "embargo_windows", 1)))
    print(f"  feature_rows_loaded        : {r['feature_rows_loaded']}")
    print(f"  official_label_windows     : {r['official_label_windows']}")
    print(f"  training_eligible_rows     : {r['training_eligible_rows']}  "
          f"(usable executable book-backed rows joined to OFFICIAL labels)")
    print(f"  gate_windows (authoritative): {r['gate_windows']}")
    print(f"  label_balance              : {r['label_balance']}")
    print(f"  feature_columns            : {r['n_feature_columns']}")
    print("  -- column missingness (fraction None over training-eligible rows) --")
    for col, frac in r["column_missingness"].items():
        flag = "  <-- always missing" if frac >= 0.999 else ("  <-- often missing" if frac >= 0.5 else "")
        print(f"     {col}: {frac}{flag}")
    if r.get("feature_version_counts"):
        print(f"  -- feature_set_version distribution (eligible rows): {r['feature_version_counts']}")
    de = r.get("deribit")
    if de:
        print("  -- deribit (OPTIONAL context; never gates the model) --")
        print(f"     candidate_feature_group_status={de['candidate_feature_group_status']}")
        print(f"     enabled_in_config={de['enabled_in_config']}  "
              f"include_in_model_features={de['include_in_model_features']}  "
              f"columns_present={de['columns_present']}  "
              f"selected_for_model_features={de['selected_for_model_features']}")
        print(f"     rows_with_deribit (historical availability)={de['rows_with_deribit_used']}/{de['rows_total']} "
              f"(stale={de['rows_with_deribit_stale']}, fraction_used={de['fraction_used']})  "
              f"selected_candidate_feature_count={de['selected_candidate_feature_count']}")
    pe = r["purge_embargo"]
    print("  -- purge/embargo --")
    if pe.get("applied"):
        print(f"     embargo_windows={pe['embargo_windows']} ({pe['embargo_ms']}ms)  "
              f"test_window={pe['test_window']}  test_rows={pe['test_rows']}")
        print(f"     train_rows_after_purge_embargo={pe['train_rows_after_purge_embargo']}  "
              f"purged/embargoed={pe['rows_purged_or_embargoed']}")
        print(f"     {pe['note']}")
    else:
        print(f"     not applied: {pe.get('reason')}")
    print("  == GATE DECISION ==")
    print(f"     backtest_allowed: {r['backtest_allowed']}  "
          f"(gate {r['gate_windows']}/{r['backtest_gate_threshold']})")
    print(f"     train_allowed   : {r['train_allowed']}  "
          f"(gate {r['gate_windows']}/{r['train_gate_threshold']} windows AND "
          f"{r['training_eligible_rows']}/{r['train_gate_min_rows']} rows)")
    if r["train_allowed"]:
        print("  TRAINING-ELIGIBLE: gate met. (Still a dry-run — fit/calibrate is a separate task.)")
    else:
        print("  TRAINING BLOCKED — refusing to train:")
        for b in r["blockers"]:
            print(f"     - {b}")
    print(f"  safety: {r['safety']}")
    return 0


def cmd_kalshi_hotpath_smoke(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Short, safe, PAPER-ONLY low-latency hot-path smoke. Never submits orders."""
    from .venues.kalshi.low_latency_runtime import run_hotpath_smoke

    run_hotpath_smoke(
        cfg, series=args.series, seconds=float(args.seconds),
        max_markets=int(args.max_markets), sources=args.sources, emit=print)
    return 0


def cmd_kalshi_latency_benchmark(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Offline/synthetic latency benchmark for the hot path. No network, no orders."""
    from .venues.kalshi.low_latency_runtime import run_latency_benchmark

    run_latency_benchmark(
        cfg, series=args.series, samples=int(getattr(args, "samples", 1000)), emit=print)
    return 0


def _f3(x):
    return f"{x:.3f}" if isinstance(x, (int, float)) else "None"


def cmd_kalshi_build_model_dataset(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Build the model-ready dataset (feature-backed OFFICIAL labels only). No training."""
    from .venues.kalshi.model_dataset import build_model_dataset, write_dataset

    print(f"=== kalshi-build-model-dataset: series={args.series} ===")
    ds = build_model_dataset(
        cfg, series=args.series, include_deribit=getattr(args, "include_deribit", "auto"),
        strict=bool(getattr(args, "strict", False)),
        feature_version=getattr(args, "feature_version", "latest"))
    g, c = ds["gate"], ds["counts"]
    print(f"  status: {g['status']}")
    print(f"  final_model_rows: {c['final_model_rows']}  distinct_windows: {ds['distinct_windows']}")
    print(f"  gate_windows: {g['gate_windows']} (train {g['train_gate_threshold']} / "
          f"backtest {g['backtest_gate_threshold']})  remaining_to_train={g['windows_remaining_to_train']}  "
          f"remaining_to_backtest={g['windows_remaining_to_backtest']}")
    print(f"  feature_set_version_counts: {ds['feature_version_counts']}  "
          f"deribit_included(selected_for_model)={ds['deribit_included']}")
    de = ds.get("deribit") or {}
    if de:
        print("  -- deribit (OPTIONAL; column presence != candidate-feature selection) --")
        print(f"     candidate_feature_group_status={de['candidate_feature_group_status']}  "
              f"columns_present={de['columns_present']}  enabled_in_config={de['enabled_in_config']}  "
              f"include_in_model_features={de['include_in_model_features']}  "
              f"selected_for_model_features={de['selected_for_model_features']}")
        print(f"     rows_with_deribit_used={de['rows_with_deribit_used']}/{de['rows_total']} "
              f"(stale={de['rows_with_deribit_stale']}, fraction_used={de['fraction_used']})  "
              f"selected_candidate_feature_count={de['selected_candidate_feature_count']}")
    print("  -- row accounting (every drop has a reason) --")
    for k, v in c.items():
        print(f"     {k}: {v}")
    staged = bool(getattr(args, "staged", False))
    update_latest = bool(getattr(args, "update_latest", False))
    paths = write_dataset(cfg, ds, fmt=getattr(args, "format", "jsonl"),
                          output=getattr(args, "output", None),
                          staged=staged, update_latest=update_latest)
    if ds.get("parquet_fallback"):
        print("  note: parquet deps unavailable -> wrote JSONL fallback (no fragile deps added).")
    print(f"  staged={paths['staged']}  update_latest={paths['update_latest']}  "
          f"(active kalshi_model_dataset_latest.* / kalshi_feature_schema.json "
          f"{'UPDATED' if update_latest else 'left UNCHANGED'})")
    for k, v in paths.items():
        if k in ("staged", "update_latest"):
            continue
        print(f"  {k}: {v}")
    minw = int(getattr(args, "min_windows", 150) or 150)
    if ds["distinct_windows"] < minw and not getattr(args, "diagnostic_ok", False):
        print(f"  NOT_TRAINING_READY: distinct_windows={ds['distinct_windows']} < --min-windows {minw} "
              "(dataset written for inspection; real training stays blocked).")
    print("  safety: read-only build; no training, no orders, live disabled.")
    return 0


def cmd_kalshi_split_report(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Report purged/embargoed window-level chronological + walk-forward splits."""
    from .venues.kalshi.model_dataset import build_model_dataset
    from .venues.kalshi.splits import chronological_split, walk_forward_splits

    print(f"=== kalshi-split-report: series={args.series} ===")
    rows = build_model_dataset(cfg, series=args.series)["rows"]
    emb = int(getattr(args, "embargo_windows", 1))
    sp = chronological_split(rows, embargo_windows=emb)
    print(f"  distinct_windows: {sp['n_windows']}  embargo_windows: {sp['embargo_windows']}")
    if not sp["applied"]:
        print(f"  BLOCKER: {sp['reason']}")
    else:
        print(f"  train_windows={sp['train_windows']}  val_windows={sp['val_windows']}  "
              f"embargoed/purged={sp['embargoed_windows']}")
        print(f"  train_rows={sp['train_rows']} (balance {sp['train_label_balance']})")
        print(f"  val_rows={sp['val_rows']} (balance {sp['val_label_balance']})")
        print(f"  no_validation_leak: {sp['no_leak']}")
    wf = walk_forward_splits(rows, n_splits=3, embargo_windows=emb)
    print(f"  walk_forward_folds: {len(wf)}")
    for f in wf:
        print(f"     fold {f['fold']}: train_w={f['train_windows']} val_w={f['val_windows']} "
              f"train_rows={f['train_rows']} val_rows={f['val_rows']} val_balance={f['val_label_balance']}")
    print("  safety: read-only; split BY WINDOW (no row-level leakage); purge/embargo; no orders.")
    return 0


def cmd_kalshi_train_baselines(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Train baselines (gated). Refuses below the window gate unless --diagnostic-only."""
    from .venues.kalshi.train_baselines import run_train_baselines

    diag = bool(getattr(args, "diagnostic_only", False))
    # Staging is ENFORCED in this build: artifacts go to data/models/staged/ and the
    # runtime cannot auto-select them. Promotion is a separate, explicit future step.
    print(f"=== kalshi-train-baselines: series={args.series} diagnostic_only={diag} staged=True ===")
    r = run_train_baselines(cfg, series=args.series, diagnostic_only=diag,
                            embargo_windows=int(getattr(args, "embargo_windows", 1)), staged=True)
    g = r["gate"]
    print(f"  training_backend: {r.get('training_backend')}  staged: {r.get('staged')} "
          "(STAGED_NON_PROMOTED; runtime cannot auto-load)")
    print(f"  status: {g['status']}  gate_windows: {g['gate_windows']}/{g['train_gate_threshold']}  rows: {r['n_rows']}")
    if r.get("refused"):
        print("  TRAINING REFUSED (below gate) — no artifacts produced:")
        for b in r["blockers"]:
            print(f"     - {b}")
        print("  safety: no tradable artifact; models uncalibrated; no orders; live disabled.")
        return 0
    sp = r.get("split", {})
    if sp.get("applied"):
        print(f"  split: train_w={sp['train_windows']} val_w={sp['val_windows']} "
              f"purged/embargoed={sp['embargoed_windows']} no_leak={sp['no_leak']}")
    else:
        print(f"  split: not applied ({sp.get('reason')}) -> in-sample diagnostic fit")
    for name, m in r["models"].items():
        if "error" in m:
            print(f"  [{name}] {m['error']}")
            continue
        print(f"  [{name}] eval={m.get('evaluation')} n={m.get('n')} acc={_f3(m.get('accuracy'))} "
              f"auc={_f3(m.get('roc_auc'))} brier={_f3(m.get('brier'))} "
              f"logloss={_f3(m.get('log_loss'))} calib={m.get('calibration_status')}")
    for a in r["artifacts"]:
        print(f"  artifact: {a['artifact_file']} [{a['tradability']}] "
              f"{a.get('tradable_status')} backend={a.get('backend')}")
        print(f"            card: {a['model_card']}")
    print("  note: hard Up/Down class is DIAGNOSTIC ONLY; models UNCALIBRATED -> no PAPER_CANDIDATE.")
    print("  safety: STAGED_NON_PROMOTED (data/models/staged/); not promoted; no orders; live disabled.")
    return 0


def cmd_kalshi_train_model(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Train a single named model (logistic now; lightgbm blocks on missing dependency)."""
    from .venues.kalshi.train_baselines import run_train_model

    model = getattr(args, "model", "logistic")
    diag = bool(getattr(args, "diagnostic_only", False))
    print(f"=== kalshi-train-model: series={args.series} model={model} diagnostic_only={diag} staged=True ===")
    r = run_train_model(cfg, series=args.series, model=model, diagnostic_only=diag,
                        embargo_windows=int(getattr(args, "embargo_windows", 1)), staged=True)
    if r.get("refused"):
        print(f"  REFUSED ({r.get('status')}):")
        for b in r["blockers"]:
            print(f"     - {b}")
        print("  safety: no artifact; no orders; live disabled.")
        return 0
    m = r.get("metrics", {})
    print(f"  trained={r['trained']} status={r.get('status')}  training_backend={r.get('training_backend')}  "
          f"staged={r.get('staged')} (STAGED_NON_PROMOTED)")
    if m:
        print(f"  metrics: acc={_f3(m.get('accuracy'))} auc={_f3(m.get('roc_auc'))} "
              f"brier={_f3(m.get('brier'))} logloss={_f3(m.get('log_loss'))} calib={m.get('calibration_status')}")
    for a in r.get("artifacts", []):
        print(f"  artifact: {a['artifact_file']} [{a['tradability']}] {a.get('tradable_status')} "
              f"backend={a.get('backend')}  card: {a['model_card']}")
    print("  note: UNCALIBRATED -> not usable by paper/live policy; no PAPER_CANDIDATE.")
    print("  safety: STAGED_NON_PROMOTED (data/models/staged/); not promoted; no orders; live disabled.")
    return 0


def cmd_kalshi_calibration_report(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Before/after calibration report on HELD-OUT test windows. No artifact saved."""
    from .venues.kalshi.calibration_report import run_calibration_report

    method = getattr(args, "method", "isotonic")
    print(f"=== kalshi-calibration-report: series={args.series} method={method} ===")
    r = run_calibration_report(cfg, series=args.series, method=method,
                               embargo_windows=int(getattr(args, "embargo_windows", 1)))
    print(f"  gate_windows: {r['gate_windows']}/{r.get('gate_min_windows')}  "
          f"gate_met={r.get('gate_met')}  diagnostic={r.get('diagnostic')}")
    if not r.get("applied"):
        print(f"  BLOCKER: {r.get('reason')}")
        print("  safety: no orders; live disabled.")
        return 0
    sp, b, a = r["split"], r["before"], r["after"]
    print(f"  split(windows): train={sp['train_windows']} calib={sp['calib_windows']} "
          f"test={sp['test_windows']} embargo={sp['embargo_windows']}")
    print(f"  TEST n={b['n']}  brier {_f3(b['brier'])}->{_f3(a['brier'])}  "
          f"logloss {_f3(b['log_loss'])}->{_f3(a['log_loss'])}  ECE {_f3(b['ece'])}->{_f3(a['ece'])}")
    for k, v in (r.get("reports") or {}).items():
        print(f"  {k}: {v}")
    print("  note: calibration fit on HELD-OUT windows; diagnostic => NON_TRADABLE; no PAPER_CANDIDATE.")
    return 0


def cmd_kalshi_calibrate_model(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Fit + (gated) save a calibrator artifact. Below gate requires --diagnostic-only."""
    from .venues.kalshi.calibration_report import run_calibrate_model

    method = getattr(args, "method", "isotonic")
    diag = bool(getattr(args, "diagnostic_only", False))
    print(f"=== kalshi-calibrate-model: series={args.series} method={method} diagnostic_only={diag} staged=True ===")
    r = run_calibrate_model(cfg, series=args.series, method=method, diagnostic_only=diag,
                            embargo_windows=int(getattr(args, "embargo_windows", 1)), staged=True)
    print(f"  gate_windows: {r['gate_windows']}/{r.get('gate_min_windows')}  gate_met={r.get('gate_met')}")
    if r.get("refused"):
        print("  REFUSED:")
        for b in r.get("blockers", []):
            print(f"     - {b}")
        print("  safety: no tradable calibrator; no orders; live disabled.")
        return 0
    b, a = r["before"], r["after"]
    print(f"  TEST brier {_f3(b['brier'])}->{_f3(a['brier'])}  ECE {_f3(b['ece'])}->{_f3(a['ece'])}")
    ov = r.get("overfit")
    if ov:
        print(f"  overfit_risk: {ov['overfit_risk']}" + (f"  ({'; '.join(ov['messages'])})" if ov.get("messages") else ""))
    if r.get("artifact"):
        print(f"  calibrator: {r['artifact']['calibrator_file']} [{r['artifact']['tradability']}] "
              f"{r['artifact'].get('tradable_status')}  staged={r.get('staged')}")
    if r.get("reports"):
        print(f"  report: {r['reports']['report_md']}")
    print("  note: UNCALIBRATED model + diagnostic calibrator => still NON_TRADABLE; no PAPER_CANDIDATE.")
    print("  safety: STAGED_NON_PROMOTED (data/models/staged/); not promoted; no orders; live disabled.")
    return 0


def cmd_kalshi_backtest_baselines(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Executable backtest of no-trade / market-implied / distance-time-vol / microstructure."""
    from .venues.kalshi.executable_backtest import run_backtest_baselines

    diag = bool(getattr(args, "diagnostic_only", False))
    staged = bool(getattr(args, "staged", False))
    model_path = None
    if staged:
        from .venues.kalshi.executable_backtest import latest_staged_model_artifact_path
        model_path = latest_staged_model_artifact_path(cfg)
    print(f"=== kalshi-backtest-baselines: series={args.series} diagnostic_only={diag} "
          f"staged={staged} staged_model={model_path} ===")
    r = run_backtest_baselines(cfg, series=args.series, diagnostic_only=diag,
                               embargo_windows=int(getattr(args, "embargo_windows", 1)),
                               model_path=model_path)
    print(f"  gate_windows: {r['gate_windows']}/{r['gate_min_windows']}  "
          f"gate_met={r['gate_met']}  diagnostic={r['diagnostic']}")
    if r.get("refused"):
        print("  REFUSED:")
        for b in r["blockers"]:
            print(f"     - {b}")
        print("  safety: no orders; live disabled.")
        return 0
    for name, a in r["results"].items():
        if name == "no_trade":
            print("  [no_trade] net_pnl=0.0 (floor)")
            continue
        if "error" in a:
            print(f"  [{name}] error: {a['error']}")
            continue
        cal = a.get("calibration", {})
        print(f"  [{name}] trades={a['total_simulated_trades']} net_pnl={a['net_pnl']} "
              f"hit={_f3(a['hit_rate'])} brier={_f3(cal.get('brier'))} side={a.get('pnl_by_side')}")
        if a.get("walk_forward"):
            print(f"            walk_forward_net_pnl={[round(f['net_pnl'],4) for f in a['walk_forward']]}")
    if r.get("reports"):
        print(f"  report: {r['reports']['comparison_md']}")
    print("  note: EVIDENCE only (not profitability); diagnostic => NON_TRADABLE; no orders.")
    return 0


def cmd_kalshi_backtest_model(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Executable backtest of a saved model artifact (+ optional calibrator) on held-out val."""
    from .venues.kalshi.executable_backtest import run_backtest_model

    diag = bool(getattr(args, "diagnostic_only", False))
    staged = bool(getattr(args, "staged", False))
    mraw = getattr(args, "model", "latest")
    model = "latest" if mraw in ("latest", "logistic", "microstructure", None, "") else mraw
    calibrator = getattr(args, "calibrator", "latest")
    if staged:
        # Resolve to the newest STAGED artifacts (runtime never scans staged/).
        from .venues.kalshi.calibrate import latest_staged_calibrator_path
        from .venues.kalshi.executable_backtest import latest_staged_model_artifact_path
        if model in ("latest", "staged"):
            model = latest_staged_model_artifact_path(cfg) or "latest"
        if calibrator in ("latest", "staged"):
            sc = latest_staged_calibrator_path(cfg)
            calibrator = sc if sc else calibrator
    print(f"=== kalshi-backtest-model: series={args.series} model={model} calibrator={calibrator} "
          f"diagnostic_only={diag} staged={staged} ===")
    r = run_backtest_model(cfg, series=args.series, model=model, calibrator=calibrator,
                           diagnostic_only=diag, embargo_windows=int(getattr(args, "embargo_windows", 1)))
    if r.get("refused"):
        print("  REFUSED:")
        for b in r["blockers"]:
            print(f"     - {b}")
        print("  safety: no orders; live disabled.")
        return 0
    a = r["result"]
    print(f"  model_artifact: {r['model_artifact']}  tradable_artifact={r['tradable_artifact']}  "
          f"diagnostic={r['diagnostic']}")
    print(f"  trades={a['total_simulated_trades']} net_pnl={a['net_pnl']} hit={_f3(a['hit_rate'])} "
          f"avg_edge={_f3(a['avg_net_edge'])} side={a.get('pnl_by_side')}")
    if r.get("reports"):
        print(f"  report: {r['reports']['backtest_md']}")
    print("  note: pre-trained artifact is in-sample => diagnostic; UNCALIBRATED => no PAPER_CANDIDATE; no orders.")
    return 0


def cmd_kalshi_threshold_sweep(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Sweep executable-backtest gates (research only; no policy auto-selection)."""
    from .venues.kalshi.threshold_sweep import run_threshold_sweep

    diag = bool(getattr(args, "diagnostic_only", False))
    staged = bool(getattr(args, "staged", False))
    sweep_model = getattr(args, "model", "latest")
    sweep_cal = getattr(args, "calibrator", "latest")
    if staged:
        from .venues.kalshi.calibrate import latest_staged_calibrator_path
        from .venues.kalshi.executable_backtest import latest_staged_model_artifact_path
        if sweep_model in ("latest", "logistic", "microstructure", "staged", None, ""):
            sweep_model = latest_staged_model_artifact_path(cfg) or "latest"
        if sweep_cal in ("latest", "staged"):
            sc = latest_staged_calibrator_path(cfg)
            sweep_cal = sc if sc else "latest"
    print(f"=== kalshi-threshold-sweep: series={args.series} diagnostic_only={diag} staged={staged} ===")
    r = run_threshold_sweep(cfg, series=args.series, model=sweep_model,
                            calibrator=sweep_cal, diagnostic_only=diag,
                            embargo_windows=int(getattr(args, "embargo_windows", 1)))
    print(f"  gate_windows: {r['gate_windows']}/{r['gate_min_windows']}  "
          f"gate_met={r['gate_met']}  diagnostic={r['diagnostic']}")
    if r.get("refused"):
        print("  REFUSED:")
        for b in r["blockers"]:
            print(f"     - {b}")
        print("  safety: no orders; live disabled.")
        return 0
    traded = [c for c in r["configs"] if (c["trades"] or 0) > 0]
    print(f"  prob_source={r.get('prob_source')}  configs={len(r['configs'])}  configs_with_trades={len(traded)}")
    print("  (NOT auto-selecting a policy — max in-sample P&L overfits; require paper validation)")
    for k, v in (r.get("reports") or {}).items():
        print(f"  {k}: {v}")
    print("  note: research only; EVIDENCE not profitability; no orders; live disabled.")
    return 0


def cmd_kalshi_policy_dry_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Evaluate the paper-candidate policy over recent rows. Emits NO orders."""
    from .venues.kalshi.policy_runtime import run_policy_dry_run

    limit = int(args.limit) if getattr(args, "limit", None) is not None else 20
    fmt = getattr(args, "policy_format", "table")
    print(f"=== kalshi-policy-dry-run: series={args.series} limit={limit} ===")
    r = run_policy_dry_run(cfg, series=args.series, ticker=getattr(args, "ticker", None),
                           limit=limit, include_rejected=bool(getattr(args, "include_rejected", False)),
                           fmt=fmt)
    print(f"  policy_enabled={r['policy_enabled']}  can_emit_PAPER_CANDIDATE={r['can_emit_paper_candidate']}")
    if r["blockers"]:
        print(f"  blockers: {r['blockers']}")
    print(f"  gate_windows={r['gate_windows']} rows={r['n_rows']} decisions_by_state={r['decisions_by_state']}")
    mv, cv, bv = r["model_validity"], r["calibration_validity"], r["backtest_validity"]
    print(f"  model: exists={mv['exists']} trained={mv['trained']} diagnostic_only={mv['diagnostic_only']}")
    print(f"  calibrator: exists={cv['exists']} valid={cv['valid']} diagnostic_only={cv['diagnostic_only']}")
    print(f"  backtest: exists={bv['exists']} valid={bv['valid']} windows={bv['windows']}")
    shown = r["decisions"][:limit]
    if fmt in ("json", "jsonl"):
        for d in shown:
            print(json.dumps(d))
    else:
        for d in shown[:12]:
            pp = d.get("calibrated_probability_yes")
            pp = pp if pp is not None else d.get("model_probability_yes")
            print(f"   [{d['decision_state']}] {d.get('selected_side') or '-'} p={_f3(pp)} "
                  f"yes_ask={_f3(d.get('executable_yes_price'))} net={_f3(d.get('selected_net_edge'))} "
                  f"{d['reason_codes']}")
    print("  note: PAPER_CANDIDATE requires trained+calibrated+non-diagnostic+backtested; no orders; live disabled.")
    return 0


def cmd_kalshi_policy_report(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Aggregate policy decisions + validity + source health. Explains blockers."""
    from .venues.kalshi.policy_runtime import run_policy_report

    print(f"=== kalshi-policy-report: series={args.series} ===")
    r = run_policy_report(cfg, series=args.series,
                          limit=int(args.limit) if getattr(args, "limit", None) is not None else 0)
    print(f"  policy_enabled={r['policy_enabled']}  can_emit_PAPER_CANDIDATE={r['can_emit_paper_candidate']}")
    if r["blockers"]:
        print(f"  blockers: {r['blockers']}")
    print(f"  gate_windows={r['gate_windows']} rows={r['n_rows']}")
    print(f"  decisions_by_state={r['decisions_by_state']}")
    print(f"  reason_counts={r['reason_counts']}")
    print(f"  edge_distribution={r['edge_distribution']}")
    print(f"  source_health={r['source_health']}")
    for c in r["candidate_examples"]:
        print(f"   candidate: {c}")
    print(f"  report: {r['reports']['report_md']}")
    print("  note: PAPER_CANDIDATE blocked unless trained+calibrated+validated; no orders; live disabled.")
    return 0


def cmd_kalshi_paper_policy_sim(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Simulate paper fills for PAPER_CANDIDATE policy decisions. NEVER live."""
    from .venues.kalshi.policy_runtime import run_paper_policy_sim

    limit = int(args.limit) if getattr(args, "limit", None) is not None else 100
    print(f"=== kalshi-paper-policy-sim: series={args.series} limit={limit} ===")
    r = run_paper_policy_sim(cfg, series=args.series, limit=limit,
                             diagnostic_only=bool(getattr(args, "diagnostic_only", False)))
    print(f"  policy_enabled={r['policy_enabled']}  can_emit_PAPER_CANDIDATE={r['can_emit_paper_candidate']}")
    if r["blockers"]:
        print(f"  blockers: {r['blockers']}")
    print(f"  decisions_by_state={r['decisions_by_state']}")
    print(f"  paper_candidates={r['paper_candidates']} ledger_rows={r['ledger_rows']}")
    if r.get("ledger_file"):
        print(f"  ledger: {r['ledger_file']}")
    print(f"  live_submission_allowed={r['live_submission_allowed']}")
    if r["paper_candidates"] == 0:
        print("  note: 0 PAPER_CANDIDATEs (policy blocked / no edge) — no paper orders simulated.")
    print("  safety: simulation only; no live orders; live disabled.")
    return 0


def cmd_kalshi_lock_dry_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Evaluate post-entry lock decisions on OPEN paper positions. Emits NO orders."""
    from .venues.kalshi.lock_runtime import run_lock_dry_run

    fmt = getattr(args, "policy_format", "table")
    print(f"=== kalshi-lock-dry-run: series={args.series} ===")
    r = run_lock_dry_run(
        cfg, series=args.series, ticker=getattr(args, "ticker", None),
        limit=int(args.limit) if getattr(args, "limit", None) is not None else 0,
        include_rejected=bool(getattr(args, "include_rejected", False)), fmt=fmt,
        mode=getattr(args, "lock_mode", None),
        allow_partial=(True if getattr(args, "allow_partial", False) else None))
    print(f"  module_enabled={r['module_enabled']}  open_positions={r['open_positions']}  "
          f"live_submission_allowed={r['live_submission_allowed']}")
    if r.get("status") == "NO_POSITION":
        print(f"  NO_POSITION: {r['message']}")
        print("  safety: post-entry lock only (not a flat arb scanner); no orders; live disabled.")
        return 0
    print(f"  decisions_by_state={r.get('decisions_by_state')}")
    for d in r["decisions"][:20]:
        if fmt in ("json", "jsonl"):
            print(json.dumps(d))
        else:
            print(f"   [{d['decision_state']}] {d['human_summary']}")
    if r.get("reports"):
        print(f"  report: {r['reports']['report_md']}")
    print("  note: post-entry lock only (not a flat arb scanner); paper-only; no live orders.")
    return 0


def cmd_kalshi_lock_sim(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Replay lock decisions over open paper positions' later book rows (diagnostic)."""
    from .venues.kalshi.lock_runtime import run_lock_sim

    print(f"=== kalshi-lock-sim: series={args.series} ===")
    r = run_lock_sim(cfg, series=args.series,
                     limit=int(args.limit) if getattr(args, "limit", None) is not None else 100,
                     mode=getattr(args, "lock_mode", None),
                     allow_partial=(True if getattr(args, "allow_partial", False) else None))
    print(f"  module_enabled={r['module_enabled']}  open_positions={r['open_positions']}")
    if r.get("status") == "NO_POSITION":
        print(f"  NO_POSITION: {r['message']}")
        print("  safety: post-entry lock only; no orders; live disabled.")
        return 0
    print(f"  summary={r['summary']}")
    if r.get("reports"):
        print(f"  report: {r['reports']['report_md']}")
    print("  note: diagnostic paper simulation; post-entry lock only; no live orders.")
    return 0


def cmd_kalshi_position_monitor_dry_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Evaluate post-entry lifecycle decisions on OPEN paper positions. Emits NO orders."""
    from .venues.kalshi.position_lifecycle_runtime import run_position_monitor_dry_run

    fmt = getattr(args, "policy_format", "table")
    print(f"=== kalshi-position-monitor-dry-run: series={args.series} ===")
    r = run_position_monitor_dry_run(
        cfg, series=args.series, ticker=getattr(args, "ticker", None),
        limit=int(args.limit) if getattr(args, "limit", None) is not None else 0,
        include_rejected=bool(getattr(args, "include_rejected", False)), fmt=fmt,
        latest=bool(getattr(args, "latest", False)))
    print(f"  module_enabled={r['module_enabled']}  open_positions={r['open_positions']}  "
          f"live_submission_allowed={r['live_submission_allowed']}")
    if r.get("status") == "NO_POSITION":
        print(f"  NO_POSITION: {r['message']}")
        print("  safety: post-entry lifecycle only (not a flat arb scanner); no orders; live disabled.")
        return 0
    print(f"  decisions_by_action={r.get('decisions_by_action')}")
    for d in r["decisions"][:20]:
        if fmt in ("json", "jsonl"):
            print(json.dumps(d))
        else:
            print(f"   [{d['action']}] {d['human_summary']}")
    if r.get("reports"):
        print(f"  report: {r['reports']['report_md']}")
    print("  note: post-entry only; same-leg sell vs opposite-leg lock vs continue EV; paper-only; no live orders.")
    return 0


def cmd_kalshi_position_monitor_sim(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Replay lifecycle decisions over open paper positions' later book rows (diagnostic)."""
    from .venues.kalshi.position_lifecycle_runtime import run_position_monitor_sim

    print(f"=== kalshi-position-monitor-sim: series={args.series} ===")
    r = run_position_monitor_sim(
        cfg, series=args.series,
        limit=int(args.limit) if getattr(args, "limit", None) is not None else 100)
    print(f"  module_enabled={r['module_enabled']}  open_positions={r['open_positions']}")
    if r.get("status") == "NO_POSITION":
        print(f"  NO_POSITION: {r['message']}")
        print("  safety: post-entry lifecycle only; no orders; live disabled.")
        return 0
    print(f"  summary={r['summary']}")
    if r.get("reports"):
        print(f"  report: {r['reports']['report_md']}")
    print("  note: diagnostic paper simulation; post-entry only; no live orders.")
    return 0


def cmd_kalshi_position_summary(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Summarize open paper positions: sell/lock opportunities, ride, exposure, paper P&L."""
    from .venues.kalshi.position_lifecycle_runtime import run_position_summary

    print(f"=== kalshi-position-summary: series={args.series} ===")
    r = run_position_summary(cfg, series=args.series)
    print(f"  module_enabled={r['module_enabled']}  open_positions={r['open_positions']}")
    if r.get("status") == "NO_POSITION":
        print(f"  NO_POSITION: {r['message']}")
        print("  safety: post-entry lifecycle only; no open positions; live disabled.")
        return 0
    print(f"  exposure={r['exposure']}")
    print(f"  opportunities={r['opportunities']}")
    print(f"  paper_pnl={r['paper_pnl']}")
    for p in r["positions"][:20]:
        print(f"   {p['ticker']} held={p['held']} action={p['action']}")
    print("  safety: post-entry only; paper-only; no live orders; live disabled.")
    return 0


def _freq_header(r: dict) -> None:
    print(f"  prob_source={r.get('prob_source')}  diagnostic={r.get('diagnostic')} "
          f"{r.get('stamp', '')}  gate_windows={r.get('gate_windows')}  promoted=False")
    for b in (r.get("blockers") or []):
        print(f"  blocker: {b}")


def cmd_kalshi_frequency_sweep(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Simulate many frequency policies over held-out rows (research evidence only)."""
    from .venues.kalshi.trade_frequency_runtime import run_frequency_sweep

    print(f"=== kalshi-frequency-sweep: series={args.series} ===")
    r = run_frequency_sweep(cfg, series=args.series,
                            diagnostic_only=bool(getattr(args, "diagnostic_only", False)),
                            max_scenarios=getattr(args, "max_scenarios", None))
    _freq_header(r)
    if r.get("status") != "BLOCKED":
        print(f"  candidates={r.get('candidate_count')}  distinct_windows={r.get('distinct_windows')}  "
              f"scenarios={r.get('scenarios_evaluated')}")
        if r.get("reports"):
            print(f"  reports: {r['reports']}")
    print("  note: research evidence only; do NOT pick a policy by max in-sample P&L; "
          "no promotion; live disabled.")
    return 0


def cmd_kalshi_frequency_report(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Combined frequency report + staged conservative paper-policy suggestion (not promoted)."""
    from .venues.kalshi.trade_frequency_runtime import run_frequency_report

    print(f"=== kalshi-frequency-report: series={args.series} ===")
    r = run_frequency_report(cfg, series=args.series,
                             diagnostic_only=bool(getattr(args, "diagnostic_only", False)),
                             max_scenarios=getattr(args, "max_scenarios", None))
    _freq_header(r)
    if r.get("status") != "BLOCKED":
        print(f"  candidates={r.get('candidate_count')}  distinct_windows={r.get('distinct_windows')}")
        sug = r.get("recommended_paper_policy_suggestion") or {}
        print(f"  conservative suggestion (NOT promoted, manual review): "
              f"min_net_edge_cents={sug.get('min_net_edge_cents')} max_trades_per_window={sug.get('max_trades_per_window')} "
              f"cooldown={sug.get('cooldown_after_entry_seconds')}s max_daily={sug.get('max_daily_trades')}")
    if r.get("reports"):
        print(f"  reports: {r['reports']}")
    print("  note: no settings promoted; no live trading; recommendations require paper validation.")
    return 0


def cmd_kalshi_marginal_trade_curve(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Rank candidates by net edge; report where marginal trades stop adding value."""
    from .venues.kalshi.trade_frequency_runtime import run_marginal_trade_curve

    print(f"=== kalshi-marginal-trade-curve: series={args.series} ===")
    r = run_marginal_trade_curve(cfg, series=args.series,
                                 diagnostic_only=bool(getattr(args, "diagnostic_only", False)))
    _freq_header(r)
    if r.get("status") != "BLOCKED":
        c = r.get("curve", {})
        print(f"  candidates={r.get('candidate_count')}  peak_cumulative_net_pnl={c.get('peak_cumulative_net_pnl')} "
              f"at rank {c.get('peak_at_rank')}/{c.get('total_candidates')}")
        for w in (c.get("warnings") or []):
            print(f"  [!] {w}")
        if r.get("reports"):
            print(f"  reports: {r['reports']}")
    print("  note: research evidence only; no policy promoted; live disabled.")
    return 0


def cmd_kalshi_time_to_close_analysis(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Bucket candidate/trade performance by time remaining in the window."""
    from .venues.kalshi.trade_frequency_runtime import run_time_to_close_analysis

    print(f"=== kalshi-time-to-close-analysis: series={args.series} ===")
    r = run_time_to_close_analysis(cfg, series=args.series,
                                   diagnostic_only=bool(getattr(args, "diagnostic_only", False)))
    _freq_header(r)
    if r.get("status") != "BLOCKED":
        for b in r.get("buckets", []):
            print(f"   {b['bucket']:8s} cand={b['candidates']} exec={b['executed']} "
                  f"windows={b['distinct_windows']} net_pnl={b['net_pnl']}")
        if r.get("reports"):
            print(f"  reports: {r['reports']}")
    print("  note: research evidence only; no policy promoted; live disabled.")
    return 0


def cmd_kalshi_within_window_frequency(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Within-window concentration / overtrading analysis (distinct windows vs raw trades)."""
    from .venues.kalshi.trade_frequency_runtime import run_within_window_frequency

    print(f"=== kalshi-within-window-frequency: series={args.series} ===")
    r = run_within_window_frequency(cfg, series=args.series,
                                    diagnostic_only=bool(getattr(args, "diagnostic_only", False)))
    _freq_header(r)
    if r.get("status") != "BLOCKED":
        print(f"  eligible_candidates={r.get('eligible_candidates')}  distinct_windows={r.get('distinct_windows')}")
        for name, p in (r.get("policies") or {}).items():
            print(f"   {name}: trades={p['trades']} windows={p['distinct_windows']} net_pnl={p['net_pnl']}")
        for w in (r.get("warnings") or []):
            print(f"  [!] [{w['code']}] {w['message']}")
    print("  note: ten trades in one window are not ten independent samples; no promotion; live disabled.")
    return 0


def cmd_kalshi_edge_policy_report(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Confidence-aware edge policy: funnel, calibration buckets, conservative settings."""
    from .venues.kalshi.edge_policy_runtime import run_edge_policy_report

    print(f"=== kalshi-edge-policy-report: series={args.series} ===")
    r = run_edge_policy_report(cfg, series=args.series,
                               diagnostic_only=bool(getattr(args, "diagnostic_only", False)))
    print(f"  prob_source={r.get('prob_source')}  diagnostic={r.get('diagnostic')} {r.get('stamp', '')}  "
          f"gate_windows={r.get('gate_windows')}  promoted=False")
    for b in (r.get("blockers") or []):
        print(f"  blocker: {b}")
    if r.get("status") != "BLOCKED":
        print(f"  funnel={r.get('funnel')}")
        print(f"  edge_ok_settlement={r.get('edge_ok_settlement')}")
        sug = r.get("recommended_settings", {})
        print(f"  conservative (NOT promoted): min_raw={sug.get('min_raw_edge_cents')}c "
              f"min_final={sug.get('min_final_edge_cents')}c conf={sug.get('confidence_level')} "
              f"min_bucket_n={sug.get('min_calibration_bucket_n')}")
    if r.get("reports"):
        print(f"  reports: {r['reports']}")
    print("  note: edge = conservative-bound edge minus fees+uncertainty+regime+overtrading+min-profit; "
          "no promotion; live disabled.")
    return 0


def cmd_kalshi_edge_threshold_sweep(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Sweep edge-policy thresholds/buffers (research evidence only; no auto-select)."""
    from .venues.kalshi.edge_policy_runtime import run_edge_threshold_sweep

    print(f"=== kalshi-edge-threshold-sweep: series={args.series} ===")
    r = run_edge_threshold_sweep(cfg, series=args.series,
                                 diagnostic_only=bool(getattr(args, "diagnostic_only", False)))
    print(f"  prob_source={r.get('prob_source')}  diagnostic={r.get('diagnostic')} {r.get('stamp', '')}  promoted=False")
    for b in (r.get("blockers") or []):
        print(f"  blocker: {b}")
    if r.get("status") != "BLOCKED":
        print(f"  configs_evaluated={len(r.get('configs', []))}")
        if r.get("reports"):
            print(f"  reports: {r['reports']}")
    print("  note: research evidence only; do NOT auto-select a production threshold; no promotion; live disabled.")
    return 0


def cmd_kalshi_uncertainty_audit(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY calibration-uncertainty audit of the edge-policy-blocked cohort.

    Recomputes the edge/uncertainty breakdown via the production evaluate_edge, decomposes
    the calibration buffer into bias + sampling, and reports per-bucket ROW vs DISTINCT-WINDOW
    counts. Never trades, never promotes, never enables paper/live, never mutates artifacts.
    """
    from .venues.kalshi.uncertainty_audit import run_uncertainty_audit

    r = run_uncertainty_audit(
        cfg, series=args.series, ledger=getattr(args, "ledger", None),
        cohort=getattr(args, "cohort", "edge_blocked"),
        top_n=int(getattr(args, "top_n", 20) or 20),
        latest=bool(getattr(args, "latest", False)),
        write_csv=True, write_md=True, write_json=bool(getattr(args, "json", False)))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str))
        return 0
    print(f"=== kalshi-uncertainty-audit: series={args.series} ===")
    if r.get("status") == "NO_LEDGER":
        print(f"  {r.get('note')}")
        for c in (r.get("candidates") or []):
            print(f"    candidate: {c}")
        return 0
    s = r.get("summary", {})
    v = r.get("verdict", {})
    print(f"  ledger: {r.get('ledger')}")
    print(f"  cohort={r.get('cohort')}  rows={r.get('n_cohort')}/{r.get('n_decisions')}  sides={s.get('side_counts')}")
    print(f"  calibration rebuild: {'OK' if r.get('rebuild_ok') else 'UNAVAILABLE ' + str(r.get('rebuild_blockers'))}")
    print(f"  edge identity (final==raw-required): {s.get('identity_pass')}/{s.get('identity_total')} "
          f"=> {v.get('edge_identity_holds')}")
    print(f"  median buffers (recomputed): calibration={_fmtc(s.get('calibration_buffer_cents_median'))} "
          f"model/ensemble={_fmtc(s.get('model_uncertainty_buffer_cents_median'))} "
          f"required={_fmtc(s.get('required_edge_cents_median'))}")
    print(f"  buffer split: bias={_fmtc(v.get('median_bias_cents'))} sampling={_fmtc(v.get('median_sampling_cents'))} "
          f"(bias_fraction={v.get('bias_fraction_of_buffer')})  bias_dominated={v.get('buffer_is_bias_dominated')}")
    print(f"  window-based buffer LARGER than row-based: {v.get('window_based_buffer_is_larger')} "
          f"(row={_fmtc(v.get('median_buffer_row_cents'))} window={_fmtc(v.get('median_buffer_window_cents'))})")
    print(f"  final policy edge: median={_fmtc(s.get('final_policy_edge_cents_median'))} "
          f"best={_fmtc(s.get('final_policy_edge_cents_best'))}  positive_final={s.get('n_positive_final')}/{s.get('n')}")
    print(f"  model-minus-market median={_fmtc(s.get('model_minus_market_cents_median'))} (model sits above market)")
    for b in (r.get("cohort_buckets") or []):
        print(f"   bucket {b['bucket']}: row_n={b['row_n']} window_n={b['distinct_window_n']} "
              f"row_yes={b['row_yes_rate']} win_yes={b['window_yes_rate']} "
              f"buffer_row={b['calib_buffer_row_cents']}c bias={b['calib_bias_row_cents']}c "
              f"samp={b['calib_sampling_row_cents']}c buffer_win={b['calib_buffer_window_cents']}c")
    if r.get("reports"):
        print(f"  reports: {r['reports']}")
    print("  note: READ-ONLY audit; buffer is bias-dominated => reduce by RECALIBRATION, not by removing it; "
          "no promotion; paper/live disabled; live_submission_allowed=false.")
    return 0


def _fmtc(x) -> str:
    return f"{x:.2f}c" if isinstance(x, (int, float)) else str(x)


def _nfmt(x, nd: int = 4) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "None"


def cmd_kalshi_calibration_compare(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only: compare raw/identity/Platt/isotonic/market/promoted calibration."""
    from .venues.kalshi.probability_repair import run_calibration_compare

    r = run_calibration_compare(cfg, series=args.series, staged=True)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-calibration-compare: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')}  reason={r.get('reason')}"); return 0
    print(f"  split={r['split']}  gate_windows={r['gate_windows']}")
    for name, m in r["metrics"].items():
        print(f"  {name}: ECE_window={_nfmt(m.get('ece_window'))} ECE_row={_nfmt(m.get('ece_row'))} "
              f"brier={_nfmt(m.get('brier'))} YES_overpred={_nfmt(m.get('yes_overprediction_cents'),2)}c")
    print(f"  best_source(window ECE, excl. promoted reference): {r['reports'].get('best_source')}")
    print(f"  runtime_unchanged={r.get('runtime_unchanged')}  reports={r['reports']}")
    print("  note: STAGED/report-only; distinct-window ECE is PRIMARY; promoted=reference-only; "
          "no promotion; live disabled.")
    return 0


def cmd_kalshi_market_shrink_sweep(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only: market-shrink alpha sweep (alpha selected by OOS calibration)."""
    from .venues.kalshi.probability_repair import run_market_shrink_sweep

    r = run_market_shrink_sweep(cfg, series=args.series, staged=True)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-market-shrink-sweep: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')}  reason={r.get('reason')}"); return 0
    rec = r.get("recommendation", {})
    mb = r.get("market_baseline", {})
    print(f"  split={r['split']}")
    print(f"  market-implied baseline: ECE_window={_nfmt(mb.get('ece_window'))} brier={_nfmt(mb.get('brier'))}")
    for base, b in r.get("best_per_base", {}).items():
        print(f"  base={base}: best_alpha_by_ece={b['best_alpha_by_ece']} best_ece_window={_nfmt(b['best_ece_window'])}")
    print(f"  RECOMMENDED: base={rec.get('recommended_base')} alpha={rec.get('recommended_alpha')} "
          f"beats_market={rec.get('beats_market_baseline')}  alpha_stable={r.get('alpha_stability',{}).get('stable')}")
    print(f"  staged_artifact={r.get('staged_artifact')}")
    print(f"  runtime_unchanged={r.get('runtime_unchanged')}  reports={r['reports']}")
    print("  note: alpha=0 is pure market, alpha=1 is pure model; selected by OOS window ECE (not P&L); "
          "STAGED; no promotion; live disabled.")
    return 0


def cmd_kalshi_candidate_repair_audit(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only: re-evaluate the edge-blocked cohort under each repaired probability."""
    from .venues.kalshi.probability_repair import run_candidate_repair_audit

    r = run_candidate_repair_audit(cfg, series=args.series, ledger=getattr(args, "ledger", None))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-candidate-repair-audit: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')}  reason={r.get('reason')}  note={r.get('note')}"); return 0
    print(f"  ledger={r.get('ledger')}  cohort_rows={r.get('n_cohort')}  "
          f"shrink(base={r.get('shrink_base')},alpha={r.get('shrink_alpha')})")
    for name, m in r.get("per_method", {}).items():
        print(f"  {name}: +unc_adj={m['n_pos_uncertainty_adjusted']}/{m['n_rows']} pass={m['n_pass_final_edge']} "
              f"med_final={_nfmt(m['median_final_edge_cents'],2)}c best_final={_nfmt(m['best_final_edge_cents'],2)}c "
              f"med_calib_buf={_nfmt(m['median_calib_buffer_cents'],2)}c reduces_overpred={m['n_reduces_yes_overprediction']}")
    rp = r.get("reports", {})
    print(f"  any_pass_full_edge={rp.get('any_pass')}  any_positive_uncertainty_adjusted={rp.get('any_positive_uncertainty_adjusted')}")
    print(f"  runtime_unchanged={r.get('runtime_unchanged')}  reports={rp}")
    print("  note: buffer per source uses that source's OWN held-out reliability (never removed); "
          "STAGED/report-only; no promotion; live disabled.")
    return 0


def cmd_kalshi_probability_repair(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only umbrella: calibration compare + market-shrink + cohort repair + backtest."""
    from .venues.kalshi.probability_repair import run_probability_repair

    r = run_probability_repair(cfg, series=args.series, staged=True, ledger=getattr(args, "ledger", None))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-probability-repair: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')}  reason={r.get('reason')}"); return 0
    print(f"  split={r['split']}  gate_windows={r['gate_windows']}")
    print(f"  best_calibration_source={r['calibration_compare'].get('best_source')}")
    ms = r.get("market_shrink", {}).get("recommendation", {})
    print(f"  market-shrink recommended: base={ms.get('recommended_base')} alpha={ms.get('recommended_alpha')} "
          f"beats_market={ms.get('beats_market_baseline')}")
    for n, a in r.get("backtest", {}).items():
        print(f"  backtest[{n}]: trades={a.get('total_simulated_trades')} windows={a.get('windows_touched')} "
              f"net_pnl={_nfmt(a.get('net_pnl'))} hit_rate={_nfmt(a.get('hit_rate'))}")
    cand = r.get("candidate", {})
    print(f"  cohort any_REPAIRED_pass={cand.get('any_repaired_pass')} "
          f"best_repaired_final={_nfmt(cand.get('best_repaired_final_cents'),2)}c "
          f"(promoted-reference is not a repair)")
    print(f"  staged_artifacts={r.get('staged_artifacts')}")
    print(f"  runtime_unchanged={r.get('runtime_unchanged')}  reports={r.get('reports')}")
    print("  note: STAGED/report-only; honest calibration repair, NOT buffer removal; no promotion; live disabled.")
    return 0


def cmd_kalshi_shadow_compare_probability_repairs(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only: shadow-score the same active rows with every repaired probability."""
    from .venues.kalshi.shadow_repair_compare import run_shadow_compare

    minutes = args.minutes if getattr(args, "minutes", None) is not None else 30.0
    r = run_shadow_compare(cfg, series=args.series, minutes=float(minutes),
                           poll_interval=float(getattr(args, "poll_interval", 0.5) or 0.5),
                           replay_ledger=getattr(args, "ledger", None),
                           max_iterations=getattr(args, "max_iterations", None))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-shadow-compare-probability-repairs: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')}  blockers={r.get('blockers')}")
        print(f"  runtime_unchanged={r.get('runtime_unchanged')}"); return 0
    fb = " (fell back to replay — no fresh active rows)" if r.get("fell_back_to_replay") else ""
    print(f"  mode={r['mode']}{fb}  rows_read={r.get('rows_read')}  executable_rows={r.get('executable_rows')}")
    print(f"  split={r['split']}  shrink_base={r['shrink_base']}  alphas={r['alphas']}")
    for name, s in r["summary"].items():
        print(f"  {name}: rows={s['n_rows']} candidate_like={s['candidate_like_rows']} "
              f"pass_final={s['pass_final_edge']} med_final={_nfmt(s['median_final_edge_cents'],2)}c "
              f"best_final={_nfmt(s['best_final_edge_cents'],2)}c "
              f"med_calib_buf={_nfmt(s['median_calib_buffer_cents'],2)}c sides={s['side_distribution']}")
    v = r["verdict"]
    print(f"  any_REPAIRED_pass={v['any_repaired_pass']}  best_repaired_final={_nfmt(v['best_repaired_final_cents'],2)}c")
    print(f"  STAGED_SHADOW_CANDIDATE={v.get('staged_shadow_candidate')}")
    print(f"  recommendation: {v['recommendation']}")
    print(f"  staged_candidates={len(r['staged_candidates'])}  runtime_unchanged={r['runtime_unchanged']}  "
          f"ledger={r.get('ledger_file')}")
    print(f"  reports={r['reports']}")
    print("  note: shadow scoring only; per-source buffer never removed; STAGED; no promotion; live/paper disabled.")
    return 0


def cmd_kalshi_calibrator_replacement_review(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only: should the promoted isotonic calibrator be replaced later? (no promotion)"""
    from .venues.kalshi.calibrator_replacement import run_calibrator_replacement_review

    r = run_calibrator_replacement_review(cfg, series=args.series, ledger=getattr(args, "ledger", None))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-calibrator-replacement-review: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')}  reason={r.get('reason')}  blockers={r.get('blockers')}")
        print(f"  runtime_unchanged={r.get('runtime_unchanged')}"); return 0
    print(f"  split={r['split']}  gate_windows={r['gate_windows']}  reliability_unit={r['reliability_unit']}")
    for m, x in r["metrics"].items():
        bt = r["backtest"].get(m, {})
        print(f"  {m}: ECE_window={_nfmt(x.get('ece_window'))} ECE_row={_nfmt(x.get('ece_row'))} "
              f"brier={_nfmt(x.get('brier'))} YES_overpred={_nfmt(x.get('yes_overprediction_cents'),2)}c "
              f"backtest_net={_nfmt(bt.get('net_pnl'),2)} trades={bt.get('total_simulated_trades')}")
    print(f"  recommended_replacement_candidate={r['recommended_replacement_candidate']}  "
          f"eligible_for_promotion_review={r['replacement_eligible_for_promotion_review']}")
    print(f"  blockers={r['eligibility']['blockers']}  warnings={r['eligibility']['warnings']}")
    print(f"  rationale: {r['eligibility']['rationale']}")
    print(f"  runtime_unchanged={r['runtime_unchanged']}  staged={len(r['staged_artifacts'])}  reports={r['reports']}")
    print("  note: REVIEW only — NOT a promotion; promoted isotonic stays ACTIVE; window ECE is primary; "
          "live/paper disabled.")
    return 0


def cmd_kalshi_candidate_replacement_impact(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only: edge-blocked cohort re-scored under each calibrator (row + window buffers)."""
    from .venues.kalshi.calibrator_replacement import run_candidate_replacement_impact

    r = run_candidate_replacement_impact(cfg, series=args.series, ledger=getattr(args, "ledger", None))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-candidate-replacement-impact: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')}  reason={r.get('reason')}"); return 0
    print(f"  ledger={r.get('ledger')}  cohort={r.get('n_cohort')}  reliability_unit={r['reliability_unit']}")
    for u, pm in (r.get("by_unit") or {}).items():
        print(f"  -- unit={u} --")
        for m, s in pm.items():
            print(f"    {m}: candidate_like={s['candidate_like']} pass_final={s['pass_final']} "
                  f"distinct_pass_windows={s['distinct_pass_windows']} "
                  f"best_final={_nfmt(s['best_final_cents'],2)}c "
                  f"med_calib_buf={_nfmt(s['median_calib_buffer_cents'],2)}c sides={s['side_distribution']}")
    print(f"  runtime_unchanged={r['runtime_unchanged']}  reports={r.get('reports')}")
    print("  note: row vs window calibration buffers; window is the honest/WIDER unit; no promotion; live disabled.")
    return 0


def cmd_kalshi_stage_calibrator_replacements(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only: write staged identity/Platt/isotonic/market-shrunk replacement candidates."""
    from .venues.kalshi.calibrator_replacement import run_stage_calibrator_replacements

    r = run_stage_calibrator_replacements(cfg, series=args.series)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-stage-calibrator-replacements: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')}  reason={r.get('reason')}"); return 0
    for a in r["staged_artifacts"]:
        print(f"  staged {a['candidate']} ({a['method']}) -> {a['tradable_status']}: "
              f"{a.get('artifact_file') or a.get('calibrator_file')}")
    print(f"  catalog={r.get('catalog')}  runtime_unchanged={r['runtime_unchanged']}")
    print("  note: STAGED_NON_PROMOTED/DIAGNOSTIC_ONLY only; data/models/staged/; manifest unchanged; live disabled.")
    return 0


def cmd_kalshi_build_residual_dataset(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only: build the residual (y - p_market) modeling dataset."""
    from .venues.kalshi.residual_alpha import run_build_residual_dataset

    r = run_build_residual_dataset(cfg, series=args.series)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-build-residual-dataset: series={args.series} ===")
    m = r.get("metadata", {})
    mc = m.get("market_implied_calibration", {})
    print(f"  dataset_file={r.get('dataset_file')} ({r.get('format')})")
    print(f"  rows={m.get('n_rows')} distinct_windows={m.get('distinct_windows')} "
          f"base_rate={_nfmt(m.get('base_rate'))} residual mean/std={_nfmt(m.get('residual_mean'))}/"
          f"{_nfmt(m.get('residual_std'))}")
    print(f"  market-implied baseline: brier={_nfmt(mc.get('brier'))} ECE_window={_nfmt(mc.get('ece_window'))}")
    print(f"  candidate_pnl_positive_rows={m.get('candidate_pnl_positive_rows')}/{m.get('n_rows')}")
    print(f"  runtime_unchanged={r.get('runtime_unchanged')} report={r.get('report')}")
    print("  note: target=residual_vs_market; executable asks (no midpoint); STAGED; no promotion; live disabled.")
    return 0


def _residual_models_print(r) -> None:
    print(f"  split={r['split']} rows={r['n_rows']} sklearn={r.get('sklearn_available')} "
          f"lightgbm={r.get('lightgbm_available')}")
    mm = r.get("market_metrics", {})
    print(f"  market baseline: brier={_nfmt(mm.get('brier'))} ECE_window={_nfmt(mm.get('ece_window'))}")
    for kind, res in r.get("results", {}).items():
        if "metrics" not in res:
            print(f"  {kind}: error={res.get('error')}"); continue
        mt = res["metrics"]; ew = res["edge_window"]; bt = res["backtest"]
        print(f"  {kind}: dBrier_vs_mkt={_nfmt(mt.get('delta_brier_vs_market'))} "
              f"IC={_nfmt(mt.get('residual_ic_spearman'))} sign_hit={_nfmt(mt.get('residual_sign_hit_rate'))} "
              f"pass_final(win)={ew['pass_final']} dist_pass_win={ew['distinct_pass_windows']} "
              f"backtest_net={_nfmt(bt.get('net_pnl'),2)}")
    v = r.get("verdict", {})
    print(f"  any_beats_market_oos={v.get('any_model_beats_market_oos')} {v.get('models_beating_market')}")
    print(f"  any_multi_window_edge={v.get('any_model_multi_window_edge')} {v.get('edge_winners')}")
    print(f"  recommendation: {v.get('recommendation')}")
    print(f"  staged={len(r.get('staged_artifacts', []))} runtime_unchanged={r.get('runtime_unchanged')} "
          f"reports={r.get('reports')}")


def cmd_kalshi_train_residual_models(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only: train residual-over-market models + metrics/backtest/edge reports."""
    from .venues.kalshi.residual_alpha import run_train_residual_models

    r = run_train_residual_models(cfg, series=args.series)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-train-residual-models: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')} reason={r.get('reason')}"); return 0
    _residual_models_print(r)
    print("  note: market is the BASELINE; buffers intact; +2c gate intact; STAGED; no promotion; live disabled.")
    return 0


def cmd_kalshi_residual_model_report(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only: residual model report (same compute as train; report focus)."""
    from .venues.kalshi.residual_alpha import run_residual_model_report

    r = run_residual_model_report(cfg, series=args.series)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-residual-model-report: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')} reason={r.get('reason')}"); return 0
    _residual_models_print(r)
    print("  note: STAGED/report-only; no promotion; live disabled.")
    return 0


def cmd_kalshi_residual_replay(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only: replay residual models over the latest shadow ledger."""
    from .venues.kalshi.residual_alpha import run_residual_replay

    r = run_residual_replay(cfg, series=args.series, ledger=getattr(args, "ledger", None),
                            latest_shadow=bool(getattr(args, "latest_shadow", True)))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-residual-replay: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')} reason={r.get('reason')}  runtime_unchanged={r.get('runtime_unchanged')}")
        return 0
    print(f"  ledger={r.get('ledger')} rows_scored={r.get('rows_scored')}")
    for name, s in (r.get("summary") or {}).items():
        print(f"  {name}: candidate_like={s['candidate_like']} pass_final={s['pass_final']} "
              f"distinct_pass_windows={s['distinct_pass_windows']} best_final={_nfmt(s['best_final_cents'],2)}c "
              f"sides={s['side_distribution']}")
    print(f"  runtime_unchanged={r.get('runtime_unchanged')} report={r.get('report')}")
    print("  note: replay only; buffers intact; no promotion; live disabled.")
    return 0


def cmd_kalshi_shadow_compare_residual_models(cfg: AppConfig, args: argparse.Namespace) -> int:
    """STAGED/report-only: live shadow compare of market baseline vs residual models."""
    from .venues.kalshi.residual_alpha import run_shadow_compare_residual

    minutes = args.minutes if getattr(args, "minutes", None) is not None else 30.0
    r = run_shadow_compare_residual(cfg, series=args.series, minutes=float(minutes),
                                    poll_interval=float(getattr(args, "poll_interval", 0.5) or 0.5))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-shadow-compare-residual-models: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')} blockers={r.get('blockers')}  "
              f"runtime_unchanged={r.get('runtime_unchanged')}"); return 0
    print(f"  mode={r.get('mode')} rows_read={r.get('rows_read')} executable_rows={r.get('executable_rows')} "
          f"rows_scored={r.get('rows_scored')}")
    for name, s in (r.get("summary") or {}).items():
        print(f"  {name}: candidate_like={s['candidate_like']} pass_final={s['pass_final']} "
              f"distinct_pass_windows={s['distinct_pass_windows']} best_final={_nfmt(s['best_final_cents'],2)}c "
              f"sides={s['side_distribution']}")
    print(f"  runtime_unchanged={r.get('runtime_unchanged')} report={r.get('report')}")
    print("  note: shadow only; buffers intact; no promotion; live/paper disabled.")
    return 0


def cmd_kalshi_maker_entry_study(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY maker-entry feasibility study (conservative trade-through fills)."""
    from .venues.kalshi.maker_entry import run_maker_entry_study

    horizons_arg = getattr(args, "rest_horizons", None)
    horizons = None
    if horizons_arg:
        horizons = [h if h == "close" else float(h) for h in str(horizons_arg).split(",") if h]
    fill_model = getattr(args, "fill_model", "quote") or "quote"
    r = run_maker_entry_study(cfg, series=args.series,
                              improve_cents=int(getattr(args, "improve_cents", 1) or 1),
                              maker_fee_rate=float(getattr(args, "maker_fee_rate", 0.0) or 0.0),
                              rest_horizons=horizons, fill_model=fill_model)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-maker-entry-study: series={args.series} fill_model={fill_model} ===")
    sp = r.get("spread_stats", {})
    tf = r.get("taker_fee_stats", {})
    print(f"  windows={r.get('n_windows')} decision_points={r.get('n_decision_points')}")
    print(f"  cost-to-cross: spread mean/median={_nfmt(sp.get('mean'), 3)}/"
          f"{_nfmt(sp.get('median'), 3)}  taker_fee mean={_nfmt(tf.get('mean'), 4)}")
    for side, a in (r.get("central_cohorts") or {}).items():
        print(f"  {side}/join/close: eligible={a['eligible']} fills={a['fills']} "
              f"fill_rate={_nfmt(a['fill_rate'], 3)} win|fill={_nfmt(a['win_rate_given_fill'], 3)} "
              f"makerEV={_nfmt(a['maker_ev_cents_per_fill'], 2)}c/fill "
              f"takerEV={_nfmt(a['taker_ev_cents_per_decision'], 2)}c/decision")
    df = r.get("double_fill", {})
    print(f"  both-sides: double_fills={df.get('n_double_fills')}/{df.get('n_quote_points')} "
          f"mean_locked_net={_nfmt(df.get('mean_locked_net'), 4)}")
    v = r.get("verdict", {})
    print(f"  verdict: positive_lower_bound_sides={v.get('sides_with_positive_conservative_maker_ev')}")
    print(f"  {v.get('interpretation')}")
    print(f"  report={r.get('report_file')}")
    print("  note: READ-ONLY lower-bound study; no orders; no paper; live disabled.")
    return 0


def cmd_kalshi_backfill_trades(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY: backfill historical PUBLIC trade prints (idempotent; no orders)."""
    from .venues.kalshi.backfill_trades import backfill_trades

    start = getattr(args, "start_date", None)
    if not start:
        print("ERROR: --start-date YYYYMMDD is required (history verified to >= 20260601)")
        return 1
    print(f"=== kalshi-backfill-trades: series={args.series} start={start} "
          f"end={getattr(args, 'end_date', None) or 'now'} ===")
    r = backfill_trades(cfg, series=args.series, start_date=start,
                        end_date=getattr(args, "end_date", None),
                        chunk_hours=int(getattr(args, "chunk_hours", 1) or 1))
    print(f"  chunks={r['chunks']} fetched={r['fetched']} series_matched={r['series_matched']} "
          f"written={r['written']} dupes_skipped={r['duplicates_skipped']} errors={r['errors']}")
    if r.get("pages_capped_chunks"):
        print(f"  WARNING: {r['pages_capped_chunks']} chunk(s) hit the page cap -> shrink --chunk-hours")
    print(f"  days_touched={r['days_touched']}")
    print("  note: READ-ONLY public tape; idempotent (trade_id dedupe); no orders; live disabled.")
    return 0


def cmd_kalshi_paper_calibrator_swap_review(cfg: AppConfig, args: argparse.Namespace) -> int:
    """PAPER-ONLY calibration-safety review: is identity_raw/Platt safer than promoted isotonic?"""
    from .venues.kalshi.paper_calibrator_swap import run_swap_review

    r = run_swap_review(cfg, series=args.series)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-paper-calibrator-swap-review: series={args.series} ===")
    print(f"  current promoted calibrator: {r.get('current_promoted_calibrator')} "
          f"(promoted_valid={r.get('promoted_valid')})")
    metrics = r.get("review_metrics") or {}
    for m in ("current_promoted_isotonic", "identity_raw", "platt", "fresh_isotonic", "market_implied"):
        if m in metrics:
            x = metrics[m]; bt = (r.get("review_backtest") or {}).get(m, {})
            print(f"  {m}: ECE_window={_nfmt(x.get('ece_window'))} brier={_nfmt(x.get('brier'))} "
                  f"YES_overpred={_nfmt(x.get('yes_overprediction_cents'),2)}c "
                  f"backtest_net={_nfmt(bt.get('net_pnl'),2)} pass_final=0")
    for cand, c in r.get("candidates", {}).items():
        if c.get("available"):
            print(f"  candidate {cand}: eligible={c.get('eligible')} blockers={c.get('blockers')}")
    print(f"  recommended_candidate={r.get('recommended_candidate')} "
          "(calibration-safety only; NO tradable edge; pass_final=0)")
    print(f"  runtime_unchanged={r.get('runtime_unchanged')}  reports={r.get('reports')}")
    print("  note: review only; no promotion; paper/live disabled; edge gates unchanged; reversible.")
    return 0


def cmd_kalshi_paper_calibrator_swap(cfg: AppConfig, args: argparse.Namespace) -> int:
    """PAPER-ONLY calibrator swap. Dry-run by default; --write applies (reversible). NEVER live."""
    from .venues.kalshi.paper_calibrator_swap import swap_dry_run, swap_write

    candidate = getattr(args, "candidate", None) or "identity_raw"
    write = bool(getattr(args, "write", False))
    r = swap_write(cfg, series=args.series, candidate=candidate) if write \
        else swap_dry_run(cfg, series=args.series, candidate=candidate)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-paper-calibrator-swap: series={args.series} candidate={candidate} write={write} ===")
    print(f"  status={r.get('status')}")
    if r.get("status") in ("REFUSED", "REFUSED_NOT_ELIGIBLE", "REFUSED_NO_BACKUP"):
        print(f"  reason={r.get('reason')}  eligibility={r.get('eligibility')}")
        return 0
    e = r.get("eligibility") or {}
    print(f"  eligible={e.get('eligible')} (better_window_ece={e.get('better_window_ece')} "
          f"reduces_yes_overpred={e.get('reduces_yes_overprediction')} not_worse_brier={e.get('not_worse_brier')})")
    if r.get("status") == "DRY_RUN":
        pm = r.get("planned_manifest", {})
        print(f"  staged_source={r.get('staged_source')}")
        print(f"  calibrator_type: {r.get('current_calibrator_type')} -> {pm.get('calibrator_type')} (planned)")
        print(f"  model PRESERVED: {pm.get('model_artifact_path')}")
        print(f"  planned manifest: promoted_for={pm.get('promoted_for')} live_approved={pm.get('live_approved')} "
              f"no_live_orders={pm.get('no_live_orders')} previous_calibrator={pm.get('previous_calibrator_artifact_path')}")
        print(f"  manifest_written={r.get('manifest_written')} paper_disabled={r.get('paper_disabled')} "
              f"live_disabled={r.get('live_disabled')}")
        print(f"  note: {r.get('note')}")
    else:
        print(f"  new_calibrator={r.get('new_calibrator_path')}")
        print(f"  previous_calibrator={r.get('previous_calibrator_path')}  backup={r.get('pre_swap_manifest_backup_path')}")
        print(f"  model_preserved={r.get('model_preserved')} new_promotion_valid={r.get('new_promotion_valid')} "
              f"paper_disabled={r.get('paper_disabled')} live_disabled={r.get('live_disabled')}")
        print(f"  reason={r.get('reason')}  rollback: kalshi-paper-calibrator-swap-rollback --write")
    print("  note: PAPER-ONLY calibrator swap; model+gates preserved; no edge; reversible; live disabled.")
    return 0


def cmd_kalshi_paper_calibrator_swap_rollback(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Restore the previous paper-promoted calibrator (dry-run unless --write). NEVER live."""
    from .venues.kalshi.paper_calibrator_swap import swap_rollback

    r = swap_rollback(cfg, series=args.series, write=bool(getattr(args, "write", False)))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-paper-calibrator-swap-rollback: series={args.series} "
          f"write={bool(getattr(args, 'write', False))} ===")
    print(f"  status={r.get('status')}")
    for k in ("restore_from_backup", "previous_calibrator", "restored_calibrator", "method",
              "new_promotion_valid", "can_restore", "note"):
        if r.get(k) is not None:
            print(f"  {k}={r.get(k)}")
    print("  note: restores previous paper calibrator; artifacts preserved; live disabled.")
    return 0


def _payload_from_latest_ledger(cfg: AppConfig, kind: str):
    """Build a dry-run payload from the latest policy/lock paper ledger row (or None)."""
    from .venues.kalshi.order_planner import build_dry_run_order_payload
    d = cfg.data_path() / "paper"
    pat = "kalshi_policy_paper_ledger-*.jsonl" if kind == "policy" else "kalshi_lock_ledger-*.jsonl"
    files = sorted(d.glob(pat)) if d.exists() else []
    last = None
    for f in files:
        for row in _iter_jsonl_safe(str(f)):
            side = row.get("selected_side") or row.get("side")
            price = row.get("selected_entry_price") or row.get("price")
            if side and price is not None:
                last = row
    if not last:
        return None
    return build_dry_run_order_payload(
        config=cfg, ticker=last.get("ticker"), side=(last.get("selected_side") or last.get("side")),
        action="buy", quantity=(last.get("size") or last.get("quantity")),
        limit_price=(last.get("selected_entry_price") or last.get("price")),
        tif="fill_or_kill", price_is_cents=False)


def cmd_kalshi_live_blockers(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Print all live blockers + next steps. No network mutation; no orders."""
    from .venues.kalshi.live_readiness import assess_live_readiness, write_audit_log

    print(f"=== kalshi-live-blockers: series={args.series} ===")
    r = assess_live_readiness(cfg)
    print(f"  state={r['state']}  live_submission_allowed={r['live_submission_allowed']}  "
          f"dry_run_only={r['dry_run_only']}  readiness_enabled={r['readiness_enabled']}")
    print("  blockers:")
    for b in r["blockers"]:
        print(f"     - [{b['code']}] {b['message']}")
    print("  required_next_actions:")
    for a in r["required_next_actions"]:
        print(f"     - {a}")
    write_audit_log(cfg, r)
    print("  safety: no orders; no live cancel; no network mutation; live disabled.")
    return 0


def cmd_kalshi_live_readiness(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Full live-readiness report (optionally for the latest policy/lock intent). No submit."""
    from .venues.kalshi.live_readiness import assess_live_readiness, write_audit_log

    payload = None
    if getattr(args, "from_policy_latest", False) or getattr(args, "order_intent", None) == "latest-paper-candidate":
        payload = _payload_from_latest_ledger(cfg, "policy")
    elif getattr(args, "from_lock_latest", False):
        payload = _payload_from_latest_ledger(cfg, "lock")
    r = assess_live_readiness(cfg, order_payload=payload)
    if getattr(args, "json", False):
        print(json.dumps(r, default=str))
    else:
        print(f"=== kalshi-live-readiness: series={args.series} ===")
        print(f"  state={r['state']}  live_submission_allowed={r['live_submission_allowed']}  "
              f"dry_run_only={r['dry_run_only']}")
        print(f"  model={r['model_status']}")
        print(f"  calibration={r['calibration_status']}")
        print(f"  backtest={r['backtest_status']}")
        print(f"  paper_evidence={r['paper_evidence_status']}")
        print(f"  risk={r['risk_status']}")
        print(f"  source_health={r['source_health_status']}")
        print(f"  credentials(no values)={r['credential_status_without_values']}")
        print(f"  order_plan_status={r['order_plan_status']}")
        print("  blockers:")
        for b in r["blockers"]:
            print(f"     - [{b['code']}] {b['message']}")
        if getattr(args, "verbose", False):
            print("  required_next_actions:")
            for a in r["required_next_actions"]:
                print(f"     - {a}")
    write_audit_log(cfg, r, order_payload=payload)
    print("  safety: dry-run only; nothing submitted; live disabled.")
    return 0


def cmd_kalshi_live_dry_run_order(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Build + validate a dry-run live order payload. NEVER submits."""
    from .venues.kalshi.live_readiness import assess_live_readiness, write_audit_log
    from .venues.kalshi.order_planner import build_dry_run_order_payload

    if not getattr(args, "ticker", None):
        print("usage: kalshi-live-dry-run-order --ticker <TICKER> --side YES|NO --action buy "
              "--qty <N> --price <cents> --tif fill_or_kill|immediate_or_cancel")
        print("  ERROR: --ticker is required (no order is ever submitted).")
        return 2
    payload = build_dry_run_order_payload(
        config=cfg, ticker=args.ticker, side=getattr(args, "side", "YES"),
        action=getattr(args, "action", "buy"), quantity=getattr(args, "qty", None),
        limit_price=getattr(args, "price", None), tif=getattr(args, "tif", "fill_or_kill"),
        price_is_cents=None)
    r = assess_live_readiness(cfg, order_payload=payload)
    print(f"=== kalshi-live-dry-run-order: {args.ticker} {getattr(args,'side','YES')} "
          f"{getattr(args,'action','buy')} qty={getattr(args,'qty',None)} "
          f"price={getattr(args,'price',None)} tif={getattr(args,'tif','fill_or_kill')} ===")
    print(f"  order_plan_status={r['order_plan_status']}  state={r['state']}  "
          f"live_submission_allowed={r['live_submission_allowed']}")
    if payload.blockers:
        print(f"  payload_blockers={payload.blockers}")
    print(f"  sanitized_payload={payload.payload}")
    print(f"  endpoint={payload.method} {payload.endpoint}  (DOCUMENTED; NOT called)")
    print(f"  checksum={payload.checksum}")
    print("  live blockers:")
    for b in r["blockers"][:12]:
        print(f"     - [{b['code']}] {b['message']}")
    write_audit_log(cfg, r, ticker=args.ticker, order_payload=payload)
    print("  safety: dry-run only; payload NOT submitted; live disabled.")
    return 0


def cmd_kalshi_private_read_preflight(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Read-only private preflight. Calls NO endpoint in this build; no secrets printed."""
    from .venues.kalshi.live_readiness import kalshi_private_read_preflight

    print(f"=== kalshi-private-read-preflight: series={args.series} ===")
    r = kalshi_private_read_preflight(cfg, allow_private_read=bool(getattr(args, "allow_private_read", False)))
    for k, v in r.items():
        print(f"  {k}: {v}")
    print("  safety: read-only; no orders/cancels; no secrets printed; live disabled.")
    return 0


def _ops_md(data, level=0):
    lines = []
    ind = "  " * level
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{ind}- **{k}**:")
                lines.extend(_ops_md(v, level + 1))
            else:
                lines.append(f"{ind}- **{k}**: {v}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                lines.extend(_ops_md(item, level))
            else:
                lines.append(f"{ind}- {item}")
    return lines


def _ops_emit(cfg, args, data, subdir, stem, title):
    """Shared --json / --markdown / --write-report handling for ops commands."""
    if getattr(args, "json", False):
        print(json.dumps(data, default=str, indent=2))
    if getattr(args, "write_report", False) or getattr(args, "markdown", False):
        from .venues.kalshi.ops import write_report
        md = f"# {title}\n\n" + "\n".join(_ops_md(data)) + "\n"
        paths = write_report(cfg, subdir, stem, data, markdown=md)
        for k, v in paths.items():
            print(f"  report_{k}: {v}")


def cmd_kalshi_ops_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Unified read-only ops dashboard. Never collects, never trades, no secrets."""
    from .venues.kalshi.ops import ops_status

    s = ops_status(cfg, include_models=not getattr(args, "include_paper", False) or True,
                   include_paper=True, include_live_readiness=True)
    if not getattr(args, "json", False):
        print(f"=== kalshi-ops-status: {s['primary_venue']} (mode={s['trading_mode']}, tz={s['timezone']}) ===")
        print(f"  polymarket_dormant={s['polymarket_dormant']}  deribit_enabled={s['deribit_enabled']}")
        c = s["collector"]
        print(f"  collector: {c['verdict']} — {c['recommendation']}")
        for n, sv in c["sources"].items():
            print(f"     {n:8s} rows_today={sv['rows_today']} age={sv['age']} stale={sv['stale']}")
        g = s["gate"]
        print(f"  gate: {g['gate_windows']}/{g['backtest_gate_threshold']} backtest, "
              f"{g['gate_windows']}/{g['train_gate_threshold']} train | usable_rows={g['usable_rows']} | "
              f"capture~{g['capture_rate_per_hour']}/h | bottleneck={g['bottleneck']}")
        m = s.get("model", {})
        print(f"  model: {m.get('status')} | calibration_valid={m.get('calibration_valid')} | "
              f"backtest_valid={m.get('backtest_valid')} | can_emit_candidate={m.get('policy_can_emit_paper_candidate')}")
        p = s.get("paper", {})
        print(f"  paper: {p.get('status')} | states={p.get('decisions_by_state', {})} | "
              f"open_positions={p.get('open_paper_positions', 0)}")
        print(f"  safety: {s['safety']['headline']} | live_submission_allowed={s['safety']['live_submission_allowed']}")
        print("  next actions:")
        for a in s["next_actions"]:
            print(f"     - {a}")
    _ops_emit(cfg, args, s, "ops", "kalshi_ops_status", "Kalshi ops status")
    return 0


def cmd_kalshi_collector_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Infer collector health from files + source-health. Never touches collectors."""
    from .venues.kalshi.ops import collector_status

    s = collector_status(cfg, stale_threshold_seconds=int(getattr(args, "stale_threshold_seconds", 120) or 120),
                         record_history=True)
    if not getattr(args, "json", False):
        print(f"=== kalshi-collector-status: {s['verdict']} ===")
        print(f"  recommendation: {s['recommendation']}")
        for n, sv in s["sources"].items():
            print(f"  {n:8s} rows_today={sv['rows_today']} age={sv['age']} stale={sv['stale']} enabled={sv['enabled']}")
        print(f"  features age={s['feature_age']}  labels age={s['label_age']}  "
              f"gate_windows={s.get('gate_windows')}  delta_since_last={s.get('gate_windows_delta_since_last')}")
    _ops_emit(cfg, args, s, "ops", "kalshi_collector_status", "Kalshi collector status")
    return 0


def cmd_kalshi_gate_progress(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Distinct feature-backed official window gate progress (orphans excluded)."""
    from .venues.kalshi.ops import gate_progress

    g = gate_progress(cfg)
    if not getattr(args, "json", False):
        print(f"=== kalshi-gate-progress: {args.series} ===")
        print(f"  gate_windows={g['gate_windows']}  feature_backed={g['feature_backed_official_windows']}  "
              f"orphans_excluded={g['orphan_labels_excluded']}  usable_rows={g['usable_rows']}")
        print(f"  backtest gate {g['gate_windows']}/{g['backtest_gate_threshold']} "
              f"(remaining {g['windows_remaining_backtest']}) | train gate {g['gate_windows']}/{g['train_gate_threshold']} "
              f"(remaining {g['windows_remaining_train']})")
        print(f"  recent windows 1h/3h/12h = {g['recent_windows_1h']}/{g['recent_windows_3h']}/{g['recent_windows_12h']}  "
              f"capture~{g['capture_rate_per_hour']}/h")
        print(f"  ETA to backtest: ideal(4/h)={g['eta_backtest_hours_ideal_4ph']}h  "
              f"actual={g['eta_backtest_hours_actual']}h  bottleneck={g['bottleneck']}")
        print(f"  next: {g['next_command']}")
    _ops_emit(cfg, args, g, "ops", "kalshi_gate_progress", "Kalshi gate progress")
    return 0


def cmd_kalshi_model_health(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.ops import model_health

    m = model_health(cfg)
    if not getattr(args, "json", False):
        print(f"=== kalshi-model-health: {args.series} ===")
        print(f"  status={m['status']}  latest_model={m['latest_model']}  diagnostic_only={m['model_diagnostic_only']}")
        print(f"  calibration: exists={m['calibration_exists']} valid={m['calibration_valid']} "
              f"diagnostic_only={m['calibration_diagnostic_only']}")
        print(f"  backtest: exists={m['backtest_exists']} valid={m['backtest_valid']} windows={m['backtest_windows']}")
        print(f"  can_emit_PAPER_CANDIDATE={m['policy_can_emit_paper_candidate']}")
        print(f"  blockers: {m['blockers_to_paper_candidate']}")
    _ops_emit(cfg, args, m, "models", "kalshi_model_health", "Kalshi model health")
    return 0


def cmd_kalshi_backtest_summary(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.ops import backtest_summary

    b = backtest_summary(cfg)
    if not getattr(args, "json", False):
        print(f"=== kalshi-backtest-summary: {args.series} ===")
        print(f"  status={b['status']}")
        if b["status"] == "OK":
            print(f"  diagnostic={b.get('diagnostic')}  gate_met={b.get('gate_met')}  "
                  f"usable_by_policy={b.get('usable_by_policy')}")
            print(f"  baselines={b.get('baselines')}")
            print(f"  sweep_configs={b.get('sweep_configs')} (with_trades={b.get('sweep_configs_with_trades')})")
            print(f"  note: {b.get('overfit_warning')}")
        else:
            print(f"  next: {b.get('next_command')}")
    _ops_emit(cfg, args, b, "backtests", "kalshi_backtest_summary", "Kalshi backtest summary")
    return 0


def cmd_kalshi_paper_summary(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.ops import paper_summary

    date = getattr(args, "date", None)
    p = paper_summary(cfg, date=date)
    if not getattr(args, "json", False):
        print(f"=== kalshi-paper-summary: {args.series} ({p.get('date')}) ===")
        if p["status"] != "OK":
            print(f"  {p['status']}: {p.get('note')}")
        else:
            print(f"  ledger_rows={p['ledger_rows']}  decisions_by_state={p['decisions_by_state']}")
            print(f"  fills={p['fill_status_counts']}  paper_pnl={p['paper_pnl']}  pnl_by_side={p['pnl_by_side']}")
            print(f"  skipped_due_to_timing={p.get('skipped_due_to_timing', 0)}  "
                  f"rejected_due_to_book={p.get('rejected_due_to_book', 0)}  "
                  f"rejected_due_to_model_uncalibrated={p.get('rejected_due_to_model_uncalibrated', 0)}")
            print(f"  open_positions={p['open_paper_positions']}  locked_pairs={p['locked_pairs']}  "
                  f"naked_yes={p['naked_yes']} naked_no={p['naked_no']}")
            print(f"  top_reason_codes={p['top_reason_codes']}  lock_events={p['lock_events']}")
    _ops_emit(cfg, args, p, "paper", "kalshi_paper_summary", "Kalshi paper summary")
    return 0


def cmd_kalshi_lock_summary(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.ops import lock_summary

    s = lock_summary(cfg)
    if not getattr(args, "json", False):
        print(f"=== kalshi-lock-summary: {args.series} ===")
        print(f"  status={s['status']}")
        if s["status"] == "OK":
            print(f"  open_positions={s['open_positions']}  fully_locked={s['fully_locked']}  "
                  f"naked_yes={s['naked_yes']} naked_no={s['naked_no']}")
            print(f"  lock_events={s['lock_events']}")
            print(f"  note: {s['note']}")
    _ops_emit(cfg, args, s, "paper", "kalshi_lock_summary", "Kalshi lock summary")
    return 0


def cmd_kalshi_safety_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.ops import safety_status

    s = safety_status(cfg)
    if not getattr(args, "json", False):
        print(f"=== kalshi-safety-status: {args.series} ===")
        print(f"  *** {s['headline']} ***")
        print(f"  trading_mode={s['trading_mode']}  live_trading_enabled={s['live_trading_enabled']}  "
              f"kill_switch_active={s['kill_switch_active']}")
        print(f"  require_manual_confirmation={s['require_manual_confirmation']}  "
              f"live_submit_enabled={s['live_submit_enabled']}  dry_run_only={s['dry_run_only']}")
        print(f"  kalshi_auth_configured={s['kalshi_auth_configured']}  risk_limits_set={s['risk_limits_set']}  "
              f"live_submission_allowed={s['live_submission_allowed']}")
        print(f"  live_adapter_refuses={s['live_adapter_refuses']}  live_readiness_state={s['live_readiness_state']}")
        if s["dangerous_warnings"]:
            print(f"  !! DANGEROUS: {s['dangerous_warnings']}")
    _ops_emit(cfg, args, s, "ops", "kalshi_safety_status", "Kalshi safety status")
    return 0


def cmd_kalshi_doctor(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.ops import doctor

    d = doctor(cfg, run_tests=bool(getattr(args, "run_tests", False)))
    if not getattr(args, "json", False):
        print(f"=== kalshi-doctor: {args.series} | overall={d['overall']} | {d['summary']} ===")
        for c in d["checks"]:
            print(f"  [{c['status']:4s}] {c['check']}: {c['detail']}")
    _ops_emit(cfg, args, d, "ops", "kalshi_doctor", "Kalshi doctor")
    return 0


def cmd_kalshi_eod_summary(cfg: AppConfig, args: argparse.Namespace) -> int:
    from .venues.kalshi.ops import eod_summary

    r = eod_summary(cfg, date=getattr(args, "date", None),
                    send_notification=bool(getattr(args, "send_notification", False)))
    if not getattr(args, "json", False):
        print(f"=== kalshi-eod-summary: {args.series} ({r['date']}) ===")
        print(f"  {r['notification_line']}")
        print(f"  notified={r['notified']}  model={r['model_status']}  safety={r['safety_headline']}")
        print("  next actions:")
        for a in r["next_actions"]:
            print(f"     - {a}")
    _ops_emit(cfg, args, r, "eod", "kalshi_eod_summary", "Kalshi EOD summary")
    return 0


def cmd_dependency_check(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Report optional ML/data dependency availability + degraded features. Never installs."""
    from .venues.kalshi.ops import dependency_check

    d = dependency_check(cfg)
    if not getattr(args, "json", False):
        print(f"=== dependency-check === python {d['python_version']}")
        print(f"  serious_training_available={d['serious_training_available']}  "
              f"training_path={d['training_path']}")
        print(f"  stdlib_fallback_active={d['stdlib_fallback_active']}  "
              f"lightgbm_challenger={d['lightgbm_challenger']}")
        for name, info in d["dependencies"].items():
            mark = "OK  " if info["installed"] else "MISS"
            print(f"  [{mark}] {name:14s} {str(info['version'] or ''):10s} — {info['purpose']}")
        print("  features:")
        for f, ok in d["features"].items():
            print(f"     {'on ' if ok else 'off'} {f}")
        if d["missing_ml_deps"]:
            print(f"  missing ML deps: {d['missing_ml_deps']}")
            print(f"  install: {d['recommended_install']['models']}")
            print(f"  commands that fall back to DIAGNOSTIC-ONLY when missing: {d['fallback_commands_when_missing']}")
        print(f"  note: {d['warning']}")
    _ops_emit(cfg, args, d, "ops", "dependency_check", "Dependency check")
    return 0


def cmd_kalshi_notify_test(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Send a short Kalshi test notification (Noop unless Pushover configured). No secrets."""
    notifier = build_notifier(cfg)
    ok = notifier.eod("BTC 15m KALSHI ops notify-test — live disabled; no orders")
    print(f"=== kalshi-notify-test === provider={'pushover' if cfg.notifications.pushover_configured else 'noop'} "
          f"sent={ok}")
    print("  safety: no secrets printed; Noop fallback if Pushover unconfigured.")
    return 0


def _iter_jsonl_safe(path):
    import json as _json
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        yield _json.loads(line)
                    except _json.JSONDecodeError:
                        continue
    except OSError:
        return


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _short(token: str | None) -> str:
    if not token:
        return "?"
    return token[:8] + "..." if len(token) > 8 else token


def _take(seq, n):
    """Limit a sequence; ``n <= 0`` (or None) means no limit — take all."""
    items = list(seq)
    return items if (n is None or n <= 0) else items[:n]


def _normalized_event(meta: ContractMeta, outcome: Outcome, token_id: str, book: OrderBook) -> dict:
    """Flatten an OrderBook + context into a normalized, re-derivable event."""
    return {
        "contract_id": meta.contract_id,
        "slug": meta.slug,
        "condition_id": meta.condition_id,
        "outcome": outcome.value,
        "outcome_label": meta.yes_outcome_label if outcome is Outcome.YES else meta.no_outcome_label,
        "token_id": token_id,
        "ts_ms": book.ts_ms,            # source/exchange timestamp
        "recv_ms": book.recv_ms,        # local receive timestamp
        "quote_age_ms": age_ms(book.ts_ms, ref_ms=book.recv_ms),
        "best_bid": book.best_bid.price if book.best_bid else None,
        "best_ask": book.best_ask.price if book.best_ask else None,
        "spread": book.spread,
        "is_crossed": book.is_crossed,
        "bids": [[lvl.price, lvl.size] for lvl in book.bids],
        "asks": [[lvl.price, lvl.size] for lvl in book.asks],
        "expiry_ms": meta.expiry_ms,
        "window_start_ms": meta.window_start_ms,
    }


# --------------------------------------------------------------------------- #
# Paper-only artifact promotion + shadow/paper runtime (NEVER live)
# --------------------------------------------------------------------------- #
def cmd_kalshi_paper_promotion_review(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY paper-promotion eligibility review. Never promotes, never trades."""
    from .venues.kalshi.paper_promotion import audit, review_promotion

    model = getattr(args, "model", "staged") or "staged"
    calibrator = getattr(args, "calibrator", "staged") or "staged"
    r = review_promotion(cfg, series=args.series, model=model, calibrator=calibrator)
    audit(cfg, "REVIEW", {"series": args.series, "result": ("ELIGIBLE" if r["eligible_for_paper_promotion"]
          else "NOT_ELIGIBLE"), "blockers": r["blockers"], "warnings": r["warnings"],
          "model_path": r["model_artifact_path"], "calibrator_path": r["calibrator_artifact_path"]})
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str))
        return 0
    print(f"=== kalshi-paper-promotion-review: series={args.series} ===")
    print(f"  eligible_for_paper_promotion: {r['eligible_for_paper_promotion']}")
    print(f"  model_artifact   : {r['model_artifact_path']}")
    print(f"  calibrator_artifact: {r['calibrator_artifact_path']}")
    print(f"  gate_windows: {r['gate_windows']}/{r['min_windows']}")
    print("  evidence_reports:")
    for k, v in r["evidence_reports"].items():
        print(f"     {k}: {'OK' if v else 'MISSING'}")
    if getattr(args, "verbose", False):
        print(f"  model_meta: {json.dumps(r['model_meta'], default=str)}")
        print(f"  calibrator_meta: {json.dumps(r['calibrator_meta'], default=str)}")
    if r["blockers"]:
        print("  BLOCKERS:")
        for b in r["blockers"]:
            print(f"     - {b}")
    if r["warnings"]:
        print("  WARNINGS:")
        for w in r["warnings"]:
            print(f"     - {w}")
    if r["eligible_for_paper_promotion"]:
        print(f"  recommended_model_artifact   : {r['recommended_model_artifact']}")
        print(f"  recommended_calibrator_artifact: {r['recommended_calibrator_artifact']}")
        print(f"  recommended_policy_config: {json.dumps(r['recommended_policy_config'])}")
    print(f"  why_no_live: {r['why_no_live']}")
    print("  safety: read-only; no promotion; live_submission_allowed=false.")
    return 0


def cmd_kalshi_promote_paper_artifacts(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Promote a model+calibrator FOR PAPER ONLY. Dry-run by default; --write requires eligibility."""
    from .venues.kalshi.paper_promotion import promote

    write = bool(getattr(args, "write", False))
    model = getattr(args, "model", "staged") or "staged"
    calibrator = getattr(args, "calibrator", "staged") or "staged"
    r = promote(cfg, series=args.series, model=model, calibrator=calibrator, write=write,
                reason=getattr(args, "reason", "") or "")
    print(f"=== kalshi-promote-paper-artifacts: series={args.series} "
          f"mode={'WRITE' if write else 'DRY-RUN'} ===")
    print(f"  eligible: {r['eligible']}  status: {r['status']}")
    print(f"  model_artifact   : {r['model_artifact_path']}")
    print(f"  calibrator_artifact: {r['calibrator_artifact_path']}")
    if r["blockers"]:
        print("  BLOCKERS (no manifest written):")
        for b in r["blockers"]:
            print(f"     - {b}")
    if r.get("warnings"):
        for w in r["warnings"]:
            print(f"  warning: {w}")
    if r["status"] == "DRY_RUN":
        print("  DRY-RUN: no manifest written. Re-run with --write to promote (PAPER ONLY).")
    if r["status"] == "PROMOTED_FOR_PAPER":
        print(f"  manifest: {r['manifest_path']}")
        print(f"  promoted model sha256: {r['manifest']['model_artifact_sha256'][:16]}...")
        print(f"  promoted calibrator sha256: {r['manifest']['calibrator_artifact_sha256'][:16]}...")
        print("  PROMOTED FOR PAPER ONLY. live_approved=false; no .env/live-config modified.")
    print(f"  audit: {r.get('audit_file')}")
    print("  safety: PAPER_ONLY; live_submission_allowed=false; no orders.")
    return 0


def cmd_kalshi_demote_paper_artifacts(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Disable the active paper promotion (rollback). Dry-run by default; --write applies."""
    from .venues.kalshi.paper_promotion import demote

    write = bool(getattr(args, "write", False))
    r = demote(cfg, series=args.series, write=write)
    print(f"=== kalshi-demote-paper-artifacts: series={args.series} "
          f"mode={'WRITE' if write else 'DRY-RUN'} ===")
    print(f"  status: {r['status']}  manifest_existed: {r['manifest_existed']}")
    if r.get("disabled_manifest_path"):
        print(f"  disabled manifest -> {r['disabled_manifest_path']} (artifacts preserved)")
    print(f"  audit: {r.get('audit_file')}")
    print("  safety: paper promotion disabled; artifacts preserved; live remains disabled.")
    return 0


def cmd_kalshi_paper_runtime_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY paper runtime status: mode, promotion validity, can-emit summary."""
    from .venues.kalshi.paper_runtime import runtime_status

    r = runtime_status(cfg, series=args.series)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str))
        return 0
    print(f"=== kalshi-paper-runtime-status: series={args.series} ===")
    print(f"  model_runtime_mode: {r['model_runtime_mode']}  paper_policy_enabled: {r['paper_policy_enabled']}")
    print(f"  promotion_manifest_exists: {r['promotion_manifest_exists']}  valid: {r['promotion_manifest_valid']}")
    print(f"  can_emit_PAPER_CANDIDATE: {r['can_emit_paper_candidate']}  live_submission_allowed: {r['live_submission_allowed']}")
    if r.get("promoted"):
        p = r["promoted"]
        print(f"  promoted model: {p['model_path']} ({(p.get('model_sha256') or '')[:16]}...)")
        print(f"  promoted calibrator: {p['calibrator_path']} ({(p.get('calibrator_sha256') or '')[:16]}...)")
        print(f"  promoted_for: {p['promoted_for']}  live_approved: {p['live_approved']}")
    if r["why_cannot_emit"]:
        print(f"  why_cannot_emit: {r['why_cannot_emit']}")
    print(f"  modes: {r['modes']}")
    print("  safety: read-only; manifest-based loading only (no newest-by-mtime); live disabled.")
    return 0


def cmd_kalshi_shadow_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    """SHADOW run: score recent snapshots with promoted artifacts; log only; no fills, no live."""
    from .venues.kalshi.paper_runtime import run_shadow

    seconds = float(getattr(args, "seconds", None) or 60.0)
    limit = int(getattr(args, "limit", None) or 25)
    r = run_shadow(cfg, series=args.series, seconds=seconds, limit=limit)
    print(f"=== kalshi-shadow-run: series={args.series} seconds={seconds} (SHADOW ONLY) ===")
    print(f"  status: {r.get('status')}  manifest_valid: {r.get('manifest_valid')}")
    if r.get("blockers"):
        print(f"  blockers: {r['blockers']}")
    print(f"  rows_evaluated: {r.get('n_rows_evaluated', 0)}  decisions_by_state: {r.get('decisions_by_state', {})}")
    print(f"  shadow_decisions: {r.get('shadow_decisions', 0)}  paper_candidates: {r.get('paper_candidates', 0)} "
          "(must be 0 in shadow)")
    if r.get("shadow_report_file"):
        print(f"  report: {r['shadow_report_file']}")
    if r.get("shadow_ledger_file"):
        print(f"  ledger: {r['shadow_ledger_file']}")
    print("  safety: SHADOW ONLY — no PAPER_CANDIDATE, no fills, no orders, live disabled.")
    return 0


# --------------------------------------------------------------------------- #
# Controlled paper EXPERIMENT (shadow first, paper only after preflight; NEVER live)
# --------------------------------------------------------------------------- #
def cmd_kalshi_paper_experiment_preflight(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY preflight: can we run shadow / paper safely? Never promotes/trades."""
    from .venues.kalshi.paper_experiment import preflight

    r = preflight(cfg, series=args.series)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str))
        return 0
    print(f"=== kalshi-paper-experiment-preflight: series={args.series} ===")
    print(f"  preflight_pass: {r['preflight_pass']}  paper_ready: {r['paper_ready']}  "
          f"recommended_mode: {r['recommended_mode']}")
    print(f"  shadow_completed_before: {r['shadow_completed_before']}")
    for c in r["checks"]:
        mark = {"PASS": "ok ", "WARN": "WARN", "FAIL": "FAIL"}[c["status"]]
        print(f"     [{mark}] {c['check']}: {c['detail']}")
    if r["blockers"]:
        print(f"  SEVERE BLOCKERS (no shadow/paper): {r['blockers']}")
    if r["paper_blockers"]:
        print(f"  paper_blockers (shadow ok, paper not): {r['paper_blockers']}")
    if r["warnings"]:
        print(f"  warnings: {r['warnings']}")
    print("  safety: read-only; live_submission_allowed=false; no orders.")
    return 0


def cmd_kalshi_paper_experiment_start(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Run ONE controlled experiment pass (shadow|paper). Never live; never long-collects."""
    from .venues.kalshi.paper_experiment import run_experiment

    mode = (getattr(args, "experiment_mode", None) or "shadow").lower()
    minutes = (float(args.minutes) if getattr(args, "minutes", None) else None)
    # max_iterations defaults to single-pass ONLY when no --minutes is given.
    raw_mi = getattr(args, "max_iterations", None)
    max_iter = int(raw_mi) if raw_mi else (None if minutes else 1)
    r = run_experiment(cfg, series=args.series, mode=mode, minutes=minutes,
                       skip_shadow_warning=bool(getattr(args, "skip_shadow_warning", False)),
                       limit=int(getattr(args, "limit", None) or 25),
                       max_iterations=max_iter, name=getattr(args, "name", None),
                       poll_interval=float(getattr(args, "poll_interval", None) or 5.0))
    print(f"=== kalshi-paper-experiment-start: series={args.series} mode={mode}"
          + (f" minutes={minutes} (LIVE LOOP)" if (minutes and max_iter != 1) else " (single batch pass)") + " ===")
    print(f"  experiment_id: {r.get('experiment_id')}  status: {r['status']}")
    if r.get("abort_reason"):
        print(f"  abort_reason: {r['abort_reason']}")
    s = r.get("summary", {})
    if s and s.get("live_loop"):
        print(f"  LIVE LOOP: iterations={s.get('iterations')} elapsed_s={s.get('elapsed_s')} "
              f"requested_minutes={s.get('minutes_requested')} poll_interval={s.get('poll_interval')}s "
              f"fresh_rows_evaluated={s.get('samples')}")
        print(f"  SELECTION: rows_read={s.get('rows_read')} -> active_window={s.get('active_window_rows')} "
              f"book_backed={s.get('book_backed_rows')} start_ref={s.get('start_reference_rows')} "
              f"=> eligible/executable={s.get('rows_eligible_for_scoring')} (scored)")
        print(f"  selection_diagnostics: rows_with_start_reference={s.get('rows_with_start_reference')} "
              f"rows_missing_start_reference_by_reason={s.get('rows_missing_start_reference_by_reason')} "
              f"rows_with_executable_depth={s.get('rows_with_executable_depth')} "
              f"rows_missing_depth_by_reason={s.get('rows_missing_depth_by_reason')}")
        print(f"  rejected_before_scoring: {s.get('rejected_before_scoring')} "
              f"by_reason={s.get('rejected_before_scoring_by_reason')}")
    if s:
        print(f"  rows_evaluated: {s.get('n_rows_evaluated')}  decisions_by_state: {s.get('decisions_by_state')}")
        print(f"  shadow_decisions: {s.get('shadow_decisions')}  paper_candidates: {s.get('paper_candidates')}  "
              f"would_be_paper_candidates: {s.get('would_be_paper_candidates')}")
        print(f"  paper_fills: {s.get('paper_fills')}  net_pnl_cents: {s.get('paper_net_pnl_cents')}  "
              f"freshness_stale_rows: {s.get('freshness_stale_rows')}")
        print(f"  freshness_split: book_stale_rows={s.get('book_stale_rows')} "
              f"underlying_stale_rows={s.get('underlying_stale_rows')} "
              f"feature_row_stale_rows={s.get('feature_row_stale_rows')} "
              f"deribit_stale_rows={s.get('deribit_stale_rows')}")
        print(f"  feature_row_age_ms (freshest/stalest): {s.get('freshest_feature_row_age_ms')}/"
              f"{s.get('stalest_feature_row_age_ms')}  feature_row_stale_rows: {s.get('feature_row_stale_rows')}")
    print(f"  manifest: {r.get('manifest_path')}")
    if r.get("ledger_file"):
        print(f"  ledger: {r['ledger_file']}")
    print("  safety: " + ("SHADOW — no fills" if mode == "shadow" else "PAPER — fills simulated vs label")
          + "; no live orders; live_submission_allowed=false.")
    return 0


def cmd_kalshi_paper_experiment_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY status of the latest paper experiment."""
    from .venues.kalshi.paper_experiment import status

    r = status(cfg, series=args.series)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str))
        return 0
    print(f"=== kalshi-paper-experiment-status: series={args.series} ===")
    if r.get("status") == "NO_EXPERIMENT":
        print(f"  {r['note']}")
    else:
        print(f"  experiment_id: {r.get('experiment_id')}  mode: {r.get('mode')}  status: {r.get('status')}")
        print(f"  abort_reason: {r.get('abort_reason')}  start: {r.get('start_time')}  end: {r.get('end_time')}")
        print(f"  decisions_by_state: {r.get('decisions_by_state')}")
        print(f"  shadow_decisions: {r.get('shadow_decisions')}  paper_candidates: {r.get('paper_candidates')}  "
              f"paper_fills: {r.get('paper_fills')}  open_positions: {r.get('open_positions')}")
        print(f"  paper_net_pnl_cents: {r.get('paper_net_pnl_cents')}  max_drawdown_cents: {r.get('paper_max_drawdown_cents')}")
        print(f"  rejection_reason_counts: {r.get('rejection_reason_counts')}")
        print(f"  freshness_stale_rows: {r.get('freshness_stale_rows')}")
        print(f"  freshness_split: book_stale_rows={r.get('book_stale_rows')} "
              f"underlying_stale_rows={r.get('underlying_stale_rows')} "
              f"feature_row_stale_rows={r.get('feature_row_stale_rows')} "
              f"deribit_stale_rows={r.get('deribit_stale_rows')}")
        if r.get("live_loop"):
            print(f"  SELECTION: rows_read={r.get('rows_read')} active_window={r.get('active_window_rows')} "
                  f"book_backed={r.get('book_backed_rows')} start_ref={r.get('start_reference_rows')} "
                  f"eligible/executable={r.get('rows_eligible_for_scoring')}")
            print(f"  selection_diagnostics: rows_with_start_reference={r.get('rows_with_start_reference')} "
                  f"rows_missing_start_reference_by_reason={r.get('rows_missing_start_reference_by_reason')} "
                  f"rows_with_executable_depth={r.get('rows_with_executable_depth')} "
                  f"rows_missing_depth_by_reason={r.get('rows_missing_depth_by_reason')}")
            print(f"  rejected_before_scoring: {r.get('rejected_before_scoring')} "
                  f"by_reason={r.get('rejected_before_scoring_by_reason')}")
    ls = r["live_safety"]
    print(f"  live_safety: live_blocked={ls['live_blocked']} kill_switch={ls['kill_switch']} "
          f"live_submission_allowed={ls['live_submission_allowed']}  runtime_mode={r.get('model_runtime_mode')}")
    return 0


def cmd_kalshi_paper_experiment_stop(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Write a STOP flag + mark the latest RUNNING experiment ABORTED. No collectors killed."""
    from .venues.kalshi.paper_experiment import stop

    r = stop(cfg, series=args.series, reason=(getattr(args, "reason", "") or "manual"))
    print(f"=== kalshi-paper-experiment-stop: series={args.series} ===")
    print(f"  stop_flag: {r['stop_flag']}")
    print(f"  stopped_experiment: {r['stopped_experiment']}")
    print(f"  note: {r['note']}")
    print("  safety: no collectors killed; live disabled.")
    return 0


def cmd_kalshi_paper_experiment_report(cfg: AppConfig, args: argparse.Namespace) -> int:
    """Write a markdown experiment report (decisions, fills, recommendation). No profitability claims."""
    from .venues.kalshi.paper_experiment import report

    r = report(cfg, series=args.series)
    print(f"=== kalshi-paper-experiment-report: series={args.series} ===")
    if r.get("status") == "NO_EXPERIMENT":
        print("  NO_EXPERIMENT: run kalshi-paper-experiment-start first.")
        return 0
    print(f"  status: {r['status']}  recommendation: {r.get('recommendation')}")
    print(f"  report: {r['report_file']}")
    print("  safety: read-only; no profitability claim; live disabled.")
    return 0


def _rl_kwargs(args) -> dict:
    """Shared read-only reprice-lag arguments."""
    return dict(
        series=args.series, date=getattr(args, "date", None),
        start_date=getattr(args, "start_date", None), end_date=getattr(args, "end_date", None),
        shock_threshold_bps=getattr(args, "shock_threshold_bps", None),
        min_depth=getattr(args, "min_depth", None),
        min_seconds_to_close=getattr(args, "min_seconds_to_close", None),
        max_seconds_to_close=getattr(args, "max_seconds_to_close", None),
        include_deribit=(str(getattr(args, "include_deribit", "auto")).lower() != "false"),
        include_polymarket=bool(getattr(args, "include_polymarket", False)))


def cmd_kalshi_shock_scan(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY: detect + de-dup BTC shocks from recorded Coinbase/Binance microstructure."""
    from .venues.kalshi.reprice_lag import run_shock_scan

    r = run_shock_scan(cfg, series=args.series, date=getattr(args, "date", None),
                       start_date=getattr(args, "start_date", None),
                       end_date=getattr(args, "end_date", None),
                       shock_threshold_bps=getattr(args, "shock_threshold_bps", None))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-shock-scan: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')}  {r.get('note', '')}"); return 0
    print(f"  days={r['days']}  raw_shock_rows={r['raw_shock_rows']}  dedup_events={r['dedup_events']}")
    print(f"  distinct_windows={r['distinct_windows']}  distinct_days={r['distinct_days']}  "
          f"up={r['up_shocks']} down={r['down_shocks']} near_line={r['near_line_shocks']}")
    print(f"  median_lag_cents={r['median_lag_cents']}  median_time_to_move_s={r['median_time_to_move_s']}")
    print("  note: recorded ~4s cadence cannot resolve sub-4s lag; READ-ONLY; live disabled.")
    return 0


def _v2_over(args) -> dict:
    """High-res v2 config overrides from CLI args."""
    return dict(
        shock_threshold_bps=getattr(args, "shock_threshold_bps", None),
        min_depth=getattr(args, "min_depth", None),
        min_net_edge_cents=getattr(args, "min_net_edge_cents", None),
        min_seconds_to_close=getattr(args, "min_seconds_to_close", None),
        max_seconds_to_close=getattr(args, "max_seconds_to_close", None),
        near_line_only=(True if getattr(args, "near_line_only", False) else None),
        max_source_age_ms=getattr(args, "max_source_age_ms", None),
        dedupe_seconds=getattr(args, "dedupe_seconds", None),
        horizon_ms=getattr(args, "horizon_ms", None),
        include_deribit=(str(getattr(args, "include_deribit", "auto")).lower() != "false"))


def _run_hires_v2(cfg: AppConfig, args: argparse.Namespace, *, mode: str) -> int:
    """High-res reprice-lag v2 for study/report/sensitivity — consistent block, no v1 fallback."""
    from .venues.kalshi.reprice_lag_hires import (
        run_hires_v2_study, run_hires_v2_report, run_hires_v2_sensitivity)
    dk = dict(series=args.series, date=getattr(args, "date", None),
              start_date=getattr(args, "start_date", None), end_date=getattr(args, "end_date", None))
    over = _v2_over(args)
    if mode == "sensitivity":
        r = run_hires_v2_sensitivity(cfg, **dk, **over)
    elif mode == "report":
        r = run_hires_v2_report(cfg, **dk, **over)
    else:
        r = run_hires_v2_study(cfg, **dk, **over)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-reprice-lag-{mode} --hires (HIGH-RES v2): series={args.series} ===")
    if r.get("status") != "OK":
        d = r.get("data", {})
        print(f"  BLOCKED ({r.get('status')}): {r.get('reason')}")
        print(f"  (rows={d.get('n_rows')} windows={d.get('n_windows')}; collect more with "
              "kalshi-hires-record. The low-res v1 study runs WITHOUT --hires.)")
        return 0
    print("  USED: high-res v2 on kalshi_hires_joined_snapshots (NOT low-res v1)")
    if mode == "sensitivity":
        print(f"  {'bps':>4} {'horizon':>8} {'shocks':>7} {'cands':>6} {'opps':>5} {'win':>7} "
              f"{'avg_pnl':>9} {'cover':>6}")
        for g in r["grid"]:
            print(f"  {g['shock_threshold_bps']:4} {g['horizon_ms']:8} {g['raw_shocks']:7} "
                  f"{g['raw_candidates']:6} {g['dedup_opportunities']:5} {str(g['win_rate']):>7} "
                  f"{str(g['avg_pnl']):>9} {str(g['coverage_fraction']):>6}")
        print(f"  reports: {r['reports']}")
        print("  note: READ-ONLY v2 sensitivity; live disabled.")
        return 0
    s = r["summary"]
    cov = s["coverage_by_horizon"]
    covstr = "/".join((f"{cov.get(h) * 100:.0f}%" if cov.get(h) is not None else "n/a")
                      for h in (250, 500, 1000, 2000, 5000))
    print(f"  rows={s['n_rows']} windows={s['n_windows']} days={s['days']} "
          f"(labelled windows={s['windows_with_label']}, line filled from labels={s['line_filled_from_labels']})")
    print(f"  coverage +250/+500/+1s/+2s/+5s = {covstr}  moved_expected={_nfmt(s['moved_expected_fraction'])}")
    print(f"  raw_shocks={s['raw_shock_rows']} candidates={s['raw_candidates']} -> "
          f"dedup_opps={s['dedup_opportunities']} (settled {s['settled_opportunities']}, "
          f"pending {s['pending_opportunities']}) across {s['distinct_windows_opps']} windows / {s['distinct_days']} days")
    print(f"  win_rate={_nfmt(s['win_rate'])} avg_net_pnl={_nfmt(s['avg_pnl'])} "
          f"total={_nfmt(s['total_net_pnl'])} profit_factor={_nfmt(s['profit_factor'])}")
    if mode == "report":
        for k, v in r["answers"].items():
            print(f"  - {k}: {v}")
    print(f"  verdict={r['verdict']}  reports={r['reports']}")
    print("  note: READ-ONLY v2; no paper/live; no promotion; live_submission_allowed=false.")
    return 0


def cmd_kalshi_reprice_lag_study(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY event study: BTC shocks -> Kalshi book response -> stale executable quotes."""
    from .venues.kalshi.reprice_lag import run_reprice_lag_study

    if getattr(args, "hires", False):
        return _run_hires_v2(cfg, args, mode="study")

    r = run_reprice_lag_study(cfg, write_md=True, write_csv=True, **_rl_kwargs(args))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-reprice-lag-study: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')}  {r.get('note', '')}"); return 0
    s = r["summary"]
    print(f"  days={s['days']}  raw_shock_rows={s['raw_shock_rows']}  dedup_events={s['dedup_events']}")
    print(f"  qualified_opportunities={s['qualified_opportunities']} across "
          f"{s['distinct_windows_with_opps']} windows / {s['distinct_days']} day(s)")
    print(f"  up/down shocks={s['up_shocks']}/{s['down_shocks']}  opp_win_rate={s['opp_win_rate']}  "
          f"avg_net_pnl={_nfmt(s['opp_avg_net_pnl'])}")
    print(f"  median_lag_cents={s['median_lag_cents']}  median_time_to_move_s={s['median_time_to_move_s']}  "
          f"deribit_present={r['deribit_present']}  polymarket={r['polymarket'].get('classification')}")
    print(f"  reports: {r['reports']}")
    print("  note: LOW-RES v1 (~4s cadence); pass --hires for high-res v2. READ-ONLY; no paper/live; "
          "live_submission_allowed=false.")
    return 0


def cmd_kalshi_reprice_lag_report(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY: run the event study and print the verdict (high-res v2 with --hires)."""
    from .venues.kalshi.reprice_lag import run_reprice_lag_study, study_answers

    if getattr(args, "hires", False):
        return _run_hires_v2(cfg, args, mode="report")

    r = run_reprice_lag_study(cfg, write_md=True, write_csv=bool(getattr(args, "csv", False)),
                              **_rl_kwargs(args))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-reprice-lag-report: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')}  {r.get('note', '')}"); return 0
    a = study_answers(r["summary"])
    for k in ("q1_shocks_lead_repricing", "q2_lag_seconds", "q3_executable_stale_after_fees",
              "q4_spread_across_windows", "q5_up_and_down_both_viable",
              "q6_persists_across_days_regimes", "q7_killed_by_fees_spread", "q8_worth_staged_shadow"):
        print(f"  - {k}: {a[k]}")
    print(f"  reports: {r['reports']}")
    print("  note: READ-ONLY; no paper/live; no promotion; live_submission_allowed=false.")
    return 0


def cmd_kalshi_reprice_lag_sensitivity(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY: sweep the shock threshold (high-res v2 with --hires)."""
    from .venues.kalshi.reprice_lag import run_sensitivity

    if getattr(args, "hires", False):
        return _run_hires_v2(cfg, args, mode="sensitivity")

    r = run_sensitivity(cfg, series=args.series, date=getattr(args, "date", None),
                        start_date=getattr(args, "start_date", None),
                        end_date=getattr(args, "end_date", None), write_csv=True)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-reprice-lag-sensitivity: series={args.series} ===")
    if r.get("status") != "OK":
        print(f"  status={r.get('status')}"); return 0
    print(f"  {'bps':>5} {'shock_rows':>10} {'dedup':>6} {'windows':>7} {'opps':>5} {'opp_win':>8} {'avg_pnl':>9}")
    for g in r["grid"]:
        print(f"  {g['shock_threshold_bps']:5} {g['raw_shock_rows']:10} {g['dedup_events']:6} "
              f"{g['distinct_windows']:7} {g['qualified_opps']:5} {str(g['opp_win_rate']):>8} "
              f"{str(g['avg_net_pnl']):>9}")
    print(f"  reports: {r['reports']}")
    print("  note: READ-ONLY sensitivity grid; live disabled.")
    return 0


def cmd_kalshi_hires_record(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY high-res measurement (threaded writer): CB/Binance WS + Kalshi active-book REST."""
    from .venues.kalshi.hires import run_hires_record

    r = run_hires_record(
        cfg, series=args.series, seconds=float(args.seconds),
        kalshi_source=getattr(args, "kalshi_source", None),
        kalshi_poll_ms=getattr(args, "kalshi_poll_ms", None),
        coinbase_source=getattr(args, "coinbase_source", None),
        binance_source=getattr(args, "binance_source", None), joined=True,
        raw=(True if getattr(args, "raw", False) else None),
        normalized=(True if getattr(args, "normalized", False) else None),
        max_markets=args.max_markets, output_dir=getattr(args, "output_dir", None),
        writer_mode=getattr(args, "writer_mode", None),
        aggtrade=(True if getattr(args, "aggtrade", False) else None),
        verbose=getattr(args, "verbose", False), dry_run=getattr(args, "dry_run", False))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-hires-record: series={args.series} seconds={args.seconds} ===")
    if r.get("status") == "DRY_RUN":
        print(f"  DRY-RUN planned_sources={r['planned_sources']}  writer_mode={r['writer_mode']}  "
              f"aggtrade={r['aggtrade_enabled']}  blockers={r['blockers']}")
        print("  no network, no files written; live disabled."); return 0
    s = r["summary"]; q = s["queue"]; w = s["writer"]; bs = s["binance_streams"]
    print(f"  active_ticker={s['active_ticker']}  joined_snapshots={s['joined_snapshots']}  counts={s['counts']}")
    print(f"  binance bookTicker/s={bs['binance_book_ticker_msgs_per_sec']} aggTrade/s={bs['binance_agg_trade_msgs_per_sec']} "
          f"(enabled={bs['aggtrade_enabled']})")
    print(f"  queue depth max/warn={q['depth_max']}/{q['warn_size']} warned={q['warned']} "
          f"high_overflow={q['high_priority_overflow']} dropped={q['dropped_by_stream'] or 'none'}")
    print(f"  writer_lag p50/p95/max={w['writer_lag_ms']['p50']}/{w['writer_lag_ms']['p95']}/{w['writer_lag_ms']['max']}ms "
          f"rotate={w['rotate_count']} compress={w['compression_count']} errors={w['writer_errors']}")
    print(f"  kalshi_poll target/actual={s['kalshi_poll_ms']['target']}/{s['kalshi_poll_ms']['actual_median']}ms")
    if r.get("blockers"):
        print(f"  notes: {r['blockers']}")
    print(f"  reports: {r.get('reports')}")
    print("  note: READ-ONLY measurement; no orders; no paper/live; live_submission_allowed=false.")
    return 0


def cmd_kalshi_hires_record_loop(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY bounded repeated record sessions (graceful Ctrl+C)."""
    from .venues.kalshi.hires import run_hires_record_loop

    r = run_hires_record_loop(
        cfg, series=args.series, session_seconds=float(getattr(args, "session_seconds", 900.0)),
        max_sessions=int(getattr(args, "max_sessions", 0) or 0),
        kalshi_source=getattr(args, "kalshi_source", None),
        kalshi_poll_ms=getattr(args, "kalshi_poll_ms", None),
        aggtrade=(True if getattr(args, "aggtrade", False) else None))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-hires-record-loop: series={args.series} sessions_run={r['sessions_run']} ===")
    for sess in r["sessions"]:
        print(f"  session {sess['session']}: active={sess['active_ticker']} joined={sess['joined']} "
              f"queue_depth_max={sess['queue_depth_max']} dropped={sess['dropped'] or 'none'}")
    print("  note: READ-ONLY; no orders; live disabled. Ctrl+C stops gracefully after the session.")
    return 0


def cmd_kalshi_hires_compact(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY-ish: gzip CLOSED hires segments + optional retention. Skips active files."""
    from .venues.kalshi.hires import run_hires_compact

    r = run_hires_compact(cfg, write=bool(getattr(args, "write", False)),
                          enforce_retention=bool(getattr(args, "retention", False)))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-hires-compact ({'WRITE' if r['write'] else 'DRY-RUN'}) ===")
    for kind, c in r["compress"].items():
        print(f"  compress {kind}: files={c['files_planned']} done={c['files_compressed']} "
              f"bytes_before={c['bytes_before']:,} after/est={c['bytes_after_or_estimate']:,}")
    for kind, rt in r["retention"].items():
        print(f"  retention {kind}: days={rt['retention_days']} over_age={rt['files_over_age']} "
              f"deleted={rt['files_deleted']} freed={rt['bytes_freed']:,}")
    print(f"  totals: before={r['bytes_before']:,} after/est={r['bytes_after']:,} freed={r['bytes_freed']:,}")
    print(f"  report: {r.get('report_md')}")
    print("  note: never touches files modified within the active-grace window; "
          "retention deletes only with --write --retention; live disabled.")
    return 0


def cmd_kalshi_hires_smoke(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY short high-res smoke; reports rates, queue/writer health, and v2 usability."""
    from .venues.kalshi.hires import run_hires_smoke

    r = run_hires_smoke(cfg, series=args.series, seconds=float(args.seconds))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-hires-smoke: series={args.series} seconds={args.seconds} ===")
    sm = r["smoke"]
    print(f"  rows_per_source={sm['rows_per_source']}  joined_snapshots={sm['joined_snapshots']}  "
          f"active_ticker={sm['active_ticker']}")
    print(f"  source_age(joined) coinbase/binance={sm['source_age']['coinbase']}/{sm['source_age']['binance']}ms")
    print(f"  binance bookTicker/s={sm['binance_book_ticker_msgs_per_sec']} "
          f"aggTrade/s={sm['binance_agg_trade_msgs_per_sec']} (enabled={sm['aggtrade_enabled']})")
    print(f"  aggtrade_load_manageable={sm['aggtrade_load_manageable']}  "
          f"queue_below_warning={sm['queue_below_warning']}  "
          f"high_priority_rows_dropped={sm['high_priority_rows_dropped']}")
    print(f"  joined_one_to_one_with_kalshi={sm['joined_one_to_one_with_kalshi']}  "
          f"usable_for_reprice_lag_v2={sm['joined_usable_for_reprice_lag_v2']}")
    if r.get("blockers"):
        print(f"  notes: {r['blockers']}")
    print(f"  reports: {r.get('reports')}")
    print("  note: READ-ONLY smoke; no orders; live disabled.")
    return 0


def cmd_kalshi_hires_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY: file freshness/sizes/rates, last-session writer health, and v2 readiness."""
    from .venues.kalshi.hires import run_hires_status

    r = run_hires_status(cfg, series=args.series)
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-hires-status: series={args.series} ===")
    for key, d in r["files"].items():
        if not d.get("present"):
            print(f"  {key}: (no files yet)")
        else:
            print(f"  {key}: segs={d['segments']} size={d['total_bytes']:,}B age_ms={d['age_ms']} "
                  f"msgs/s={d['msgs_per_sec']}" + (f" active={d['active_ticker']}" if d.get("active_ticker") else ""))
    se = r.get("session") or {}
    if se:
        print(f"  last session: queue_depth_max={se.get('queue_depth_max')} "
              f"dropped={se.get('dropped_by_stream') or 'none'} writer_errors={se.get('writer_errors')} "
              f"compress={se.get('compression_count')}")
    v2 = r["reprice_lag_v2"]
    print(f"  reprice_lag_v2_ready: {r['reprice_lag_v2_ready']}  "
          f"(joined_rows={v2['joined_rows']} windows={v2['distinct_windows']} "
          f"subsec_frac={v2['subsecond_return_fraction']})")
    if v2.get("reason"):
        print(f"    reason: {v2['reason']}")
    print("  note: READ-ONLY; no orders; live_submission_allowed=false.")
    return 0


def cmd_kalshi_ws_feasibility(cfg: AppConfig, args: argparse.Namespace) -> int:
    """READ-ONLY Kalshi market-data WS feasibility probe. No orders. No secrets printed."""
    from .venues.kalshi.hires.kalshi_ws import run_ws_feasibility, READ_ONLY_BANNER

    print(READ_ONLY_BANNER)
    r = run_ws_feasibility(cfg, series=args.series, seconds=float(getattr(args, "seconds", 30) or 30))
    if getattr(args, "json", False):
        print(json.dumps(r, indent=2, default=str)); return 0
    print(f"=== kalshi-ws-feasibility: series={args.series} ===")
    print(f"  dependencies={r['dependencies']}")
    ws_api = r.get("websockets_connect") or {}
    if ws_api:
        print(f"  websockets={ws_api.get('version')} header_arg={ws_api.get('header_arg')}")
    print(f"  credentials (presence only)={r['credentials']}")
    print(f"  active_ticker={r.get('active_ticker')}  ws_url={r.get('ws_url')}")
    print(f"  STATUS: {r.get('status')}")
    print(f"  blocker: {r.get('blocker', 'none')}")
    if "connected" in r or "subscribed" in r:
        print(f"  connected={r.get('connected')} subscribed={r.get('subscribed')}")
    if r.get("exception_type") or r.get("exception_message"):
        print(f"  exception_type={r.get('exception_type')} exception_message={r.get('exception_message')}")
    if "book_messages" in r:
        print(f"  book_messages={r['book_messages']} updates/s={r.get('book_updates_per_sec')} "
              f"median_interarrival_ms={r.get('median_interarrival_ms')} "
              f"subsecond_available={r.get('subsecond_book_updates_available')}")
        print(f"  recv_age_ms={r.get('recv_age_ms')}")
    if str(r.get("status", "")).startswith("BLOCKED"):
        print(f"  required env vars (NAMES only): {r['required_env_vars']}")
    print(f"  report: {r.get('report_md')}")
    print(f"  {READ_ONLY_BANNER}")
    return 0


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
_COMMANDS = {
    "init": cmd_init,
    "status": cmd_status,
    "smoke": cmd_smoke,
    "check-live-disabled": cmd_check_live_disabled,
    "notify-test": cmd_notify_test,
    "notification-health": cmd_notification_health,
    "kalshi-notification-health": cmd_notification_health,
    # ----- Kalshi BTC 15m (PRIMARY venue) -----
    "kalshi-discover": cmd_kalshi_discover,
    "kalshi-nearest-markets": cmd_kalshi_nearest_markets,
    "kalshi-collector-targets": cmd_kalshi_collector_targets,
    "kalshi-inspect": cmd_kalshi_inspect,
    "kalshi-record": cmd_kalshi_record,
    "kalshi-collect-continuous": cmd_kalshi_collect_continuous,
    "kalshi-backfill-settlements": cmd_kalshi_backfill_settlements,
    "kalshi-label-audit": cmd_kalshi_label_audit,
    "kalshi-clean-orphan-labels": cmd_kalshi_clean_orphan_labels,
    "kalshi-train-dry-run": cmd_kalshi_train_dry_run,
    "kalshi-data-readiness": cmd_kalshi_data_readiness,
    "kalshi-hotpath-smoke": cmd_kalshi_hotpath_smoke,
    "kalshi-latency-benchmark": cmd_kalshi_latency_benchmark,
    "kalshi-build-model-dataset": cmd_kalshi_build_model_dataset,
    "kalshi-split-report": cmd_kalshi_split_report,
    "kalshi-train-baselines": cmd_kalshi_train_baselines,
    "kalshi-train-model": cmd_kalshi_train_model,
    "kalshi-calibration-report": cmd_kalshi_calibration_report,
    "kalshi-calibrate-model": cmd_kalshi_calibrate_model,
    "kalshi-backtest-baselines": cmd_kalshi_backtest_baselines,
    "kalshi-backtest-model": cmd_kalshi_backtest_model,
    "kalshi-threshold-sweep": cmd_kalshi_threshold_sweep,
    "kalshi-policy-dry-run": cmd_kalshi_policy_dry_run,
    "kalshi-policy-report": cmd_kalshi_policy_report,
    "kalshi-paper-policy-sim": cmd_kalshi_paper_policy_sim,
    # ----- paper-only promotion + shadow/paper runtime (NEVER live) -----
    "kalshi-paper-promotion-review": cmd_kalshi_paper_promotion_review,
    "kalshi-promote-paper-artifacts": cmd_kalshi_promote_paper_artifacts,
    "kalshi-demote-paper-artifacts": cmd_kalshi_demote_paper_artifacts,
    "kalshi-paper-runtime-status": cmd_kalshi_paper_runtime_status,
    "kalshi-shadow-run": cmd_kalshi_shadow_run,
    # ----- controlled paper experiment (shadow first; NEVER live) -----
    "kalshi-paper-experiment-preflight": cmd_kalshi_paper_experiment_preflight,
    "kalshi-paper-experiment-start": cmd_kalshi_paper_experiment_start,
    "kalshi-paper-experiment-status": cmd_kalshi_paper_experiment_status,
    "kalshi-paper-experiment-stop": cmd_kalshi_paper_experiment_stop,
    "kalshi-paper-experiment-report": cmd_kalshi_paper_experiment_report,
    "kalshi-lock-dry-run": cmd_kalshi_lock_dry_run,
    "kalshi-lock-sim": cmd_kalshi_lock_sim,
    "kalshi-live-blockers": cmd_kalshi_live_blockers,
    "kalshi-live-readiness": cmd_kalshi_live_readiness,
    "kalshi-live-dry-run-order": cmd_kalshi_live_dry_run_order,
    "kalshi-private-read-preflight": cmd_kalshi_private_read_preflight,
    # ----- ops / monitoring (read-only) -----
    "kalshi-ops-status": cmd_kalshi_ops_status,
    "kalshi-collector-status": cmd_kalshi_collector_status,
    "kalshi-gate-progress": cmd_kalshi_gate_progress,
    "kalshi-model-health": cmd_kalshi_model_health,
    "kalshi-backtest-summary": cmd_kalshi_backtest_summary,
    "kalshi-paper-summary": cmd_kalshi_paper_summary,
    "kalshi-lock-summary": cmd_kalshi_lock_summary,
    "kalshi-position-monitor-dry-run": cmd_kalshi_position_monitor_dry_run,
    "kalshi-position-monitor-sim": cmd_kalshi_position_monitor_sim,
    "kalshi-position-summary": cmd_kalshi_position_summary,
    "kalshi-frequency-sweep": cmd_kalshi_frequency_sweep,
    "kalshi-frequency-report": cmd_kalshi_frequency_report,
    "kalshi-marginal-trade-curve": cmd_kalshi_marginal_trade_curve,
    "kalshi-time-to-close-analysis": cmd_kalshi_time_to_close_analysis,
    "kalshi-within-window-frequency": cmd_kalshi_within_window_frequency,
    "kalshi-edge-policy-report": cmd_kalshi_edge_policy_report,
    "kalshi-edge-threshold-sweep": cmd_kalshi_edge_threshold_sweep,
    "kalshi-uncertainty-audit": cmd_kalshi_uncertainty_audit,
    "kalshi-maker-entry-study": cmd_kalshi_maker_entry_study,
    "kalshi-backfill-trades": cmd_kalshi_backfill_trades,
    "kalshi-calibration-compare": cmd_kalshi_calibration_compare,
    "kalshi-probability-repair": cmd_kalshi_probability_repair,
    "kalshi-market-shrink-sweep": cmd_kalshi_market_shrink_sweep,
    "kalshi-candidate-repair-audit": cmd_kalshi_candidate_repair_audit,
    # ----- repricing-lag / stale-quote structural event study (READ-ONLY) -----
    "kalshi-shock-scan": cmd_kalshi_shock_scan,
    "kalshi-reprice-lag-study": cmd_kalshi_reprice_lag_study,
    "kalshi-reprice-lag-report": cmd_kalshi_reprice_lag_report,
    "kalshi-reprice-lag-sensitivity": cmd_kalshi_reprice_lag_sensitivity,
    # ----- high-res measurement layer (READ-ONLY; no orders) -----
    "kalshi-hires-record": cmd_kalshi_hires_record,
    "kalshi-hires-record-loop": cmd_kalshi_hires_record_loop,
    "kalshi-hires-smoke": cmd_kalshi_hires_smoke,
    "kalshi-hires-status": cmd_kalshi_hires_status,
    "kalshi-hires-compact": cmd_kalshi_hires_compact,
    "kalshi-ws-feasibility": cmd_kalshi_ws_feasibility,
    "kalshi-shadow-compare-probability-repairs": cmd_kalshi_shadow_compare_probability_repairs,
    # alias: calibrator-focused name for the same staged shadow comparison (reuses the engine)
    "kalshi-shadow-compare-calibrators": cmd_kalshi_shadow_compare_probability_repairs,
    "kalshi-calibrator-replacement-review": cmd_kalshi_calibrator_replacement_review,
    "kalshi-candidate-replacement-impact": cmd_kalshi_candidate_replacement_impact,
    "kalshi-stage-calibrator-replacements": cmd_kalshi_stage_calibrator_replacements,
    "kalshi-paper-calibrator-swap-review": cmd_kalshi_paper_calibrator_swap_review,
    "kalshi-paper-calibrator-swap": cmd_kalshi_paper_calibrator_swap,
    "kalshi-paper-calibrator-swap-rollback": cmd_kalshi_paper_calibrator_swap_rollback,
    "kalshi-build-residual-dataset": cmd_kalshi_build_residual_dataset,
    "kalshi-train-residual-models": cmd_kalshi_train_residual_models,
    "kalshi-residual-model-report": cmd_kalshi_residual_model_report,
    "kalshi-residual-replay": cmd_kalshi_residual_replay,
    "kalshi-shadow-compare-residual-models": cmd_kalshi_shadow_compare_residual_models,
    "kalshi-safety-status": cmd_kalshi_safety_status,
    "kalshi-doctor": cmd_kalshi_doctor,
    "kalshi-eod-summary": cmd_kalshi_eod_summary,
    "kalshi-notify-test": cmd_kalshi_notify_test,
    "dependency-check": cmd_dependency_check,
    "source-health": cmd_source_health,
    "kalshi-source-freshness-smoke": cmd_kalshi_source_freshness_smoke,
    "record-deribit": cmd_record_deribit,
    "kalshi-auth-smoke": cmd_kalshi_auth_smoke,
    "run-kalshi-paper-pipeline": cmd_run_kalshi_paper_pipeline,
    # shared BTC underlying recorder (Coinbase/Binance REST; venue-agnostic)
    "record-underlying": cmd_record_underlying,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="btc5m",
        description="BTC binary-options research CLI. PRIMARY venue: Kalshi BTC 15m "
                    "(KXBTC15M); Polymarket BTC 5m is dormant/reference. Record-only / "
                    "paper-first; live trading disabled by default.")
    parser.add_argument("command", choices=sorted(_COMMANDS), help="command to run")
    parser.add_argument("--mode", default=None, help="config mode overlay (e.g. paper)")
    parser.add_argument("--asset", default="BTC", help="asset symbol (default BTC)")
    parser.add_argument("--duration", default="5m", help="contract duration (default 5m)")
    parser.add_argument("--seconds", type=float, default=None,
                        help="duration in seconds; if omitted, record*/run-paper default to 60 "
                             "and collect-continuous runs until stopped (Ctrl-C)")
    parser.add_argument("--interval", type=float, default=2.0, help="poll interval seconds")
    parser.add_argument("--max-markets", type=int, default=3, dest="max_markets",
                        help="max markets to show/record; 0 = no limit (all discovered)")
    parser.add_argument("--live-only", action="store_true", dest="live_only",
                        help="record: only windows that are live or starting soon (usable data)")
    parser.add_argument("--lead-seconds", type=int, default=30, dest="lead_seconds",
                        help="record --live-only: also include windows starting within N seconds")
    parser.add_argument("--sources", default="coinbase,binance",
                        help="record-underlying sources (comma-separated: coinbase,binance)")
    parser.add_argument("--line-source", default="coinbase", dest="line_source",
                        help="BTC feed for provisional line capture (coinbase|binance)")
    parser.add_argument("--no-line-capture", action="store_true", dest="no_line_capture",
                        help="disable provisional line capture during record")
    parser.add_argument("--no-network", action="store_true", dest="no_network",
                        help="backfill without network (recorded data only)")
    parser.add_argument("--allow-uncalibrated", action="store_true", dest="allow_uncalibrated",
                        help="decide: allow PAPER_CANDIDATE from the uncalibrated baseline (demo)")
    parser.add_argument("--sigma", type=float, default=None,
                        help="decide: override per-sqrt-second volatility estimate")
    parser.add_argument("--size", type=float, default=10.0,
                        help="paper: requested contracts per simulated order")
    # Manual override + discovery diagnostics + continuous collection.
    parser.add_argument("--slug", default=None,
                        help="inspect/record-market: explicit market slug (btc-updown-5m-<ts>)")
    parser.add_argument("--url", default=None,
                        help="inspect/record-market: a Polymarket market/event URL")
    parser.add_argument("--lookback-minutes", type=int, default=30, dest="lookback_minutes",
                        help="debug-discovery: minutes before now to enumerate slugs")
    parser.add_argument("--lookahead-hours", type=float, default=2.0, dest="lookahead_hours",
                        help="debug-discovery: hours after now to enumerate slugs")
    parser.add_argument("--show-raw", action="store_true", dest="show_raw",
                        help="debug-discovery: print a raw market sample")
    parser.add_argument("--rediscover-seconds", type=float, default=30.0, dest="rediscover_seconds",
                        help="collect-continuous: re-run discovery every N seconds")
    parser.add_argument("--process-seconds", type=float, default=60.0, dest="process_seconds",
                        help="collect-continuous: backfill+features+readiness every N seconds")
    parser.add_argument("--max-cycles", type=int, default=0, dest="max_cycles",
                        help="collect-continuous: stop after N loop cycles (0 = unbounded)")
    # Kalshi (primary venue)
    parser.add_argument("--series", default="KXBTC15M",
                        help="Kalshi series ticker (default KXBTC15M)")
    parser.add_argument("--ticker", default=None,
                        help="kalshi-record/inspect: explicit Kalshi market ticker override")
    parser.add_argument("--status", default="open",
                        help="kalshi-discover status filter: open|unopened|closed|settled|all")
    parser.add_argument("--lookahead-minutes", type=int, default=60, dest="lookahead_minutes",
                        help="kalshi-discover: minutes ahead to include upcoming windows")
    # kalshi-collect-continuous
    parser.add_argument("--seconds-per-cycle", type=float, default=900.0, dest="seconds_per_cycle",
                        help="kalshi-collect-continuous: record seconds before each rediscovery")
    parser.add_argument("--readiness-every", type=int, default=1, dest="readiness_every",
                        help="kalshi-collect-continuous: run readiness every N cycles")
    parser.add_argument("--backfill-every", type=int, default=1, dest="backfill_every",
                        help="kalshi-collect-continuous: backfill settlements every N cycles")
    # kalshi-clean-orphan-labels
    parser.add_argument("--write", action="store_true", dest="write",
                        help="kalshi-clean-orphan-labels: write a compacted file (default dry-run)")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="kalshi-clean-orphan-labels: explicit dry-run (default; no writes)")
    # record-deribit
    parser.add_argument("--currency", default="BTC",
                        help="record-deribit: currency (default BTC)")
    # kalshi-train-dry-run
    parser.add_argument("--embargo-windows", type=int, default=1, dest="embargo_windows",
                        help="kalshi-train-dry-run: embargo N 15m windows around the test fold")
    # kalshi-latency-benchmark
    parser.add_argument("--samples", type=int, default=1000,
                        help="kalshi-latency-benchmark: number of synthetic hot-path iterations")
    # model dataset / training pipeline
    parser.add_argument("--output", default=None, help="kalshi-build-model-dataset: output file path")
    parser.add_argument("--max-scenarios", type=int, default=None, dest="max_scenarios",
                        help="kalshi-frequency-sweep/report: cap the scenario grid size")
    parser.add_argument("--format", default="jsonl", choices=["jsonl", "csv", "parquet"],
                        help="kalshi-build-model-dataset: output format (parquet falls back to jsonl if deps absent)")
    parser.add_argument("--min-windows", type=int, default=150, dest="min_windows",
                        help="kalshi-build-model-dataset: training-ready threshold (distinct windows)")
    parser.add_argument("--diagnostic-ok", action="store_true", dest="diagnostic_ok",
                        help="kalshi-build-model-dataset: silence NOT_TRAINING_READY note")
    parser.add_argument("--include-deribit", default="auto", dest="include_deribit",
                        help="model dataset: include Deribit columns (true|false|auto)")
    parser.add_argument("--feature-version", default="all", dest="feature_version",
                        help="model dataset: feature_set_version filter (all|latest); old v2/v3 rows coexist")
    parser.add_argument("--strict", action="store_true", dest="strict",
                        help="model dataset: drop rows failing source-health (both underlying feeds stale)")
    # Artifact/dataset STAGING safety (PART L). --staged routes new artifacts/datasets to
    # data/models/staged/ (invisible to runtime auto-selection). Dataset latest pointers are
    # left UNCHANGED unless --update-latest is passed. Training/calibration always stage.
    parser.add_argument("--staged", action="store_true", dest="staged",
                        help="write/use STAGED (non-promoted) artifacts/datasets in data/models/staged/")
    parser.add_argument("--reason", default="", dest="reason",
                        help="kalshi-promote-paper-artifacts / experiment-stop: human reason for the audit log")
    parser.add_argument("--paper-policy-enabled", action="store_true", dest="paper_policy_enabled",
                        help="kalshi-collect-continuous: also evaluate the PROMOTED paper manifest per cycle "
                             "(shadow/paper per KALSHI_MODEL_RUNTIME_MODE); never submits orders")
    # ----- paper experiment -----
    parser.add_argument("--experiment-mode", default="shadow", dest="experiment_mode",
                        choices=["disabled", "shadow", "paper"],
                        help="kalshi-paper-experiment-start: shadow (score+log, no fills) | paper (gated fills). NEVER live.")
    parser.add_argument("--minutes", type=float, default=None, dest="minutes",
                        help="kalshi-paper-experiment-start: run a LIVE LOOP for ~N minutes, re-sampling "
                             "the latest feature rows every --poll-interval s (feature-row age enforced). "
                             "Omit (or --max-iterations 1) for a single batch pass over stored rows.")
    parser.add_argument("--name", default="", dest="name",
                        help="kalshi-paper-experiment-start: optional experiment name")
    parser.add_argument("--max-iterations", type=int, default=None, dest="max_iterations",
                        help="kalshi-paper-experiment-start: cap loop iterations (default: 1 single pass when no --minutes; unbounded within --minutes)")
    parser.add_argument("--poll-interval", type=float, default=5.0, dest="poll_interval",
                        help="kalshi-paper-experiment-start --minutes: seconds between fresh-row re-samples (default 5)")
    parser.add_argument("--skip-shadow-warning", action="store_true", dest="skip_shadow_warning",
                        help="kalshi-paper-experiment-start --experiment-mode paper: allow paper without a prior shadow run (still NEVER live)")
    parser.add_argument("--runtime-mode", default=None, dest="runtime_mode",
                        choices=["disabled", "shadow", "paper"],
                        help="kalshi-collect-continuous: set the in-process model runtime mode for this run (never live)")
    parser.add_argument("--update-latest", action="store_true", dest="update_latest",
                        help="model dataset: also overwrite kalshi_model_dataset_latest.* / kalshi_feature_schema.json (off by default)")
    parser.add_argument("--diagnostic-only", action="store_true", dest="diagnostic_only",
                        help="kalshi-train-baselines/model: fit NON-TRADABLE toy models below the gate")
    parser.add_argument("--model", default="logistic",
                        help="kalshi-train-model: logistic | lightgbm; backtest/sweep: 'latest' or artifact path")
    # calibration + executable backtest
    parser.add_argument("--method", default="isotonic",
                        help="kalshi-calibrate-model/calibration-report: isotonic | platt | identity")
    parser.add_argument("--calibrator", default="latest",
                        help="kalshi-backtest-model/threshold-sweep/policy: 'latest' | path | 'none'")
    # paper-candidate policy
    parser.add_argument("--limit", type=int, default=None,
                        help="policy commands: number of recent rows to evaluate")
    parser.add_argument("--include-rejected", action="store_true", dest="include_rejected",
                        help="kalshi-policy-dry-run: include REJECTED decisions in output")
    parser.add_argument("--policy-format", default="table", dest="policy_format",
                        choices=["table", "json", "jsonl"], help="kalshi-policy-dry-run output format")
    parser.add_argument("--source", default="latest",
                        help="kalshi-policy-dry-run: source-health snapshot selector")
    # post-entry lock-profit module
    parser.add_argument("--lock-mode", default=None, choices=["fok", "ioc"], dest="lock_mode",
                        help="kalshi-lock-dry-run/sim: paper order mode (fok|ioc)")
    parser.add_argument("--allow-partial", action="store_true", dest="allow_partial",
                        help="kalshi-lock-*: allow IOC partial locks (residual naked exposure remains)")
    parser.add_argument("--latest", action="store_true", dest="latest",
                        help="kalshi-lock-dry-run: evaluate against the latest book per position")
    # live-readiness scaffolding (dry-run only; never submits)
    parser.add_argument("--side", default="YES", help="kalshi-live-dry-run-order: YES|NO")
    parser.add_argument("--action", default="buy", help="kalshi-live-dry-run-order: buy|sell")
    parser.add_argument("--qty", type=float, default=None, help="kalshi-live-dry-run-order: contracts")
    parser.add_argument("--price", type=float, default=None,
                        help="kalshi-live-dry-run-order: limit price (cents, e.g. 55, or decimal 0.55)")
    parser.add_argument("--tif", default="fill_or_kill",
                        help="kalshi-live-dry-run-order: fill_or_kill|immediate_or_cancel")
    parser.add_argument("--allow-private-read", action="store_true", dest="allow_private_read",
                        help="kalshi-private-read-preflight: opt-in to read-only private endpoints (still none called)")
    parser.add_argument("--json", action="store_true", dest="json",
                        help="kalshi-live-readiness: emit JSON")
    parser.add_argument("--verbose", action="store_true", dest="verbose",
                        help="kalshi-live-readiness: include required next actions")
    parser.add_argument("--from-policy-latest", action="store_true", dest="from_policy_latest",
                        help="kalshi-live-readiness: build dry-run payload from latest policy paper entry")
    parser.add_argument("--from-lock-latest", action="store_true", dest="from_lock_latest",
                        help="kalshi-live-readiness: build dry-run payload from latest lock fill")
    parser.add_argument("--order-intent", default=None, dest="order_intent",
                        help="kalshi-live-readiness: e.g. latest-paper-candidate")
    # ops / monitoring
    parser.add_argument("--markdown", action="store_true", dest="markdown",
                        help="ops commands: also write a markdown report")
    parser.add_argument("--write-report", action="store_true", dest="write_report",
                        help="ops commands: write JSON (+ markdown) report under reports/")
    parser.add_argument("--stale-threshold-seconds", type=int, default=120, dest="stale_threshold_seconds",
                        help="kalshi-collector-status: per-source stale threshold (seconds)")
    parser.add_argument("--run-tests", action="store_true", dest="run_tests",
                        help="kalshi-doctor: also run pytest (slower)")
    parser.add_argument("--send-notification", action="store_true", dest="send_notification",
                        help="kalshi-eod-summary: send the short EOD notification (Noop unless Pushover)")
    parser.add_argument("--date", default=None, help="kalshi-paper-summary/eod-summary: YYYYMMDD")
    parser.add_argument("--today", action="store_true", dest="today", help="ops: use today's date")
    parser.add_argument("--all", action="store_true", dest="all", help="ops: include all items")
    parser.add_argument("--include-files", action="store_true", dest="include_files",
                        help="kalshi-ops-status: include latest file timestamps")
    parser.add_argument("--include-models", action="store_true", dest="include_models",
                        help="kalshi-ops-status: include model/backtest sections")
    parser.add_argument("--include-paper", action="store_true", dest="include_paper",
                        help="kalshi-ops-status: include paper/lock sections")
    parser.add_argument("--include-live-readiness", action="store_true", dest="include_live_readiness",
                        help="kalshi-ops-status: include live-readiness state")
    # ----- kalshi-uncertainty-audit (READ-ONLY) -----
    parser.add_argument("--ledger", default=None, dest="ledger",
                        help="kalshi-uncertainty-audit: explicit decision ledger path (default: latest)")
    parser.add_argument("--cohort", default="edge_blocked", dest="cohort",
                        choices=["edge_blocked", "all"],
                        help="kalshi-uncertainty-audit: which ledger rows to audit (default edge_blocked)")
    parser.add_argument("--csv", action="store_true", dest="csv",
                        help="kalshi-uncertainty-audit: (always-on) write CSV breakdowns under reports/edge/")
    parser.add_argument("--top-n", type=int, default=20, dest="top_n",
                        help="kalshi-uncertainty-audit: number of near-pass rows to report (default 20)")
    parser.add_argument("--latest-shadow", action="store_true", dest="latest_shadow",
                        help="kalshi-residual-replay: replay the latest shadow ledger (default)")
    parser.add_argument("--candidate", default=None, dest="candidate",
                        choices=["identity_raw", "platt", "fresh_isotonic"],
                        help="kalshi-paper-calibrator-swap: which staged calibrator to swap in")
    # ----- kalshi-maker-entry-study (READ-ONLY) -----
    parser.add_argument("--improve-cents", type=int, default=1, dest="improve_cents",
                        help="kalshi-maker-entry-study: cents above best bid for 'improve' mode (default 1)")
    parser.add_argument("--maker-fee-rate", type=float, default=0.0, dest="maker_fee_rate",
                        help="kalshi-maker-entry-study: maker fee rate (default 0.0 = ASSUMED zero maker fee)")
    parser.add_argument("--rest-horizons", default=None, dest="rest_horizons",
                        help="kalshi-maker-entry-study: comma list of rest seconds + 'close' (default 60,180,300,close)")
    parser.add_argument("--fill-model", default="quote", dest="fill_model",
                        choices=["quote", "prints-through", "prints-front"],
                        help="kalshi-maker-entry-study: quote-crossing (v1 lower bound) or REAL "
                             "trade prints (certain trade-through / optimistic front-of-queue)")
    parser.add_argument("--chunk-hours", type=int, default=1, dest="chunk_hours",
                        help="kalshi-backfill-trades: tape chunk size in hours (default 1)")
    # ----- kalshi-reprice-lag-* / shock-scan (READ-ONLY event study) -----
    parser.add_argument("--start-date", default=None, dest="start_date",
                        help="reprice-lag: start day YYYYMMDD (inclusive)")
    parser.add_argument("--end-date", default=None, dest="end_date",
                        help="reprice-lag: end day YYYYMMDD (inclusive)")
    parser.add_argument("--shock-threshold-bps", type=float, default=None, dest="shock_threshold_bps",
                        help="reprice-lag: 5s shock threshold in bps (scales 15/30/60s)")
    parser.add_argument("--horizon-seconds", default=None, dest="horizon_seconds",
                        help="reprice-lag: response horizons CSV (informational; recorded cadence ~4s)")
    parser.add_argument("--min-depth", type=float, default=None, dest="min_depth",
                        help="reprice-lag: min executable ask size (contracts) for an opportunity")
    parser.add_argument("--min-seconds-to-close", type=float, default=None, dest="min_seconds_to_close",
                        help="reprice-lag: minimum seconds-to-close (avoid settlement race)")
    parser.add_argument("--max-seconds-to-close", type=float, default=None, dest="max_seconds_to_close",
                        help="reprice-lag: maximum seconds-to-close filter")
    parser.add_argument("--include-polymarket", action="store_true", dest="include_polymarket",
                        help="reprice-lag: classify Polymarket 5m comparability (reference only)")
    parser.add_argument("--hires", action="store_true", dest="hires",
                        help="reprice-lag study/report/sensitivity: use HIGH-RES v2 (joined snapshots); "
                             "blocks clearly if insufficient — never falls back to low-res v1")
    parser.add_argument("--horizon-ms", type=int, default=None, dest="horizon_ms",
                        help="reprice-lag v2: optional single response-horizon focus (ms)")
    parser.add_argument("--min-net-edge-cents", type=float, default=None, dest="min_net_edge_cents",
                        help="reprice-lag v2: min fee+buffer-adjusted net proxy edge for a candidate (cents)")
    parser.add_argument("--near-line-only", action="store_true", dest="near_line_only",
                        help="reprice-lag v2: only shocks near the reference/start line")
    parser.add_argument("--max-source-age-ms", type=float, default=None, dest="max_source_age_ms",
                        help="reprice-lag v2: max Coinbase/Binance source age (ms) for a candidate")
    parser.add_argument("--dedupe-seconds", type=float, default=None, dest="dedupe_seconds",
                        help="reprice-lag v2: dedup cluster window seconds (default 20)")
    # ----- kalshi-hires-* (READ-ONLY high-res measurement layer) -----
    parser.add_argument("--kalshi-source", default=None, dest="kalshi_source",
                        choices=["rest", "websocket", "auto"],
                        help="kalshi-hires-record: active-book source (rest|websocket|auto; WS needs auth)")
    parser.add_argument("--kalshi-poll-ms", type=int, default=None, dest="kalshi_poll_ms",
                        help="kalshi-hires-record: Kalshi REST poll interval ms (>= configured minimum)")
    parser.add_argument("--coinbase-source", default=None, dest="coinbase_source",
                        choices=["websocket", "rest", "off"],
                        help="kalshi-hires-record: Coinbase source (websocket|rest|off)")
    parser.add_argument("--binance-source", default=None, dest="binance_source",
                        choices=["websocket", "rest", "off"],
                        help="kalshi-hires-record: Binance source (websocket|rest|off)")
    parser.add_argument("--joined", action="store_true", dest="joined",
                        help="kalshi-hires-record: emit joined high-res snapshots (on by default)")
    parser.add_argument("--raw", action="store_true", dest="raw",
                        help="kalshi-hires-record: force-record raw payloads (on by default)")
    parser.add_argument("--normalized", action="store_true", dest="normalized",
                        help="kalshi-hires-record: force-record normalized rows (on by default)")
    parser.add_argument("--output-dir", default=None, dest="output_dir",
                        help="kalshi-hires-record: override base data dir for hires/ files")
    parser.add_argument("--writer-mode", default=None, dest="writer_mode",
                        choices=["threaded", "sync"],
                        help="kalshi-hires-record: writer mode (threaded default | sync)")
    parser.add_argument("--aggtrade", action="store_true", dest="aggtrade",
                        help="kalshi-hires-record: enable heavy Binance aggTrade stream (off by default)")
    parser.add_argument("--session-seconds", type=float, default=900.0, dest="session_seconds",
                        help="kalshi-hires-record-loop: seconds per bounded session (default 900)")
    parser.add_argument("--max-sessions", type=int, default=0, dest="max_sessions",
                        help="kalshi-hires-record-loop: stop after N sessions (0 = until Ctrl+C)")
    parser.add_argument("--retention", action="store_true", dest="retention",
                        help="kalshi-hires-compact: also enforce age-based retention (requires --write)")
    args = parser.parse_args(argv)

    # Per-command default for the shared --seconds flag: collect-continuous runs
    # unbounded (until Ctrl-C) when no duration is given; others default to 60s.
    if args.seconds is None:
        args.seconds = 0.0 if args.command == "collect-continuous" else 60.0

    cfg = load_config(mode=args.mode)
    return _COMMANDS[args.command](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
