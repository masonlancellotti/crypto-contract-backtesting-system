"""Kalshi settlement + labeling.

Source of truth = Kalshi's OFFICIAL ``result`` field ("yes"/"no") once a market
is finalized/settled. BTC reference prices (Coinbase/Binance, or Kalshi's stated
"Target Price") are useful for features/diagnostics but are NEVER promoted to an
official label. This is Kalshi semantics — do NOT reuse Polymarket/Chainlink
line logic. If the rule text is unclear, comparison is UNKNOWN and we label only
by the official result.

VERIFIED rule wording (KXBTC15M): "If the simple average of the sixty seconds of
CF Benchmarks' BRTI before <close> ... is at least the simple average ... before
<open>" → YES on >= (GTE), source = CF Benchmarks BRTI (not Chainlink).
"""

from __future__ import annotations

import re
from typing import Optional

from .client import iso_to_ms

_PRICE_RE = re.compile(r"\$?\s*([0-9][0-9,]*\.?[0-9]*)")


def parse_target_price(sub_title: Optional[str]) -> Optional[float]:
    """Parse the start reference from ``yes_sub_title`` ('Target Price: $72,901.10')."""
    if not sub_title:
        return None
    m = _PRICE_RE.search(sub_title)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def comparison_from_rules(rules_primary: Optional[str]) -> str:
    """Derive comparison semantics from the explicit rule text. Never guessed
    beyond clear wording; otherwise UNKNOWN."""
    t = (rules_primary or "").lower()
    if "at least" in t or "greater than or equal" in t or "at or above" in t:
        return "GTE"
    if "greater than" in t or "strictly above" in t or "higher than" in t:
        return "GT"
    return "UNKNOWN"


def reference_source_from_rules(rules_primary: Optional[str]) -> Optional[str]:
    """Name the settlement reference ONLY when the rule text states it.

    KXBTC15M rules cite CF Benchmarks' BRTI (NOT Chainlink). Never assume from
    the title; if the rule text does not name a source, return None.
    """
    t = (rules_primary or "").lower()
    if "brti" in t:
        return "CF Benchmarks BRTI (60s average)"
    if "cf benchmarks" in t:
        return "CF Benchmarks"
    return None


def official_result(market: dict) -> Optional[str]:
    """Return 'yes'/'no' ONLY for a finalized/settled market; else None."""
    status = (market.get("status") or "").lower()
    result = (market.get("result") or "").strip().lower()
    if status in ("finalized", "settled") and result in ("yes", "no"):
        return result
    # Some payloads carry result without an explicit terminal status.
    if result in ("yes", "no") and status not in ("active", "initialized", "unopened"):
        return result
    return None


def _provisional_label(start: Optional[float], end: Optional[float], comparison: str) -> Optional[int]:
    if start is None or end is None or comparison == "UNKNOWN":
        return None
    if comparison == "GTE":
        return 1 if end >= start else 0
    return 1 if end > start else 0


def build_label_row(
    market: dict,
    *,
    reference_end_price: Optional[float] = None,
    reference_source: Optional[str] = None,
    created_at_ms: Optional[int] = None,
) -> dict:
    """Build one Kalshi label row. OFFICIAL when Kalshi has settled; otherwise
    PROVISIONAL_REFERENCE (if BTC refs allow a computed guess) or UNKNOWN.
    Disagreement between official and computed → MANUAL_REVIEW (both kept)."""
    from ...timeutils import now_ms
    created = created_at_ms if created_at_ms is not None else now_ms()

    ticker = market.get("ticker")
    comparison = comparison_from_rules(market.get("rules_primary"))
    start_price = parse_target_price(market.get("yes_sub_title"))
    official = official_result(market)
    computed = _provisional_label(start_price, reference_end_price, comparison)

    dist = (reference_end_price - start_price) if (reference_end_price is not None and start_price is not None) else None

    if official is not None:
        official_yes = 1 if official == "yes" else 0
        if computed is not None and computed != official_yes:
            status, label, reason = "MANUAL_REVIEW", official_yes, "OFFICIAL_VS_PROVISIONAL_DISAGREE"
        else:
            status, label, reason = "OFFICIAL", official_yes, "OK"
    elif computed is not None:
        official_yes = None
        status, label, reason = "PROVISIONAL_REFERENCE", computed, "NO_OFFICIAL_RESULT_PROVISIONAL_ONLY"
    else:
        official_yes = None
        status, label = "UNKNOWN", None
        if comparison == "UNKNOWN":
            reason = "UNKNOWN_COMPARISON"
        elif start_price is None:
            reason = "MISSING_START_REFERENCE"
        elif reference_end_price is None:
            reason = "MISSING_END_REFERENCE"
        else:
            reason = "NO_OFFICIAL_RESULT"

    return {
        "venue": "kalshi",
        "series_ticker": market.get("series_ticker") or (ticker.split("-")[0] if ticker else None),
        "market_ticker": ticker,
        "event_ticker": market.get("event_ticker"),
        "window_start_ms": iso_to_ms(market.get("open_time")),
        "close_ms": iso_to_ms(market.get("close_time")),
        "settled_ms": iso_to_ms(market.get("expected_expiration_time") or market.get("expiration_time")),
        "official_result": official,
        "official_winning_side": official,
        "label_yes_resolved": label,
        "label_source_status": status,
        "reference_start_price": start_price,
        "reference_start_source": "kalshi_target_price" if start_price is not None else None,
        "reference_end_price": reference_end_price,
        "reference_source": reference_source,
        "settlement_distance": dist,
        "comparison_semantics": comparison,
        "settlement_reference_source": reference_source_from_rules(market.get("rules_primary")),
        "rules_excerpt": (market.get("rules_primary") or "")[:240] or None,
        "reason_code": reason,
        "created_at_ms": created,
        "raw_market_ref": ticker,
    }
