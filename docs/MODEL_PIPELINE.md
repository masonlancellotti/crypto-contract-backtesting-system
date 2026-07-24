# MODEL_PIPELINE — Kalshi BTC 15m

How a probability becomes (eventually) a paper candidate. Everything is gated and
pure-stdlib by default; nothing here trains a production model or enables live.

## 1. Labels & gate (orphans can never unlock anything)
- OFFICIAL settlement labels come from Kalshi `result` once finalized.
- **gate_windows (authoritative)** = distinct OFFICIAL-labeled 15-minute windows with
  ≥1 *usable executable book-backed* feature row (`readiness.feature_row_usable`:
  has Kalshi book + BTC underlying + pre-close + valid book).
- Counts narrow: `official_binary_labels` ≥ `feature_backed_official_windows`
  (presence) ≥ `gate_windows` (usable). **Orphan labels** (official result, no feature
  rows) are EXCLUDED and cannot inflate the gate. Underlying-only rows (no Kalshi book)
  are never executable examples.
- Thresholds: **backtest gate = 60 windows**, **train/calibration gate = 150 windows**
  (and ≥500 usable rows). Check with `kalshi-gate-progress` / `kalshi-data-readiness`.

## 2. Dataset (`kalshi-build-model-dataset`)
- Joins point-in-time v3 feature rows to **feature-backed OFFICIAL labels only**.
- **No look-ahead:** feature `as_of_ms < close_ms`; every dropped row is counted
  with a reason. Output JSONL/CSV (+ metadata/schema/missingness/gate reports);
  parquet only if pandas/pyarrow present, else JSONL fallback.

## 3. Feature schema & leakage (`feature_schema.py`)
- Explicit, versioned groups A–G (contract/time, Kalshi book, returns, volatility,
  microstructure, Deribit-optional, source-health). Each feature typed + marked
  required/optional + allowed-for-training.
- **Leakage exclusions (never in the training matrix):** `label_yes_resolved`,
  `label_source_status`, `result`, settlement/post-close fields, `paper_pnl`,
  `decision_state`/`fill_status`, and non-stationary price LEVELS (`reference_price`,
  raw bids/asks levels, microprice). `assert_no_leakage` enforces this.
- Old v2 / new v3 rows coexist; missingness flags + `feature_set_version` are reported.

## 4. Splits (`splits.py`, `kalshi-split-report`)
- **Window-level** (never row-level) chronological train/val + 3-way train/calib/test,
  plus walk-forward folds. **Mandatory purge/embargo** of ≥1 full 15m window between
  segments; a leak check verifies train horizons end before validation.

## 5. Baselines (`train_baselines.py`, `kalshi-train-baselines`)
- **Market-implied** (benchmark, no fit), **distance/time/vol logistic**,
  **microstructure logistic** — pure-Python `models/pure_ml.LogisticRegression`
  (mean-impute + standardize). LightGBM/XGBoost block on the missing optional dep.
- REAL training refuses below the 150-window gate; `--diagnostic-only` fits
  NON-TRADABLE sanity models. A hard Up/Down class is reported only as a diagnostic.

## 6. Artifacts (`model_artifacts.py`)
- Bundle model params + feature schema + imputer + split metadata + metrics. Stamped
  `TRADABLE` only at/above gate; `is_tradable()` additionally requires
  `calibration_status == "calibrated"`. Diagnostic/below-gate ⇒
  `NON_TRADABLE_DIAGNOSTIC_ONLY`.

## 7. Calibration (`calibrate.py`, `kalshi-calibration-report` / `kalshi-calibrate-model`)
- Pure-Python isotonic (PAV) / Platt / identity, fit on HELD-OUT calib windows
  (never model-fit rows). Metrics: Brier, log-loss, ECE, reliability, slope/intercept,
  before/after. Below gate ⇒ diagnostic, calibrator stamped NON_TRADABLE.

## 8. Executable backtest (`executable_backtest.py`, `kalshi-backtest-*`)
- Simulates the real decision at each held-out row: model P → executable YES/NO **ask**
  (never midpoint) → fees → depth/staleness/spread/time gates → settle vs OFFICIAL
  label. Reports net P&L, hit rate, drawdown, P&L by bucket; baselines incl. no-trade
  floor. `kalshi-threshold-sweep` sweeps gates and **never auto-selects** a policy
  (overfit warning). Current evidence: no tradable edge after costs.

## 9. Paper-candidate policy (`policy.py`, `kalshi-policy-*`)
- `WATCH / MANUAL_REVIEW / REJECTED / PAPER_CANDIDATE` from calibrated probability +
  executable EV + reservation prices, with reason codes. **PAPER_CANDIDATE requires
  policy enabled + trained + calibrated + non-diagnostic + backtested model passing
  every gate.** No `LIVE_CANDIDATE`. Today: REJECTED (model diagnostic).

## 10. Post-entry lock-profit (`lock_profit.py`, `kalshi-lock-*`)
- After a paper directional fill, monitors the OPPOSITE leg to lock guaranteed profit
  after fees (`1 − yes_total_cost − no_total_cost`), deciding LOCK/RIDE/WATCH/REJECT.
  Position management, **not** a flat arb scanner; paper-only; never live.

> Status (2026-06-10): gate = 770 windows -> BOTH gates passed. A fresh
> microstructure_logistic + isotonic pair (held-out ECE 0.026) is promoted for
> PAPER ONLY. No edge is demonstrated (see RESEARCH_LEDGER.md); the policy
> correctly emits no PAPER_CANDIDATEs.
