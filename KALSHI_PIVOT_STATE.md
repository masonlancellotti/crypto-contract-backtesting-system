# KALSHI_PIVOT_STATE.md

> Read this first. The project's PRIMARY venue is now **Kalshi BTC 15-minute
> Up/Down** (series **KXBTC15M**). Polymarket BTC 5m is **parked/dormant**.

## Identity
- **Primary venue:** Kalshi
- **Primary series:** KXBTC15M (BTC "up in next 15 mins?", 15-minute Up/Down)
- **Target:** P(Kalshi YES/Up resolves to 1 at the 15-minute window close)
- **Decision problem:** is YES or NO mispriced vs the model's calibrated
  settlement probability after executable bid/ask, depth, fees, staleness,
  latency, and risk gates?
- **Mode:** record-only / paper-first. Live infrastructure is built but **live
  orders are blocked by default**.
- **Polymarket status:** PARKED / DORMANT (account/funding). Legacy BTC 5m code
  still exists under `btc5m.data` / `btc5m.discovery` / `btc5m.labels` and is
  guarded by `venues/polymarket/require_polymarket_enabled` (set
  `POLYMARKET_DORMANT=false` to run it manually). Not in the default pipeline.

## Verified against the LIVE Kalshi API (2026-06-01)
- Base `https://external-api.kalshi.com/trade-api/v2` answers 200 and **public
  market data needs NO auth** (also works via `api.elections.kalshi.com`; legacy
  `trading-api.kalshi.com` returns 401/moved).
- `GET /series/KXBTC15M` → exists (category Crypto, contract terms CRYPTO15M.pdf).
- `GET /markets?series_ticker=KXBTC15M&status=open|unopened|settled` → markets
  exist; ticker `KXBTC15M-<YYMONDD><HHMM>-<MM>`; status `active`→open, `finalized`→settled.
- Market detail: `title` "BTC price up in next 15 mins?"; `yes_sub_title` carries
  the **start "Target Price"**; 15-min window = `[open_time, close_time]`;
  `result` ∈ {"", "yes", "no"} is the OFFICIAL settlement; `*_dollars`/`*_fp`
  fields are fixed-point.
- Rules: YES if 60-second-average **CF Benchmarks BRTI** at close ≥ at open
  (GTE; **BRTI, not Chainlink** — do not reuse Polymarket logic).
- `GET /markets/{ticker}/orderbook` → `orderbook_fp.{yes_dollars,no_dollars}` =
  ascending `[price,size]` **bid** arrays (best bid = max price). **Executable
  asks (verified == Kalshi's own):** `yes_ask = 1 - best_no_bid`,
  `no_ask = 1 - best_yes_bid`.

## Working commands (verified live unless noted)
- `kalshi-discover --series KXBTC15M [--status open|all] [--max-markets N]` —
  verified: returned 1 current + 80 upcoming + 1000 settled, classified by phase.
- `kalshi-nearest-markets --series KXBTC15M [--max-markets N]` — READ-ONLY diagnostic for
  discovery `cur=0`: nearest CURRENT/UPCOMING markets with open/close times, seconds-to-open/close,
  status, classified phase, and BOTH current UTC + Kalshi server time (exposes clock skew).
  Verified live: `cur=1` with the active `status='active'` market marked `>>`.
  Classification is **status-aware**: Kalshi's explicit `status='active'`/`open` ⇒ CURRENT_IN_WINDOW
  (even at/just-before `open_time`); `initialized`/`unopened` ⇒ UPCOMING (not yet tradeable);
  open/close timing is the fallback only when status is missing. This fixed `cur=0` despite a live
  15-minute market (the old timing-only rule demoted a tradeable market to UPCOMING at the boundary).
- `kalshi-collector-targets --series KXBTC15M [--max-markets N]` — READ-ONLY: shows exactly what
  `kalshi-collect-continuous` would SELECT to record this cycle and why, mirroring its
  rediscover + `select_collection_targets` path. Target selection is **phase-prioritized**: the
  active `CURRENT_IN_WINDOW` market is always chosen FIRST, then nearest `UPCOMING` (recorded for
  backfill, never scored), then `CLOSED_PENDING_SETTLE`. This fixed the collector recording the
  just-closed market instead of the active one at a window boundary (a just-closed market still
  returns `status='active'` for a settlement period; the old close-ascending `keep[:max_markets]`
  put its earlier close-time ahead of the active market, so with `--max-markets 1` it grabbed the
  only slot — and the active ticker was never recorded). Heartbeat/session now print
  `selected_current_tickers` / `selected_upcoming_tickers` / `selected_closed_tickers`.
- `kalshi-inspect --ticker <T>` / `--url <U>` — metadata + normalized executable book.
- `kalshi-record --series KXBTC15M --seconds 900 --interval 1 --max-markets 4`
  (or `--ticker <T>`) — writes raw + normalized orderbooks.
- `record-underlying --seconds 900 --sources coinbase,binance` — BTC feeds (reused).
- `run-kalshi-paper-pipeline --seconds 900 --sources coinbase,binance` — verified
  end-to-end in a temp dir: discovered, recorded books + underlying, built feature
  rows, ran the baseline model, wrote ledger + session summary (0 PAPER_CANDIDATEs
  — correct, model uncalibrated).
- `kalshi-collect-continuous --series KXBTC15M --sources coinbase,binance --seconds-per-cycle 900 --interval 1 --max-markets 4 --readiness-every 1 --backfill-every 1` — single-process continuous loop (rediscover → record books + underlying → rich features → backfill → readiness → heartbeat); Ctrl-C safe. Also `.\scripts\collect_kalshi_continuous.ps1`.
- `kalshi-backfill-settlements --series KXBTC15M` — labels settled windows by OFFICIAL result.
- `kalshi-label-audit --series KXBTC15M` — total/deduped/orphan/feature-backed labels + gate counts.
- `kalshi-clean-orphan-labels --series KXBTC15M [--dry-run|--write]` — dedup + compact to SEPARATE files (a full `*_compacted-*` with `is_orphan`/`gate_eligible` tags AND a clean `kalshi_training_labels-*` holding ONLY gate-eligible official labels); raw files never touched.
- `kalshi-train-dry-run --series KXBTC15M [--embargo-windows N]` — joins usable executable rows to OFFICIAL labels, groups by window, applies purge/embargo, reports columns + per-column missingness + label balance, then REFUSES to train below the gate. Never fits a model, never trades.
- `kalshi-data-readiness` — category-split readiness with ONE authoritative `gate_windows`; honest split of `official_binary_labels` vs `feature_backed_official_windows` (presence) vs `gate_windows` (usable) vs `orphan_labels`.
- `source-health --series KXBTC15M` — per-source enabled/implemented/freshness/staleness/used-in-features (kalshi, coinbase, binance, deribit) + notifier. Deribit is reported NON-CONTRADICTORILY: `implemented` (code exists) is separate from `enabled_by_config`; `historical_rows_present` / `disabled_by_config_but_rows_present` / `joined_into_feature_rows` / `selected_for_model_features` are distinct facts, so "disabled but rows on disk" never looks like a bug.
- **Source freshness — LIVENESS vs DECISION are SEPARATE (do not mix).** `source-health` now reports, per source, `liveness_*` (alive? loose ~60s) AND `decision_*` (trade-fresh? strict ~1s book / ~5s underlying) plus `fresh_for_collection/decision/training/paper_candidate`. A collector can be ALIVE while DECISION-stale (e.g. Coinbase age 33s: liveness-fresh under 60s, decision-stale over 5s). The underlying group reports `underlying_liveness_ok` AND `underlying_decision_ok` with explicit **Binance fallback** (Coinbase primary; Binance stands in only when `UNDERLYING_ALLOW_BINANCE_FALLBACK` AND itself decision-fresh; both-stale ⇒ not fresh). The paper runtime enforces a strict decision-freshness gate (`freshness.paper_candidate_freshness`) so **STALE data can NEVER become a PAPER_CANDIDATE** — book/underlying decision-stale ⇒ REJECTED (`BOOK_DECISION_STALE` / `UNDERLYING_BOTH_STALE` / `UNDERLYING_DECISION_STALE`). Thresholds are config-driven (`config.freshness`; `KALSHI_BOOK_DECISION_MAX_AGE_MS`, `COINBASE/BINANCE_DECISION_MAX_AGE_MS`, `UNDERLYING_*`, `KALSHI_REJECT_PAPER_IF_*`). Decision records + shadow ledger + `policy-report` carry the freshness fields. WebSocket feed adapters remain scaffolds; REST polling (1s) is the live path.
- `record-deribit --currency BTC --seconds 60 --interval 15` — OPTIONAL public Deribit snapshot (index, DVOL, hist-vol, near-expiry/ATM IV, OI + put/call split, volume, skew); no-op blocker when `DERIBIT_ENABLED=false`. Public reads need NO credentials. Persists per `DERIBIT_RECORD_RAW`/`DERIBIT_RECORD_NORMALIZED`.
- Deribit-with-collector: `kalshi-collect-continuous --series KXBTC15M --sources coinbase,binance,deribit ...` (set `DERIBIT_ENABLED=true`). Deribit is polled on its own loose interval (`DERIBIT_POLL_INTERVAL_SECONDS`, default 30s) and joined point-in-time into feature rows; the Kalshi book loop never blocks on it. `--sources …,deribit` with `DERIBIT_ENABLED=false` prints an explicit skip blocker (never silently ignored).
- **Deribit model-feature selection (separate from collection):** `DERIBIT_INCLUDE_IN_MODEL_FEATURES` (default false) decides whether the `deribit_*` columns enter the model CANDIDATE feature group. It is independent of `DERIBIT_ENABLED`: a disabled Deribit whose columns linger on historical v3 rows is NEVER silently fed to the model. Using leftover columns while disabled additionally requires `DERIBIT_ALLOW_HISTORICAL_FEATURES_WHEN_DISABLED=true`. `kalshi-build-model-dataset` / `kalshi-train-dry-run` report `candidate_feature_group_status` ∈ {INCLUDED, EXCLUDED_BY_CONFIG, UNAVAILABLE, STALE} and distinguish column-presence from selection.
- `kalshi-auth-smoke` — verified: no keys → public usable, no secrets printed.
- `check-live-disabled` — verified: BOTH Kalshi and Polymarket adapters refuse.
- `kalshi-hotpath-smoke --series KXBTC15M --seconds 30 --max-markets 1 --sources coinbase,binance` — PAPER-ONLY low-latency hot-path smoke (in-memory book→features→scorer→executable EV→gates→WATCH/MANUAL_REVIEW/REJECTED). Degrades to synthetic ticks if offline. No orders.
- `kalshi-latency-benchmark --series KXBTC15M --samples 1000` — offline/synthetic p50/p90/p99 latency for feature build, model score, EV decision. No network, no creds, no orders.
- `kalshi-build-model-dataset --series KXBTC15M [--format jsonl|csv|parquet] [--feature-version all|latest] [--strict] [--include-deribit auto|true|false]` — join feature-backed OFFICIAL labels (orphans excluded) → model-ready table + metadata/schema/missingness/gate reports under `data/models/` + `reports/models/`. Marks `NOT_TRAINING_READY` below the gate. No training.
- `kalshi-split-report --series KXBTC15M [--embargo-windows N]` — purged/embargoed window-level chronological + walk-forward splits (train/val/embargo windows, rows, label balance, leak check).
- `kalshi-train-baselines --series KXBTC15M [--diagnostic-only]` — market-implied + distance/time/vol + microstructure logistic baselines. REFUSES below the train gate unless `--diagnostic-only` (which fits NON-TRADABLE toy models). Models stay UNCALIBRATED → never PAPER_CANDIDATE.
- `kalshi-train-model --series KXBTC15M --model logistic|lightgbm` — single model; `logistic` refuses below gate (or `--diagnostic-only`); `lightgbm` blocks (optional dep not installed) — never faked.
- `kalshi-calibration-report --series KXBTC15M [--method isotonic|platt|identity]` — before/after calibration (Brier/log-loss/ECE/reliability) on HELD-OUT test windows (3-way train/calib/test, purged/embargoed). Report only; diagnostic below gate.
- `kalshi-calibrate-model --series KXBTC15M --method isotonic [--diagnostic-only]` — fit + (gated) save a calibrator artifact; below gate requires `--diagnostic-only` → stamped NON_TRADABLE_DIAGNOSTIC_ONLY.
- `kalshi-backtest-baselines --series KXBTC15M [--diagnostic-only]` — executable backtest of no-trade / market-implied / distance-time-vol / microstructure (+ model if an artifact exists), leakage-safe (fit on train, eval on held-out val), walk-forward stability. EVIDENCE only.
- `kalshi-backtest-model --series KXBTC15M --model latest --calibrator latest [--diagnostic-only]` — executable backtest of a saved artifact (+ optional calibrator); pre-trained artifact is in-sample ⇒ diagnostic.
- `kalshi-threshold-sweep --series KXBTC15M [--diagnostic-only]` — sweep min-net-edge × max-book-age × max-underlying-age; per-config economics + walk-forward spread; **never auto-selects a policy**.
- `kalshi-policy-dry-run --series KXBTC15M [--limit N] [--policy-format table|json|jsonl] [--include-rejected]` — evaluate the paper-candidate policy over recent rows; prints decisions + validity + can-emit blockers. No orders.
- `kalshi-policy-report --series KXBTC15M [--limit N]` — decisions-by-state, reason counts, edge distribution, model/calibration/backtest validity, source-health, and whether PAPER_CANDIDATE can be emitted. Writes `reports/models/kalshi_policy_report-*.md`.
- `kalshi-paper-policy-sim --series KXBTC15M --limit N` — simulate paper fills for PAPER_CANDIDATE decisions (settle vs OFFICIAL label) → `data/paper/kalshi_policy_paper_ledger-*.jsonl`. `live_submission_allowed=false`; emits nothing when blocked.
- `kalshi-lock-dry-run --series KXBTC15M [--ticker T] [--lock-mode fok|ioc] [--allow-partial]` — POST-ENTRY lock-profit on OPEN paper positions (held YES→monitor NO, held NO→monitor YES). Reports NO_POSITION when none exist; never scans flat markets; no orders.
- `kalshi-lock-sim --series KXBTC15M --limit N` — replay: would a lock have triggered later for each open paper position? Reports locked-vs-naked exposure + lock-vs-ride P&L (diagnostic, paper-only).
- `kalshi-position-monitor-dry-run / kalshi-position-monitor-sim / kalshi-position-summary --series KXBTC15M` — POST-ENTRY position **lifecycle** manager: for an EXISTING paper position it compares same-leg SELL value vs opposite-leg LOCK value vs updated continue/ride EV (CURRENT calibrated probability, not entry-time belief) and decides HOLD/RIDE / SELL_SAME_LEG / LOCK_WITH_OPPOSITE_LEG / PARTIAL_LOCK / RISK_EXIT / WATCH. Reuses the lock module; executable bids/asks only; reports NO_POSITION when none exist; never scans flat markets; paper-only; no live orders.
- `kalshi-frequency-report / kalshi-frequency-sweep / kalshi-marginal-trade-curve / kalshi-time-to-close-analysis / kalshi-within-window-frequency --series KXBTC15M` — TRADE-FREQUENCY frontier / overtrading **analysis** (research/reporting only). Score constantly, trade selectively: measures marginal net edge vs trade frequency on a leakage-safe held-out set (frequency frontier, marginal-trade curve, time-to-close buckets, within-window concentration). Distinct windows matter more than raw trades. Fees + executable prices (no midpoint); NON_TRADABLE until a calibrated model exists; no policy promotion (staged suggestion JSON `promoted=false`); reports → `reports/frequency/`; no live.
- `kalshi-edge-policy-report / kalshi-edge-threshold-sweep --series KXBTC15M` — CONFIDENCE-AWARE edge threshold / reservation-price **policy** (paper-only). Does NOT trade on `model_prob > price`: uses a conservative probability bound (YES p_lower / NO 1−p_upper) minus fees + depth + staleness + model/calibration (Wilson reliability buckets) + regime + overtrading + minimum-profit buffers → final policy edge + reservation price. Required edge rises when uncalibrated/thin-sample/stale/volatile/concentrated. Conservative defaults (min raw 5c, require confidence bounds); rejects uncalibrated/diagnostic models; no policy promotion; reports → `reports/edge/`; no live. Lifecycle ride EV can use `conservative_continue_ev`.
- `kalshi-live-blockers --series KXBTC15M` — print every live blocker + next actions (no network mutation; no orders).
- `kalshi-live-readiness --series KXBTC15M [--from-policy-latest|--from-lock-latest] [--json] [--verbose]` — full live-readiness report (credentials w/o values, model/calibration/backtest/paper-evidence/risk/source-health/order-plan); `live_submission_allowed=false`; writes a sanitized audit row.
- `kalshi-live-dry-run-order --series KXBTC15M --ticker T --side YES --action buy --qty 1 --price 55 --tif fill_or_kill` — validate + build a SANITIZED dry-run order payload (+ checksum + documented endpoint); NEVER submitted.
- `kalshi-private-read-preflight --series KXBTC15M --allow-private-read` — reports whether read-only private endpoints could be called; calls NONE in this build; no secrets printed.
- **Ops/monitoring (READ-ONLY; safe while collectors run):** `kalshi-ops-status` (unified dashboard), `kalshi-collector-status` (ACTIVE/DEGRADED/STALLED from file freshness — never touches collectors), `kalshi-gate-progress` (window gate + capture-rate ETA), `kalshi-model-health`, `kalshi-backtest-summary`, `kalshi-paper-summary`, `kalshi-lock-summary`, `kalshi-safety-status` (LIVE TRADING DISABLED), `kalshi-doctor` (pass/warn/fail; `--run-tests`), `kalshi-eod-summary` (short notification + report), `kalshi-notify-test`. All support `--json`/`--markdown`/`--write-report`; reports land in `reports/ops` & `reports/eod`. Helper scripts in `scripts/` (ops_status/check_sources/check_readiness/doctor/eod_summary/safety_check). Full cheat sheet: `COMMANDS.md`.
- `dependency-check` — reports Python version + optional ML/data deps (numpy/pandas/sklearn/lightgbm/pyarrow/scipy/websockets/cryptography) and which features degrade to the stdlib fallback; recommends `pip install -e ".[models]"` for serious training. Missing optional deps never break collection/readiness/safety.
- **Consolidated docs (Prompt 9):** `ARCHITECTURE.md` (system map), `MODEL_PIPELINE.md` (labels→gate→dataset→baselines→calibration→backtest→policy→lock), `LIVE_SAFETY.md` (why nothing can submit), `INTEGRATION_REGRESSION_REPORT.md` (final audit). Final regression pass: all CLI commands run or block cleanly; **396 tests pass**; backtest gate (60) reached, train gate (150) pending; PAPER_CANDIDATE still impossible (diagnostic model); live disabled.

## Implemented (this pivot)
- `venues/kalshi/`: `client.py` (public REST + discovery + phase classification +
  ticker/URL parse), `orderbook.py` (Decimal yes/no-bid → executable asks + depth
  walk + validity flags), `fees.py` (configurable, ASSUMED), `settlement.py`
  (official `result`; provisional BTC ref; rules/Target-Price parse; comparison +
  CF-Benchmarks-BRTI reference source + rules excerpt; MANUAL_REVIEW on
  disagreement), `readiness.py` (feature-backed distinct-window gating; orphan
  accounting), `paper.py` (rich feature row + fee-aware decision + enriched Kalshi
  ledger + session summary).
- **NEW** `venues/kalshi/features.py`: `UnderlyingMicrostructureState` — point-in-
  time Coinbase/Binance returns (5/15/30/60/180s + since-window-start), realized
  vol (30/60/180s + window-to-date), spot-perp basis + change, perp microprice /
  queue imbalance / best-level OFI, spot+perp CVD / signed-trade-imbalance / trade
  intensity, feed freshness/staleness, with explicit missingness flags + reason
  codes (no invented features). `feature_set_version=2`.
- **NEW** `venues/kalshi/labels_audit.py` (dedup OFFICIAL>PROVISIONAL>MANUAL>UNKNOWN,
  latest-wins; orphan detection; safe separate-file compaction),
  `source_health.py` (per-source health), `collector.py` (continuous loop).
- **NEW (native optional)** `data/deribit_client.py`: public Deribit REST client +
  pure parsers → a normalized snapshot (index, DVOL, historical vol, near-expiry +
  ATM IV, OI with call/put split, volume with call/put split, put/call OI & volume
  ratios, skew; `source_ts_ms`, `deribit_missing_reason`, endpoint names) +
  `fetch_deribit_snapshot()`. `venues/kalshi/deribit_features.py`: `DeribitState`
  cache + **point-in-time join** (latest snapshot at/before `as_of_ms`, no
  look-ahead) → `deribit_*` feature fields with `deribit_enabled/available/used/
  age_ms/stale/missing_reason`, `deribit_iv_minus_realized_vol_60s/180s`,
  `deribit_regime`. Feature rows are now **v3** (`feature_set_version=3`); old v2/v1
  rows coexist (readiness/dry-run report missingness by version). Deribit is
  OPTIONAL and disabled by default; if disabled/stale/missing the Kalshi pipeline
  is unaffected. **Model-feature inclusion is a SEPARATE control**
  (`DERIBIT_INCLUDE_IN_MODEL_FEATURES`, default false, gated by
  `select_for_model_features` so disabled never selects silently): a disabled
  Deribit's leftover historical columns are dropped from the training matrix.
  Config: `DeribitConfig` + `DERIBIT_ENABLED`/`DERIBIT_API_URL`/
  `DERIBIT_POLL_INTERVAL_SECONDS`/`DERIBIT_STALE_THRESHOLD_SECONDS`/
  `DERIBIT_INCLUDE_IN_MODEL_FEATURES`/`DERIBIT_ALLOW_HISTORICAL_FEATURES_WHEN_DISABLED`/
  `DERIBIT_RECORD_RAW`/`DERIBIT_RECORD_NORMALIZED`. NOT a venue.
- `venues/polymarket/__init__.py`: dormant guard. `execution/live_kalshi.py`:
  live-disabled adapter + `kalshi_auth_smoke`. Config: `KalshiConfig` + env +
  `polymarket_dormant`/`primary_venue`.
- Tests: **252 passing** offline (216 base + Kalshi suites incl. rich features,
  label audit/orphans, source health, Deribit parsers, continuous collector incl.
  Ctrl-C, gate consistency, training dry-run). Network tests skip offline.

## Authoritative gate (read this — resolves the 38-vs-35 confusion)
There is ONE gate count, used by readiness, label-audit AND the training dry-run:

> **`gate_windows`** = distinct OFFICIAL-labeled 15m windows that have **≥1 usable
> executable book-backed feature row** (has Kalshi book + BTC underlying ref +
> pre-close + valid book). The shared predicate is `readiness.feature_row_usable`.

Three label counts, narrowing to the gate:
- `official_binary_labels` — every settled OFFICIAL result (incl. orphans). Big.
- `feature_backed_official_windows` (PRESENCE) — official windows with ANY feature row.
- `gate_windows` (USABLE, AUTHORITATIVE) — official windows with a usable executable row.
- `orphan_labels` — official results with NO feature rows; EXCLUDED from the gate.

`feature_backed_official_windows − gate_windows = feature_backed_unusable_windows`
(windows whose only rows are post-close / empty / invalid book). That gap was the
old "38 vs 35"; both commands now print the same `gate_windows` and explain the gap.

## Verified with real API responses + local data (2026-06-02)
- Base URL + public access; KXBTC15M series + markets; market field names;
  orderbook yes/no-bid shape and the ask conversion (matched Kalshi's own asks);
  settled market `result`/`finalized`; the 15-minute window from open/close times.
- Local recorded data (collectors running): **~1012 OFFICIAL labels, ~39
  feature-backed, ~36 `gate_windows` (usable), 974 orphans**; **~22k Kalshi feature
  rows**; ~22k normalized orderbook snapshots; ~32k underlying rows. Both gates
  correctly BLOCKED (gate 36 < 60 backtest / < 150 train).

## Low-latency hot path (5-minute-grade architecture; paper-only)
- **NEW** in-memory, event-driven Kalshi decision layer built so future 5m markets
  need no architectural rewrite. Modules under `venues/kalshi/`: `hotpath_state.py`
  (bounded deques; composes the local book + underlying microstructure + Deribit +
  `build_feature_row` → v3 snapshot), `local_book.py` (snapshot+delta; complement
  asks via `normalize_orderbook`; age/staleness/validity), `ws_client.py` (auth-gated
  WS **scaffold** → honest blocker, REST fallback), `scorer.py` (preloaded model;
  neutral/uncalibrated until a real artifact exists; never per-tick load),
  `low_latency_runtime.py` (`evaluate_ev` executable-ask EV + stale/depth/line/model
  gates; `run_hotpath_smoke`; `run_latency_benchmark`), `latency.py` (p50/p90/p99 +
  rejection counts), `order_planner.py` (PLANNED limit/FOK/IOC objects;
  `live_submission_allowed=False`). Config: `LowLatencyConfig` + `KALSHI_LOW_LATENCY_*`
  env (all SAFE/off by default; horizon knobs are config-driven for 15m-now/5m-later).
- **Hot-path rule:** no file reads, no pandas, no per-tick model load, no
  full-history recompute. Measured compute is sub-millisecond (feature/score/decision);
  REST `get_orderbook` round-trip dominates end-to-end → motivates WS later.
- **Safety:** paper-only; uncalibrated model is capped at MANUAL_REVIEW (never
  PAPER_CANDIDATE); no order path can submit. Decision events buffered to
  `data/decisions/kalshi_hotpath_decisions-*.jsonl` (not per-tick disk I/O).

## Model dataset + training pipeline (gated; pure-stdlib; UNCALIBRATED → not tradable)
- **NEW** under `venues/kalshi/`: `feature_schema.py` (explicit versioned groups A–G,
  required/optional, **leakage exclusions** incl. label/result/post-close/P&L and
  non-stationary price levels; hard Up/Down is DIAGNOSTIC only), `model_dataset.py`
  (join feature-backed OFFICIAL labels only — orphans can't enter; NO look-ahead:
  `as_of_ms < close_ms`; full row accounting; JSONL/CSV, parquet→JSONL fallback),
  `splits.py` (window-level purge/embargo chronological + walk-forward; leak check),
  `train_baselines.py` + `model_artifacts.py`, and `models/pure_ml.py` (dependency-free
  StandardImputer + LogisticRegression + metrics — no numpy/sklearn installed).
- **Gates (authoritative, window-based):** train 150 / backtest 60 distinct
  feature-backed OFFICIAL 15m windows, min 500 rows. Real training REFUSES below the
  gate; `--diagnostic-only` fits NON-TRADABLE sanity models. LightGBM/XGBoost block on
  the missing optional dependency (never faked).
- **Tradability:** artifacts are stamped `TRADABLE` only at/above the gate; ALL models
  are still UNCALIBRATED, so `model_artifacts.is_tradable()` returns False (needs a
  later calibration step) → **no PAPER_CANDIDATE, no live use**. Diagnostic artifacts
  are stamped `NON_TRADABLE_DIAGNOSTIC_ONLY`.

## Calibration + executable backtest (gated; RESEARCH EVIDENCE; pure-stdlib)
- **NEW** under `venues/kalshi/`: `calibrate.py` (pure-Python isotonic PAV + Platt
  + identity calibrators; artifacts stamped NON_TRADABLE_DIAGNOSTIC_ONLY below gate),
  `calibration_report.py` (Brier/log-loss/ECE/reliability/slope/intercept, before vs
  after, fit on a 3-way train/calib/**held-out test** window split), `executable_backtest.py`
  (executable YES/NO **ask** entries — never midpoint — net of fees/depth/staleness/
  source-health/window gates; binary settlement P&L; P&L by side/time/distance/vol/
  health/prob/edge buckets; one position per window; walk-forward stability), and
  `threshold_sweep.py` (gate grid; per-config economics; **no policy auto-selection**).
  Config: `BacktestConfig` + `KALSHI_BACKTEST_*` env (safe defaults; gates 60/150/150).
- **Honest early evidence (diagnostic, 47 windows):** market-implied makes 0 trades
  (can't beat the market at its own price); fitted baselines mostly LOSE money after
  fees; walk-forward P&L is negative/unstable → **no tradable edge demonstrated**.
  AUC ≈ 0.85 does NOT imply profit after paying the ask. Reported as evidence, not alpha.
- **Safety:** every model is UNCALIBRATED and below the gate, so all reports are
  diagnostic / NON_TRADABLE; the backtest simulates only and references no live order;
  no PAPER_CANDIDATE is reachable.

## Paper-candidate policy engine (strict, explainable; gated; NEVER live)
- **NEW** `venues/kalshi/policy.py` (pure `evaluate_policy` → WATCH / MANUAL_REVIEW /
  REJECTED / PAPER_CANDIDATE with reason codes + human summary; reservation prices +
  raw/net edges from executable YES/NO **asks**; dataclasses PolicyConfig/Input/Decision,
  Model/Calibration/Backtest Validity, SourceFreshness, ExecutablePrices,
  CandidateOrderIntent) and `policy_runtime.py` (assemble validity from disk, build
  inputs from the model dataset, dry-run/report/paper-sim runners, Noop-safe notify,
  low-latency hook). Config: `PaperPolicyConfig` + `KALSHI_PAPER_POLICY_*` /
  `KALSHI_REQUIRE_*` env + `config/kalshi_paper_policy.example.yaml`.
- **PAPER_CANDIDATE requires ALL of:** policy enabled, model trained + non-diagnostic,
  calibrator valid + non-diagnostic, backtest evidence valid + ≥ window gate, calibrated
  probability present, executable asks/valid book, net edge ≥ min & raw edge ≥ min,
  price ≤ reservation & ≤ cap, fresh book/underlying (+ optional Deribit), spread/depth
  OK, time-in-window, and risk limits OK. A hard Up/Down class alone NEVER trades.
- **Current state:** disabled by default; even enabled it REJECTS (model is
  NON_TRADABLE_DIAGNOSTIC_ONLY, calibrator diagnostic, backtest below gate) → no
  PAPER_CANDIDATE is reachable; `live_submission_allowed` is always False. The paper
  ledger/order-intent carry `opposite_side_ask` + position metadata so the Prompt 6
  lock-profit module can later monitor open paper positions.

## Post-entry lock-profit module (paper-only; post-entry only; NEVER live)
- **NEW** `venues/kalshi/lock_profit.py` (price-unit helpers; `KalshiPositionLot`/
  `KalshiPositionState` with weighted-avg cost, locked-pairs = min(yes,no), naked =
  |yes−no|; `evaluate_lock` → NO_POSITION / ALREADY_FULLY_LOCKED / WATCH / RIDE /
  LOCK_FULL / LOCK_PARTIAL / REJECTED) and `lock_runtime.py` (load OPEN positions from
  the policy paper ledger + prior lock fills, current-book lookup, dry-run/sim runners,
  lock ledger events, Noop-safe notify, low-latency hook). Config: `LockConfig` +
  `KALSHI_LOCK_*` env.
- **Lock math (decimal 0–1; thresholds in cents):** held YES → `max_no = 1 −
  yes_total_cost − no_fee − slippage − min_locked_profit`; `locked_profit_per_pair =
  1 − yes_total_cost − (no_ask + no_fee + slippage)`. Continue-EV for the naked leg =
  `calibrated_p_yes − yes_total_cost` (YES) / `(1−p) − no_total_cost` (NO). Hard lock
  (≥ hard threshold) overrides ride; conditional lock needs a model (else WATCH);
  ride only when continue-EV materially exceeds the guaranteed lock.
- **Boundary:** this is POSITION MANAGEMENT, not alpha and **not a flat arb scanner** —
  it only acts on an EXISTING paper position, never scans flat YES+NO<1. FOK by default;
  IOC partials only with `--allow-partial` (residual naked exposure tracked). Paper-only;
  `live_submission_allowed=false`. Ledger events: PAPER_ENTRY / PAPER_LOCK_INTENT /
  PAPER_LOCK_FILLED / PAPER_LOCK_PARTIAL / PAPER_LOCK_REJECTED / PAPER_FULLY_LOCKED /
  PAPER_RIDE_DECISION. Currently NO_POSITION (the policy emits no candidates yet).

## Live-readiness scaffolding (DRY-RUN ONLY; the plane stays in the hangar)
- **NEW** `venues/kalshi/live_readiness.py` (states NOT_CONFIGURED / LIVE_DISABLED /
  KILL_SWITCH_ACTIVE / MISSING_CREDENTIALS / MODEL|CALIBRATOR|BACKTEST_NOT_APPROVED /
  PAPER_EVIDENCE_MISSING / RISK_BLOCKED / SOURCE_HEALTH_BLOCKED / ORDER_PLAN_INVALID /
  MANUAL_CONFIRMATION_REQUIRED / DRY_RUN_READY / WOULD_SUBMIT_IF_ENABLED / BLOCKED —
  **no** LIVE_READY_TO_SUBMIT / SUBMITTED / LIVE_FILLED). Credential preflight reports
  presence/readability only (never key material/passphrase/headers). Manual-confirmation
  scaffold (`NoConfirmationProvider` → never confirms). Paper-evidence gate reads an
  optional `data/models/kalshi_live_approval.json` (default **not approved**; example
  shipped). Risk preflight wires the existing `RiskManager` + live caps. Sanitized
  audit log → `data/audit/kalshi_live_readiness_*.jsonl` (no secrets).
- `order_planner.build_dry_run_order_payload` / `payload_from_intent` → validated,
  SANITIZED Kalshi order payload (limit-only, FOK/IOC, binary-price bounds, size/notional
  caps) + sha256 checksum + documented endpoint (`POST /trade-api/v2/portfolio/orders`,
  **never called**). Policy/lock intents convert to the same payload (paper↔live parity).
- `execution/live_kalshi.py`: `submit()`/`cancel()` ALWAYS refuse with structured
  blockers and issue **no HTTP**; blockers now also include `KALSHI_LIVE_SUBMIT_ENABLED`
  + `KALSHI_LIVE_DRY_RUN_ONLY`. Config: `LiveReadinessConfig` + `KALSHI_LIVE_*` env +
  `config/live.example.yaml` (Kalshi-primary, all safe/locked).
- **Proof of safety:** `live_submission_allowed` is hard-False on config/result/payload/
  adapter; tests assert no order/cancel HTTP mutation occurs under default config; every
  gate (kill switch, manual confirm, model/calibration/backtest/paper, risk) is required
  and never bypassed. Enabling live is a SEPARATE future prompt after real evidence.

## Ops / monitoring layer (READ-ONLY; visibility for daily operation)
- **NEW** `venues/kalshi/ops.py` — thin read-only aggregators over the existing
  building blocks: `collector_status` (freshness/stale verdict + optional history at
  `data/audit/kalshi_collector_status_history.jsonl`), `gate_progress` (distinct
  feature-backed official windows, orphans excluded, recent capture rate + ETA),
  `model_health`, `backtest_summary`, `paper_summary`, `lock_summary`, `safety_status`,
  `ops_status` (one dashboard), `doctor` (pass/warn/fail), `eod_summary` (short safe
  notification line + report). 11 new CLI commands; markdown/JSON/report outputs to
  `reports/ops` & `reports/eod`. None collect, trade, or print secrets.
- **Interpretation:** `kalshi-collector-status` says ACTIVE / DEGRADED / STALLED purely
  from file ages + source-health — it NEVER stops/restarts a collector; on STALLED it
  recommends checking the PowerShell window / restarting at a 15m boundary.

## Still stubbed / not done
- Authenticated **Kalshi WebSocket** streaming (REST polling is the working path;
  `ws_client.py` is an honest scaffold — WS needs RSA signing + keys + the
  `websockets` lib; the runtime falls back to REST automatically).
- **First real paper position** — the policy engine + post-entry lock-profit module now
  both EXIST (`kalshi-policy-*`, `kalshi-lock-*`), but no open paper position exists yet
  because PAPER_CANDIDATE is unreachable until a real (gated, non-diagnostic, calibrated,
  backtested-with-edge) model exists — currently none does, so the lock module reports
  NO_POSITION. Authenticated **Kalshi WebSocket** streaming also remains a scaffold.
  Live stays disabled throughout.
- LightGBM/quantile **challenger** training (optional `models` deps not installed;
  `--model lightgbm` blocks with a clear message — never faked).
- Provisional BTC end-reference join in `kalshi-backfill-settlements` (official
  `result` is used; the provisional end price is an optional future add).
- Deribit per-strike IV term-structure / smile beyond the current near-expiry +
  ATM-proxy summary (the `near_expiry_iv` "front" proxy is median-across-strikes
  and runs hotter than ATM; ATM IV ≈ DVOL and is the more representative level).

## Known blockers
- No model training/backtest until `kalshi-data-readiness` shows enough DISTINCT
  **`gate_windows`** (≥60 backtest / ≥150 train) — currently ~36 (the ~1000
  OFFICIAL labels are mostly orphans and DO NOT count).
- Live trading requires Kalshi auth (KEY_ID + RSA private key) AND all gates off;
  intentionally not enabled.
- **Coinbase staleness:** source-health may show Coinbase briefly stale (>60s)
  while Binance stays fresh. Recorded cadence shows Coinbase≈Binance row counts, so
  this is a **transient** REST hiccup, not a chronic feed failure. Coinbase is the
  PRIMARY spot reference; Binance `can_serve_as_spot_fallback`. Feature rows already
  flag `coinbase_stale` at a 5s per-tick threshold, so stale spot ticks are visible,
  not silently used. (Auto spot→perp failover in the live ref path is a future add.)

## Latency-safe notifications & explanations
- Notifications are **async**: the loop `enqueue()`s in-memory and a background
  worker sends (Pushover→Noop). **Nothing notifies/explains/HTTP-calls on the
  decision/order path.** Bounded queue; WATCH/REJECTED coalesced/suppressed;
  high-priority (PAPER_CANDIDATE/fills/lock/collector-stale/error) preserved.
- **Explanations are post-decision**, generated in the worker from structured
  reason codes via offline templates — **no LLM/API** anywhere in the hot path.
- Modules: `notifications/queue.py`, `notifications/explanations.py`. Config:
  `NotificationConfig` (`NOTIFICATIONS_*`). Ops: `notification-health`;
  `kalshi-latency-benchmark` now reports notification-enqueue overhead.
- Pushover→Noop fallback intact; no Pusher; **no secrets printed**; live disabled.
- Binance endpoints may be geo-restricted in some environments; Coinbase suffices.

## Paper-ONLY artifact promotion + shadow/paper runtime (explicit; NEVER live)
Staged artifacts (`data/models/staged/`) are INACTIVE. The runtime no longer loads
"newest `.pkl` by mtime" — for shadow/paper it loads ONLY an explicit promotion
manifest (`data/models/paper_promoted/kalshi_paper_promotion_manifest.json`).
- `kalshi-paper-promotion-review --model <staged.pkl> --calibrator <staged.pkl>` —
  READ-ONLY eligibility (requires non-diagnostic+calibrated model, matching calibrator,
  gate windows, calibration/backtest/edge/frequency reports). Reports blockers + honest
  warnings (edge unproven, isotonic overfit). Never promotes.
- `kalshi-promote-paper-artifacts --model <m> --calibrator <c> [--reason ..] [--write]` —
  DRY-RUN by default; `--write` COPIES the pair into `paper_promoted/` (stamped
  `is_promoted=true`, `promoted_for=PAPER_ONLY`, `live_approved=false`) + writes the
  SHA-pinned manifest. Never touches staged sources, `.env`, live config, or the legacy
  active artifacts; never auto-promotes.
- `kalshi-demote-paper-artifacts --write` — rollback (disables the manifest, preserves
  artifacts). `kalshi-paper-runtime-status` — mode + manifest validity + can-emit.
- `kalshi-shadow-run --seconds N` — SHADOW: score recent snapshots with the promoted
  artifacts, run policy + confidence-aware **edge policy**, write SHADOW_DECISION rows;
  NEVER emits PAPER_CANDIDATE, NEVER fills, NEVER live.
- **Runtime modes** (`KALSHI_MODEL_RUNTIME_MODE`, default `disabled`): disabled →
  no candidates; shadow → score/log only; paper → PAPER_CANDIDATE+paper-fills ONLY when
  promoted + every gate passes (edge policy required, freshness/depth/time, per-window
  cap, daily cap, cooldown). `live_submission_allowed` is always False. Manifest SHA
  mismatch / is_promoted=false / diagnostic / uncalibrated all block. Every action is
  audited to `data/audit/kalshi_paper_promotion_*.jsonl` (no secrets, live_approved=false).
  Promotion is NOT proof of profitability.

## Controlled PAPER experiment (shadow first, paper only after preflight; NEVER live)
A disciplined harness (`venues/kalshi/paper_experiment.py`) to run the PROMOTED paper
model with strict monitoring + abort criteria. SHADOW first, PAPER only if preflight
passes. Per-run manifest under `data/paper/experiments/` (CREATED/RUNNING/COMPLETED/
ABORTED) + a tagged decision ledger. Config: `PaperExperimentConfig` /
`KALSHI_PAPER_EXPERIMENT_*` (disabled + shadow by default; conservative caps).
- `kalshi-paper-experiment-preflight` — READ-ONLY: live-disabled, promotion valid + SHA
  match, model non-diagnostic, calibrator valid, edge/backtest/calibration/frequency
  reports present, source DECISION-freshness, conservative thresholds, ledger writable.
  Reports `preflight_pass` / `paper_ready` / `recommended_mode` (disabled|shadow|paper).
- `kalshi-paper-experiment-start --experiment-mode shadow|paper [--minutes N]
  [--poll-interval S] [--max-iterations K] [--name X] [--skip-shadow-warning]` — with
  `--minutes N` it runs a **LIVE LOOP** for ~N min, re-reading the LATEST feature rows every
  `--poll-interval` s (default 5). **ROW SELECTION:** the collector records a row for every
  discovered market (open / upcoming / closed) as a *collection* row; the loop keeps only the
  freshest snapshot per market and then `_decision_eligibility` filters to **executable ACTIVE
  rows** before scoring — current in-window market, `0 < seconds_to_close ≤ market_duration`,
  within the policy time window, executable book + start-reference + sufficient depth, and
  feature-row fresh. Non-executable rows (upcoming / closed / no-book / no-reference / illiquid /
  stale) are **counted by reason but never scored** (thresholds are the policy's own — never
  weakened). Output reports the funnel: `rows_read → active_window_rows / book_backed_rows /
  start_reference_rows → executable_rows (= rows_eligible_for_scoring)` plus
  `rejected_before_scoring{,_by_reason}`. With no `--minutes` (or `--max-iterations 1`) it is a
  SINGLE batch pass over the most recent stored rows (never a long collector). SHADOW logs
  SHADOW_DECISION (no fills/candidates); PAPER may emit PAPER_CANDIDATE + simulate fills (settle
  vs OFFICIAL label) ONLY after preflight passes AND a prior shadow run (unless
  `--skip-shadow-warning`) AND every gate passes. `live_submission_allowed` is always false.
- `kalshi-paper-experiment-status` / `kalshi-paper-experiment-report` — decisions, fills,
  rejection reasons, freshness, P&L/drawdown, live-safety, and a recommendation
  (keep shadowing / proceed to paper / pause / tighten / demote). No profitability claims.
- `kalshi-paper-experiment-stop --reason X` — writes a STOP flag + marks the RUNNING
  experiment ABORTED (kills NO collectors). **Abort criteria**: unexpected live
  enabled/permitted, source decision-stale, manifest hash mismatch / artifact missing,
  model/policy/fill exception, paper loss / drawdown over limit, too many consecutive
  rejections/stale, any `live_submission_allowed=true`.
- Collector integration: `kalshi-collect-continuous --runtime-mode shadow|paper` sets the
  in-process mode without editing `.env` (never live). `live_submission_allowed` is
  ALWAYS False across every path.

## Safety status
Live disabled by default; `check-live-disabled` passes (both adapters refuse).
Kill switch on. Pushover→Noop fallback intact; no Pusher; no secrets printed.
No midpoint fills; fees always subtracted; uncalibrated model never trades.
Runtime loads only PROMOTED-for-paper artifacts (no newest-by-mtime); staged stay inactive.

## Next 3 actions
> Status (2026-06-02): `gate_windows ≈ 85` — the **backtest diagnostic gate (60) is
> reached**; the **training/calibration gate (150) is not** (~65 windows to go).
> Check anytime with `kalshi-ops-status` / `kalshi-gate-progress`.
1. Keep the continuous collector running and grow **`gate_windows`** toward 150
   (train/calibration). Monitor with `kalshi-ops-status --series KXBTC15M` and
   `kalshi-collector-status` (it reports ACTIVE/STALLED without touching collectors).
2. Now that backtest is allowed, periodically run `kalshi-backtest-baselines` and
   `kalshi-calibration-report` to track whether any signal shows edge after costs
   (current diagnostic evidence: none — market-implied trades 0, fitted baselines lose).
3. When `gate_windows ≥ 150`, run `kalshi-clean-orphan-labels --write`, then fit +
   calibrate + backtest a real (non-diagnostic) model and review
   `kalshi-model-health` / `kalshi-policy-report` before trusting any PAPER_CANDIDATE.
   Keep live disabled (a separate explicit step enables it later).


<!-- HIRES-MEASUREMENT-LAYER -->

## High-resolution measurement layer (READ-ONLY)

A sub-second / near-sub-second measurement layer (`btc5m.venues.kalshi.hires`) records
Coinbase + Binance **public WebSocket** ticks and **fast Kalshi active-book REST** polls
with immediate local `recv_ms` timestamps, plus optional point-in-time joined snapshots.

- **Measurement only**: no paper, no live, no orders, no promotion; every row carries
  `live_submission_allowed=false` and `HIRES_NO_ORDERS`/`live` are force-set in code.
- **Why**: the existing collector samples spot/perp/Kalshi on the same ~4s clock, which is
  too coarse to test the repricing-lag/stale-quote hypothesis; this layer reaches ~30-80ms
  underlying and ~1s Kalshi-book resolution (Kalshi REST is RTT-bound; WS needs auth).
- **Kalshi**: active KXBTC15M ticker only (status-aware, active-first, rediscover at handoff),
  public REST (Kalshi market-data WS is an auth-gated scaffold).
- **Coinbase/Binance**: public WebSocket preferred (`websockets`); REST fallback if absent.
- **Deribit**: stays a SEPARATE slower volatility/regime source — never in the sub-second
  hot path; it can be joined point-in-time to high-res shock events later.
- **Polymarket**: cross-venue research is out of scope for this branch (not added).
- **Files**: separated under `data/{raw,normalized}/hires/` and `data/features/hires/`;
  production normalized files are never touched. Reports under `reports/hires/`.

Commands: `kalshi-hires-smoke` / `kalshi-hires-record` / `kalshi-hires-status` (see COMMANDS.md).


<!-- HIRES-HARDENING-1.5 -->

## High-res recorder hardening (Prompt 1.5)

The high-res recorder is hardened for long unattended runs (still READ-ONLY measurement; no paper/live/orders):

- **Threaded, bounded, priority-aware writer**: source threads enqueue; one writer thread owns files.
  Under overload, LOW-priority rows (raw verbose, Binance aggTrade) drop first; **Kalshi active-book +
  joined snapshots are NEVER dropped** (loud overflow metric if pressured). Verified live at ~575
  bookTicker/s with writer lag p50/p95 ~2/7ms, queue far below warning, zero high-priority drops.
- **Binance aggTrade is heavy and OFF by default**; bookTicker (the ~500-780/s firehose) is usually
  enough for the repricing-lag first pass. aggTrade is opt-in (`--aggtrade` / env) with sampling
  (`BINANCE_HIRES_AGGTRADE_SAMPLE_EVERY_N`) + per-stream rate cap (`BINANCE_HIRES_MAX_MSGS_PER_SECOND`).
- **Rotation / compression / retention**: files rotate every 15 min into
  `data/{raw,normalized,features}/hires/YYYYMMDD/` segments; closed segments gzip to `.jsonl.gz`;
  retention is raw 7d / normalized 30d / joined 90d, enforced ONLY via `kalshi-hires-compact --write
  --retention` (never touches active files; ~8x size reduction).
- **Safe unattended loop**: `kalshi-hires-record-loop --session-seconds 900` (graceful Ctrl+C) or the
  documented PowerShell while-loop. Bounded runtime per session.
- **Deribit** stays a SEPARATE slower regime source (`record-deribit --interval 30`); never in the
  sub-second hot path; its staleness never blocks the high-res collector. **Polymarket cross-venue
  remains out of scope.** No paper/live; `live_submission_allowed=false`.
