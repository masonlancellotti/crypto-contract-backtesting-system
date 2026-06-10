"""In-memory hot-path state for Kalshi low-latency decisioning.

Holds bounded, incrementally-updated state for one or more active markets and the
shared BTC underlying / Deribit context, then assembles a point-in-time feature
snapshot on demand. It COMPOSES the existing fast primitives — the local book
(:mod:`.local_book`), the underlying microstructure buffers (:mod:`.features`),
the Deribit cache (:mod:`.deribit_features`), and :func:`build_feature_row` — so
the hot path produces the SAME v3 schema as the recorder without any rewrite.

HARD RULE: no file reads, no pandas, no per-tick model loading, no full-history
recompute. Updates are O(1)/O(window) on bounded deques.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Optional

from .deribit_features import DeribitState, deribit_feature_fields
from .features import UnderlyingMicrostructureState
from .local_book import KalshiLocalBook
from .paper import build_feature_row
from .start_reference import StartReferenceResolver

_SPOT_SOURCES = {"coinbase", "coinbase_spot", "cb"}
_PERP_SOURCES = {"binance_futures", "binance", "binance_perp"}


def _num(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


class HotPathState:
    """Mutable in-memory state shared across the scoring loop."""

    def __init__(
        self,
        config: Any,
        *,
        fee_model: Any,
        deribit_enabled: bool = False,
        max_book_age_ms: int = 1000,
        max_underlying_age_ms: int = 2000,
        max_deribit_age_ms: int = 180_000,
        spot_sample_cap: int = 4000,
    ) -> None:
        self.config = config
        self.fee_model = fee_model
        self.deribit_enabled = deribit_enabled
        self.max_book_age_ms = max_book_age_ms
        self.max_underlying_age_ms = max_underlying_age_ms
        self.max_deribit_age_ms = max_deribit_age_ms

        self.micro = UnderlyingMicrostructureState()
        self.deribit = DeribitState()
        self.books: dict[str, KalshiLocalBook] = {}
        self.meta: dict[str, dict] = {}
        self.start_refs = StartReferenceResolver()
        self.spot_samples: deque[tuple[int, float]] = deque(maxlen=spot_sample_cap)
        self.last_spot_price: Optional[float] = None
        self.last_spot_ms: Optional[int] = None
        self.last_perp_ms: Optional[int] = None

    # ----- market registration ------------------------------------------- #
    def set_market(self, meta: dict) -> None:
        tk = meta.get("ticker")
        if not tk:
            return
        from .client import iso_to_ms  # local import avoids import cycle at module load
        close_ms = iso_to_ms(meta.get("close_time")) if meta.get("close_time") else meta.get("close_ms")
        window_start_ms = iso_to_ms(meta.get("open_time")) if meta.get("open_time") else meta.get("window_start_ms")
        self.meta[tk] = {
            "close_ms": close_ms, "window_start_ms": window_start_ms,
            "status": meta.get("status"), "event_ticker": meta.get("event_ticker"),
            "ticker": tk,
            "yes_sub_title": meta.get("yes_sub_title"),
            "no_sub_title": meta.get("no_sub_title"),
            "open_time": meta.get("open_time"),
            "close_time": meta.get("close_time"),
            "rules_primary": meta.get("rules_primary"),
        }
        if tk not in self.books:
            self.books[tk] = KalshiLocalBook(
                ticker=tk, series_ticker=(tk.split("-")[0] if tk else None),
                event_ticker=meta.get("event_ticker"), status=meta.get("status"),
                window_start_ms=window_start_ms, close_ms=close_ms,
                max_book_age_ms=self.max_book_age_ms,
                fee_status=getattr(self.fee_model, "status", "ASSUMED"),
            )

    # ----- ingestion ------------------------------------------------------ #
    def ingest_underlying(self, ev: dict) -> None:
        self.micro.ingest(ev)
        src = (ev.get("source") or "").lower()
        ts = ev.get("recv_ms") or ev.get("exchange_ts_ms")
        if ts is None:
            return
        ts = int(ts)
        if src in _SPOT_SOURCES:
            bid, ask = _num(ev.get("best_bid")), _num(ev.get("best_ask"))
            mid = ((bid + ask) / 2.0) if (bid is not None and ask is not None) else _num(ev.get("price"))
            if mid is not None:
                self.spot_samples.append((ts, mid))
                self.last_spot_price = mid
            self.last_spot_ms = max(self.last_spot_ms or 0, ts)
        elif src in _PERP_SOURCES:
            self.last_perp_ms = max(self.last_perp_ms or 0, ts)

    def ingest_deribit(self, norm: dict) -> None:
        self.deribit.ingest(norm)

    def update_book(self, ticker: str, raw: dict, *, recv_ms: int,
                    source_ts_ms: Optional[int] = None) -> Optional[dict]:
        book = self.books.get(ticker)
        if book is None:
            return None
        return book.apply_snapshot(raw, recv_ms=recv_ms, source_ts_ms=source_ts_ms)

    # ----- reads ---------------------------------------------------------- #
    def sigma(self) -> Optional[float]:
        return UnderlyingMicrostructureState._sigma_per_sqrt_s(list(self.spot_samples))

    def last_underlying_ms(self) -> Optional[int]:
        vals = [t for t in (self.last_spot_ms, self.last_perp_ms) if t is not None]
        return max(vals) if vals else None

    def underlying_age_ms(self, as_of_ms: int) -> Optional[int]:
        last = self.last_underlying_ms()
        return (as_of_ms - last) if last is not None else None

    def feature_snapshot(self, ticker: str, as_of_ms: int) -> Optional[dict]:
        """Assemble the point-in-time v3 feature row for ``ticker`` (no look-ahead)."""
        book = self.books.get(ticker)
        meta = self.meta.get(ticker)
        if book is None or meta is None or book.normalized() is None:
            return None
        und_extra = self.micro.features(
            as_of_ms=as_of_ms, window_start_ms=meta.get("window_start_ms"))
        deribit_extra = deribit_feature_fields(
            snapshot=self.deribit.latest_at_or_before(as_of_ms), as_of_ms=as_of_ms,
            enabled=self.deribit_enabled, stale_threshold_ms=self.max_deribit_age_ms,
            realized_vol_60s=und_extra.get("realized_vol_60s"),
            realized_vol_180s=und_extra.get("realized_vol_180s"))
        start_ref = self.start_refs.resolve(meta, as_of_ms=as_of_ms, micro_state=self.micro)
        row = build_feature_row(
            book.normalized(), as_of_ms=as_of_ms, reference_price=self.last_spot_price,
            sigma_per_sqrt_s=self.sigma(), start_reference=start_ref.price,
            fee_model=self.fee_model, underlying_extra=und_extra, deribit_extra=deribit_extra,
            start_reference_provenance=start_ref.feature_fields(as_of_ms))
        # Attach explicit hot-path staleness (time since WE received the data) for
        # the gates/decision event — distinct from the row's source->receive
        # quote_age_ms / book_age_ms (which measure source latency).
        row["hotpath_book_age_ms"] = book.book_age_ms(as_of_ms)
        row["hotpath_book_stale"] = book.is_stale(as_of_ms)
        row["hotpath_underlying_age_ms"] = self.underlying_age_ms(as_of_ms)
        return row
