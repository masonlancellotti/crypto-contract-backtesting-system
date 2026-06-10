# NEXT_STEPS.md

> **PRIMARY venue is Kalshi BTC 15m (KXBTC15M).** See `KALSHI_PIVOT_STATE.md` for
> the authoritative state. The sections below the Kalshi block are the legacy
> (dormant) Polymarket BTC 5m notes.

## Kalshi BTC 15m — the three immediate next actions (authoritative)
1. Keep the continuous collector running across many 15-minute windows:
   `.\scripts\collect_kalshi_continuous.ps1` (single process; Ctrl-C safe). It
   records books + Coinbase/Binance underlying, builds rich features, and backfills
   OFFICIAL settlements every cycle.
2. Watch `python -m btc5m.cli kalshi-data-readiness` — grow the authoritative
   **`gate_windows`** (distinct OFFICIAL windows with a USABLE executable feature
   row) toward 60 (backtest) / 150 (train). `kalshi-label-audit` shows the same gate
   and confirms orphans stay excluded; `kalshi-train-dry-run` validates the
   features↔labels join + purge/embargo + column missingness while still BLOCKED.
3. When `gate_windows ≥ 60`, run `kalshi-clean-orphan-labels --write` for the clean
   `kalshi_training_labels-*` set, then fit + calibrate on purged/embargoed 15m
   windows before trusting any PAPER_CANDIDATE; keep live disabled.

**Gate vocabulary:** `official_binary_labels` (all settled results) ≥
`feature_backed_official_windows` (have any feature row) ≥ `gate_windows`
(have a USABLE executable row — AUTHORITATIVE). `orphan_labels` (no features) are
excluded. **Source-health:** Coinbase = primary BTC spot; Binance = perp +
spot fallback; a brief Coinbase >60s "stale" is a transient REST hiccup (cadence
≈ Binance), and feature rows already flag stale spot ticks at a 5s threshold.

Public Kalshi market data needs NO credentials. For authenticated WS/account/live
later, set `KALSHI_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH` (env-only; key in a
gitignored file). Never paste keys into chat.

**Ops / monitoring (READ-ONLY; run these in a window beside the collectors).** Daily
visibility without touching collectors or live: `kalshi-ops-status --series KXBTC15M`
(one dashboard: collector freshness, gate progress, model/backtest/paper health,
safety), `kalshi-collector-status` (ACTIVE/DEGRADED/STALLED from file ages — never
stops/restarts a collector), `kalshi-gate-progress` (window gate + recent capture rate
+ ETA; orphans excluded), `kalshi-model-health`, `kalshi-backtest-summary`,
`kalshi-paper-summary`, `kalshi-lock-summary`, `kalshi-safety-status` (LIVE TRADING
DISABLED), `kalshi-doctor` (pass/warn/fail; `--run-tests`), `kalshi-eod-summary
--write-report` (short safe notification). All support `--json`/`--markdown`/
`--write-report` (→ `reports/ops`, `reports/eod`); helper scripts under `scripts/`;
full copy-paste reference in `COMMANDS.md`. Run `dependency-check` to see which
optional ML/data deps are installed (numpy/pandas/sklearn/lightgbm/pyarrow) and which
features fall back to pure-stdlib. **How to read the gate:** `gate_windows` = distinct
feature-backed OFFICIAL 15m windows (orphans excluded); backtest gate 60,
train/calibration gate 150. As of 2026-06-02 `gate_windows ≈ 86` (backtest gate reached;
train gate not yet). Consolidated docs: `ARCHITECTURE.md`, `MODEL_PIPELINE.md`,
`LIVE_SAFETY.md`, `INTEGRATION_REGRESSION_REPORT.md`.

**Live-readiness scaffolding (DRY-RUN ONLY; the plane stays in the hangar).** The live
path is now INSPECTABLE without being enabled. `kalshi-live-blockers --series KXBTC15M`
lists every blocker + next actions; `kalshi-live-readiness --series KXBTC15M [--json]`
gives the full report (credentials w/o values, model/calibration/backtest/paper-evidence/
risk/source-health/order-plan); `kalshi-live-dry-run-order --series KXBTC15M --ticker T
--side YES --action buy --qty 1 --price 55 --tif fill_or_kill` validates + builds a
SANITIZED dry-run payload (+checksum; endpoint documented, NEVER called);
`kalshi-private-read-preflight` calls no endpoint in this build. **Nothing submits:**
`live_submission_allowed` is hard-False on config/result/payload/adapter; `submit()`/
`cancel()` refuse and issue no HTTP; the kill switch, manual confirmation (absent by
default), model/calibrator/backtest/paper-evidence, and risk gates are all required and
never bypassed. Paper-evidence is NEVER auto-approved (manual
`data/models/kalshi_live_approval.json`, default false). **Enabling live is a SEPARATE
future prompt after real paper evidence — not now.** All `KALSHI_LIVE_*` defaults are
safe/locked (see `.env.example` / `config/live.example.yaml`).

**Post-entry lock-profit module (paper-only; post-entry only; NEVER live).** POSITION
MANAGEMENT after a paper entry — **not** a flat-position arb scanner. It monitors the
OPPOSITE leg of an EXISTING paper position (held YES→monitor NO, held NO→monitor YES)
and decides NO_POSITION / ALREADY_FULLY_LOCKED / WATCH / RIDE / LOCK_FULL /
LOCK_PARTIAL / REJECTED from guaranteed locked profit after fees vs the naked
continue-EV (when a model exists), under depth/staleness/time gates. Commands:
`kalshi-lock-dry-run --series KXBTC15M`, `kalshi-lock-sim --series KXBTC15M --limit 100`.
It never opens directional positions, never scans flat markets, and never submits a
live order (`live_submission_allowed=false`; FOK default, IOC partials only with
`--allow-partial`). Today both report **NO_POSITION** because the policy emits no
PAPER_CANDIDATE yet. The module activates only once a real (calibrated, backtested,
gated) model produces a paper entry. Live trading stays disabled.

**Paper-candidate policy engine (strict, gated; NEVER live).** The operational layer
that decides when a model output may become a `PAPER_CANDIDATE`. It uses the
calibrated probability + executable YES/NO **ask** EV (never midpoint) and gates on
model/calibration/backtest validity, freshness, depth, spread, time-to-close, and
risk limits, emitting `WATCH / MANUAL_REVIEW / REJECTED / PAPER_CANDIDATE` with reason
codes. Commands: `kalshi-policy-dry-run --series KXBTC15M`, `kalshi-policy-report
--series KXBTC15M`, `kalshi-paper-policy-sim --series KXBTC15M --limit 100`. Disabled
by default (`KALSHI_PAPER_POLICY_ENABLED=false`); even enabled it currently REJECTS
because the only model is NON_TRADABLE_DIAGNOSTIC_ONLY (calibrator diagnostic, backtest
below gate) — so **no PAPER_CANDIDATE is reachable** and `live_submission_allowed` is
always False. A hard Up/Down class alone never trades. The next prompt is the
post-entry **lock-profit** module (monitor the opposite leg of an open paper position);
the policy ledger already carries `opposite_side_ask` + position metadata for it. Live
trading stays disabled.

**Calibration + executable backtest (gated; pure-stdlib; RESEARCH EVIDENCE).** The
proof pipeline that answers whether probabilities are calibrated and whether any
signal is tradable AFTER executable Kalshi ask prices + fees + depth + staleness.
`kalshi-calibration-report --series KXBTC15M` (Brier/log-loss/ECE/reliability,
before vs after, on a held-out test window split), `kalshi-calibrate-model --series
KXBTC15M --method isotonic [--diagnostic-only]` (saves a calibrator; NON_TRADABLE
below gate), `kalshi-backtest-baselines --series KXBTC15M --diagnostic-only`
(no-trade / market-implied / distance-time-vol / microstructure, leakage-safe,
walk-forward), `kalshi-backtest-model --series KXBTC15M --model latest --calibrator
latest --diagnostic-only`, `kalshi-threshold-sweep --series KXBTC15M --diagnostic-only`
(gate grid; **never auto-selects** a policy — max in-sample P&L overfits). Uses
executable **ask** prices, never midpoint. Current diagnostic evidence shows **no
tradable edge after costs** (market-implied trades 0; fitted baselines lose) — this
is evidence, not a profitability claim. Calibration is **mandatory before any
PAPER_CANDIDATE**; the next prompt is the paper-candidate policy engine (NOT live).

**Model dataset + training pipeline (gated; pure-stdlib).** Build the dataset and
inspect readiness now; real training stays blocked until ≥150 feature-backed
OFFICIAL windows. Training uses **feature-backed OFFICIAL labels only** (orphans
excluded), **windows (not rows)** drive the gate, **purge/embargo is mandatory**,
and a hard Up/Down class is **diagnostic only** — trade decisions need probability
+ executable EV + calibration + gates. Commands:
`kalshi-build-model-dataset --series KXBTC15M` (→ `data/models/` table + metadata/
schema/missingness/gate reports; marks `NOT_TRAINING_READY` below the gate),
`kalshi-split-report --series KXBTC15M` (purged/embargoed window splits),
`kalshi-train-baselines --series KXBTC15M` (REFUSES below gate; add `--diagnostic-only`
to fit NON-TRADABLE market-implied + distance/time/vol + microstructure-logistic
sanity models), `kalshi-train-model --series KXBTC15M --model lightgbm` (blocks: the
optional `models` deps — numpy/pandas/sklearn/lightgbm — are not installed; nothing
faked). Every model is UNCALIBRATED, so artifacts are not usable by paper/live
policy (`is_tradable()` False) and **PAPER_CANDIDATE stays blocked**. Calibration +
executable backtest are the next prompts.

**Low-latency hot path (5-minute-grade; paper-only).** An in-memory, event-driven
Kalshi decision layer is built so future 5m markets need no rewrite. Try it safely:
`kalshi-hotpath-smoke --series KXBTC15M --seconds 30 --max-markets 1 --sources coinbase,binance`
(book→features→preloaded scorer→executable EV→stale/depth/line/model gates→
WATCH/MANUAL_REVIEW/REJECTED; degrades to synthetic ticks if offline; **no orders**).
Measure compute latency: `kalshi-latency-benchmark --series KXBTC15M --samples 1000`
(offline; p50/p90/p99 for feature/score/decision). All `KALSHI_LOW_LATENCY_*`
settings are SAFE/off by default; horizon knobs (duration, quote-age, lookbacks)
are config-driven for 15m-now / 5m-later. WebSocket needs Kalshi auth; otherwise
REST polling fallback. Uncalibrated model is capped at MANUAL_REVIEW (never
PAPER_CANDIDATE); live trading remains impossible.

**Optional — Deribit native vol/options source (NOT a venue).** Disabled by default.
Enable with `DERIBIT_ENABLED=true` (public reads need no credentials) and either run
`record-deribit --currency BTC --seconds 60 --interval 15` or add `deribit` to the
collector's `--sources` (`coinbase,binance,deribit`). Deribit is polled on a loose
interval (`DERIBIT_POLL_INTERVAL_SECONDS`, default 30s) and joined point-in-time into
v3 feature rows as `deribit_*` (index/DVOL/hist-vol/near-expiry+ATM IV/OI+put-call
split/volume/ratios/skew/IV-minus-realized-vol/regime) with freshness + missingness
flags. Disabled/stale/missing Deribit never blocks Kalshi collection, features,
readiness, training, or paper. `source-health` and `kalshi-train-dry-run` report
Deribit coverage; `kalshi-data-readiness` gating is unchanged (Deribit never gates).

**Whether Deribit columns enter the MODEL is a separate switch from collection.**
`DERIBIT_INCLUDE_IN_MODEL_FEATURES` (default false) decides if the `deribit_*`
candidate columns are eligible for training; it is independent of `DERIBIT_ENABLED`.
Historical `deribit_*` columns can exist on old rows even while disabled, but they
are NEVER silently fed to the model — selection requires the include flag plus an
enabled source (or `DERIBIT_ALLOW_HISTORICAL_FEATURES_WHEN_DISABLED=true` to opt in
to using historical columns while disabled). `kalshi-build-model-dataset` /
`kalshi-train-dry-run` print `candidate_feature_group_status`
(INCLUDED / EXCLUDED_BY_CONFIG / UNAVAILABLE / STALE) and distinguish column
presence from selection; `source-health` shows `disabled_by_config_but_rows_present`
and `selected_for_model_features`. Recording obeys `DERIBIT_RECORD_RAW` /
`DERIBIT_RECORD_NORMALIZED`.

---

## (LEGACY / DORMANT — Polymarket BTC 5m) Immediate setup actions
1. Create a virtualenv and `pip install -e .`.
2. `copy .env.example .env` and fill in local values (see below).
3. Run `python -m btc5m.cli init` then `pytest -q` to confirm a clean baseline.

## Manual credential / config items (set locally in `.env`, never in chat)
- `LOCAL_TIMEZONE` (default `Europe/Dublin`) and `EOD_SUMMARY_TIME`.
- Risk limits: `MAX_ORDER_SIZE`, `MAX_POSITION_PER_CONTRACT`, `MAX_DAILY_LOSS`,
  `MAX_OPEN_RISK`, `MAX_TRADES_PER_HOUR`, `PAPER_STARTING_BANKROLL`.
- Pushover (optional): `PUSHOVER_ENABLED=true`, `PUSHOVER_APP_TOKEN`,
  `PUSHOVER_USER_KEY` (+ optional `PUSHOVER_DEVICE`, `PUSHOVER_PRIORITY`,
  `PUSHOVER_SOUND`). Missing/disabled → Noop fallback.
- Polymarket (only when enabling live later): `POLYMARKET_API_KEY`,
  `POLYMARKET_API_SECRET`, `POLYMARKET_API_PASSPHRASE`,
  `POLYMARKET_FUNDER_ADDRESS`, `POLYMARKET_WALLET_ADDRESS`. Not needed for
  paper or for public discovery/recording.
- Keep `LIVE_TRADING_ENABLED=false` until backtest + paper evidence exists.

## Data-source smoke checks
- `python -m btc5m.cli status` — config + which feeds are live vs stubbed.
- `python -m btc5m.cli debug-discovery --asset BTC --duration 5m --lookahead-hours 2`
  — full discovery diagnostics: routes, window classification, UI-mismatch check.
- `python -m btc5m.cli discover-markets --asset BTC --duration 5m` — current/upcoming
  markets (slug-grid discovery; reliably includes the live window).
- `python -m btc5m.cli record --asset BTC --duration 5m --seconds 60` — books + provisional line.

### If discovery and the Polymarket UI ever disagree (manual override)
- `python -m btc5m.cli inspect-market --url "<paste current Polymarket BTC 5m URL>"`
- `python -m btc5m.cli inspect-market --slug "btc-updown-5m-<unix_ts>"`
- `python -m btc5m.cli record-market --url "<paste URL>" --seconds 300`
- `python -m btc5m.cli record-underlying --seconds 60 --sources coinbase,binance` — BTC feeds.
- `python -m btc5m.cli backfill-settlements --asset BTC --duration 5m` — label completed windows.
- `python -m btc5m.cli label-status` — summarize label rows.
- `python -m btc5m.cli check-live-disabled` — confirms live adapter refuses.
- `python -m btc5m.cli notify-test` — Noop unless Pushover enabled+configured.

## What is OFFICIAL vs PROVISIONAL
- OFFICIAL (settlement-grade): the binary Up/Down outcome from Gamma once resolved.
- PROVISIONAL_REFERENCE: all numeric lines, final prices, and settlement_distance
  (Coinbase/Binance proxy, NOT the Chainlink resolution source). Disagreements
  near ties are flagged MANUAL_REVIEW, not silently resolved.

## Next engineering milestones
1. Source an OFFICIAL Chainlink BTC/USD value (data.chain.link stream / on-chain
   report) to upgrade lines + final prices to settlement-grade.
2. Add the Polymarket / Coinbase / Binance WS streams (optional `websockets`) for
   lower-latency data; reconcile against REST snapshots.
3. Build the first feature rows from normalized underlying + book data.

## Paper-ready commands (current)
- `python -m btc5m.cli run-paper-pipeline --seconds 600 --sources coinbase,binance`
  — full record-only/paper loop: discover → record (+line) → record-underlying →
  backfill-settlements → build-features → decide → **paper ledger** → **session
  summary**. Each step fails safe and reports blockers. Add `--no-network` to run
  only on already-recorded data.
- `python -m btc5m.cli notification-health` — notification queue + provider health
  (offline self-test; no network, no secrets).

## Post-entry position lifecycle manager (paper-only)
Monitors EXISTING paper positions and compares same-leg SELL value vs opposite-leg
LOCK value vs updated continue/ride EV (current calibrated probability, not
entry-time belief) → HOLD/RIDE / SELL_SAME_LEG / LOCK_WITH_OPPOSITE_LEG /
PARTIAL_LOCK / RISK_EXIT / WATCH. Reuses the lock module; executable bids/asks only;
not a flat arb scanner; never opens positions; no live orders. Disabled by default
(`KALSHI_POSITION_LIFECYCLE_ENABLED=false`). CLI: `kalshi-position-monitor-dry-run /
-sim / kalshi-position-summary` (report NO_POSITION until a paper position exists).

## Trade-frequency frontier / overtrading analysis (research-only)
Score constantly, trade selectively. `trade_frequency.py` measures marginal net edge
vs trade frequency on a leakage-safe held-out set: frequency frontier, marginal-trade
curve (where extra trades stop adding value), time-to-close buckets, within-window
concentration (distinct windows > raw trades). Fees + executable prices; no midpoint;
NON_TRADABLE until calibrated. No promotion, no live — conservative suggestions are
staged JSON (`promoted=false`). CLI: `kalshi-frequency-report / -sweep /
kalshi-marginal-trade-curve / kalshi-time-to-close-analysis / kalshi-within-window-frequency`
→ `reports/frequency/`.

## Paper-ONLY promotion + shadow/paper runtime (NEVER live)
Staged artifacts are inactive. The shadow/paper runtime loads model/calibrator ONLY from
an explicit, SHA-pinned promotion manifest (`data/models/paper_promoted/`) — never
newest-by-mtime, never staged, never diagnostic/uncalibrated. Flow:
`kalshi-paper-promotion-review` (eligibility + honest warnings) →
`kalshi-promote-paper-artifacts … [--write]` (dry-run default; COPIES + manifests,
`live_approved=false`) → `kalshi-shadow-run` (score/log only, no fills) →
`kalshi-demote-paper-artifacts --write` (rollback). `KALSHI_MODEL_RUNTIME_MODE`
(disabled|shadow|paper, default disabled) + `KALSHI_PAPER_POLICY_ENABLED` gate emission;
PAPER_CANDIDATE additionally requires the confidence-aware edge policy + per-window/daily/
cooldown caps. `live_submission_allowed` always False; every action audited. Promotion is
NOT proof of profitability. CLI: `kalshi-paper-runtime-status` for state.

## Controlled PAPER experiment (shadow first, paper only after preflight; NEVER live)
`paper_experiment.py` runs the PROMOTED model under strict monitoring + abort criteria.
Flow: `kalshi-paper-experiment-preflight` (live-disabled, promotion valid+SHA, non-diagnostic,
calibrator valid, reports present, source DECISION-freshness, conservative thresholds →
`preflight_pass` / `paper_ready` / `recommended_mode`) → `kalshi-paper-experiment-start
--experiment-mode shadow` (log-only, no fills) → review `…-status` / `…-report` → only then
`--experiment-mode paper` (gated fills, settle vs OFFICIAL label) which REQUIRES a prior shadow
run (unless `--skip-shadow-warning`). Per-run manifest under `data/paper/experiments/`
(CREATED/RUNNING/COMPLETED/ABORTED); `…-stop --reason X` writes a STOP flag + marks ABORTED
(no collectors killed). Abort on: unexpected live, source stale, hash mismatch, model/policy/fill
error, loss/drawdown limit. Config `KALSHI_PAPER_EXPERIMENT_*` (disabled+shadow default).
Live is never honored. `kalshi-collect-continuous --runtime-mode shadow` runs continuous shadow.

## Confidence-aware edge threshold / reservation-price policy (paper-only)
`edge_policy.py` + `uncertainty.py`: don't trade on `model_prob > price` — use a
conservative probability bound (YES p_lower / NO 1−p_upper), then subtract fees,
depth, staleness, model + calibration (Wilson buckets), regime, overtrading, and
minimum-profit buffers → final policy edge + reservation price. Required edge rises
when uncalibrated/thin/stale/volatile/concentrated. Conservative by default; rejects
uncalibrated/diagnostic models; never promotes; no live. CLI: `kalshi-edge-policy-report
/ kalshi-edge-threshold-sweep` → `reports/edge/`.

## Notifications & explanations (latency-safe)
Notifications are async/background (enqueue-and-continue); the decision/order path
never blocks on a send, explanation, or HTTP call. Explanations are generated
**after** the decision from structured reason codes (offline templates; no
LLM/API). WATCH/REJECTED are coalesced/suppressed by default; high-priority events
(PAPER_CANDIDATE, fills, lock, collector/source-stale, errors) are preserved in a
bounded queue. Tune with `NOTIFICATIONS_*` in `.env`. Live trading stays disabled.
- `python -m btc5m.cli data-readiness --asset BTC --duration 5m` — whether
  training/backtest is allowed (stays blocked until enough non-leaky OFFICIAL rows).
- `python -m btc5m.cli paper-backtest --asset BTC --duration 5m` — gated minimum
  backtest (blocked, with exact missing data, on sparse data; never fakes P&L).
- `python -m btc5m.cli build-features` / `decide` — features and gated decisions.
- `python -m btc5m.cli backfill-official-chainlink` — OFFICIAL lines (gated).

Outputs: `data/paper/paper_ledger-YYYYMMDD.jsonl`,
`reports/paper/session_summary-YYYYMMDD.md`.

## (LEGACY / DORMANT — Polymarket BTC 5m) next actions — NOT authoritative
> The authoritative immediate actions are the **Kalshi** block at the TOP of this
> file (and `KALSHI_PIVOT_STATE.md`). The steps below apply ONLY if the dormant
> Polymarket path is explicitly re-enabled (`POLYMARKET_DORMANT=false`).
1. Run `collect-continuous --max-markets 0` (single rolling process) for several
   hours across many full 5-minute windows; watch `data-readiness` climb
   (official_binary_labels, provisional_numeric_lines, feature_rows_with_line).
2. Provide Chainlink Data Streams creds locally and run
   `backfill-official-chainlink`, then re-run `backfill-settlements` for
   settlement-grade numerics and to clear MANUAL_REVIEW windows.
3. When `data-readiness` reports `backtest_allowed=true`, run `paper-backtest`,
   then fit + calibrate the LightGBM/quantile models (currently honest scaffolds).


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
