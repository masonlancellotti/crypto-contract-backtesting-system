# Kalshi model card — logistic_model

- tradability: **TRADABLE**
- tradable (usable by paper/live policy): **False**
- lifecycle: **STAGED_NON_PROMOTED**  (is_staged=True is_promoted=False promotion_required=True live_approved=False)
- model_backend: sklearn
- created_by_command: kalshi-train-model
- calibration_status: uncalibrated
- created_at: 2026-06-03T20:48:57.675778+00:00  created_at_ms: 1780519737675
- model_schema_version: 1

## Intended use
- Estimate P(YES resolves to 1) for Kalshi BTC 15m markets.
- Output is a PROBABILITY. A hard Up/Down class is a DIAGNOSTIC only and
  must never trigger a trade. Trading needs probability + executable EV +
  calibration + gates. This artifact is NOT calibrated, so it cannot emit
  PAPER_CANDIDATE and cannot be used live.

## Training data
- train_windows: 130  val_windows: 56
- train_rows: 16489  val_rows: 7469
- embargo_windows: 1  no_leak: True
- gate_windows: 187  training_ready: True

## Validation metrics (diagnostic; NOT a profitability claim)
- accuracy: 0.7757397241933325
- roc_auc: 0.8615141443210412
- brier: 0.15619920604772652
- log_loss: 0.47682664260780744
- confusion_matrix: {'tp': 2431, 'tn': 3363, 'fp': 598, 'fn': 1077}

## Features
- distance_to_start, distance_to_line_vol_normalized, seconds_to_close, fraction_window_elapsed, spot_sigma_per_sqrt_s, realized_vol_60s, realized_vol_180s, spot_return_30s, spot_return_60s, spot_return_since_window_start, spot_perp_basis, binance_queue_imbalance, binance_ofi_best, perp_cvd_60s, depth_imbalance, yes_spread, no_spread, top_depth, quote_age_ms, yes_ask, no_ask

## Limitations / safety
- Uncalibrated; diagnostic-only artifacts are NON_TRADABLE.
- No P&L/backtest here; executable backtest + calibration are later steps.
- STAGING: STAGED_NON_PROMOTED — written to data/models/staged/ when staged; the runtime (policy/lock) only scans data/models/ (non-recursive), so staged artifacts are NEVER auto-selected. Promotion is a SEPARATE explicit step (not performed here).
- Live trading disabled; live_approved=false; PAPER_CANDIDATE blocked.
