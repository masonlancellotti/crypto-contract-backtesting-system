# PROJECT_STATE.md

> **Hard rule:** Read this file before continuing any future major work.
> Do not continue coding blindly if this file contradicts current assumptions.
> Verify claims against code/data/live API before trusting them.

> ## ⚑ PROJECT PIVOT — PRIMARY VENUE IS NOW KALSHI BTC 15m (KXBTC15M)
> The active system is the **Kalshi BTC 15-minute Up/Down** probability +
> paper/live-ready execution system (series **KXBTC15M**), discovered
> dynamically via the Kalshi market APIs. **See `KALSHI_PIVOT_STATE.md` for the
> authoritative current state and next actions.**
>
> Target: **P(Kalshi YES/Up resolves to 1 at the 15-minute window close)**.
> Decision: is YES/NO mispriced vs the model's calibrated settlement probability
> after executable bid/ask, depth, fees, staleness, latency, and risk gates?
>
> **Paper-only promotion + shadow runtime (2026-06-03):** the runtime no longer loads
> "newest `.pkl` by mtime". Staged artifacts are INACTIVE; the shadow/paper runtime loads
> ONLY an explicit, SHA-pinned PAPER promotion manifest (`data/models/paper_promoted/`).
> `KALSHI_MODEL_RUNTIME_MODE` (disabled|shadow|paper, default disabled) gates behavior;
> shadow scores+logs but never fills, paper can emit PAPER_CANDIDATE only when promoted +
> every gate (incl. the confidence-aware edge policy) passes. `live_submission_allowed` is
> always False. Promote/demote are explicit, audited CLI commands; promotion is NOT proof
> of profitability. See `KALSHI_PIVOT_STATE.md`.
>
> **Controlled paper experiment (2026-06-03):** `venues/kalshi/paper_experiment.py` adds a
> disciplined SHADOW→PAPER harness with preflight, per-run manifest
> (`data/paper/experiments/`), abort criteria, status/report + recommendation. SHADOW logs
> only (no fills); PAPER fills (settle vs OFFICIAL label) only after preflight passes + a
> prior shadow run + every gate (edge policy, source DECISION-freshness, rate caps).
> `kalshi-paper-experiment-preflight/start/status/stop/report`;
> `KALSHI_PAPER_EXPERIMENT_*` (disabled+shadow default). Never live.
>
> **Polymarket BTC 5m (everything below this banner) is PARKED / DORMANT** — a
> reference implementation only, not part of the default pipeline. It runs only
> if `POLYMARKET_DORMANT=false`. New work should target `btc5m.venues.kalshi`.
> Run `pytest -q` (252 passing) and `kalshi-data-readiness` for current status.
> **The authoritative next actions live in `KALSHI_PIVOT_STATE.md`** — the
> "Next 3 actions" at the very bottom of this file are LEGACY Polymarket notes.
>
> **Authoritative training gate = `gate_windows`** (distinct OFFICIAL 15m windows
> with ≥1 usable executable book-backed feature row). `feature_backed_official_windows`
> (presence) ≥ `gate_windows` (usable) ≥ training-eligible; `orphan_labels` (official
> result, no features) are EXCLUDED. `kalshi-data-readiness`, `kalshi-label-audit`,
> and `kalshi-train-dry-run` all report the SAME `gate_windows`.

## (LEGACY / DORMANT — Polymarket BTC 5m) Current purpose
A record-only / paper-first system that estimates calibrated settlement
probabilities for **Polymarket 5-minute BTC Up/Down binary contracts** —
**P(YES/Up resolves to 1)** = P(end reference price ≥ window-start reference
price; ties resolve Up) — and evaluates executable expected value **after
costs**, paper-trades candidates, and supports gated live trading later. Live
trading is **disabled by default** and must stay that way.

## Current phase
**paper-ready (record-only/paper)** with **discovery now FIXED**. The full
pipeline runs end-to-end (discover → record books + provisional line → record
underlying → backfill labels → build features → decide → paper ledger →
session summary → data-readiness). Model training/backtest stay BLOCKED until
enough non-leaky OFFICIALLY-labeled rows exist. OFFICIAL numeric lines remain
gated on Chainlink credentials (off by default → numerics are provisional).

## VERIFIED Polymarket BTC 5m semantics (checked live against Gamma, 2026-06-01)
- Slug form `btc-updown-5m-<unix_ts>`. **`<unix_ts>` = the window START in epoch
  SECONDS, aligned to 300s.** Verified: slug `...-1780288800` ↔
  `eventStartTime 2026-06-01T04:40:00Z`, `endDate` = start + 300s.
- Outcomes are `["Up","Down"]`; Up = YES = `clobTokenIds[0]`.
- Settlement (from the explicit **description**, never the title): resolve **Up**
  if the Chainlink BTC/USD end price is **greater than or equal to** the start
  price → comparison **GTE** (a tie resolves Up).
- Each window is listed ~24h **before** it opens and is `acceptingOrders=true`
  the whole time. `acceptingOrders` is a venue flag, **not** "in-window".
- `outcomePrices` is the live market price; it is only a settlement signal once
  `closed=true` (a clean {0,1} pair).

## Discovery: the bug and the fix
- **Root cause (was):** `discover_markets` sorted `/markets` by `startDate`
  descending (newest-CREATED first) and unioned an end-date-window query. Because
  windows are listed ~24h ahead, the newest-created batch is always the
  far-future windows; the live window (created ~24h ago) never appears.
  **Live proof:** `order=startDate desc` → 1 far-future market; end-date-window
  query → 0; the current window (fetched by slug) existed and was accepting
  orders. The shipped `discover-markets` returned "1 market, ~23.9h to expiry,
  0 live" while 15+ near-term windows existed. This starved the pipeline: 6655 of
  6657 feature rows had no line.
- **Fix:** `btc5m/discovery.py` + a rewritten `PolymarketClient.discover_markets`
  now ENUMERATE the deterministic 5-min slug grid around `now` and **batch-fetch**
  by slug (repeated `slug=` params; verified Gamma supports it). This is
  clock-driven and order-independent → it cannot miss the live window. The old
  query is kept only as an optional far-future supplement.
- **Verified after fix:** `discover-markets`/`debug-discovery`/`collect-continuous`
  all surface `CURRENTLY_IN_WINDOW` + upcoming windows, and the background
  `record` loop began capturing in-window provisional lines immediately.

## What is implemented (cross-checked against code + live runs)
- **Discovery** (`discovery.py`, `data/polymarket_client.py`): slug grid +
  classification (`WindowPhase`: UPCOMING_PRE_WINDOW / CURRENTLY_IN_WINDOW /
  POST_WINDOW_NOT_RESOLVED / RESOLVED_OR_CLOSED / STALE_PAST / FAR_FUTURE /
  UNKNOWN_TIMING), slug↔window mapping, URL parsing, `get_markets_by_slugs`
  (batched), slug-derived timing fallback, 404→empty-book tolerance.
- **CLI commands** (`cli.py`): `debug-discovery`, `inspect-market` (--slug/--url),
  `record-market` (--slug/--url), `collect-continuous` (rolling rediscovery loop)
  plus the existing `discover-markets`, `record`, `record-underlying`,
  `backfill-settlements`, `backfill-official-chainlink`, `build-features`,
  `decide`, `data-readiness`, `paper-backtest`, `run-paper-pipeline`,
  `label-status`, `status`, `check-live-disabled`, `notify-test`, `smoke`, `eod`.
- **Recording**: CLOB books (raw + normalized), provisional window-start line for
  in-window markets, Coinbase + Binance underlying (REST polling). `Recorder` now
  has `flush()` so a long-running collector re-reads current data.
- **Line/label provenance** (`labels/settlement_backfill.py`): OFFICIAL binary
  outcome from Gamma `outcomePrices` only when `closed=true`; numeric line/final
  from Chainlink (OFFICIAL, gated) else Coinbase/Binance (PROVISIONAL_REFERENCE);
  official vs computed disagreement → **MANUAL_REVIEW** (both kept). A missing
  numeric line does **not** drop a known OFFICIAL binary label.
- **Data-readiness** (`paper/readiness.py`): richer breakdown — official binary
  labels, official/provisional numeric lines, provisional final prices, feature
  rows with/without line / with book / with underlying, and model-specific usable
  rows (baseline-line / non-line / microstructure) with separate gates + reasons.
- **Features** (`features/`): point-in-time, no-lookahead rows with YES/NO
  bid/ask/spread/depth/imbalance/quote-age/crossed, executable implied prob from
  ask AND bid (never midpoint-only), spot+perp returns/realized-vol/CVD/basis,
  distance-from-line (+ vol-normalized), and staleness/feed-health flags.
- **Models/decision/paper**: baseline (uncalibrated by design → WATCH/
  MANUAL_REVIEW), isotonic calibration, gated decision layer (never LIVE by
  default), non-midpoint paper fills, persistent JSONL ledger, session summaries,
  gated paper-backtest. Live adapter refuses every order by default.
- **Notifications**: Pushover (stdlib, env-only, no token logging) with **Noop**
  fallback; Pusher fully removed.
- **Tests**: **184 passing** offline (network tests are skip-gated). New suites:
  `test_discovery`, `test_discovery_client`, `test_cli_manual_override`,
  `test_readiness_categories`.

## Official vs provisional (important)
- **OFFICIAL (settlement-grade):** the binary Up/Down outcome from Gamma once
  `closed=true`.
- **PROVISIONAL_REFERENCE (NOT settlement-grade):** all numeric line/final prices
  + `settlement_distance` (Coinbase/Binance proxy, not Chainlink). Used for
  features + disagreement detection only. Never silently treated as OFFICIAL.

## Known blockers / risks (precise)
- **No OFFICIAL numeric line without Chainlink.** Gamma/CLOB expose no official
  start/end price; numeric lines/distances are PROVISIONAL_REFERENCE until
  Chainlink Data Streams creds are set (env-only) and `backfill-official-chainlink`
  runs. The client is gated-ready but unverified end-to-end without creds.
- **Sparse OFFICIAL-labeled rows.** Until the fixed collector runs across many
  full windows, `usable_labeled_rows` stays well under the 500/200 train/backtest
  thresholds → training + backtest remain BLOCKED (correctly).
- **Concurrent recorders.** Multiple overlapping `record` processes append to the
  same JSONL files (possible interleaving). Prefer the single-process
  `collect-continuous` for continuous collection.
- **CLOB book source timestamp can lead the local clock** → occasional negative
  `quote_age_ms`; treat as a clock-skew diagnostic, not staleness.
- WS streams are still REST polling; DuckDB/Parquet remain stubs. **Deribit is now
  a native OPTIONAL source** (disabled by default): public REST snapshot +
  point-in-time join into Kalshi v3 feature rows (`deribit_*` with freshness/
  missingness flags). It is NOT a trading venue and never blocks the Kalshi
  pipeline when disabled/stale/missing. **Collection (`DERIBIT_ENABLED`) and
  model-feature inclusion (`DERIBIT_INCLUDE_IN_MODEL_FEATURES`, default false) are
  separate controls:** historical `deribit_*` columns may linger on old rows while
  disabled, but they are never silently selected for the model — `source-health`,
  `kalshi-build-model-dataset`, and `kalshi-train-dry-run` report
  `selected_for_model_features` / `candidate_feature_group_status`
  (INCLUDED / EXCLUDED_BY_CONFIG / UNAVAILABLE / STALE) distinctly from mere
  column presence, so the previously-confusing "disabled yet rows present" state
  now reads clearly (`disabled_by_config_but_rows_present`).
- **Low-latency hot path (NEW, paper-only):** an in-memory/event-driven Kalshi
  decision layer (`venues/kalshi/hotpath_state.py`, `local_book.py`, `scorer.py`,
  `low_latency_runtime.py`, `latency.py`, `order_planner.py`, `ws_client.py`)
  built to 5-minute-grade so future 5m markets need no rewrite. No pandas/file
  reads/model-load in the hot path; executable-ask EV with stale/depth/line/model
  gates; uncalibrated model capped at MANUAL_REVIEW; **no live orders** (WS is an
  auth-gated scaffold → REST fallback). Smoke: `kalshi-hotpath-smoke`; benchmark:
  `kalshi-latency-benchmark`. All `KALSHI_LOW_LATENCY_*` settings SAFE/off by default.
- **Model dataset + training pipeline (NEW, gated, pure-stdlib):**
  `kalshi-build-model-dataset` (feature-backed OFFICIAL labels only; orphans
  excluded; no look-ahead; explicit leakage exclusions; JSONL/CSV; missingness +
  gate reports), `kalshi-split-report` (window-level purge/embargo chronological +
  walk-forward), `kalshi-train-baselines` (market-implied + distance/time/vol +
  microstructure logistic via `models/pure_ml.py` — no numpy/sklearn installed),
  `kalshi-train-model` (lightgbm blocks on the missing optional dep). REAL training
  REFUSES below 150 windows / 500 rows; `--diagnostic-only` fits NON-TRADABLE
  models. Hard Up/Down is diagnostic only. All models are UNCALIBRATED →
  `is_tradable()` False → **no PAPER_CANDIDATE; live disabled**.
- **Calibration + executable backtest (NEW, gated, pure-stdlib):**
  `kalshi-calibration-report` / `kalshi-calibrate-model` (isotonic PAV / Platt /
  identity on a 3-way train/calib/held-out-test window split; Brier/log-loss/ECE/
  reliability before-vs-after), `kalshi-backtest-baselines` / `kalshi-backtest-model`
  (executable YES/NO **ask** entries — never midpoint — net of fees/depth/staleness;
  binary settlement P&L; bucketed; walk-forward), `kalshi-threshold-sweep` (gate grid;
  **no policy auto-selection**). Real runs gated (60/150); below-gate requires
  `--diagnostic-only` and is NON_TRADABLE. Early evidence: market-implied trades 0,
  fitted baselines lose after fees → **no tradable edge demonstrated** (evidence, not
  alpha). Nothing emits PAPER_CANDIDATE; live disabled.
- **Paper-candidate policy engine (NEW, strict, gated, never live):**
  `venues/kalshi/policy.py` + `policy_runtime.py` — `evaluate_policy` emits
  WATCH / MANUAL_REVIEW / REJECTED / PAPER_CANDIDATE with reason codes + human
  summary, computing reservation prices + raw/net edges from executable YES/NO
  **asks** (never midpoint). PAPER_CANDIDATE requires policy enabled + trained +
  calibrated + non-diagnostic + sufficiently-backtested model passing every
  freshness/depth/spread/time/risk gate. Commands: `kalshi-policy-dry-run`,
  `kalshi-policy-report`, `kalshi-paper-policy-sim`; integrates into the low-latency
  runtime behind `KALSHI_PAPER_POLICY_ENABLED`. Disabled by default; currently
  REJECTS (diagnostic model) → no PAPER_CANDIDATE reachable; `live_submission_allowed`
  always False. Carries `opposite_side_ask` + position metadata for the Prompt 6
  lock-profit module.
- **Post-entry lock-profit module (NEW, paper-only, post-entry only, never live):**
  `venues/kalshi/lock_profit.py` + `lock_runtime.py` — manages an EXISTING paper
  position by monitoring the OPPOSITE leg (held YES→NO, held NO→YES) to lock
  guaranteed profit after fees. `evaluate_lock` → NO_POSITION / ALREADY_FULLY_LOCKED
  / WATCH / RIDE / LOCK_FULL / LOCK_PARTIAL / REJECTED, with weighted-avg cost basis,
  locked-vs-naked accounting, hard/conditional lock vs ride (continue-EV when a model
  exists), FOK default (IOC partials only with `--allow-partial`). **NOT a flat arb
  scanner** — never scans flat markets, never opens directional positions, never
  submits a live order. Commands: `kalshi-lock-dry-run`, `kalshi-lock-sim`; both report
  NO_POSITION today (the policy emits no candidates yet). `live_submission_allowed`
  always False.
- **Live-readiness scaffolding (NEW, DRY-RUN ONLY, never submits):**
  `venues/kalshi/live_readiness.py` (readiness state machine + credential preflight
  with NO secret values + manual-confirmation scaffold + paper-evidence gate +
  risk preflight + sanitized audit log) and `order_planner.build_dry_run_order_payload`
  / `payload_from_intent` (validated, sanitized, checksummed dry-run payloads;
  policy/lock parity; limit-only, FOK/IOC, no market orders). `execution/live_kalshi`
  `submit()`/`cancel()` ALWAYS refuse and issue no HTTP. Commands:
  `kalshi-live-blockers`, `kalshi-live-readiness`, `kalshi-live-dry-run-order`,
  `kalshi-private-read-preflight`. Config `LiveReadinessConfig` + `KALSHI_LIVE_*`;
  all safe/locked by default. `live_submission_allowed` is hard-False everywhere;
  enabling live is a SEPARATE future step after real paper evidence.
- **Ops / monitoring layer (NEW, READ-ONLY):** `venues/kalshi/ops.py` + 11 CLI
  commands aggregate everything for daily operation — `kalshi-ops-status` (dashboard),
  `kalshi-collector-status` (ACTIVE/DEGRADED/STALLED from file freshness; never touches
  collectors), `kalshi-gate-progress` (window gate + capture-rate ETA, orphans excluded),
  `kalshi-model-health`, `kalshi-backtest-summary`, `kalshi-paper-summary`,
  `kalshi-lock-summary`, `kalshi-safety-status` (LIVE TRADING DISABLED),
  `kalshi-doctor` (pass/warn/fail), `kalshi-eod-summary` (short safe notification +
  report), `kalshi-notify-test`. JSON/markdown/report outputs to `reports/ops` &
  `reports/eod`; helper scripts in `scripts/`; cheat sheet `COMMANDS.md`. All
  read-only, no collection, no orders, no secrets.
- **Final integration/regression pass (Prompt 9):** added `dependency-check` (optional
  ML/data deps + degraded-feature report; stdlib fallback always works); verified
  every CLI command runs or blocks cleanly; consolidated docs `ARCHITECTURE.md` /
  `MODEL_PIPELINE.md` / `LIVE_SAFETY.md` / `INTEGRATION_REGRESSION_REPORT.md`.
  **396 tests pass.** Backtest gate (60) reached (~86 windows); train/calibration
  gate (150) pending; PAPER_CANDIDATE still impossible (diagnostic model); live disabled.

## Safety
- Live trading **disabled by default**; `check-live-disabled` confirms the live
  adapter refuses (kill switch + mode + creds + risk-limit + manual-confirm
  blockers). Discovery/recording are read-only and place no orders.
- No Pusher anywhere; Noop fallback verified; no secrets printed; `.env.example`
  carries the full Pushover block (`PUSHOVER_ENABLED=false`, …).

## Important commands
- `python -m btc5m.cli debug-discovery --asset BTC --duration 5m --lookahead-hours 2`
- `python -m btc5m.cli discover-markets --asset BTC --duration 5m --max-markets 20`
- `python -m btc5m.cli inspect-market --slug "btc-updown-5m-<ts>"` (or `--url`)
- `python -m btc5m.cli record-market --slug "btc-updown-5m-<ts>" --seconds 300`
- `python -m btc5m.cli collect-continuous --asset BTC --duration 5m --rediscover-seconds 30 --process-seconds 60 --max-markets 0`
- `python -m btc5m.cli data-readiness --asset BTC --duration 5m`
- `python -m btc5m.cli backfill-settlements --asset BTC --duration 5m`
- `python -m btc5m.cli check-live-disabled` · `notify-test` · `status`
- `pytest -q` (run from the repo root)

## Anti-fake-edge reminders
No midpoint fills · no stale quotes as edge · no profit/alpha/arbitrage claims ·
no calibration skip · no live orders by default · no title-similarity settlement ·
no overlapping labels without purge/embargo · keep uncertain outputs WATCH/MANUAL_REVIEW.

## Post-entry position lifecycle manager (paper-only; post-entry only; never live)
`venues/kalshi/position_lifecycle.py` (+ `_runtime`) monitors EXISTING paper
positions and compares same-leg SELL value vs opposite-leg LOCK value vs updated
continue/ride EV — using the CURRENT calibrated probability, not the entry-time
belief — choosing HOLD/RIDE / SELL_SAME_LEG / LOCK_WITH_OPPOSITE_LEG / PARTIAL_LOCK
/ RISK_EXIT / WATCH. It reuses the lock module's position accounting + lock math,
uses executable bids/asks only (never midpoint), gates on fees/depth/book-age/
time/source-health, reasons every decision, and writes a separate lifecycle
ledger. CLI: `kalshi-position-monitor-dry-run / -sim / kalshi-position-summary`.
Not a flat arb scanner; never opens positions; paper-only; live disabled.

## Trade-frequency frontier / overtrading analysis (research/reporting only)
`venues/kalshi/trade_frequency.py` (+ `_runtime`) measures the relationship between
trade frequency and net performance on a leakage-safe held-out set: a frequency-policy
frontier (edge floors, per-window caps, cooldowns, daily caps, time-to-close filters), a
marginal-trade curve (rank by net edge → where extra trades stop adding value), per
time-to-close buckets, within-window concentration, and frequency-vs-calibration. It
reuses the executable backtest (`evaluate_row`/`settle_trade`/`simulate_backtest`) so
fees + executable asks are included (never midpoint). **Principle: score constantly,
trade selectively; distinct windows matter more than raw trade count.** Stamped
NON_TRADABLE until a calibrated model exists; no policy is promoted (conservative
suggestion is a staged `promoted=false` JSON); reports → `reports/frequency/`; no live.
CLI: `kalshi-frequency-report / -sweep / kalshi-marginal-trade-curve /
kalshi-time-to-close-analysis / kalshi-within-window-frequency`.

## Confidence-aware edge threshold / reservation-price policy (paper-only; never live)
`venues/kalshi/edge_policy.py` (+ `uncertainty.py`) converts model probabilities into
conservative trade/no-trade thresholds. It does NOT trade on `model_prob > price`:
it uses a conservative probability bound (YES → lower; NO → `1 − upper`), then subtracts
fees, depth/slippage, stale-quote, source-health, model + calibration (Wilson interval
on reliability buckets), regime, and overtrading buffers + a minimum-profit buffer →
**final policy edge** + **reservation price**. Required edge rises automatically when
the model is uncalibrated, buckets are thin/weak, the book is stale/thin, vol is high,
or trading is concentrated. Conservative by default; uncalibrated/diagnostic models are
rejected; never promotes a config; no live. CLI: `kalshi-edge-policy-report /
kalshi-edge-threshold-sweep` → `reports/edge/`. Lifecycle ride EV can use
`conservative_continue_ev` (YES p_lower / NO 1−p_upper).

## Latency-safe notifications & explanations
Pushover sends are **async/background** (`notifications/queue.py`): the decision
loop enqueues and returns; a worker sends. No notification, explanation, or HTTP
call runs on the decision/order path. Explanations are **post-decision**,
template-based, offline (no LLM/API) — see `notifications/explanations.py`.
WATCH/REJECTED spam is coalesced/suppressed; the bounded queue drops low-priority
events when full and preserves high-priority ones. Health/overhead:
`notification-health` and `kalshi-latency-benchmark`. Missing Pushover creds →
Noop. Notifications are operational aids, **not trade logic**; live stays disabled.

## (LEGACY / DORMANT — Polymarket BTC 5m) Next actions — NOT authoritative
> The authoritative next actions are in **`KALSHI_PIVOT_STATE.md`**. The steps
> below apply ONLY if the dormant Polymarket path is explicitly re-enabled
> (`POLYMARKET_DORMANT=false`); they are kept for reference, not for current work.
1. Run `collect-continuous --max-markets 0` (single process) for several hours and
   watch `data-readiness` climb (official_binary_labels, provisional_numeric_lines,
   feature_rows_with_line, usable_rows_for_* counts).
2. Provide Chainlink Data Streams creds in `.env` and run
   `backfill-official-chainlink` + `backfill-settlements` to upgrade numerics to
   settlement-grade and clear MANUAL_REVIEW windows.
3. When `data-readiness` reports `backtest_allowed=true`, run `paper-backtest`
   (executable bid/ask/depth, purge/embargo), then fit + calibrate the models.


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


<!-- KALSHI-WS-FEASIBILITY -->

## Kalshi market-data WebSocket feasibility (READ-ONLY)

The high-res reprice-lag v2 result is **research-only / no edge yet**: the Kalshi book is
REST-polled (~1.1s), so +250ms/+500ms response horizons are ~0% covered and stale-quote
candidates are net-negative after fees/buffer. True sub-second stale-quote testing would need
read-only Kalshi market-data WebSocket book updates.

`kalshi-ws-feasibility` is an OPTIONAL, READ-ONLY spike: it checks deps + credentials
(presence only - secrets never printed), finds the active KXBTC15M ticker, and (if read-only
creds are present) opens a short market-data WS connection (`orderbook_delta`), measuring book
update frequency + sub-second availability. Kalshi gates even market-data WS behind a key, so
without credentials it blocks cleanly (env-var NAMES only). A `KalshiWSBookSource` exists behind
`KALSHI_HIRES_BOOK_SOURCE=websocket` (REST stays default + fallback; never auto-enabled).
Credentials, if configured, are for **read-only market data only** - no orders, no paper/live,
no portfolio/account endpoints. `live_submission_allowed=false` throughout.
