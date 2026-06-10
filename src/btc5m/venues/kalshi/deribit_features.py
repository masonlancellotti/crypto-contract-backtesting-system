"""Point-in-time Deribit feature join for Kalshi feature rows.

Deribit is an OPTIONAL volatility/options/regime context source — NOT a trading
venue and NOT required for the Kalshi MVP. These helpers map a normalized Deribit
snapshot into the ``deribit_*`` feature fields carried on each Kalshi feature row.

HARD RULES
- No look-ahead: only a Deribit snapshot timestamped **at or before** the feature
  row's ``as_of_ms`` may be used (:meth:`DeribitState.latest_at_or_before`).
- Never fabricate: when Deribit is disabled, unavailable at/before ``as_of``, or
  stale, the fields are still present but ``None`` with explicit flags
  (``deribit_enabled`` / ``deribit_available`` / ``deribit_used`` /
  ``deribit_stale`` / ``deribit_missing_reason``). A missing/stale/disabled
  Deribit NEVER blocks Kalshi feature generation, readiness, training, or paper.

IV vs realized-vol: Deribit IV/DVOL are annualized percentages. The Kalshi
``realized_vol_*s`` features are sigma-per-√second, so they are annualized here
via ``sigma * sqrt(seconds_per_year) * 100`` before subtracting from IV.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Optional

SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0
_ANNUALIZE = math.sqrt(SECONDS_PER_YEAR)
DEFAULT_STALE_MS = 180_000

# The deribit_* value columns carried on every v3 feature row (kept stable so the
# schema is predictable and missingness is reportable by column).
DERIBIT_VALUE_FIELDS = (
    "deribit_index_price", "deribit_dvol", "deribit_historical_vol",
    "deribit_near_expiry_iv", "deribit_atm_iv",
    "deribit_options_open_interest_total", "deribit_call_open_interest_total",
    "deribit_put_open_interest_total", "deribit_options_volume_total",
    "deribit_call_volume_total", "deribit_put_volume_total",
    "deribit_put_call_oi_ratio", "deribit_put_call_volume_ratio",
    "deribit_skew_proxy", "deribit_iv_minus_realized_vol_60s",
    "deribit_iv_minus_realized_vol_180s", "deribit_regime",
)
# Status/provenance flags always set on the row.
DERIBIT_FLAG_FIELDS = (
    "deribit_enabled", "deribit_available", "deribit_used",
    "deribit_age_ms", "deribit_stale", "deribit_missing_reason",
)


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def annualized_vol_pct(sigma_per_sqrt_s: Optional[float]) -> Optional[float]:
    """Convert a sigma-per-√second realized vol into an annualized percentage."""
    s = _f(sigma_per_sqrt_s)
    return None if s is None else s * _ANNUALIZE * 100.0


def regime_from_vol(dvol: Optional[float], near_iv: Optional[float]) -> Optional[str]:
    """Coarse, non-directional vol-regime bucket from DVOL (or near-expiry IV).

    Context only — never a directional signal. None when no vol level is known.
    """
    v = _f(dvol)
    if v is None:
        v = _f(near_iv)
    if v is None:
        return None
    if v < 40.0:
        return "low_vol"
    if v < 70.0:
        return "normal_vol"
    return "high_vol"


class DeribitState:
    """Rolling in-memory cache of normalized Deribit snapshots for the join.

    Feed each recorded normalized Deribit row via :meth:`ingest`; read the latest
    snapshot at/before a feature timestamp via :meth:`latest_at_or_before`. The
    Kalshi hot path never blocks on Deribit — it only reads this cache.
    """

    def __init__(self, max_rows: int = 1024) -> None:
        self._rows: deque[tuple[int, dict]] = deque(maxlen=max_rows)

    def ingest(self, norm: Optional[dict]) -> None:
        if not isinstance(norm, dict):
            return
        ts = norm.get("recv_ms")
        if ts is None:
            ts = norm.get("source_ts_ms")
        if ts is None:
            return
        try:
            self._rows.append((int(ts), norm))
        except (TypeError, ValueError):
            return

    def latest_at_or_before(self, as_of_ms: int) -> Optional[dict]:
        """Most recent snapshot with ts <= as_of_ms (no look-ahead), or None."""
        best: Optional[tuple[int, dict]] = None
        for ts, row in self._rows:
            if ts <= as_of_ms and (best is None or ts >= best[0]):
                best = (ts, row)
        return best[1] if best else None

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._rows)


def empty_deribit_fields(*, enabled: bool = False) -> dict:
    """All deribit_* keys present, values None, flagged disabled/unavailable."""
    return deribit_feature_fields(snapshot=None, as_of_ms=0, enabled=enabled)


def deribit_feature_fields(
    *,
    snapshot: Optional[dict],
    as_of_ms: int,
    enabled: bool,
    stale_threshold_ms: int = DEFAULT_STALE_MS,
    realized_vol_60s: Optional[float] = None,
    realized_vol_180s: Optional[float] = None,
) -> dict:
    """Build the deribit_* feature fields from a point-in-time snapshot.

    ``snapshot`` must already be the latest normalized Deribit row at/before
    ``as_of_ms`` (use :meth:`DeribitState.latest_at_or_before`). Returns a flat
    dict that always contains every key in ``DERIBIT_VALUE_FIELDS`` +
    ``DERIBIT_FLAG_FIELDS``.
    """
    out: dict[str, Any] = {k: None for k in DERIBIT_VALUE_FIELDS}
    out["deribit_enabled"] = bool(enabled)

    if not enabled:
        out.update(deribit_available=False, deribit_used=False, deribit_age_ms=None,
                   deribit_stale=False, deribit_missing_reason="DERIBIT_DISABLED")
        return out
    if not snapshot:
        out.update(deribit_available=False, deribit_used=False, deribit_age_ms=None,
                   deribit_stale=True,
                   deribit_missing_reason="NO_DERIBIT_SNAPSHOT_AT_OR_BEFORE_ASOF")
        return out

    ts = snapshot.get("recv_ms")
    if ts is None:
        ts = snapshot.get("source_ts_ms")
    age = (as_of_ms - int(ts)) if ts is not None else None
    stale = bool(age is not None and age > stale_threshold_ms)
    out["deribit_available"] = True
    out["deribit_age_ms"] = age
    out["deribit_stale"] = stale
    out["deribit_used"] = not stale

    # Direct passthrough of the snapshot's value fields.
    for k in ("deribit_index_price", "deribit_dvol", "deribit_historical_vol",
              "deribit_near_expiry_iv", "deribit_atm_iv",
              "deribit_options_open_interest_total", "deribit_call_open_interest_total",
              "deribit_put_open_interest_total", "deribit_options_volume_total",
              "deribit_call_volume_total", "deribit_put_volume_total",
              "deribit_put_call_oi_ratio", "deribit_put_call_volume_ratio",
              "deribit_skew_proxy"):
        out[k] = snapshot.get(k)

    # Derived: IV minus annualized realized vol (near-expiry IV, else DVOL).
    iv = out["deribit_near_expiry_iv"]
    if iv is None:
        iv = out["deribit_dvol"]
    rv60 = annualized_vol_pct(realized_vol_60s)
    rv180 = annualized_vol_pct(realized_vol_180s)
    out["deribit_iv_minus_realized_vol_60s"] = (iv - rv60) if (iv is not None and rv60 is not None) else None
    out["deribit_iv_minus_realized_vol_180s"] = (iv - rv180) if (iv is not None and rv180 is not None) else None
    out["deribit_regime"] = regime_from_vol(out["deribit_dvol"], out["deribit_near_expiry_iv"])

    snap_missing = snapshot.get("deribit_missing_reason")
    out["deribit_missing_reason"] = "STALE" if stale else snap_missing
    return out
