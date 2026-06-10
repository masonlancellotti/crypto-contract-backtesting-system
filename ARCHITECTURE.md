# ARCHITECTURE — Kalshi BTC 15m

Concise map of the system after the prompt 0–9 build. Authoritative current state
lives in `PROJECT_STATE.md` + `RESEARCH_LEDGER.md`; copy-paste commands in `COMMANDS.md`; model
details in `MODEL_PIPELINE.md`; safety in `LIVE_SAFETY.md`.

## Venues & feeds
- **Primary venue: Kalshi `KXBTC15M`** (BTC up in next 15 min, Up/Down binary).
  Public REST market data needs no auth. Target = calibrated
  `P(YES/Up resolves to 1)`; settlement = 60s-avg **CF Benchmarks BRTI** at close ≥ open (GTE, tie→YES).
- **Removed 2026-06-10: Polymarket BTC 5m** — the legacy leg lives in git
  history only (commit "Remove dormant Polymarket BTC 5m leg"); formerly guarded by
  `POLYMARKET_DORMANT=true`; not in the default pipeline; live adapter refuses.
- **Core underlying feeds:** Coinbase BTC-USD spot (primary reference) + Binance
  USDT-M perp (basis/microprice/OFI + spot fallback), public REST polling.
- **Deribit:** NATIVE OPTIONAL vol/options/regime source (disabled by default);
  point-in-time joined into feature rows with freshness flags; never required.

## Decision principle
`calibrated model probability + executable YES/NO ASK price − fees − depth/slippage
− uncertainty − staleness/risk gates = decision`. Executable asks are the complement
of the opposite side's best bid (`yes_ask = 1 − best_no_bid`). **No midpoint fills.**
A hard Up/Down class is a **diagnostic only** — it never triggers a trade.

## Pipeline stages (each gated & live-disabled)
```
collectors (REST) ─► raw/normalized JSONL ─► point-in-time v3 feature rows ─► OFFICIAL labels
   │                                                                              │
   ├─ source-health / readiness / label-audit (orphans excluded)                 │
   ▼                                                                              ▼
model dataset (feature-backed official only, no look-ahead)  ◄── purge/embargo by 15m window
   ▼
baselines (market-implied · distance/time/vol · microstructure)  [pure-stdlib; numpy/sklearn optional]
   ▼
calibration (isotonic/Platt, held-out) ─► executable backtest (ask prices, fees, depth) ─► threshold sweep
   ▼
paper-candidate POLICY (calibrated P + executable EV + validity/freshness/risk gates)
   ▼
paper ledger ─► post-entry LOCK-PROFIT (monitor opposite leg; paper-only)
   ▼
live-readiness scaffolding (DRY-RUN ONLY; refuses; never submits)
   ▲
ops/monitoring (read-only): ops-status · collector-status · gate-progress · doctor · EOD
```

## Source layout (`src/btc5m/`)
- `venues/kalshi/` — `client`, `orderbook`, `fees`, `settlement`, `readiness`,
  `labels_audit`, `features`, `deribit_features`, `source_health`, `collector`,
  `paper`, `train_prep`, `model_dataset`, `feature_schema`, `splits`,
  `train_baselines`, `model_artifacts`, `calibrate`, `calibration_report`,
  `executable_backtest`, `threshold_sweep`, `policy`, `policy_runtime`,
  `lock_profit`, `lock_runtime`, `local_book`, `ws_client`, `hotpath_state`,
  `scorer`, `latency`, `low_latency_runtime`, `order_planner`, `live_readiness`, `ops`.
- `models/` — `baseline` (uncalibrated normal), `calibration` (isotonic), `pure_ml`
  (stdlib LogisticRegression/StandardImputer/metrics); LightGBM/quantile are scaffolds.
- `data/` — Coinbase/Binance REST, Deribit client, recorder; WS adapters scaffold.
- `execution/` — `risk` (RiskManager), `paper`, `live_kalshi` (refusal adapter),
  `live_kalshi` (refuses every order).
- `notifications/` — Pushover (stdlib urllib) + Noop fallback (no Pusher).

## Dependencies
Core runs on **stdlib + pyyaml + python-dotenv only**. numpy/pandas/scikit-learn/
lightgbm/pyarrow are OPTIONAL (`pip install -e ".[models]"`); when absent the repo
uses pure-Python models + JSONL/CSV output and reports degraded features via
`dependency-check`. ML deps (numpy/pandas/sklearn/lightgbm) and `cryptography` are installed in the working venv; WS auth additionally needs Kalshi API credentials.

## Safety posture
Paper/record-only by default; `LIVE_TRADING_ENABLED=false`, kill switch on, manual
confirmation required, live submit disabled, dry-run-only. Both venue live adapters
refuse; no order/cancel HTTP mutation; no market orders; `live_submission_allowed`
is hard-False at every layer. PAPER_CANDIDATE is impossible without a trained +
calibrated + non-diagnostic + backtested model. See `LIVE_SAFETY.md`.
