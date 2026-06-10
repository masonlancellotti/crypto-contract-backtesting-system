"""Kalshi orderbook decision-freshness provenance.

``quote_age_ms`` is exchange/source timestamp latency when Kalshi provides a
source timestamp. REST snapshots often have no source timestamp, so the decision
freshness age must fall back to the local receive timestamp carried with the
snapshot. This module keeps that fallback explicit and prevents a missing
exchange timestamp from being treated as an automatically stale fresh REST book.
"""

from __future__ import annotations

from typing import Optional


def _int_or_none(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def effective_book_age(snapshot: dict, *, as_of_ms: Optional[int] = None) -> dict:
    """Return the decision book age plus provenance for a normalized/feature row.

    Preference order:
    1. ``quote_age_ms`` when it exists, because it was computed from a source
       timestamp on ingest.
    2. Precomputed ``book_age_ms`` from a feature row when present.
    3. ``as_of_ms - source_ts_ms`` when a source timestamp exists but the latency
       field is absent.
    4. ``as_of_ms - recv_ms`` for REST snapshots that only have local receive time.

    The function never uses future data: a timestamp after ``as_of_ms`` is
    reported as missing/stale rather than clamped to a fresh value.
    """
    ref = _int_or_none(as_of_ms)
    if ref is None:
        ref = _int_or_none(snapshot.get("as_of_ms"))
    if ref is None:
        ref = _int_or_none(snapshot.get("as_of_ts_ms"))

    recv = _int_or_none(snapshot.get("recv_ms"))
    if recv is None:
        recv = _int_or_none(snapshot.get("book_recv_ms"))
    source_ts = _int_or_none(snapshot.get("source_ts_ms"))
    if source_ts is None:
        source_ts = _int_or_none(snapshot.get("book_source_ts_ms"))
    quote_age = _int_or_none(snapshot.get("quote_age_ms"))
    existing_book_age = _int_or_none(snapshot.get("book_age_ms"))

    base = {
        "book_recv_ms": recv,
        "book_source_ts_ms": source_ts,
    }

    if quote_age is not None:
        return {
            **base,
            "book_age_ms": max(0, quote_age),
            "book_age_basis": "quote_age_ms",
            "book_age_method": "SOURCE_TS_TO_RECV_MS",
            "book_age_source": "kalshi_source_timestamp",
            "book_age_confidence": "exchange_source_ts",
        }

    if existing_book_age is not None:
        return {
            **base,
            "book_age_ms": max(0, existing_book_age),
            "book_age_basis": snapshot.get("book_age_basis") or "book_age_ms",
            "book_age_method": snapshot.get("book_age_method") or "PRECOMPUTED_BOOK_AGE_MS",
            "book_age_source": snapshot.get("book_age_source"),
            "book_age_confidence": snapshot.get("book_age_confidence") or "precomputed",
        }

    if ref is not None and source_ts is not None:
        if source_ts > ref:
            return {
                **base,
                "book_age_ms": None,
                "book_age_basis": "source_ts_ms_after_as_of",
                "book_age_method": "MISSING_FUTURE_SOURCE_TS",
                "book_age_source": "kalshi_source_timestamp",
                "book_age_confidence": "missing",
            }
        return {
            **base,
            "book_age_ms": ref - source_ts,
            "book_age_basis": "source_ts_ms",
            "book_age_method": "AS_OF_MINUS_SOURCE_TS_MS",
            "book_age_source": "kalshi_source_timestamp",
            "book_age_confidence": "exchange_source_ts",
        }

    if ref is not None and recv is not None:
        if recv > ref:
            return {
                **base,
                "book_age_ms": None,
                "book_age_basis": "recv_ms_after_as_of",
                "book_age_method": "MISSING_FUTURE_RECV_MS",
                "book_age_source": "kalshi_rest_recv_ms",
                "book_age_confidence": "missing",
            }
        return {
            **base,
            "book_age_ms": ref - recv,
            "book_age_basis": "recv_ms",
            "book_age_method": "AS_OF_MINUS_RECV_MS",
            "book_age_source": "kalshi_rest_recv_ms",
            "book_age_confidence": "local_receive_time",
        }

    return {
        **base,
        "book_age_ms": None,
        "book_age_basis": "missing",
        "book_age_method": "MISSING_BOOK_TIMESTAMP",
        "book_age_source": None,
        "book_age_confidence": "missing",
    }
