"""Explicit, versioned Kalshi model feature schema + leakage exclusions.

Declares every model input by group, dtype, required/optional, and whether it is
allowed for training. Trade decisions use the model PROBABILITY + executable EV
gates — a hard Up/Down class is diagnostic only and is NEVER a training/trading
target feature. Leakage fields (the realized outcome, official label, post-close
or paper-P&L fields, anything computed after as_of) are excluded explicitly and
asserted absent from any training matrix.
"""

from __future__ import annotations

from dataclasses import dataclass

# Bump if the model feature schema (selection/encoding) changes.
MODEL_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str                 # A..G (see below)
    dtype: str                 # "numeric" | "bool" | "categorical"
    required: bool = False     # required-for-training (must be present/usable)
    allowed_for_training: bool = True


# Feature groups (A..G per the model spec).
GROUPS = {
    "A": "contract/time",
    "B": "kalshi_orderbook",
    "C": "underlying_returns",
    "D": "underlying_volatility",
    "E": "underlying_microstructure",
    "F": "deribit_optional",
    "G": "source_health_missingness",
}

# --------------------------------------------------------------------------- #
# Leakage exclusions — fields that must NEVER enter the training matrix.
# (Feature rows don't carry these, but we assert it to stay safe forever.)
# --------------------------------------------------------------------------- #
LEAKAGE_EXCLUDED = frozenset({
    "label_yes_resolved", "label_source_status", "label_source",
    "known_outcome", "settlement_outcome_when_known", "settlement_outcome",
    "result", "paper_pnl", "paper_pnl_when_known", "is_paper",
    "decision_state", "fill_status", "simulated_fill_price", "simulated_fill_size",
    "settlement_status",
    # Non-stationary raw price LEVELS are excluded to avoid spurious fit (use
    # distance_to_line / returns instead). Not leakage, but excluded from training.
    "reference_price", "reference_start_price", "binance_microprice",
    "coinbase_best_bid", "coinbase_best_ask", "binance_best_bid", "binance_best_ask",
    "mid_yes_diagnostic",
})

# Hard class output name (diagnostic only — never a trading signal).
HARD_CLASS_FIELD = "hard_class_prediction"


def _spec(name, group, dtype="numeric", required=False, allowed=True):
    return FeatureSpec(name=name, group=group, dtype=dtype, required=required,
                       allowed_for_training=allowed)


# Full schema. ``allowed_for_training`` False => carried in the dataset for context
# but not fed to the model (levels, categoricals, or provenance-only fields).
SCHEMA: list[FeatureSpec] = [
    # A. contract / time
    _spec("seconds_to_close", "A", required=True),
    _spec("fraction_window_elapsed", "A"),
    _spec("distance_to_start", "A"),                       # == distance_to_line
    _spec("distance_to_line_vol_normalized", "A"),
    _spec("market_duration_seconds", "A", allowed=False),
    # B. kalshi orderbook
    _spec("yes_bid", "B"), _spec("yes_ask", "B", required=True),
    _spec("no_bid", "B"), _spec("no_ask", "B", required=True),
    _spec("executable_yes_buy_price", "B"), _spec("executable_no_buy_price", "B"),
    _spec("yes_spread", "B"), _spec("no_spread", "B"),
    _spec("top_depth", "B"), _spec("depth_imbalance", "B"),
    _spec("quote_age_ms", "B"),
    _spec("yes_crossed", "B", dtype="bool", allowed=False),
    _spec("no_crossed", "B", dtype="bool", allowed=False),
    _spec("incomplete_book", "B", dtype="bool", allowed=False),
    # C. underlying returns
    _spec("spot_return_5s", "C"), _spec("spot_return_15s", "C"),
    _spec("spot_return_30s", "C"), _spec("spot_return_60s", "C"),
    _spec("spot_return_180s", "C"), _spec("spot_return_since_window_start", "C"),
    # D. underlying volatility
    _spec("spot_sigma_per_sqrt_s", "D"),
    _spec("realized_vol_30s", "D"), _spec("realized_vol_60s", "D"),
    _spec("realized_vol_180s", "D"), _spec("realized_vol_window_to_date", "D"),
    # E. underlying microstructure
    _spec("spot_perp_basis", "E"), _spec("spot_perp_basis_change_60s", "E"),
    _spec("binance_queue_imbalance", "E"), _spec("binance_ofi_best", "E"),
    _spec("spot_cvd_60s", "E"), _spec("perp_cvd_60s", "E"),
    _spec("spot_signed_trade_imbalance_60s", "E"), _spec("perp_signed_trade_imbalance_60s", "E"),
    _spec("spot_trade_intensity_60s", "E"), _spec("perp_trade_intensity_60s", "E"),
    _spec("coinbase_spread", "E"), _spec("binance_spread", "E"),
    # F. deribit (optional)
    _spec("deribit_available", "F", dtype="bool"),
    _spec("deribit_stale", "F", dtype="bool"),
    _spec("deribit_age_ms", "F", allowed=False),
    _spec("deribit_dvol", "F"), _spec("deribit_historical_vol", "F"),
    _spec("deribit_near_expiry_iv", "F"), _spec("deribit_atm_iv", "F"),
    _spec("deribit_options_open_interest_total", "F"),
    _spec("deribit_put_call_oi_ratio", "F"), _spec("deribit_put_call_volume_ratio", "F"),
    _spec("deribit_skew_proxy", "F"), _spec("deribit_iv_minus_realized_vol_60s", "F"),
    _spec("deribit_regime", "F", dtype="categorical", allowed=False),
    # G. source-health / missingness
    _spec("coinbase_stale", "G", dtype="bool"), _spec("binance_stale", "G", dtype="bool"),
    _spec("has_spot_feed", "G", dtype="bool"), _spec("has_perp_feed", "G", dtype="bool"),
]

SPEC_BY_NAME = {s.name: s for s in SCHEMA}

# Named feature sets for the baselines (all entries are allowed_for_training).
DISTANCE_TIME_VOL_FEATURES = [
    "distance_to_start", "distance_to_line_vol_normalized", "seconds_to_close",
    "fraction_window_elapsed", "spot_sigma_per_sqrt_s", "realized_vol_60s", "realized_vol_180s",
]
MICROSTRUCTURE_FEATURES = DISTANCE_TIME_VOL_FEATURES + [
    "spot_return_30s", "spot_return_60s", "spot_return_since_window_start",
    "spot_perp_basis", "binance_queue_imbalance", "binance_ofi_best", "perp_cvd_60s",
    "depth_imbalance", "yes_spread", "no_spread", "top_depth", "quote_age_ms",
    "yes_ask", "no_ask",
]


def training_feature_names() -> list[str]:
    """All schema features allowed for training (numeric/bool), leakage excluded."""
    return [s.name for s in SCHEMA if s.allowed_for_training and s.name not in LEAKAGE_EXCLUDED]


def deribit_candidate_feature_names() -> list[str]:
    """The deribit_* (group F) schema features eligible for the model candidate set.

    These are the columns that enter training ONLY when Deribit is selected for model
    features (``DeribitConfig.select_for_model_features``). When Deribit is disabled /
    not included, these are dropped from the training matrix so leftover historical
    Deribit columns are never silently fed to the model.
    """
    return [s.name for s in SCHEMA
            if s.group == "F" and s.allowed_for_training and s.name not in LEAKAGE_EXCLUDED]


def assert_no_leakage(feature_names: list[str]) -> None:
    bad = [f for f in feature_names if f in LEAKAGE_EXCLUDED]
    if bad:
        raise ValueError(f"leakage columns in training features: {bad}")


def _to_number(value, dtype: str):
    """Encode a raw feature value for the model: bool->0/1, numeric->float, else None."""
    if value is None:
        return None
    if dtype == "bool":
        return 1.0 if bool(value) else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def feature_vector(row: dict, feature_names: list[str]) -> list:
    """Extract an (encoded) feature vector for ``feature_names`` (missing -> None)."""
    assert_no_leakage(feature_names)
    vec = []
    for name in feature_names:
        spec = SPEC_BY_NAME.get(name)
        dtype = spec.dtype if spec else "numeric"
        vec.append(_to_number(row.get(name), dtype))
    return vec


def schema_json() -> dict:
    return {
        "model_schema_version": MODEL_SCHEMA_VERSION,
        "groups": GROUPS,
        "features": [
            {"name": s.name, "group": s.group, "group_name": GROUPS.get(s.group),
             "dtype": s.dtype, "required": s.required,
             "allowed_for_training": s.allowed_for_training}
            for s in SCHEMA
        ],
        "leakage_excluded": sorted(LEAKAGE_EXCLUDED),
        "hard_class_field": HARD_CLASS_FIELD,
        "hard_class_note": "Hard Up/Down class is a DIAGNOSTIC only; trade decisions "
                           "require probability + executable EV + calibration + gates.",
        "named_feature_sets": {
            "distance_time_vol": DISTANCE_TIME_VOL_FEATURES,
            "microstructure": MICROSTRUCTURE_FEATURES,
        },
    }
