"""Kalshi public market-data REST client + discovery (stdlib only).

Public endpoints require NO credentials (verified live). Authenticated routes are
not used here. Base URL comes from config/env (default
``https://external-api.kalshi.com/trade-api/v2``). Raw responses are preserved by
the caller; this module only fetches + classifies.

Endpoints used (all GET, public):
    /exchange/status
    /series/{series_ticker}
    /markets?series_ticker=&status=&limit=&cursor=&min_close_ts=&max_close_ts=
    /markets/{ticker}
    /markets/{ticker}/orderbook
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

_UA = "btc15m-kalshi/0.1 (+research; read-only public endpoints)"


class MarketPhase(str, Enum):
    UPCOMING = "UPCOMING"                       # before open_time
    CURRENT_IN_WINDOW = "CURRENT_IN_WINDOW"     # open_time <= now <= close_time
    CLOSED_PENDING_SETTLE = "CLOSED_PENDING_SETTLE"  # past close, not yet finalized
    SETTLED = "SETTLED"                         # finalized / settled / result present
    UNKNOWN = "UNKNOWN"


def iso_to_ms(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


# Kalshi market-object ``status`` vocabulary (observed on KXBTC15M: 'active' for the
# open/tradeable market, 'initialized' for not-yet-open, 'finalized' for settled; the
# /markets ``status=`` QUERY filter uses open/unopened/closed/settled). These are the
# EXPLICIT tradeability signals — distinct from open/close timing.
_SETTLED_STATUSES = frozenset({"finalized", "settled"})
_CLOSED_STATUSES = frozenset({"closed", "determined"})
_OPEN_STATUSES = frozenset({"active", "open"})
_UPCOMING_STATUSES = frozenset({"initialized", "unopened"})


def classify_market(market: dict, *, now_ms: int) -> MarketPhase:
    """Classify a Kalshi market by its EXPLICIT status first, then open/close timing.

    Kalshi reports the genuinely open/tradeable market with ``status='active'`` (and serves
    it under the ``status=open`` query) — often from the instant it activates, which can be
    at or marginally before its ``open_time``. The previous timing-only rule (strict
    ``open_time <= now <= close_time``) therefore demoted a market Kalshi is ACTIVELY TRADING
    to UPCOMING at the window boundary, yielding ``cur=0`` despite a live market. So we trust
    the explicit status: an active/open market that has not passed its close is CURRENT; an
    initialized/unopened market is UPCOMING even if its ``open_time`` has technically passed
    (Kalshi has not activated it, so it is not tradeable). Timing is the fallback only when the
    status is missing/unknown. This is a discovery/classification fix only — no trading gate is
    affected (the policy/freshness/edge/risk gates are unchanged)."""
    status = (market.get("status") or "").strip().lower()
    result = (market.get("result") or "").strip().lower()
    open_ms = iso_to_ms(market.get("open_time"))
    close_ms = iso_to_ms(market.get("close_time"))
    # ----- terminal states win -----
    if status in _SETTLED_STATUSES or result in ("yes", "no"):
        return MarketPhase.SETTLED
    if status in _CLOSED_STATUSES:
        return MarketPhase.CLOSED_PENDING_SETTLE
    # ----- explicit tradeable: Kalshi says this market is open/active right now -----
    if status in _OPEN_STATUSES:
        if close_ms is not None and now_ms > close_ms:
            return MarketPhase.CLOSED_PENDING_SETTLE   # past close -> awaiting settle
        return MarketPhase.CURRENT_IN_WINDOW
    # ----- explicitly created-but-not-open -> upcoming (not tradeable yet) -----
    if status in _UPCOMING_STATUSES:
        return MarketPhase.UPCOMING
    # ----- unknown/missing status -> fall back to open/close timing -----
    if open_ms is None or close_ms is None:
        return MarketPhase.UNKNOWN
    if now_ms < open_ms:
        return MarketPhase.UPCOMING
    if open_ms <= now_ms <= close_ms:
        return MarketPhase.CURRENT_IN_WINDOW
    return MarketPhase.CLOSED_PENDING_SETTLE


def select_collection_targets(discovered: list[dict], *, max_markets: Optional[int] = None) -> dict:
    """Choose which discovered markets the collector should record, PHASE-PRIORITIZED.

    The active ``CURRENT_IN_WINDOW`` market(s) are always selected FIRST, so when discovery
    reports ``cur>=1`` the live market is never displaced by an upcoming or just-closed market —
    in particular with ``--max-markets 1``. (A naive "sort all kept markets by close-time" puts a
    just-closed ``CLOSED_PENDING_SETTLE`` market — whose close is in the PAST, i.e. a smaller
    close_ms — ahead of the active market, so the single slot would collect the wrong ticker at a
    window boundary. This is exactly the 'active ticker never recorded' failure.)

    Order: CURRENT (soonest close first) -> UPCOMING (soonest open first; recorded for pre-window
    data/backfill but never scored — the decision-window gate handles that) -> CLOSED_PENDING_SETTLE
    (most-recent close first; label backfill). SETTLED markets are not collection targets. If no
    phased market exists, fall back to whatever was discovered. Returns a dict with ``targets``
    (the capped, ordered selection) plus the per-phase lists ``current`` / ``upcoming`` / ``closed``
    and the full ``ordered`` list."""
    def _close(m: dict) -> int:
        v = m.get("_close_ms")
        return v if v is not None else 0

    def _open(m: dict) -> int:
        v = m.get("_open_ms")
        return v if v is not None else 0

    current = sorted((m for m in discovered if m.get("_phase") == MarketPhase.CURRENT_IN_WINDOW.value),
                     key=_close)
    upcoming = sorted((m for m in discovered if m.get("_phase") in
                       (MarketPhase.UPCOMING.value, "UPCOMING_PRE_WINDOW")), key=_open)
    closed = sorted((m for m in discovered if m.get("_phase") == MarketPhase.CLOSED_PENDING_SETTLE.value),
                    key=_close, reverse=True)
    ordered = current + upcoming + closed
    pool = ordered or list(discovered)
    targets = pool[: max_markets] if (max_markets and max_markets > 0) else pool
    return {"targets": targets, "current": current, "upcoming": upcoming,
            "closed": closed, "ordered": ordered}


def parse_market_url(url: str) -> Optional[str]:
    """Best-effort: extract a Kalshi market ticker from a URL or bare ticker.

    Kalshi tickers look like ``KXBTC15M-26JUN010345-45``. Returns an
    upper-cased ticker if a ticker-shaped segment is found, else None.
    """
    if not url:
        return None
    s = url.strip()
    tick_re = re.compile(r"^KX[A-Z0-9]+-[A-Z0-9]+(-[A-Z0-9]+)?$", re.IGNORECASE)
    if tick_re.match(s):
        return s.upper()
    s2 = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", s).split("?", 1)[0].split("#", 1)[0]
    for seg in reversed([p for p in s2.split("/") if p]):
        if tick_re.match(seg):
            return seg.upper()
    return None


class KalshiClient:
    """Read-only Kalshi public market-data client."""

    def __init__(self, config):
        self.config = config
        self.base = config.kalshi.api_base.rstrip("/")
        self.series_ticker = config.kalshi.series_ticker

    # ----- low-level ------------------------------------------------------- #
    def _get(self, path: str, params: Optional[dict] = None, *, timeout: float = 20.0) -> Any:
        url = f"{self.base}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            url = f"{url}?{urllib.parse.urlencode(clean)}"
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def server_date_header(self) -> Optional[str]:
        try:
            req = urllib.request.Request(f"{self.base}/exchange/status",
                                         headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.headers.get("Date")
        except Exception:  # noqa: BLE001
            return None

    # ----- endpoints ------------------------------------------------------- #
    def exchange_status(self) -> dict:
        return self._get("/exchange/status")

    def get_series(self, series_ticker: Optional[str] = None) -> dict:
        return self._get(f"/series/{series_ticker or self.series_ticker}")

    def get_market(self, ticker: str) -> Optional[dict]:
        try:
            return self._get(f"/markets/{ticker}").get("market")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def get_orderbook(self, ticker: str, *, depth: Optional[int] = None) -> dict:
        params = {"depth": depth} if depth else None
        try:
            return self._get(f"/markets/{ticker}/orderbook", params)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}
            raise

    def list_markets(
        self,
        *,
        series_ticker: Optional[str] = None,
        status: Optional[str] = None,
        min_close_ts: Optional[int] = None,
        max_close_ts: Optional[int] = None,
        limit: int = 100,
        max_pages: int = 20,
    ) -> list[dict]:
        """List markets for a series with cursor pagination (bounded by max_pages)."""
        out: list[dict] = []
        cursor = None
        for _ in range(max_pages):
            params = {
                "series_ticker": series_ticker or self.series_ticker,
                "status": status,
                "limit": limit,
                "cursor": cursor,
                "min_close_ts": min_close_ts,
                "max_close_ts": max_close_ts,
            }
            data = self._get("/markets", params)
            markets = data.get("markets") or []
            out.extend(markets)
            cursor = data.get("cursor") or None
            if not cursor or not markets:
                break
        return out

    # ----- discovery ------------------------------------------------------- #
    def discover(
        self,
        *,
        series_ticker: Optional[str] = None,
        statuses: tuple[str, ...] = ("open", "unopened"),
        now_ms: Optional[int] = None,
        max_pages: int = 10,
    ) -> list[dict]:
        """Discover markets across the given status filters, deduped by ticker,
        each annotated with a ``_phase`` (MarketPhase) and parsed time fields.
        Sorted by close_time ascending (soonest first)."""
        from ...timeutils import now_ms as _now
        ref = now_ms if now_ms is not None else _now()
        seen: dict[str, dict] = {}
        for st in statuses:
            try:
                for m in self.list_markets(series_ticker=series_ticker, status=st,
                                           max_pages=max_pages):
                    tk = m.get("ticker")
                    if tk and tk not in seen:
                        m["_phase"] = classify_market(m, now_ms=ref).value
                        m["_open_ms"] = iso_to_ms(m.get("open_time"))
                        m["_close_ms"] = iso_to_ms(m.get("close_time"))
                        seen[tk] = m
            except Exception:  # noqa: BLE001 - tolerate one status failing
                continue
        out = list(seen.values())
        out.sort(key=lambda m: m.get("_close_ms") or 0)
        return out
