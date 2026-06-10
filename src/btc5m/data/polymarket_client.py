"""Polymarket discovery + CLOB book client.

Uses PUBLIC endpoints over the standard library (``urllib``) so discovery and
book reads work with no third-party deps and no credentials:

- Gamma markets API  (metadata/discovery): https://gamma-api.polymarket.com
- CLOB API           (order books):        https://clob.polymarket.com

BTC 5-minute markets are the "Bitcoin Up or Down" series with slugs like
``btc-updown-5m-<unix_ts>``. They settle via the Chainlink BTC/USD data stream:
"resolve to 'Up' if the end price is GREATER THAN OR EQUAL TO the start price"
(:class:`~btc5m.schemas.Comparison.GTE`; the line is the window-start price,
known only once the window opens). Settlement is taken from the explicit
description wording — NEVER from title similarity.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from ..config import AppConfig
from ..discovery import (
    duration_to_seconds,
    enumerate_slugs,
    slug_prefix as _disc_slug_prefix,
    slug_window_start_ms,
)
from ..schemas import Comparison, ContractMeta, MarketType, Outcome
from ..timeutils import now_ms
from .book_builder import BookBuilder

_log = logging.getLogger("btc5m.polymarket")

DEFAULT_GAMMA_URL = "https://gamma-api.polymarket.com"
DEFAULT_CLOB_URL = "https://clob.polymarket.com"
_USER_AGENT = "btc5m/0.1 (+research; read-only public endpoints)"


def _http_get_json(url: str, *, timeout: float = 20.0) -> Any:
    """GET a URL and parse JSON using only the standard library."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_server_date(url: str, *, timeout: float = 10.0) -> Optional[str]:
    """Return the HTTP ``Date`` header for ``url`` (server clock), or None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.headers.get("Date")
    except Exception:  # noqa: BLE001 - diagnostics only
        return None


def _iso_to_ms(value: Optional[str]) -> Optional[int]:
    """Parse an ISO-8601 timestamp (with trailing 'Z') to epoch ms."""
    if not value:
        return None
    try:
        s = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _loads_maybe(value: Any) -> Any:
    """Gamma encodes some arrays as JSON strings; decode if needed."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _comparison_from_description(description: str, default: Comparison) -> Comparison:
    """Derive the settlement comparison from EXPLICIT description wording.

    Reads the settlement rule text (not the title). Falls back to ``default``
    only when wording is absent.
    """
    text = (description or "").lower()
    if "greater than or equal" in text or "at or above" in text or ">=" in text:
        return Comparison.GTE
    if "greater than" in text or "above" in text:
        return Comparison.GT
    return default


def _slug_prefix(asset: str, duration: str) -> str:
    """Slug prefix for the Up/Down series, e.g. BTC + 5m -> 'btc-updown-5m-'."""
    return f"{asset.strip().lower()}-updown-{duration.strip().lower()}-"


class PolymarketClient:
    """Read-only Polymarket discovery + CLOB book client (public endpoints)."""

    def __init__(self, config: AppConfig):
        self.config = config
        src = config.sources.get("polymarket", {}) if config.sources else {}
        self.gamma_url = src.get("gamma_url") or DEFAULT_GAMMA_URL
        self.clob_url = src.get("rest_base_url") or DEFAULT_CLOB_URL

    # ----- Discovery --------------------------------------------------------
    def discover_markets(
        self,
        *,
        asset: str = "BTC",
        duration: str = "5m",
        lookback_minutes: int = 30,
        lookahead_minutes: int = 120,
        ref_ms: Optional[int] = None,
        include_far_future: bool = False,
        limit: int = 500,
    ) -> list[ContractMeta]:
        """Discover currently-relevant Up/Down markets for ``asset``/``duration``.

        PRIMARY strategy: enumerate the deterministic 5-minute slug grid around
        ``now`` and batch-fetch those slugs. The slug timestamp is the window
        START (verified live), so this reliably surfaces the current + upcoming
        windows regardless of API sort order or the ~24h listing lead time — the
        failure mode of the old ``order=startDate`` query, which only ever saw
        the far-future batch (see :mod:`btc5m.discovery`).

        Returns non-closed markets sorted by expiry (soonest first). Set
        ``include_far_future`` to also union the legacy newest-created query so
        the pre-listed ~24h-ahead batch is included (slug enumeration already
        covers the near term).
        """
        now = ref_ms if ref_ms is not None else now_ms()
        by_slug: dict[str, ContractMeta] = {}
        for meta in self.discover_via_slugs(
            asset=asset, duration=duration,
            lookback_minutes=lookback_minutes, lookahead_minutes=lookahead_minutes,
            ref_ms=now,
        ):
            if meta.slug:
                by_slug[meta.slug] = meta

        if include_far_future:
            for meta in self._discover_far_future_via_queries(
                asset=asset, duration=duration, limit=limit
            ):
                if meta.slug:
                    by_slug.setdefault(meta.slug, meta)

        out = [
            m for m in by_slug.values()
            if (m.status or "").lower() not in ("closed", "resolved")
        ]
        out.sort(key=lambda c: c.expiry_ms)
        return out

    def discover_via_slugs(
        self,
        *,
        asset: str = "BTC",
        duration: str = "5m",
        lookback_minutes: int = 30,
        lookahead_minutes: int = 120,
        ref_ms: Optional[int] = None,
        include_closed: bool = False,
    ) -> list[ContractMeta]:
        """Discover markets by enumerating + batch-fetching the slug grid.

        Clock-driven and order-independent: cannot miss the live window. Returns
        parsed :class:`ContractMeta` for every slug that resolved to a real
        Up/Down market (sorted by expiry).
        """
        now = ref_ms if ref_ms is not None else now_ms()
        prefix = _slug_prefix(asset, duration)
        slugs = enumerate_slugs(
            asset, duration, now,
            lookback_s=max(0, lookback_minutes) * 60,
            lookahead_s=max(0, lookahead_minutes) * 60,
        )
        raws = self.get_markets_by_slugs(slugs, include_closed=include_closed)
        out: list[ContractMeta] = []
        for m in raws:
            slug = m.get("slug", "") or ""
            if not slug.startswith(prefix):
                continue
            meta = self._parse_market(m, asset=asset)
            if meta is not None:
                out.append(meta)
        out.sort(key=lambda c: c.expiry_ms or 0)
        return out

    def get_markets_by_slugs(
        self, slugs: list[str], *, include_closed: bool = False, chunk_size: int = 20
    ) -> list[dict]:
        """Batch-fetch raw Gamma market dicts for many slugs (deduped by slug).

        Gamma accepts repeated ``slug=`` params in one request (verified), so
        this is far cheaper than one request per slug. The default query omits
        closed markets; with ``include_closed`` a second ``closed=true`` request
        per chunk unions in resolved windows (needed for labeling).
        """
        out: list[dict] = []
        seen: set[str] = set()
        for i in range(0, len(slugs), max(1, chunk_size)):
            batch = slugs[i:i + chunk_size]
            queries = [[("slug", s) for s in batch]]
            if include_closed:
                queries.append([("slug", s) for s in batch] + [("closed", "true")])
            for params in queries:
                try:
                    data = _http_get_json(f"{self.gamma_url}/markets?{urllib.parse.urlencode(params)}")
                except Exception:  # noqa: BLE001 - tolerate a chunk failing; keep going
                    continue
                if isinstance(data, list):
                    for m in data:
                        slug = m.get("slug")
                        if slug and slug not in seen:
                            seen.add(slug)
                            out.append(m)
        return out

    def _discover_far_future_via_queries(
        self, *, asset: str = "BTC", duration: str = "5m", limit: int = 500
    ) -> list[ContractMeta]:
        """Legacy newest-created query — only useful to surface the pre-listed
        far-future batch. Kept as a SUPPLEMENT (never the primary path) because
        it systematically misses the live window."""
        prefix = _slug_prefix(asset, duration)
        out: list[ContractMeta] = []
        try:
            data = _http_get_json(
                f"{self.gamma_url}/markets?closed=false&limit={limit}"
                "&order=startDate&ascending=false"
            )
        except Exception:  # noqa: BLE001
            return out
        if isinstance(data, list):
            for m in data:
                slug = m.get("slug", "") or ""
                if slug.startswith(prefix) and not m.get("closed"):
                    meta = self._parse_market(m, asset=asset)
                    if meta is not None:
                        out.append(meta)
        return out

    @staticmethod
    def is_window_live(meta: ContractMeta, *, ref_ms: Optional[int] = None) -> bool:
        """True if the contract's 5-minute window is currently open."""
        now = ref_ms if ref_ms is not None else now_ms()
        return bool(
            meta.window_start_ms is not None
            and meta.expiry_ms
            and meta.window_start_ms <= now <= meta.expiry_ms
        )

    def get_market_by_slug(self, slug: str) -> Optional[ContractMeta]:
        """Fetch a single market's metadata by slug."""
        url = f"{self.gamma_url}/markets?{urllib.parse.urlencode({'slug': slug})}"
        raw = _http_get_json(url)
        if isinstance(raw, list) and raw:
            return self._parse_market(raw[0])
        return None

    def server_date_header(self) -> Optional[str]:
        """The Gamma server's HTTP ``Date`` header (for clock-skew diagnostics)."""
        return _http_server_date(f"{self.gamma_url}/markets?limit=1")

    def get_market_raw_by_slug(self, slug: str, *, include_closed: bool = True) -> Optional[dict]:
        """Fetch one raw Gamma market dict by slug (open or, optionally, closed)."""
        rows = self.get_markets_by_slugs([slug], include_closed=include_closed)
        return rows[0] if rows else None

    def get_resolved_market_raw(self, slug: str) -> Optional[dict]:
        """Fetch the RAW market dict for a (possibly closed) market by slug.

        Resolved/closed markets are not returned by the default query, so this
        explicitly requests ``closed=true``. Returns the raw Gamma dict (with
        ``outcomePrices`` once resolved) or None.
        """
        url = f"{self.gamma_url}/markets?{urllib.parse.urlencode({'slug': slug, 'closed': 'true'})}"
        raw = _http_get_json(url)
        if isinstance(raw, list) and raw:
            return raw[0]
        return None

    def _parse_market(self, m: dict, *, asset: str = "") -> Optional[ContractMeta]:
        """Map a Gamma market dict into a typed :class:`ContractMeta`."""
        outcomes = _loads_maybe(m.get("outcomes")) or []
        token_ids = _loads_maybe(m.get("clobTokenIds")) or []
        yes_token = no_token = None
        yes_label, no_label = "YES", "NO"
        if isinstance(outcomes, list) and isinstance(token_ids, list) and len(token_ids) >= 2:
            yes_token, no_token = str(token_ids[0]), str(token_ids[1])
            if len(outcomes) >= 2:
                yes_label, no_label = str(outcomes[0]), str(outcomes[1])

        slug = m.get("slug")
        is_up_down = bool(slug and "-updown-" in slug)
        market_type = MarketType.UP_DOWN if is_up_down else MarketType.UNKNOWN
        default_cmp = Comparison.GTE if is_up_down else Comparison.GT
        comparison = _comparison_from_description(m.get("description", ""), default_cmp)

        status = "active"
        if m.get("closed"):
            status = "closed"
        if m.get("archived"):
            status = "resolved"

        # Timing: prefer the explicit Gamma fields, but fall back to the slug
        # timestamp (= window start in seconds, verified) so timing is robust
        # even if eventStartTime/endDate are absent. For 5m the expiry is
        # window_start + the duration step.
        slug_start_ms = slug_window_start_ms(slug) if slug else None
        window_start_ms = _iso_to_ms(m.get("eventStartTime")) or slug_start_ms
        expiry_ms = _iso_to_ms(m.get("endDate")) or 0
        if expiry_ms == 0 and slug_start_ms is not None:
            parsed = slug.split("-updown-", 1)[1] if slug and "-updown-" in slug else ""
            dur_token = parsed.rsplit("-", 1)[0] if "-" in parsed else ""
            try:
                expiry_ms = slug_start_ms + duration_to_seconds(dur_token) * 1000
            except (ValueError, IndexError):
                expiry_ms = 0

        return ContractMeta(
            contract_id=str(m.get("conditionId") or m.get("id") or slug or ""),
            title=str(m.get("question", "")),
            asset=asset or "BTC",
            # UP_DOWN line is the window-start price, unknown until the window
            # opens; above-strike strikes are not exposed here. Left None until
            # a concrete reference price is recorded.
            line=None,
            expiry_ms=expiry_ms,
            resolution_source=m.get("resolutionSource"),
            yes_token_id=yes_token,
            no_token_id=no_token,
            market_id=str(m.get("id")) if m.get("id") is not None else None,
            condition_id=m.get("conditionId"),
            slug=slug,
            market_type=market_type,
            comparison=comparison,
            yes_outcome_label=yes_label,
            no_outcome_label=no_label,
            window_start_ms=window_start_ms,
            status=status,
            tick_size=_safe_float(m.get("orderPriceMinTickSize")),
            min_order_size=_safe_float(m.get("orderMinSize")),
            raw=m,
        )

    # ----- Order books ------------------------------------------------------
    def get_raw_book(self, token_id: str) -> dict:
        """Fetch the raw CLOB order book payload for a token id (public).

        A resolved/expired market's book is removed from the CLOB and returns
        404; that is a legitimately EMPTY book (not an error), so we return an
        empty payload rather than raising. Other HTTP/network errors propagate
        so callers can report a precise blocker.
        """
        url = f"{self.clob_url}/book?{urllib.parse.urlencode({'token_id': token_id})}"
        try:
            return _http_get_json(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"bids": [], "asks": [], "timestamp": None}
            raise

    def get_book(self, contract_id: str, outcome: Outcome, token_id: str):
        """Fetch and normalize a CLOB book into an :class:`OrderBook`.

        Preserves the source timestamp (book ``timestamp``) and a local receive
        timestamp so downstream staleness/quote-age gates have real values.
        """
        recv = now_ms()
        payload = self.get_raw_book(token_id)
        bids = [
            (float(lvl["price"]), float(lvl["size"]))
            for lvl in payload.get("bids", [])
            if lvl.get("size") and float(lvl["size"]) > 0
        ]
        asks = [
            (float(lvl["price"]), float(lvl["size"]))
            for lvl in payload.get("asks", [])
            if lvl.get("size") and float(lvl["size"]) > 0
        ]
        ts = payload.get("timestamp")
        ts_ms = int(ts) if ts is not None else recv
        builder = BookBuilder()
        return builder.apply_snapshot(
            contract_id, outcome, bids, asks, ts_ms=ts_ms, recv_ms=recv
        )


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def select_live_or_imminent(
    metas: list[ContractMeta], *, lead_seconds: int = 30, ref_ms: Optional[int] = None
) -> list[ContractMeta]:
    """Keep only windows that are live now or open within ``lead_seconds``.

    Focuses recording on windows that will actually yield a captured line +
    settlement label, instead of pre-window markets (which become ``no_line``
    rows). Already-expired markets are dropped. Sorted by expiry (soonest first).
    """
    now = ref_ms if ref_ms is not None else now_ms()
    lead = lead_seconds * 1000
    out = [
        m
        for m in metas
        if m.window_start_ms is not None
        and m.expiry_ms
        and m.expiry_ms > now             # not expired
        and m.window_start_ms <= now + lead  # live or imminent
    ]
    out.sort(key=lambda c: c.expiry_ms)
    return out
