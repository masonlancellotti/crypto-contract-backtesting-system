# Kalshi model card — distance_time_vol

- tradability: **TRADABLE**
- tradable (usable by paper/live policy): **False**
- lifecycle: **STAGED_NON_PROMOTED**  (is_staged=True is_promoted=False promotion_required=True live_approved=False)
- model_backend: sklearn
- created_by_command: kalshi-train-baselines
- calibration_status: uncalibrated
- created_at: 2026-06-10T03:26:41.200034+00:00  created_at_ms: 1781062001200
- model_schema_version: 1

## Intended use
- Estimate P(YES resolves to 1) for Kalshi BTC 15m markets.
- Output is a PROBABILITY. A hard Up/Down class is a DIAGNOSTIC only and
  must never trigger a trade. Trading needs probability + executable EV +
  calibration + gates. This artifact is NOT calibrated, so it cannot emit
  PAPER_CANDIDATE and cannot be used live.

## Training data
- train_windows: 506  val_windows: 217
- train_rows: 81255  val_rows: 34140
- embargo_windows: 1  no_leak: True
- gate_windows: 724  training_ready: True

## Validation metrics (diagnostic; NOT a profitability claim)
- accuracy: 0.8002343292325718
- roc_auc: 0.894656577925288
- brier: 0.13300322346011295
- log_loss: 0.4061798922649735
- confusion_matrix: {'tp': 12678, 'tn': 14642, 'fp': 2612, 'fn': 4208}

## Features
- distance_to_start, distance_to_line_vol_normalized, seconds_to_close, fraction_window_elapsed, spot_sigma_per_sqrt_s, realized_vol_60s, realized_vol_180s

## Limitations / safety
- Uncalibrated; diagnostic-only artifacts are NON_TRADABLE.
- No P&L/backtest here; executable backtest + calibration are later steps.
- STAGING: STAGED_NON_PROMOTED — written to data/models/staged/ when staged; the runtime (policy/lock) only scans data/models/ (non-recursive), so staged artifacts are NEVER auto-selected. Promotion is a SEPARATE explicit step (not performed here).
- Live trading disabled; live_approved=false; PAPER_CANDIDATE blocked.
