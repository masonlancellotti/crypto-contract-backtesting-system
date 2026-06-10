# Kalshi model card — microstructure_logistic

- tradability: **NON_TRADABLE_DIAGNOSTIC_ONLY**
- tradable (usable by paper/live policy): **False**
- lifecycle: **DIAGNOSTIC_ONLY**  (is_staged=True is_promoted=False promotion_required=True live_approved=False)
- model_backend: sklearn
- created_by_command: kalshi-train-baselines
- calibration_status: uncalibrated
- created_at: 2026-06-10T15:14:02.644455+00:00  created_at_ms: 1781104442644
- model_schema_version: 1

## Intended use
- Estimate P(YES resolves to 1) for Kalshi BTC 15m markets.
- Output is a PROBABILITY. A hard Up/Down class is a DIAGNOSTIC only and
  must never trigger a trade. Trading needs probability + executable EV +
  calibration + gates. This artifact is NOT calibrated, so it cannot emit
  PAPER_CANDIDATE and cannot be used live.

## Training data
- train_windows: 3  val_windows: 2
- train_rows: 18  val_rows: 12
- embargo_windows: 1  no_leak: True
- gate_windows: 6  training_ready: False

## Validation metrics (diagnostic; NOT a profitability claim)
- accuracy: 1.0
- roc_auc: 1.0
- brier: 0.005832459148801541
- log_loss: 0.07554954988346839
- confusion_matrix: {'tp': 6, 'tn': 6, 'fp': 0, 'fn': 0}

## Features
- distance_to_start, distance_to_line_vol_normalized, seconds_to_close, fraction_window_elapsed, spot_sigma_per_sqrt_s, realized_vol_60s, realized_vol_180s, spot_return_30s, spot_return_60s, spot_return_since_window_start, spot_perp_basis, binance_queue_imbalance, binance_ofi_best, perp_cvd_60s, depth_imbalance, yes_spread, no_spread, top_depth, quote_age_ms, yes_ask, no_ask

## Limitations / safety
- Uncalibrated; diagnostic-only artifacts are NON_TRADABLE.
- No P&L/backtest here; executable backtest + calibration are later steps.
- STAGING: DIAGNOSTIC_ONLY — written to data/models/staged/ when staged; the runtime (policy/lock) only scans data/models/ (non-recursive), so staged artifacts are NEVER auto-selected. Promotion is a SEPARATE explicit step (not performed here).
- Live trading disabled; live_approved=false; PAPER_CANDIDATE blocked.
