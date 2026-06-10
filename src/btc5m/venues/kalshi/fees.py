"""Kalshi fee model (configurable; ASSUMED unless verified).

Kalshi fees are NOT Polymarket fees. Public references describe a taker fee
shaped roughly like::

    fee = round_up_to_cent( rate * contracts * price * (1 - price) )

with ``rate`` ~ 0.07. Schedules vary by market/category and change over time, so
the rate + status live in config (:class:`~btc5m.config.KalshiConfig`) and every
fee is stamped with ``fee_status`` ∈ {OFFICIAL, ASSUMED, UNKNOWN}. Never claim
edge without subtracting the configured fee. ``UNKNOWN`` uses a conservative
upper-bound rate so edge is never overstated.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_UP, Decimal

# Conservative fallback used when the fee status is UNKNOWN (overstates cost, so
# it can only make edge look WORSE — never better).
_UNKNOWN_RATE = Decimal("0.10")


@dataclass
class KalshiFeeModel:
    rate: float = 0.07
    status: str = "ASSUMED"   # OFFICIAL | ASSUMED | UNKNOWN
    formula: str = "round_up_cent(rate * contracts * price * (1 - price))"

    @classmethod
    def from_config(cls, config) -> "KalshiFeeModel":
        k = getattr(config, "kalshi", None)
        if k is None:
            return cls()
        return cls(rate=float(k.fee_rate), status=str(k.fee_status), formula=str(k.fee_formula))

    def _effective_rate(self) -> Decimal:
        return _UNKNOWN_RATE if self.status == "UNKNOWN" else Decimal(str(self.rate))

    def taker_fee(self, price: float, contracts: float) -> float:
        """Taker fee in dollars for ``contracts`` at ``price`` (rounded up to a cent).

        Returns 0.0 for degenerate inputs (price outside (0,1) or no contracts).
        """
        try:
            p = Decimal(str(price))
            n = Decimal(str(contracts))
        except Exception:  # noqa: BLE001
            return 0.0
        if n <= 0 or p <= 0 or p >= 1:
            return 0.0
        raw = self._effective_rate() * n * p * (Decimal("1") - p)
        return float(raw.quantize(Decimal("0.01"), rounding=ROUND_UP))

    def per_contract_fee(self, price: float, contracts: float = 1.0) -> float:
        """Fee expressed per contract (for cents-of-edge comparisons)."""
        n = contracts if contracts else 1.0
        return self.taker_fee(price, n) / n if n else 0.0

    def describe(self) -> dict:
        return {"fee_rate": self.rate, "fee_status": self.status, "fee_formula": self.formula}
