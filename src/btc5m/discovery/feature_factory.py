"""Feature factory — the versioned, point-in-time candidate-signal library.

Wraps the project's already-point-in-time feature columns (computed with `as_of_ms <
close_ms`, no look-ahead) as named, grouped candidate predictors, plus a small set of
principled derived interactions. Flags, raw quotes, executable prices and the market price
itself are EXCLUDED — a feature must be an orthogonal signal, not a restatement of the price
the market already shows. The factory is versioned (hash of the feature name set) so the
registry/vault can pin exactly which signals were searched."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Callable, Optional


def _f(x) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str
    fn: Callable[[dict], Optional[float]]


# direct point-in-time columns that are genuine orthogonal signals (NOT price/flags)
_BASE = {
    "distance": ["distance_to_start", "distance_to_line_vol_normalized",
                 "fraction_window_elapsed", "seconds_to_close"],
    "momentum": ["spot_return_5s", "spot_return_15s", "spot_return_30s", "spot_return_60s",
                 "spot_return_180s", "spot_return_since_window_start"],
    "vol": ["spot_sigma_per_sqrt_s", "realized_vol_30s", "realized_vol_60s",
            "realized_vol_180s", "realized_vol_window_to_date"],
    "basis": ["spot_perp_basis", "spot_perp_basis_change_60s", "binance_ofi_best",
              "binance_queue_imbalance"],
    "flow": ["spot_cvd_60s", "perp_cvd_60s", "spot_signed_trade_imbalance_60s",
             "perp_signed_trade_imbalance_60s", "spot_trade_intensity_60s",
             "perp_trade_intensity_60s"],
    "book": ["yes_spread", "no_spread", "top_depth", "depth_imbalance"],
    # Kalshi-side book volume/liquidity (top-of-book resting size)
    "liquidity": ["yes_ask_size", "no_ask_size"],
    # Deribit options (joined when collected; ALL-NULL on data where Deribit was disabled —
    # surfaced by the screen's coverage column, not silently dropped)
    "options": ["deribit_atm_iv", "deribit_iv_minus_realized_vol_60s", "deribit_skew_proxy",
                "deribit_put_call_oi_ratio", "deribit_dvol"],
}


def _col(c: str) -> Callable[[dict], Optional[float]]:
    return lambda row: _f(row.get(c))


def _ratio(a: str, b: str):
    def fn(row):
        va, vb = _f(row.get(a)), _f(row.get(b))
        return (va / vb) if (va is not None and vb not in (None, 0)) else None
    return fn


def _prod(a: str, b: str):
    def fn(row):
        va, vb = _f(row.get(a)), _f(row.get(b))
        return (va * vb) if (va is not None and vb is not None) else None
    return fn


def _diff(a: str, b: str):
    def fn(row):
        va, vb = _f(row.get(a)), _f(row.get(b))
        return (va - vb) if (va is not None and vb is not None) else None
    return fn


def _book_size_imb(row):
    ys, ns = _f(row.get("yes_ask_size")), _f(row.get("no_ask_size"))
    return ((ys - ns) / (ys + ns)) if (ys is not None and ns is not None and ys + ns > 0) else None


def _kalshi_top_size(row):
    ys, ns = _f(row.get("yes_ask_size")), _f(row.get("no_ask_size"))
    return (ys + ns) if (ys is not None and ns is not None) else None


# principled derived interactions (kept few — each adds to the multiple-testing budget)
_DERIVED = [
    FeatureSpec("ret_accel_5_30", "derived", _diff("spot_return_5s", "spot_return_30s")),
    FeatureSpec("ret_persist_5x60", "derived", _prod("spot_return_5s", "spot_return_60s")),
    FeatureSpec("vol_term_30_180", "derived", _ratio("realized_vol_30s", "realized_vol_180s")),
    FeatureSpec("ofi_x_depth", "derived", _prod("binance_ofi_best", "depth_imbalance")),
    FeatureSpec("flow_div_spot_perp", "derived",
                _diff("spot_signed_trade_imbalance_60s", "perp_signed_trade_imbalance_60s")),
    FeatureSpec("basis_x_mom", "derived",
                _prod("spot_perp_basis_change_60s", "spot_return_60s")),
    FeatureSpec("book_size_imb", "derived", _book_size_imb),
    FeatureSpec("kalshi_top_size", "derived", _kalshi_top_size),
]


def feature_specs() -> list[FeatureSpec]:
    specs = [FeatureSpec(c, g, _col(c)) for g, cols in _BASE.items() for c in cols]
    return specs + _DERIVED


def feature_names() -> list[str]:
    return [s.name for s in feature_specs()]


def extract(row: dict) -> dict:
    """Candidate-feature dict for one decision-snapshot row."""
    return {s.name: s.fn(row) for s in feature_specs()}


def version() -> str:
    h = hashlib.sha256("|".join(sorted(feature_names())).encode()).hexdigest()
    return f"ff1:{h[:12]}"
