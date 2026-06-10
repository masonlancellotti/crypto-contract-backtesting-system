"""Point-in-time feature rows for each candidate decision timestamp.

A feature row is keyed by (slug / condition_id / window_start_ms / as_of_ms) and
must only use information available at ``as_of_ms`` — no look-ahead. Each row
carries source + receive timestamps, quote ages, staleness flags, and feed-health
fields so the decision layer can gate on data quality.

This module is deliberately pure/deterministic: callers supply the latest
point-in-time inputs (YES/NO Polymarket book events, the line record, and
per-source :class:`~btc5m.features.window.UnderlyingWindow` objects). The
event-replay assembly lives in the CLI ``build-features`` command.
"""

from __future__ import annotations

from typing import Optional

from .window import UnderlyingWindow

# Default data-quality thresholds (mirrors config risk gates; overridable).
DEFAULT_MAX_QUOTE_AGE_MS = 1500
DEFAULT_THIN_DEPTH = 50.0          # contracts at top of book
DEFAULT_WIDE_SPREAD = 0.03         # probability units


def _depth(levels, n: int = 5) -> float:
    total = 0.0
    for lvl in (levels or [])[:n]:
        try:
            total += float(lvl[1])
        except (TypeError, ValueError, IndexError):
            pass
    return total


def polymarket_book_features(event: Optional[dict], as_of_ms: int, *, prefix: str) -> dict:
    """Features for one outcome's Polymarket book from a normalized event dict."""
    out: dict = {
        f"{prefix}_bid": None, f"{prefix}_ask": None, f"{prefix}_spread": None,
        f"{prefix}_depth_bid": None, f"{prefix}_depth_ask": None,
        f"{prefix}_book_imbalance": None, f"{prefix}_quote_age_ms": None,
        f"{prefix}_is_crossed": None, f"{prefix}_ts_ms": None,
    }
    if not event:
        return out
    bid = event.get("best_bid")
    ask = event.get("best_ask")
    bids = event.get("bids") or []
    asks = event.get("asks") or []
    ts = event.get("ts_ms")
    out[f"{prefix}_bid"] = bid
    out[f"{prefix}_ask"] = ask
    out[f"{prefix}_spread"] = event.get("spread")
    out[f"{prefix}_is_crossed"] = event.get("is_crossed")
    out[f"{prefix}_ts_ms"] = ts
    out[f"{prefix}_depth_bid"] = _depth(bids)
    out[f"{prefix}_depth_ask"] = _depth(asks)
    top_bid_sz = float(bids[0][1]) if bids else 0.0
    top_ask_sz = float(asks[0][1]) if asks else 0.0
    denom = top_bid_sz + top_ask_sz
    out[f"{prefix}_book_imbalance"] = (top_bid_sz - top_ask_sz) / denom if denom > 0 else None
    if ts is not None:
        out[f"{prefix}_quote_age_ms"] = as_of_ms - int(ts)
    return out


def build_feature_row(
    *,
    as_of_ms: int,
    slug: Optional[str],
    condition_id: Optional[str],
    window_start_ms: Optional[int],
    expiry_ms: Optional[int],
    comparison: str,
    yes_event: Optional[dict],
    no_event: Optional[dict],
    line_record: Optional[dict],
    spot_window: Optional[UnderlyingWindow] = None,
    perp_window: Optional[UnderlyingWindow] = None,
    yes_token_id: Optional[str] = None,
    no_token_id: Optional[str] = None,
    max_quote_age_ms: int = DEFAULT_MAX_QUOTE_AGE_MS,
    thin_depth: float = DEFAULT_THIN_DEPTH,
    wide_spread: float = DEFAULT_WIDE_SPREAD,
) -> dict:
    """Assemble a single point-in-time feature row (no look-ahead)."""
    row: dict = {
        "as_of_ms": as_of_ms,
        "slug": slug,
        "condition_id": condition_id,
        "yes_token_id": yes_token_id,
        "no_token_id": no_token_id,
        "window_start_ms": window_start_ms,
        "expiry_ms": expiry_ms,
        "comparison": comparison,
    }

    # ----- time / duration -------------------------------------------------
    secs_to_expiry = (expiry_ms - as_of_ms) / 1000.0 if expiry_ms else None
    row["seconds_to_expiry"] = secs_to_expiry
    row["time_since_market_opened_s"] = (
        (as_of_ms - window_start_ms) / 1000.0 if window_start_ms else None
    )
    row["near_expiry_30s"] = (secs_to_expiry is not None and 0 <= secs_to_expiry <= 30)
    row["is_expired"] = (secs_to_expiry is not None and secs_to_expiry <= 0)

    # ----- line + reference price ------------------------------------------
    line_price = line_record.get("line_price") if line_record else None
    line_status = line_record.get("line_source_status") if line_record else "UNKNOWN"
    row["line_price"] = line_price
    row["line_source_status"] = line_status or "UNKNOWN"

    ref_price = None
    if spot_window is not None:
        ref_price = spot_window.last_price(as_of_ms)
    if ref_price is None and perp_window is not None:
        ref_price = perp_window.last_price(as_of_ms)
    row["reference_price"] = ref_price

    if ref_price is not None and line_price is not None:
        dist = ref_price - line_price
        row["distance_from_line"] = dist
        row["abs_distance_from_line"] = abs(dist)
    else:
        row["distance_from_line"] = None
        row["abs_distance_from_line"] = None

    # ----- Polymarket contract microstructure (YES + NO) -------------------
    row.update(polymarket_book_features(yes_event, as_of_ms, prefix="yes"))
    row.update(polymarket_book_features(no_event, as_of_ms, prefix="no"))

    # Market-implied YES probability from EXECUTABLE prices (never midpoint-only).
    yes_ask, yes_bid = row.get("yes_ask"), row.get("yes_bid")
    no_ask, no_bid = row.get("no_ask"), row.get("no_bid")
    row["mkt_implied_yes_from_ask"] = yes_ask   # cost to BUY YES now
    row["mkt_implied_yes_from_bid"] = yes_bid   # proceeds to SELL YES now
    row["mkt_implied_no_from_ask"] = no_ask
    row["mkt_implied_no_from_bid"] = no_bid
    if yes_bid is not None and yes_ask is not None:
        row["yes_mid_diagnostic"] = (yes_bid + yes_ask) / 2.0
    else:
        row["yes_mid_diagnostic"] = None
    # No-arbitrage sanity (diagnostic): YES ask + NO ask should be >= 1.
    if yes_ask is not None and no_ask is not None:
        row["yes_no_ask_sum"] = yes_ask + no_ask

    # ----- underlying microstructure (spot + perp) -------------------------
    recent_rv = None
    if spot_window is not None:
        sf = spot_window.features(as_of_ms, prefix="spot_")
        row.update(sf)
        recent_rv = sf.get("spot_rv_60s") or sf.get("spot_rv_30s")
    if perp_window is not None:
        pf = perp_window.features(as_of_ms, prefix="perp_")
        row.update(pf)

    # spot-perp basis (diagnostic for futures pressure)
    sp = row.get("spot_last_price")
    pp = row.get("perp_last_price")
    if sp is not None and pp is not None:
        row["spot_perp_basis"] = pp - sp

    # distance normalized by recent volatility (in "sigma" units, diagnostic)
    if row.get("distance_from_line") is not None and recent_rv and ref_price:
        # convert per-tick rv to an absolute price sigma estimate (rough)
        sigma_price = recent_rv * ref_price
        row["distance_normalized_by_recent_volatility"] = (
            row["distance_from_line"] / sigma_price if sigma_price > 0 else None
        )
    else:
        row["distance_normalized_by_recent_volatility"] = None

    # ----- staleness / feed-health flags -----------------------------------
    yes_age = row.get("yes_quote_age_ms")
    no_age = row.get("no_quote_age_ms")
    row["stale_yes_quote"] = (yes_age is not None and yes_age > max_quote_age_ms)
    row["stale_no_quote"] = (no_age is not None and no_age > max_quote_age_ms)
    row["missing_yes_book"] = yes_event is None
    row["missing_no_book"] = no_event is None
    row["thin_yes_book"] = (
        row.get("yes_depth_ask") is not None and row["yes_depth_ask"] < thin_depth
    )
    row["wide_yes_spread"] = (
        row.get("yes_spread") is not None and row["yes_spread"] > wide_spread
    )
    row["crossed_yes_book"] = bool(row.get("yes_is_crossed"))
    row["line_known"] = line_price is not None
    row["feed_health_ok"] = (
        not row["stale_yes_quote"]
        and not row["missing_yes_book"]
        and not row["crossed_yes_book"]
    )
    return row
