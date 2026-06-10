"""Settlement resolution for BTC 5-minute binary contracts.

This module resolves whether **YES** settled to 1 by comparing the final
settlement/reference price against the contract line using the contract's exact
comparison operator. It never infers settlement from title text and never
guesses when expiry, line, or settlement price is missing — it returns an
explicit reason code instead.

Polymarket BTC 5-minute "Up or Down" markets settle as:
    "resolve to 'Up' if the price at the end ... is GREATER THAN OR EQUAL TO the
     price at the beginning ... Otherwise 'Down'."
i.e. ``final >= line`` (line = window-start price), so a tie resolves **Up/YES**
(:class:`~btc5m.schemas.Comparison.GTE`). "Above-strike" markets use strict
``>`` (:class:`~btc5m.schemas.Comparison.GT`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..schemas import Comparison, ContractMeta


class ReasonCode(str, Enum):
    """Explicit settlement reason codes — never silently guess."""

    OK = "OK"
    MISSING_METADATA = "MISSING_METADATA"
    MISSING_LINE = "MISSING_LINE"
    INVALID_LINE = "INVALID_LINE"
    MISSING_EXPIRY = "MISSING_EXPIRY"
    MISSING_SETTLEMENT_PRICE = "MISSING_SETTLEMENT_PRICE"
    UNKNOWN = "UNKNOWN"


@dataclass
class SettlementResult:
    """Outcome of a settlement evaluation.

    ``yes_resolved`` is 1 (YES), 0 (NO), or None (undeterminable). When None,
    ``reason`` explains why and ``yes_resolved`` must NOT be treated as a label.
    """

    yes_resolved: Optional[int]
    reason: ReasonCode
    settlement_distance: Optional[float] = None  # final_reference_price - line
    final_above_strike: Optional[bool] = None
    detail: str = ""

    @property
    def is_known(self) -> bool:
        return self.yes_resolved is not None and self.reason is ReasonCode.OK


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #
def parse_line(value: object) -> tuple[Optional[float], ReasonCode]:
    """Parse/validate a contract line/strike into a finite float.

    Returns (line, OK) on success or (None, MISSING_LINE/INVALID_LINE).
    """
    if value is None:
        return None, ReasonCode.MISSING_LINE
    try:
        line = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None, ReasonCode.INVALID_LINE
    if line != line or line in (float("inf"), float("-inf")):  # NaN/inf guard
        return None, ReasonCode.INVALID_LINE
    return line, ReasonCode.OK


def validate_expiry(expiry_ms: object) -> bool:
    """True only if expiry is a positive integer-like epoch-ms timestamp."""
    try:
        return int(expiry_ms) > 0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def settlement_distance(final_reference_price: float, line: float) -> float:
    """Signed distance final - line. Positive means final is above the line."""
    return float(final_reference_price) - float(line)


def label_final_above_strike(
    final_reference_price: float, line: float, comparison: Comparison = Comparison.GT
) -> bool:
    """Whether the final price clears the line under the given comparison.

    GT  -> final > line     (strict above)
    GTE -> final >= line    (at-or-above; tie clears)
    """
    if comparison is Comparison.GTE:
        return float(final_reference_price) >= float(line)
    return float(final_reference_price) > float(line)


# --------------------------------------------------------------------------- #
# Main resolution
# --------------------------------------------------------------------------- #
def label_yes_resolved(
    meta: ContractMeta,
    final_reference_price: Optional[float],
    *,
    comparison: Optional[Comparison] = None,
) -> SettlementResult:
    """Resolve YES (1) / NO (0) / unknown (None) with an explicit reason code.

    - Uses ``meta.comparison`` unless an explicit ``comparison`` is passed.
    - Never uses title text. Never guesses on missing inputs.
    """
    if not validate_expiry(meta.expiry_ms):
        return SettlementResult(None, ReasonCode.MISSING_EXPIRY, detail="expiry missing/invalid")

    if not meta.asset:
        return SettlementResult(None, ReasonCode.MISSING_METADATA, detail="asset missing")

    line, line_reason = parse_line(meta.line)
    if line_reason is not ReasonCode.OK:
        return SettlementResult(None, line_reason, detail=f"line={meta.line!r}")

    if final_reference_price is None:
        return SettlementResult(
            None,
            ReasonCode.MISSING_SETTLEMENT_PRICE,
            detail="no final reference price provided",
        )
    price, price_reason = parse_line(final_reference_price)  # reuse numeric validation
    if price_reason is not ReasonCode.OK or price is None:
        return SettlementResult(
            None, ReasonCode.MISSING_SETTLEMENT_PRICE, detail="final price invalid"
        )

    cmp = comparison or meta.comparison
    dist = settlement_distance(price, line)
    above = label_final_above_strike(price, line, cmp)
    return SettlementResult(
        yes_resolved=1 if above else 0,
        reason=ReasonCode.OK,
        settlement_distance=dist,
        final_above_strike=above,
        detail=f"cmp={cmp.value} final={price} line={line}",
    )


def resolve_settlement(meta: ContractMeta, settlement_price: Optional[float]) -> Optional[int]:
    """Backward-compatible thin wrapper returning 1 / 0 / None.

    Honors ``meta.comparison`` (default strict GT). Prefer
    :func:`label_yes_resolved` for the full result + reason code.
    """
    return label_yes_resolved(meta, settlement_price).yes_resolved
