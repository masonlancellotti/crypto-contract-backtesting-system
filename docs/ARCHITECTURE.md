# Architecture — Kalshi crypto 15-minute binary markets

A concise map of the system: how market data becomes leakage-safe features, how a
calibrated probability becomes (at most) a gated paper candidate, and why nothing
here can submit a live order. Model details live in `MODEL_PIPELINE.md`; the
alpha-discovery engine in `ALPHA_DISCOVERY.md`; every research verdict in
`RESEARCH_LEDGER.md`; copy-paste commands in `COMMANDS.md`; operations in
`RUNBOOK.md`.

## Venues & feeds
- **Primary venue: Kalshi `KXBTC15M`** (BTC up in the next 15 minutes, up/down
  binary). Public REST market data needs no auth. Target = calibrated
  `P(YES/Up resolves to 1)`; settlement = 60-second-average **CF Benchmarks BRTI**
  at close ≥ open (GTE comparison, tie → YES).
- **Multi-asset:** the pipeline is series-parameterized; `KXETH15M`, `KXSOL15M`,
  `KXDOGE15M`, and `KXXRP15M` parse identically with per-asset spot/perp feeds.
- **Core underlying feeds:** Coinbase BTC-USD spot (primary reference) + Binance
  USDT-M perp (basis / microprice / order-flow imbalance, and spot fallback),
  public REST polling.
- **Deribit:** a native, optional volatility/options/regime source (disabled by
  default); joined point-in-time into feature rows with freshness flags; never
  required and never a directional signal.
- A legacy Polymarket BTC 5-minute leg was removed in git history once that
  account was parked; venue semantics are archived under `docs/archive/`.

## Decision principle
`calibrated model probability + executable YES/NO ASK price − fees − depth/slippage
− uncertainty − staleness/risk gates = decision`. Executable asks are the
complement of the opposite side's best bid (`yes_ask = 1 − best_no_bid`), verified
equal to Kalshi's own asks. **No midpoint fills.** A hard up/down class is a
**diagnostic only** — it never triggers a trade.

## Pipeline stages (each gated and live-disabled)
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

## Feature cadence abstraction (REST default, sub-second optional)
Every downstream consumer funnels through a small set of loader functions that
operate on the `kalshi_feature_rows` schema, so cadence is a single selector rather
than a fork. `feature_source.py` exposes `REST` (≈1–4 s recorded feature rows, the
default) and `HIRES` (sub-second WebSocket joined snapshots adapted into the *same*
schema). A single `--feature-source {rest,hires}` flag sets `config.feature_source`,
which flows to dataset build, readiness, train/calibrate/backtest, gate reporting,
and the paper/decision row source without per-signature churn. Hires rows are an
honest feature *subset* (no Kalshi bids/depth, CVD/OFI, Deribit, or long-horizon
vols); the missingness report surfaces the nulls. REST behaviour is byte-identical
when the flag is absent, and the path is read-only.

## Source layout (`src/btc5m/`)
- `venues/kalshi/` — `client`, `orderbook`, `fees`, `settlement`, `readiness`,
  `labels_audit`, `features`, `feature_source`, `deribit_features`, `source_health`,
  `collector`, `paper`, `train_prep`, `model_dataset`, `feature_schema`, `splits`,
  `train_baselines`, `model_artifacts`, `calibrate`, `calibration_report`,
  `executable_backtest`, `threshold_sweep`, `policy`, `policy_runtime`,
  `lock_profit`, `lock_runtime`, `local_book`, `ws_client`, `hotpath_state`,
  `scorer`, `latency`, `low_latency_runtime`, `order_planner`, `live_readiness`,
  `ops`, `maker_entry`, `reprice_lag` (+ `reprice_lag_hires`), `residual_alpha`,
  and the `hires/` recorder.
- `discovery/` — the alpha-discovery engine (metrics, gauntlet, CPCV, holdout
  vault, registry, feature factory, panel, screen, search, engine). See
  `ALPHA_DISCOVERY.md`.
- `models/` — `baseline` (uncalibrated normal), `calibration` (isotonic), `pure_ml`
  (stdlib logistic regression / standard imputer / metrics); LightGBM and quantile
  models are optional challengers.
- `data/` — Coinbase/Binance REST clients, Deribit client, recorder.
- `execution/` — `risk` (RiskManager), `paper`, `live_kalshi` (refusal adapter).
- `notifications/` — Pushover (stdlib urllib) with a Noop fallback.

## Dependencies
The core runs on **stdlib + pyyaml + python-dotenv only**. numpy / pandas /
scikit-learn / lightgbm / pyarrow are optional (`pip install -e ".[models]"`); when
absent the repo uses pure-Python models and JSONL/CSV output and reports degraded
features via `dependency-check`. `cryptography` and WebSocket auth are only needed
for the (disabled) live path and read-only authenticated market-data WebSocket.

## Safety model (live trading disabled and unimplemented)
Live trading is disabled by default and impossible without a separate, explicit,
intentionally-unimplemented enablement step. Nothing in this build can submit or
cancel a real order.

**Safe defaults:** `TRADING_MODE=paper`, `LIVE_TRADING_ENABLED=false`,
`KILL_SWITCH_ENABLED=true`, `REQUIRE_MANUAL_CONFIRMATION=true`,
`KALSHI_LIVE_SUBMIT_ENABLED=false`, `KALSHI_LIVE_DRY_RUN_ONLY=true`,
`KALSHI_ALLOW_MARKET_ORDERS=false`.

**Why no order can be submitted:**
- The live Kalshi execution adapter's `submit()` / `cancel()` always return a
  structured refusal and issue no HTTP (tested: `urlopen` call count is 0 under
  default config); a hard `_http_mutation` guard blocks mutation.
- `live_submission_allowed` is a hard-`False` property on every readiness config,
  policy decision, lock decision, dry-run order payload, and order intent.
- There is no `LIVE_CANDIDATE`, `SUBMITTED`, or `LIVE_FILLED` state. Market orders
  are rejected; only limit + FOK/IOC dry-run payloads are ever built.

**Why a bad model cannot produce a candidate:** the paper-candidate policy requires
*all* of — policy enabled, model trained, model non-diagnostic, calibrator valid and
non-diagnostic, backtest evidence above gate, calibrated probability present,
executable asks and a valid book, net and raw edge over threshold, price within
reservation and cap, fresh book/underlying, spread/depth acceptable, time-in-window,
and risk limits. A hard up/down class alone never trades.

**Credentials & secrets:** Kalshi auth (`KALSHI_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH`)
is environment-only; the RSA key lives in a gitignored local file. No key material,
passphrase, or auth header is ever read or printed — credential preflight reports
presence/readability only. Missing credentials are blockers, never prompts.

**Verify anytime (read-only):**
```powershell
python -m btc5m.cli kalshi-safety-status --series KXBTC15M
python -m btc5m.cli kalshi-live-blockers --series KXBTC15M
python -m btc5m.cli check-live-disabled
```
Expected: `LIVE TRADING DISABLED`, every blocker listed, the adapter refuses.

## Core invariants (do not weaken)
- Executable prices only (asks for taker entries; never midpoint). Fees are always
  subtracted (`KalshiFeeModel`; the rate is ASSUMED until verified against the
  official schedule).
- OFFICIAL labels only for training; orphan labels (official result, no feature
  rows) are excluded and can never inflate the gate. Purge/embargo on whole 15-minute
  windows; `as_of_ms < close_ms` (no look-ahead). One authoritative `gate_windows`
  count.
- Staged artifacts are inactive; the runtime loads model + calibrator only from an
  explicit, SHA-pinned paper-promotion manifest — never newest-by-mtime, never a
  staged or diagnostic artifact. Promotion and demotion are explicit, audited
  commands.
- Stale data can never become a paper candidate (decision-freshness gates are strict
  and separate from loose liveness thresholds).
- Uncertainty buffers are honest measurements — recalibrate to shrink them; never
  delete them.
