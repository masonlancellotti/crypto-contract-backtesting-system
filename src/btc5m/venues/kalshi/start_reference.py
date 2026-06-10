"""KXBTC15M start-reference capture with explicit provenance.

Kalshi KXBTC15M resolves YES when the closing BRTI reference is at least the
opening BRTI reference. Historically the market metadata exposed that opening
reference as ``yes_sub_title = "Target Price: $..."``. Current active payloads
can instead say ``Target price: TBD`` while the market is already tradeable, so
feature rows need a conservative fallback from already-recorded underlying data.

This module never uses settlement data and never looks past the feature row's
``as_of_ms``. Feed-derived references are marked provisional because Coinbase /
Binance are proxies for CF Benchmarks BRTI, not settlement-grade truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .client import iso_to_ms
from .settlement import parse_target_price

PENDING = "START_REFERENCE_PENDING"
NO_WINDOW_START = "START_REFERENCE_NO_WINDOW_START"
NO_UNDERLYING = "NO_UNDERLYING_NEAR_WINDOW_START"
UNKNOWN = "START_REFERENCE_UNKNOWN"

_AVG_WINDOW_MS = 60_000
_NEAREST_TOLERANCE_MS = 60_000
_MIN_AVG_SAMPLES = 3


def _f(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class StartReference:
    price: Optional[float]
    source: Optional[str]
    ts_ms: Optional[int]
    method: Optional[str]
    confidence: Optional[float]
    source_status: Optional[str] = None
    missing_reason: Optional[str] = None
    detail: Optional[str] = None
    sample_count: Optional[int] = None
    window_offset_ms: Optional[int] = None

    def feature_fields(self, as_of_ms: int) -> dict:
        age = (int(as_of_ms) - int(self.ts_ms)) if self.ts_ms is not None else None
        return {
            "reference_start_price_source": self.source,
            "reference_start_price_ts_ms": self.ts_ms,
            "reference_start_price_age_ms": age,
            "reference_start_price_method": self.method,
            "reference_start_price_confidence": self.confidence,
            "reference_start_price_source_status": self.source_status,
            "reference_missing_reason": self.missing_reason if self.price is None else None,
            "reference_start_price_detail": self.detail,
            "reference_start_price_sample_count": self.sample_count,
            "reference_start_price_window_offset_ms": self.window_offset_ms,
        }


def explicit_start_reference(market: dict, *, as_of_ms: int) -> Optional[StartReference]:
    """Return an explicit Kalshi line/target/strike when the payload clearly has one."""
    for field in ("yes_sub_title", "no_sub_title"):
        raw = market.get(field)
        if not raw:
            continue
        text = str(raw).lower()
        if "target" not in text and "strike" not in text and "reference" not in text:
            continue
        price = parse_target_price(str(raw))
        if price is not None:
            return StartReference(
                price=price,
                source=f"kalshi:{field}",
                ts_ms=_window_start_ms(market) or int(as_of_ms),
                method="kalshi_metadata_target_price",
                confidence=1.0,
                source_status="EXPLICIT",
                detail=f"parsed explicit start reference from {field}",
                window_offset_ms=0,
            )

    for field in (
        "target_price",
        "target_price_dollars",
        "strike_price",
        "strike_price_dollars",
        "line_price",
        "start_price",
        "reference_start_price",
    ):
        if field not in market:
            continue
        price = _f(market.get(field))
        if price is not None and price > 0:
            return StartReference(
                price=price,
                source=f"kalshi:{field}",
                ts_ms=_window_start_ms(market) or int(as_of_ms),
                method="kalshi_metadata_numeric_field",
                confidence=1.0,
                source_status="EXPLICIT",
                detail=f"read explicit start reference from {field}",
                window_offset_ms=0,
            )
    return None


class StartReferenceResolver:
    """Capture and reuse one start reference per ticker/window."""

    def __init__(
        self,
        *,
        avg_window_ms: int = _AVG_WINDOW_MS,
        nearest_tolerance_ms: int = _NEAREST_TOLERANCE_MS,
        min_avg_samples: int = _MIN_AVG_SAMPLES,
    ) -> None:
        self.avg_window_ms = int(avg_window_ms)
        self.nearest_tolerance_ms = int(nearest_tolerance_ms)
        self.min_avg_samples = int(min_avg_samples)
        self._cache: dict[str, StartReference] = {}

    def resolve(self, market: dict, *, as_of_ms: int, micro_state: Any) -> StartReference:
        key = _cache_key(market)
        explicit = explicit_start_reference(market, as_of_ms=as_of_ms)
        if explicit is not None:
            if key:
                self._cache[key] = explicit
            return explicit

        if key and key in self._cache:
            return self._cache[key]

        window_start_ms = _window_start_ms(market)
        if window_start_ms is None:
            return _missing(NO_WINDOW_START, "market has no open_time/window_start_ms")
        if int(as_of_ms) < int(window_start_ms):
            return _missing(PENDING, "window has not opened yet")

        ref = self._from_underlying(micro_state, window_start_ms=window_start_ms, as_of_ms=as_of_ms)
        if ref.price is not None and key:
            self._cache[key] = ref
        return ref

    def _from_underlying(self, micro_state: Any, *, window_start_ms: int, as_of_ms: int) -> StartReference:
        for source, label in _source_buffers(micro_state):
            samples = _samples(label, window_start_ms - self.avg_window_ms, window_start_ms, as_of_ms)
            if len(samples) >= self.min_avg_samples:
                price = sum(p for _t, p in samples) / len(samples)
                return StartReference(
                    price=price,
                    source=source,
                    ts_ms=window_start_ms,
                    method="underlying_preopen_60s_average_proxy",
                    confidence=_avg_confidence(source, len(samples)),
                    source_status="PROVISIONAL_REFERENCE",
                    detail=(
                        f"average of {len(samples)} recorded {source} samples in "
                        f"[window_start-60s, window_start]; proxy for BRTI"
                    ),
                    sample_count=len(samples),
                    window_offset_ms=0,
                )

        nearest = None
        nearest_source = None
        for source, label in _source_buffers(micro_state):
            cand = _nearest_sample(label, window_start_ms, as_of_ms, self.nearest_tolerance_ms)
            if cand is None:
                continue
            t, p = cand
            score = abs(t - window_start_ms) + (0 if source.startswith("coinbase") else 10_000)
            if nearest is None or score < nearest[0]:
                nearest = (score, t, p)
                nearest_source = source
        if nearest is not None and nearest_source is not None:
            _score, ts, price = nearest
            offset = int(ts) - int(window_start_ms)
            return StartReference(
                price=price,
                source=nearest_source,
                ts_ms=int(ts),
                method="underlying_nearest_window_start_proxy",
                confidence=_nearest_confidence(nearest_source, abs(offset), self.nearest_tolerance_ms),
                source_status="PROVISIONAL_REFERENCE",
                detail=(
                    f"nearest recorded {nearest_source} sample to window_start "
                    f"(offset_ms={offset}); proxy for BRTI"
                ),
                sample_count=1,
                window_offset_ms=offset,
            )
        if int(as_of_ms) - int(window_start_ms) <= self.nearest_tolerance_ms:
            return _missing(
                PENDING,
                "window is open but no start-reference underlying sample has been recorded yet",
            )
        return _missing(
            NO_UNDERLYING,
            f"no recorded underlying sample within {self.nearest_tolerance_ms}ms of window_start",
        )


def _window_start_ms(market: dict) -> Optional[int]:
    raw = market.get("window_start_ms") or market.get("_open_ms")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return iso_to_ms(market.get("open_time"))


def _cache_key(market: dict) -> Optional[str]:
    tk = market.get("ticker") or market.get("market_ticker")
    if tk:
        return str(tk)
    ev = market.get("event_ticker")
    ws = _window_start_ms(market)
    return f"{ev}@{ws}" if ev and ws is not None else None


def _source_buffers(micro_state: Any) -> list[tuple[str, list[tuple[int, float]]]]:
    return [
        ("coinbase:BTC-USD", list(getattr(micro_state, "spot_mid", []) or [])),
        ("binance_futures:BTCUSDT", list(getattr(micro_state, "perp_mid", []) or [])),
    ]


def _samples(buf: list[tuple[int, float]], lo_ms: int, hi_ms: int, as_of_ms: int) -> list[tuple[int, float]]:
    return [(int(t), float(p)) for t, p in buf if lo_ms <= int(t) <= hi_ms and int(t) <= int(as_of_ms)]


def _nearest_sample(
    buf: list[tuple[int, float]],
    window_start_ms: int,
    as_of_ms: int,
    tolerance_ms: int,
) -> Optional[tuple[int, float]]:
    best: Optional[tuple[int, int, float]] = None
    for t_raw, p_raw in buf:
        t = int(t_raw)
        if t > int(as_of_ms):
            continue
        dist = abs(t - int(window_start_ms))
        if dist > int(tolerance_ms):
            continue
        # Prefer before/equal on exact ties; it cannot include post-open movement.
        after_penalty = 1 if t > int(window_start_ms) else 0
        score = dist * 2 + after_penalty
        if best is None or score < best[0]:
            best = (score, t, float(p_raw))
    return (best[1], best[2]) if best is not None else None


def _avg_confidence(source: str, n: int) -> float:
    base = 0.78 if source.startswith("coinbase") else 0.68
    bonus = min(0.07, max(0, n - _MIN_AVG_SAMPLES) * 0.005)
    return round(min(0.9, base + bonus), 3)


def _nearest_confidence(source: str, distance_ms: int, tolerance_ms: int) -> float:
    source_base = 0.62 if source.startswith("coinbase") else 0.52
    closeness = max(0.0, 1.0 - (float(distance_ms) / max(1.0, float(tolerance_ms))))
    return round(max(0.25, min(0.75, source_base * (0.55 + 0.45 * closeness))), 3)


def _missing(reason: str, detail: str) -> StartReference:
    return StartReference(
        price=None,
        source=None,
        ts_ms=None,
        method=None,
        confidence=None,
        source_status="UNKNOWN",
        missing_reason=reason or UNKNOWN,
        detail=detail,
    )


__all__ = [
    "NO_UNDERLYING",
    "NO_WINDOW_START",
    "PENDING",
    "StartReference",
    "StartReferenceResolver",
    "explicit_start_reference",
]
