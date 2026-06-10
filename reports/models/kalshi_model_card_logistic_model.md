# Kalshi model card — logistic_model

- tradability: **TRADABLE**
- tradable (usable by paper/live policy): **False**
- lifecycle: **STAGED_NON_PROMOTED**  (is_staged=True is_promoted=False promotion_required=True live_approved=False)
- model_backend: sklearn
- created_by_command: kalshi-train-model
- calibration_status: uncalibrated
- created_at: 2026-06-10T15:05:00.814956+00:00  created_at_ms: 1781103900815
- model_schema_version: 1

## Intended use
- Estimate P(YES resolves to 1) for Kalshi BTC 15m markets.
- Output is a PROBABILITY. A hard Up/Down class is a DIAGNOSTIC only and
  must never trigger a trade. Trading needs probability + executable EV +
  calibration + gates. This artifact is NOT calibrated, so it cannot emit
  PAPER_CANDIDATE and cannot be used live.

## Training data
- train_windows: 538  val_windows: 231
- train_rows: 86796  val_rows: 34727
- embargo_windows: 1  no_leak: True
- gate_windows: 770  training_ready: True

## Validation metrics (diagnostic; NOT a profitability claim)
- accuracy: 0.8049356408558183
- roc_auc: 0.9012818466942234
- brier: 0.13043146700369201
- log_loss: 0.39810979702304766
- confusion_matrix: {'tp': 13614, 'tn': 14339, 'fp': 3293, 'fn': 3481}

## Features
- distance_to_start, distance_to_line_vol_normalized, seconds_to_close, fraction_window_elapsed, spot_sigma_per_sqrt_s, realized_vol_60s, realized_vol_180s, spot_return_30s, spot_return_60s, spot_return_since_window_start, spot_perp_basis, binance_queue_imbalance, binance_ofi_best, perp_cvd_60s, depth_imbalance, yes_spread, no_spread, top_depth, quote_age_ms, yes_ask, no_ask

## Limitations / safety
- Uncalibrated; diagnostic-only artifacts are NON_TRADABLE.
- No P&L/backtest here; executable backtest + calibration are later steps.
- STAGING: STAGED_NON_PROMOTED — written to data/models/staged/ when staged; the runtime (policy/lock) only scans data/models/ (non-recursive), so staged artifacts are NEVER auto-selected. Promotion is a SEPARATE explicit step (not performed here).
- Live trading disabled; live_approved=false; PAPER_CANDIDATE blocked.
