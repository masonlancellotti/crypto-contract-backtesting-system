# INTEGRATION_REGRESSION_REPORT.md

Final integration / regression pass (Prompt 9). Repo
`C:\Users\mason\Downloads\polymarket-btc-five-mins`.

**Snapshot:** 2026-06-02 (collectors live; counts tick up in real time).
**Scope:** repo-wide audit + fix concrete inconsistencies only. No new strategy, no
production training, no live enablement. Read-only verification; no orders/cancels;
no secrets read.

## 1. Executive summary
- Kalshi `KXBTC15M` is primary; Polymarket dormant/reference; Deribit native-optional
  (disabled by default) — all consistent across config, code, and docs.
- **Every audited CLI command runs (rc=0) or fails gracefully with a clear blocker.**
  35/35 commands in the sweep returned rc=0; the new `dependency-check` works.
- Tests: **396 passed** (`pytest -q`), ~12s, fully offline.
- Safety intact: live disabled, kill switch on, manual confirm required, submit
  disabled, dry-run-only, both adapters refuse, no order/cancel mutation, no market
  orders, no flat arb scanner, `live_submission_allowed` hard-False everywhere.
- One real change since prior prompts: the **backtest gate (60) is now reached**
  (gate ≈ 85–86). Training/calibration gate (150) is not. PAPER_CANDIDATE remains
  impossible (model is `NON_TRADABLE_DIAGNOSTIC_ONLY`, calibrator diagnostic).

## 2. Current state
- **Gate:** `gate_windows ≈ 86` (authoritative, feature-backed OFFICIAL windows;
  974 orphan labels excluded). Backtest gate **86/60 MET**; train gate **86/150**
  (~64 windows / ~16h at 4/h). usable_rows ≈ 10,800. Bottleneck = windows.
- **Source health / collector:** ACTIVE — Kalshi, Coinbase, Binance all fresh;
  Deribit disabled (optional). `kalshi-collector-status` reports ACTIVE without
  touching collector processes.
- **Model/training/calibration/backtest:** model artifacts =
  `NON_TRADABLE_DIAGNOSTIC_ONLY` (diagnostic logistic baselines); calibrator =
  diagnostic; backtest reports exist (diagnostic). Real training/calibration refuse
  below the 150 gate; backtest may now run non-diagnostic (gate met) but none is
  marked tradable. Diagnostic evidence shows no edge after costs.
- **Policy / lock:** policy REJECTS (model diagnostic) → no PAPER_CANDIDATE; lock
  module reports NO_POSITION (no open paper positions; not a flat arb scanner).
- **Live safety:** `LIVE TRADING DISABLED`; live-readiness state NOT_CONFIGURED;
  `live_submission_allowed=False`; dry-run order payloads validate + sanitize but are
  never sent.
- **Dependencies:** Python 3.13; numpy/pandas/scikit-learn/lightgbm/pyarrow/scipy/
  websockets/requests/cryptography **MISSING**; pyyaml + python-dotenv present.
  Stdlib fallback active (pure-Python models + JSONL/CSV). Reported by `dependency-check`.

## 3. Commands verified (all rc=0)
Core/readiness: `status`, `dependency-check`, `kalshi-data-readiness`,
`kalshi-label-audit`, `kalshi-clean-orphan-labels --dry-run`, `source-health`,
`kalshi-gate-progress`, `kalshi-collector-status`, `kalshi-train-dry-run`.
Dataset/training: `kalshi-build-model-dataset`, `kalshi-split-report`,
`kalshi-train-baselines --diagnostic-only`, `kalshi-train-model`(logistic via baselines).
Calibration/backtest: `kalshi-calibration-report`, `kalshi-calibrate-model --diagnostic-only`,
`kalshi-backtest-baselines --diagnostic-only`, `kalshi-backtest-model --diagnostic-only`,
`kalshi-threshold-sweep --diagnostic-only`, `kalshi-backtest-summary`, `kalshi-model-health`.
Policy/lock: `kalshi-policy-dry-run`, `kalshi-policy-report`, `kalshi-paper-policy-sim`,
`kalshi-lock-dry-run`, `kalshi-lock-sim`, `kalshi-lock-summary`, `kalshi-paper-summary`.
Live-readiness: `kalshi-live-blockers`, `kalshi-live-readiness`,
`kalshi-live-dry-run-order`, `kalshi-private-read-preflight`, `kalshi-safety-status`,
`check-live-disabled`.
Ops: `kalshi-ops-status`, `kalshi-collector-status`, `kalshi-doctor`,
`kalshi-eod-summary --write-report`, `kalshi-notify-test`, `kalshi-latency-benchmark`,
`kalshi-hotpath-smoke` (REST + synthetic fallback).
Commands depending on missing artifacts report a clear blocker and exit 0.

## 4. Fixes applied in this pass
- **Added `dependency-check`** (CLI + `ops.dependency_check`): reports Python version,
  optional dep availability, degraded features, recommended installs, stdlib-fallback
  note, and the "serious training needs the ML stack" warning. Never installs; never
  breaks collection/readiness/safety.
- Verified the freshly-met backtest gate does **not** unlock PAPER_CANDIDATE (policy
  still requires a non-diagnostic + calibrated model; confirmed in code + tests).
- Consolidated docs: new `ARCHITECTURE.md`, `MODEL_PIPELINE.md`, `LIVE_SAFETY.md`;
  `COMMANDS.md` updated; state docs refreshed (gate status, dependency-check).
- Added `tests/test_integration.py` (6): dependency-check structure + CLI, every
  command has a callable handler, all safe commands run on empty data, primary/
  dormant/optional invariants, safety invariants.
- No safety gate weakened; no Pusher; no live path created.

## 5. Test result
`pytest -q` → **396 passed** (offline, ~12s). No failures.

## 6. What still blocks trading (blunt)
1. **No approved model.** Only `NON_TRADABLE_DIAGNOSTIC_ONLY` diagnostic baselines
   exist; training/calibration gate (150 windows) not reached (~64 to go).
2. **No valid calibrator and no edge evidence.** Calibrator is diagnostic; diagnostic
   backtests show no edge after fees (market-implied trades 0; fitted baselines lose).
3. **Live intentionally locked.** Even with a good model, live needs a separate
   explicit enablement step (auth + approval file + flags + signed submit path), none
   of which exists here.

## 7. Next 3 actions
1. Keep collecting to the 150-window train/calibration gate; monitor with
   `kalshi-ops-status` / `kalshi-gate-progress`.
2. Once ≥150 windows: train + calibrate + run a non-diagnostic executable backtest;
   review `kalshi-model-health` + `kalshi-backtest-summary` for edge after costs.
3. Only if a model is genuinely edge-positive and calibrated, accumulate paper
   evidence via the policy; keep live disabled (separate explicit step later).

Safety: no live orders/cancels possible; live adapters refuse; no untrained/
uncalibrated/diagnostic model can emit PAPER_CANDIDATE; no flat arb scanner;
Polymarket dormant; Deribit optional. No secrets in this report.
