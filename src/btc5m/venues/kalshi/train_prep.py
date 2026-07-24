"""Kalshi training-prep DRY-RUN — join features+labels, purge/embargo, then REFUSE.

This performs every step *before* fitting a model so the data path can be
validated while collectors run, but it NEVER trains and NEVER trades:
  load usable executable feature rows  ->  join OFFICIAL labels per 15m window
  ->  group by distinct window  ->  apply purge/embargo (López de Prado)
  ->  report columns + per-column missingness + label balance
  ->  REFUSE until the authoritative gate (distinct windows) is reached.

Underlying-only rows (no Kalshi book) are excluded by construction
(:func:`readiness.feature_row_usable`), so they can never become executable
training examples. 15-minute windows do not overlap, so window-level purge/embargo
keeps each window an independent sample.
"""

from __future__ import annotations

from collections import Counter

from ...labels.labeling import LabeledSample, purge_embargo_indices
from .feature_schema import deribit_candidate_feature_names
from .labels_audit import dedup_labels, load_label_rows
from .readiness import (
    MIN_BACKTEST_WINDOWS, MIN_TRAIN_ROWS, MIN_TRAIN_WINDOWS, feature_row_usable,
)

WINDOW_MS = 15 * 60 * 1000

# Optional Deribit context columns (v3 rows). Reported separately so their (often
# high) missingness is never confused with the core executable feature set.
DERIBIT_REPORT_COLUMNS = [
    "deribit_dvol", "deribit_near_expiry_iv", "deribit_atm_iv", "deribit_skew_proxy",
    "deribit_put_call_oi_ratio", "deribit_iv_minus_realized_vol_60s", "deribit_regime",
]

# Key columns we report missingness for (the executable + rich-microstructure set).
REPORT_COLUMNS = [
    "yes_ask", "no_ask", "yes_bid", "no_bid", "seconds_to_close",
    "distance_to_start", "distance_to_line_vol_normalized", "spot_sigma_per_sqrt_s",
    "spot_return_30s", "spot_return_60s", "spot_return_since_window_start",
    "realized_vol_60s", "spot_perp_basis", "binance_microprice",
    "binance_queue_imbalance", "binance_ofi_best", "perp_cvd_60s", "depth_imbalance",
    *DERIBIT_REPORT_COLUMNS,
]


def _load_feature_rows(config, *, source=None) -> list[dict]:
    from .feature_source import load_feature_rows
    return load_feature_rows(config, source=source)


def train_dry_run(config, *, series: str = "KXBTC15M", embargo_windows: int = 1,
                  source=None) -> dict:
    """Assemble the would-be training table and report; never fits a model."""
    from .feature_source import normalize_source
    source = normalize_source(source, config=config)
    feats = _load_feature_rows(config, source=source)
    labels = dedup_labels(load_label_rows(config))
    official = {tk: lr for tk, lr in labels.items()
                if lr.get("label_source_status") == "OFFICIAL" and lr.get("label_yes_resolved") is not None}

    # Training-eligible rows: usable EXECUTABLE rows whose window has an OFFICIAL label.
    rows = [r for r in feats
            if feature_row_usable(r) and r.get("market_ticker") in official]
    # Guard: a training-eligible row must have a Kalshi book (never underlying-only).
    assert all(r.get("has_orderbook") for r in rows), "underlying-only row leaked into training set"

    windows: dict[str, dict] = {}
    for r in rows:
        windows.setdefault(r["market_ticker"], {"rows": 0, "close_ms": r.get("close_ms")})
        windows[r["market_ticker"]]["rows"] += 1
    gate_windows = len(windows)

    # Label balance (one OFFICIAL label per window).
    label_balance = Counter(official[tk].get("label_yes_resolved") for tk in windows)

    # Per-column missingness over the training-eligible rows.
    n = len(rows) or 1
    missingness = {}
    for col in REPORT_COLUMNS:
        missing = sum(1 for r in rows if r.get(col) is None)
        missingness[col] = round(missing / n, 4)
    all_columns = sorted({k for r in rows for k in r.keys()})

    # Optional Deribit context summary (never gates; reported for visibility).
    deribit_block = _deribit_summary(config, rows, missingness)
    # Feature-schema version distribution (old v2 rows coexist with v3 Deribit rows).
    version_counts = Counter(r.get("feature_set_version") for r in rows)
    feature_version_counts = {str(k): v for k, v in sorted(
        version_counts.items(), key=lambda kv: (kv[0] is None, kv[0]))}

    # Purge/embargo demonstration: treat each row's label horizon as [as_of, close];
    # hold out the most recent window as the test fold and report purge/embargo.
    purge_report = _purge_embargo_demo(rows, windows, embargo_windows)

    backtest_allowed = gate_windows >= MIN_BACKTEST_WINDOWS
    train_allowed = gate_windows >= MIN_TRAIN_WINDOWS and len(rows) >= MIN_TRAIN_ROWS
    blockers: list[str] = []
    if gate_windows < MIN_TRAIN_WINDOWS:
        blockers.append(f"distinct gate windows={gate_windows} < train threshold {MIN_TRAIN_WINDOWS}")
    if len(rows) < MIN_TRAIN_ROWS:
        blockers.append(f"training-eligible rows={len(rows)} < min rows {MIN_TRAIN_ROWS}")

    return {
        "series": series,
        "feature_rows_loaded": len(feats),
        "official_label_windows": len(official),
        "training_eligible_rows": len(rows),
        "gate_windows": gate_windows,
        "backtest_gate_threshold": MIN_BACKTEST_WINDOWS,
        "train_gate_threshold": MIN_TRAIN_WINDOWS,
        "train_gate_min_rows": MIN_TRAIN_ROWS,
        "label_balance": {("YES" if k == 1 else "NO"): v for k, v in label_balance.items()},
        "n_feature_columns": len(all_columns),
        "column_missingness": missingness,
        "feature_version_counts": feature_version_counts,
        "deribit": deribit_block,
        "purge_embargo": purge_report,
        "backtest_allowed": backtest_allowed,
        "train_allowed": train_allowed,
        "blockers": blockers,
        "trained": False,
        "safety": "DRY-RUN only — no model fit, no orders, live trading disabled.",
    }


def _deribit_summary(config, rows: list[dict], missingness: dict) -> dict:
    """Summarize OPTIONAL Deribit context coverage over training-eligible rows.

    Never affects the gate — Deribit is auxiliary. Reports COLUMN PRESENCE and
    historical availability separately from candidate-feature SELECTION, so a
    disabled/leftover Deribit is never mistaken for a model input. Candidate-group
    inclusion requires ``select_for_model_features`` (DERIBIT_INCLUDE_IN_MODEL_FEATURES,
    gated by an enabled source or an explicit allow-historical opt-in).
    """
    de_cfg = getattr(config, "deribit", None)
    enabled_cfg = bool(getattr(de_cfg, "enabled", False))
    include_flag = bool(getattr(de_cfg, "include_in_model_features", False))
    selected = bool(getattr(de_cfg, "select_for_model_features", False))
    n = len(rows) or 1
    columns_present = any("deribit_dvol" in r for r in rows)
    available = sum(1 for r in rows if r.get("deribit_available"))
    used = sum(1 for r in rows if r.get("deribit_used"))
    stale = sum(1 for r in rows if r.get("deribit_stale"))
    if not selected:
        status = "EXCLUDED_BY_CONFIG"
    elif available == 0:
        status = "UNAVAILABLE"
    elif used == 0:
        status = "STALE"
    else:
        status = "INCLUDED"
    by_col = {c: missingness.get(c) for c in DERIBIT_REPORT_COLUMNS}
    candidate_cols = deribit_candidate_feature_names()
    return {
        "enabled_in_config": enabled_cfg,
        "include_in_model_features": include_flag,
        "allow_historical_features_when_disabled":
            bool(getattr(de_cfg, "allow_historical_features_when_disabled", False)),
        "selected_for_model_features": selected,
        "columns_present": columns_present,
        "rows_total": len(rows),
        "rows_with_deribit_available": available,
        "rows_with_deribit_used": used,
        "rows_with_deribit_stale": stale,
        "fraction_used": round(used / n, 4),
        "missingness_by_deribit_column": by_col,
        "columns_missingness": by_col,  # back-compat alias
        "selected_candidate_feature_count": (len(candidate_cols) if selected else 0),
        "candidate_feature_group_status": status,
        "will_be_in_candidate_feature_group": selected,
        "note": ("Deribit is OPTIONAL vol/options context; missing/stale/disabled/not-selected "
                 "Deribit never blocks the gate, training, or backtesting. Column presence != "
                 "candidate-feature selection (requires DERIBIT_INCLUDE_IN_MODEL_FEATURES)."),
    }


def _purge_embargo_demo(rows: list[dict], windows: dict, embargo_windows: int) -> dict:
    """Hold out the most recent window; report purged/embargoed/kept train rows."""
    if not windows:
        return {"applied": False, "reason": "no training-eligible windows yet"}
    # Most recent window by close time = the test fold.
    test_tk = max(windows, key=lambda tk: windows[tk]["close_ms"] or 0)
    test_close = windows[test_tk]["close_ms"] or 0
    test_start = test_close - WINDOW_MS
    samples, idx = [], []
    for i, r in enumerate(rows):
        as_of = r.get("as_of_ms")
        close = r.get("close_ms")
        if as_of is None or close is None or close < as_of:
            continue
        samples.append(LabeledSample(as_of_ms=as_of, label_end_ms=close))
        idx.append(i)
    if not samples:
        return {"applied": False, "reason": "no rows with usable as_of/close timestamps"}
    safe = set(purge_embargo_indices(
        samples, test_start, test_close, embargo_ms=embargo_windows * WINDOW_MS))
    test_rows = sum(1 for j, i in enumerate(idx) if rows[i]["market_ticker"] == test_tk)
    train_rows = sum(1 for j, _i in enumerate(idx) if j in safe)
    dropped = len(samples) - train_rows
    return {
        "applied": True,
        "embargo_windows": embargo_windows,
        "embargo_ms": embargo_windows * WINDOW_MS,
        "test_window": test_tk,
        "test_rows": test_rows,
        "train_rows_after_purge_embargo": train_rows,
        "rows_purged_or_embargoed": dropped,
        "note": "15m windows do not overlap; purge/embargo keeps each window independent.",
    }
