"""Baseline settlement-probability model — driftless normal approximation.

This answers the *correct* question for Up/Down markets: given the current BTC
reference price ``S``, the line ``L`` (window-start price), the time remaining
``T`` seconds, and a recent volatility estimate, what is P(YES/Up resolves to 1)
= P(final >= line)?

Model: assume log-price over the remaining horizon is approximately
``ln S_T ~ Normal(ln S, sigma_total^2)`` with ``sigma_total = sigma_per_sqrt_s *
sqrt(T)`` (driftless; valid for very short 5-minute windows). Then

    P(S_T >= L) = Phi( ln(S / L) / sigma_total )

This is a hard-to-overfit reference. It is deliberately left **uncalibrated**
(``calibration_ts_ms=None``) so the risk gate keeps it non-tradable until a
calibration layer is fit on real data. It is NOT a generic up/down bot — it is
a probability for a specific contract's settlement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..config import AppConfig
from ..schemas import Comparison, ContractMeta, ModelOutput, OrderBook
from ..timeutils import now_ms


def _phi(x: float) -> float:
    """Standard normal CDF via the error function (stdlib)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class BaselineInputs:
    reference_price: Optional[float]
    line: Optional[float]
    seconds_to_expiry: Optional[float]
    sigma_per_sqrt_s: Optional[float]   # log-return stdev per sqrt-second
    comparison: Comparison = Comparison.GTE


def normal_prob_yes(inp: BaselineInputs) -> Optional[float]:
    """P(final >= line) under the driftless normal approximation.

    Returns None when inputs are insufficient (missing price/line). Handles the
    deterministic edges (expired or zero-vol) explicitly.
    """
    S, L, T = inp.reference_price, inp.line, inp.seconds_to_expiry
    if S is None or L is None or S <= 0 or L <= 0:
        return None
    # Deterministic at/after expiry or with no volatility.
    if T is None or T <= 0 or not inp.sigma_per_sqrt_s or inp.sigma_per_sqrt_s <= 0:
        if inp.comparison is Comparison.GTE:
            return 1.0 if S >= L else 0.0
        return 1.0 if S > L else 0.0
    sigma_total = inp.sigma_per_sqrt_s * math.sqrt(T)
    if sigma_total <= 0:
        return 1.0 if S >= L else 0.0
    z = math.log(S / L) / sigma_total
    return _phi(z)


class BaselineModel:
    """Normal-approximation baseline (uncalibrated by design)."""

    name = "baseline-normal"

    def __init__(self, config: AppConfig | None = None):
        self.config = config

    def predict_proba(self, inp: BaselineInputs) -> ModelOutput:
        """Return a :class:`ModelOutput` with P(YES) and a vol-based band."""
        p = normal_prob_yes(inp)
        if p is None:
            # Insufficient inputs -> neutral, wide, explicitly uncertain.
            return ModelOutput(
                contract_id="", p_yes=0.5, p_yes_lower=0.3, p_yes_upper=0.7,
                calibration_ts_ms=None, model_name=self.name, ts_ms=now_ms(),
            )
        # Rough band: +/- one "decision sigma" mapped through the same z.
        band = 0.0
        if inp.sigma_per_sqrt_s and inp.seconds_to_expiry and inp.reference_price and inp.line:
            if inp.seconds_to_expiry > 0:
                sigma_total = inp.sigma_per_sqrt_s * math.sqrt(inp.seconds_to_expiry)
                if sigma_total > 0:
                    z = math.log(inp.reference_price / inp.line) / sigma_total
                    band = abs(_phi(z + 0.5) - _phi(z - 0.5)) / 2.0
        return ModelOutput(
            contract_id="", p_yes=p,
            p_yes_lower=max(0.0, p - band), p_yes_upper=min(1.0, p + band),
            calibration_ts_ms=None,  # uncalibrated by design -> not tradable yet
            model_name=self.name, ts_ms=now_ms(),
        )

    def predict(self, book: OrderBook, meta: ContractMeta) -> ModelOutput:
        """Legacy signature. The Polymarket book lacks the BTC price + vol, so
        without those inputs this returns a SAFE neutral estimate. Use
        :meth:`predict_proba` with :class:`BaselineInputs` for a real probability.
        """
        return ModelOutput(
            contract_id=meta.contract_id, p_yes=0.5, p_yes_lower=0.4, p_yes_upper=0.6,
            calibration_ts_ms=None, model_name=self.name, ts_ms=now_ms(),
        )
