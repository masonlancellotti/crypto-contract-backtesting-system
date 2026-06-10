# RUNBOOK.md — Operations

Operational guide for running `btc5m` safely. Default mode is **paper**; live
trading is **disabled**. **Venue: Kalshi BTC 15m (KXBTC15M).** The legacy
Polymarket BTC 5m leg was removed 2026-06-10 (recoverable from git history).

---

## 0. Kalshi BTC 15m (PRIMARY) — daily run

```powershell
cd C:\Users\mason\downloads\polymarket-btc-five-mins
.\.venv\Scripts\Activate.ps1

# 1) What's open/upcoming/settled now (public; no keys needed)
python -m btc5m.cli kalshi-discover --series KXBTC15M --status open --lookahead-minutes 60

# 1b) Diagnose discovery 'cur=0' — nearest CURRENT/UPCOMING markets with open/close, seconds-to,
#     status, classified phase, and BOTH current UTC + Kalshi server time (exposes clock skew).
python -m btc5m.cli kalshi-nearest-markets --series KXBTC15M --max-markets 8

# 1c) Audit what collect-continuous WOULD record this cycle (phase-prioritized: active CURRENT
#     first, never displaced by an upcoming/just-closed market) and why. Mirrors the collector path.
python -m btc5m.cli kalshi-collector-targets --series KXBTC15M --max-markets 4

# 2) Inspect one market (metadata + executable book derived from yes/no bids)
python -m btc5m.cli kalshi-inspect --ticker "KXBTC15M-<...>"     # or --url "<kalshi url>"

# 3) Record orderbooks (REST polling; no trading) + underlying BTC in parallel
python -m btc5m.cli kalshi-record --series KXBTC15M --seconds 900 --interval 1 --max-markets 4
python -m btc5m.cli record-underlying --seconds 900 --sources coinbase,binance

# 3b) PREFERRED for long runs: one continuous single-process collector (Ctrl-C safe)
python -m btc5m.cli kalshi-collect-continuous --series KXBTC15M --sources coinbase,binance `
    --seconds-per-cycle 900 --interval 1 --max-markets 4 --readiness-every 1 --backfill-every 1
#   or: .\scripts\collect_kalshi_continuous.ps1

# 4) One safe paper pipeline (discover->record->rich features->model->ledger->summary)
python -m btc5m.cli run-kalshi-paper-pipeline --seconds 900 --sources coinbase,binance

# 5) After windows finalize, attach OFFICIAL Kalshi results; audit + check readiness
python -m btc5m.cli kalshi-backfill-settlements --series KXBTC15M
python -m btc5m.cli kalshi-label-audit --series KXBTC15M            # orphan vs feature-backed vs gate
python -m btc5m.cli kalshi-clean-orphan-labels --series KXBTC15M --dry-run
python -m btc5m.cli kalshi-data-readiness                           # gate = gate_windows (usable)

# 5b) Training-prep DRY-RUN (join+purge/embargo+missingness; REFUSES below gate; no training)
python -m btc5m.cli kalshi-train-dry-run --series KXBTC15M

# 5c) Model dataset + training pipeline (gated; pure-stdlib; UNCALIBRATED => not tradable)
#     Feature-backed OFFICIAL labels only (orphans excluded); windows (not rows) gate;
#     purge/embargo mandatory; hard Up/Down is DIAGNOSTIC only. No orders, no PAPER_CANDIDATE.
python -m btc5m.cli kalshi-build-model-dataset --series KXBTC15M   # -> data/models/ + reports/models/
python -m btc5m.cli kalshi-split-report --series KXBTC15M          # purged/embargoed window splits
python -m btc5m.cli kalshi-train-baselines --series KXBTC15M       # REFUSES below 150 windows
python -m btc5m.cli kalshi-train-baselines --series KXBTC15M --diagnostic-only  # NON-TRADABLE sanity fit
# python -m btc5m.cli kalshi-train-model --series KXBTC15M --model lightgbm     # blocks: optional dep not installed

# 5d) Calibration + executable backtest (gated; RESEARCH EVIDENCE; ASK prices, not midpoint)
#     Calibration is MANDATORY before any PAPER_CANDIDATE. Below gate => --diagnostic-only (NON_TRADABLE).
python -m btc5m.cli kalshi-calibration-report --series KXBTC15M                 # before/after on held-out test
python -m btc5m.cli kalshi-calibrate-model --series KXBTC15M --method isotonic --diagnostic-only
python -m btc5m.cli kalshi-backtest-baselines --series KXBTC15M --diagnostic-only   # no-trade/market/dtv/microstructure
python -m btc5m.cli kalshi-backtest-model --series KXBTC15M --model latest --calibrator latest --diagnostic-only
python -m btc5m.cli kalshi-threshold-sweep --series KXBTC15M --diagnostic-only      # gate grid; no auto-selection

# 5e) Paper-candidate policy engine (strict; gated; NEVER live; emits no orders)
#     WATCH/MANUAL_REVIEW/REJECTED/PAPER_CANDIDATE from calibrated prob + executable ASK EV.
#     PAPER_CANDIDATE requires trained+calibrated+non-diagnostic+backtested model; disabled by default.
python -m btc5m.cli kalshi-policy-dry-run --series KXBTC15M                # decisions + validity + blockers
python -m btc5m.cli kalshi-policy-report --series KXBTC15M                 # states/reasons/edge/validity + report
python -m btc5m.cli kalshi-paper-policy-sim --series KXBTC15M --limit 100  # paper fills for candidates (none yet)
# Enable only when a real model exists:  $env:KALSHI_PAPER_POLICY_ENABLED="true"

# 5e-bis) PAPER-ONLY artifact promotion + shadow/paper runtime (explicit; NEVER live).
#   Staged artifacts are INACTIVE. The runtime loads model/calibrator ONLY from an explicit,
#   SHA-pinned manifest (data/models/paper_promoted/), never newest-by-mtime / staged / diagnostic.
python -m btc5m.cli kalshi-paper-runtime-status --series KXBTC15M                       # mode + manifest validity
python -m btc5m.cli kalshi-paper-promotion-review --series KXBTC15M --model <m.pkl> --calibrator <c.pkl>  # eligibility
python -m btc5m.cli kalshi-promote-paper-artifacts --series KXBTC15M --model <m.pkl> --calibrator <c.pkl> --reason "..."          # DRY-RUN
python -m btc5m.cli kalshi-promote-paper-artifacts --series KXBTC15M --model <m.pkl> --calibrator <c.pkl> --reason "..." --write   # writes manifest (PAPER ONLY)
python -m btc5m.cli kalshi-shadow-run --series KXBTC15M --seconds 60                    # score+log only; no fills, no live
python -m btc5m.cli kalshi-demote-paper-artifacts --series KXBTC15M --write             # rollback (preserves artifacts)
#   Runtime mode: $env:KALSHI_MODEL_RUNTIME_MODE="shadow"|"paper" (default disabled). Paper candidates also
#   need $env:KALSHI_PAPER_POLICY_ENABLED="true" AND pass the conservative edge policy + rate caps. Never live.

# 5e-ter) CONTROLLED PAPER EXPERIMENT (shadow first, paper only after preflight; NEVER live).
#   Disciplined harness over the PROMOTED model with preflight + abort criteria + per-run manifest/report.
python -m btc5m.cli kalshi-paper-experiment-preflight --series KXBTC15M                                  # can we shadow/paper?
#   --minutes N => LIVE LOOP for ~N min: re-reads the LATEST feature rows every --poll-interval s
#   (default 5). Filters COLLECTION rows (every discovered market) to executable ACTIVE rows
#   (in-window, book+start-ref+depth, fresh) before scoring; upcoming/closed/no-book/illiquid/stale
#   rows are counted by reason but NEVER scored. Omit --minutes (or --max-iterations 1) = single pass.
python -m btc5m.cli kalshi-paper-experiment-start --series KXBTC15M --experiment-mode shadow --minutes 1 --poll-interval 5 --name run1  # log-only, no fills
python -m btc5m.cli kalshi-paper-experiment-status --series KXBTC15M                                     # decisions/fills/abort/safety
python -m btc5m.cli kalshi-paper-experiment-report --series KXBTC15M                                     # markdown report + recommendation
#   Only after a shadow run + green preflight (still NEVER live):
python -m btc5m.cli kalshi-paper-experiment-start --series KXBTC15M --experiment-mode paper --minutes 1 --poll-interval 5  # gated fills (settle vs label)
python -m btc5m.cli kalshi-paper-experiment-stop --series KXBTC15M --reason "manual"                     # STOP flag + mark ABORTED
#   With --minutes it loops live for the budget (re-sampling fresh rows); with no --minutes it is a single pass. For a full continuous collector:
python -m btc5m.cli kalshi-collect-continuous --series KXBTC15M --sources coinbase,binance --runtime-mode shadow  # Ctrl-C to stop

# 5f) Post-entry lock-profit module (paper-only; POST-ENTRY ONLY; not a flat arb scanner; never live)
#     Monitors the OPPOSITE leg of an OPEN paper position (held YES->NO, held NO->YES) to lock profit.
#     Reports NO_POSITION until the policy opens a paper position. No orders; FOK default.
python -m btc5m.cli kalshi-lock-dry-run --series KXBTC15M                  # lock decisions on open positions
python -m btc5m.cli kalshi-lock-sim --series KXBTC15M --limit 100          # replay lock vs ride P&L (diagnostic)
# Enable only when paper positions exist:  $env:KALSHI_LOCK_MODULE_ENABLED="true"

# 5f-2) Post-entry POSITION LIFECYCLE manager (paper-only; POST-ENTRY ONLY; not a flat arb scanner; never live)
#       Higher-level orchestrator over the lock module: compares same-leg SELL value vs opposite-leg LOCK
#       value vs updated continue/ride EV (using the CURRENT calibrated probability, NOT entry-time belief)
#       and decides HOLD/RIDE / SELL_SAME_LEG / LOCK_WITH_OPPOSITE_LEG / PARTIAL_LOCK / RISK_EXIT / WATCH.
#       Reports NO_POSITION until a paper position exists. Executable bids/asks only; fees/depth/freshness gated.
python -m btc5m.cli kalshi-position-monitor-dry-run --series KXBTC15M        # lifecycle decisions on open positions
python -m btc5m.cli kalshi-position-monitor-sim --series KXBTC15M --limit 25  # replay ride-vs-act P&L (diagnostic)
python -m btc5m.cli kalshi-position-summary --series KXBTC15M                # sell/lock/ride opps + exposure + paper P&L
# Enable only when paper positions exist:  $env:KALSHI_POSITION_LIFECYCLE_ENABLED="true"

# 5f-3) Trade-frequency frontier / OVERTRADING analysis (research/reporting only; never live)
#       Score constantly, trade selectively. Measures marginal net edge vs trade frequency on a
#       leakage-safe held-out set: frequency frontier, marginal-trade curve, time-to-close buckets,
#       and within-window concentration. DISTINCT WINDOWS matter more than raw trade count.
#       Diagnostic (NON_TRADABLE) until a calibrated model exists; no policy promotion; reports only.
python -m btc5m.cli kalshi-frequency-report --series KXBTC15M               # combined report + staged suggestion
python -m btc5m.cli kalshi-frequency-sweep --series KXBTC15M --diagnostic-only --max-scenarios 60
python -m btc5m.cli kalshi-marginal-trade-curve --series KXBTC15M
python -m btc5m.cli kalshi-time-to-close-analysis --series KXBTC15M
python -m btc5m.cli kalshi-within-window-frequency --series KXBTC15M
# Reports -> reports/frequency/ ; conservative suggestion is a staged JSON (manual review; never activated).

# 5f-4) Confidence-aware EDGE THRESHOLD / reservation-price policy (research/reporting; never live)
#       Do NOT trade on model_prob > price. Conservative bound (YES p_lower / NO 1-p_upper) minus
#       fees + depth + staleness + model/calibration(Wilson buckets) + regime + overtrading + min-profit
#       buffers -> final policy edge + reservation price. Required edge rises when uncalibrated/thin/
#       stale/volatile/concentrated. Conservative by default; rejects uncalibrated models; no promotion.
python -m btc5m.cli kalshi-edge-policy-report --series KXBTC15M              # funnel + calibration buckets + suggestion
python -m btc5m.cli kalshi-edge-threshold-sweep --series KXBTC15M --diagnostic-only
# Reports -> reports/edge/ ; conservative suggestion is informational only (promoted=false; manual review).

# 5g) Live-readiness scaffolding (DRY-RUN ONLY; NEVER submits; the plane stays in the hangar)
#     Inspect the live path + build sanitized dry-run order payloads. live_submission_allowed=false always.
python -m btc5m.cli kalshi-live-blockers --series KXBTC15M                 # every live blocker + next steps
python -m btc5m.cli kalshi-live-readiness --series KXBTC15M                # full readiness report (no secrets)
python -m btc5m.cli kalshi-live-dry-run-order --series KXBTC15M --ticker SOME_TICKER --side YES --action buy --qty 1 --price 55 --tif fill_or_kill
# python -m btc5m.cli kalshi-private-read-preflight --series KXBTC15M --allow-private-read   # calls NO endpoint in this build
# Audit log (sanitized, no secrets): data/audit/kalshi_live_readiness-*.jsonl
# Enabling live is a SEPARATE future step after real paper evidence — NOT done here.

# 6) DAILY OPS (READ-ONLY; safe to run in another window while collectors run; never trades)
python -m btc5m.cli kalshi-ops-status --series KXBTC15M                    # unified dashboard
python -m btc5m.cli kalshi-collector-status --series KXBTC15M              # ACTIVE/DEGRADED/STALLED (never touches collectors)
python -m btc5m.cli kalshi-gate-progress --series KXBTC15M                 # window gate + capture-rate ETA
python -m btc5m.cli kalshi-model-health --series KXBTC15M                  # model/calibration/backtest status
python -m btc5m.cli kalshi-paper-summary --series KXBTC15M                 # signals/fills/P&L by state
python -m btc5m.cli kalshi-safety-status --series KXBTC15M                 # LIVE TRADING DISABLED
python -m btc5m.cli kalshi-doctor --series KXBTC15M                        # pass/warn/fail (add --run-tests)
python -m btc5m.cli kalshi-eod-summary --series KXBTC15M --write-report    # EOD report (+ --send-notification)
# Helper scripts: .\scripts\ops_status.ps1  .\scripts\check_sources.ps1  .\scripts\doctor.ps1  .\scripts\eod_summary.ps1  .\scripts\safety_check.ps1
# Full cheat sheet: COMMANDS.md

# 6) Per-source health (kalshi/coinbase/binance/deribit) + optional native Deribit
python -m btc5m.cli source-health --series KXBTC15M
#   Reports LIVENESS (alive? loose ~60s) AND DECISION freshness (trade-fresh? strict ~1s book / ~5s underlying)
#   per source + fresh_for_collection/decision/training/paper_candidate. A feed can be ALIVE but DECISION-stale;
#   trading uses the DECISION thresholds. Underlying: Coinbase primary, Binance fallback (config-gated). The paper
#   runtime REJECTS any candidate on decision-stale book/underlying (stale data never trades). Thresholds in .env.
# Deribit is a NATIVE OPTIONAL vol/options source (NOT a venue); disabled by default.
# One-shot public snapshot (no credentials):
#   $env:DERIBIT_ENABLED="true"
python -m btc5m.cli record-deribit --currency BTC --seconds 60 --interval 15   # optional
# Continuous WITH Deribit (joined point-in-time into v3 feature rows; never blocks Kalshi):
#   $env:DERIBIT_ENABLED="true"
#   python -m btc5m.cli kalshi-collect-continuous --series KXBTC15M --sources coinbase,binance,deribit \
#     --seconds-per-cycle 900 --interval 1 --max-markets 4 --readiness-every 1 --backfill-every 1
# Continuous WITHOUT Deribit (default, unchanged):
#   python -m btc5m.cli kalshi-collect-continuous --series KXBTC15M --sources coinbase,binance \
#     --seconds-per-cycle 900 --interval 1 --max-markets 4 --readiness-every 1 --backfill-every 1

# 6c) Low-latency hot path (PAPER-ONLY; in-memory/event-driven; NO orders)
#     Fresh book->features->preloaded scorer->executable EV->gates->WATCH/MANUAL_REVIEW/REJECTED.
#     Uncalibrated model => never PAPER_CANDIDATE. Degrades to synthetic ticks if offline.
python -m btc5m.cli kalshi-hotpath-smoke --series KXBTC15M --seconds 30 --max-markets 1 --sources coinbase,binance
python -m btc5m.cli kalshi-latency-benchmark --series KXBTC15M --samples 1000   # offline; p50/p90/p99

# 7) Safety + (optional) auth presence (no secrets printed, no orders)
python -m btc5m.cli check-live-disabled
python -m btc5m.cli kalshi-auth-smoke
```

**Authoritative gate.** All three of `kalshi-data-readiness`, `kalshi-label-audit`
and `kalshi-train-dry-run` report ONE number, **`gate_windows`** = distinct OFFICIAL
15m windows with ≥1 *usable executable book-backed* feature row (Kalshi book + BTC
ref + pre-close + valid book). Counts narrow: `official_binary_labels` (all) ≥
`feature_backed_official_windows` (any feature row) ≥ `gate_windows` (usable). The
gap `feature_backed − gate` = windows whose only rows are post-close/empty/invalid.
`orphan_labels` (official result, no features) are EXCLUDED from the gate.
`kalshi-clean-orphan-labels --write` emits a clean `kalshi_training_labels-*` set
(gate-eligible only; raw files untouched).

**Source-health.** `kalshi` is REQUIRED for features (no book ⇒ no executable
example). `coinbase` = PRIMARY BTC spot (returns/vol/basis); `binance` = perp
(basis/microprice/OFI) **and spot fallback**. A brief Coinbase ">60s stale" is a
transient REST hiccup (recorded cadence ≈ Binance), not a chronic failure; feature
rows already flag stale spot ticks at a 5s per-tick threshold. `deribit` is a NATIVE
OPTIONAL vol/options/regime source (NOT a venue), disabled by default: when enabled
it is polled on a loose interval (`DERIBIT_POLL_INTERVAL_SECONDS`, default 30s) and
joined point-in-time into v3 feature rows as `deribit_*` (with `deribit_used/stale/
age_ms/missing_reason`); its source-health uses a looser stale threshold
(`DERIBIT_STALE_THRESHOLD_SECONDS`, default 180s). If Deribit is disabled, stale, or
missing, the Kalshi pipeline (collection, features, readiness, training, paper) is
unaffected. **Collection (`DERIBIT_ENABLED`) and model-feature inclusion
(`DERIBIT_INCLUDE_IN_MODEL_FEATURES`, default false) are separate controls** — a
disabled Deribit whose `deribit_*` columns linger on historical rows is never
silently fed to the model (selecting historical columns while disabled additionally
requires `DERIBIT_ALLOW_HISTORICAL_FEATURES_WHEN_DISABLED=true`). `source-health`
reports `implemented` separately from `enabled_by_config` and surfaces
`historical_rows_present` / `disabled_by_config_but_rows_present` /
`selected_for_model_features`; `kalshi-build-model-dataset` and `kalshi-train-dry-run`
report `candidate_feature_group_status` (INCLUDED / EXCLUDED_BY_CONFIG / UNAVAILABLE /
STALE), so "disabled yet rows on disk" never looks contradictory. Recording obeys
`DERIBIT_RECORD_RAW` / `DERIBIT_RECORD_NORMALIZED`.

**Semantics that matter.** Kalshi orderbooks are YES/NO **bids** only; executable
asks are derived: `yes_ask = 1 - best_no_bid`, `no_ask = 1 - best_yes_bid`
(verified == Kalshi's own asks). No midpoint fills; depth is walked; **Kalshi
fees** (config; ASSUMED until verified) are subtracted from edge. Labels come from
Kalshi's OFFICIAL `result`; a BTC proxy is only ever PROVISIONAL_REFERENCE.
Outputs: `data/raw|normalized/kalshi_*`, `data/labels/kalshi_settlement_labels-*`,
`data/features/kalshi_feature_rows-*`, `data/paper/kalshi_paper_ledger-*`,
`reports/paper/kalshi_session_summary-*`. See `PROJECT_STATE.md` and `RESEARCH_LEDGER.md`.

---

## Setup (fresh machine)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[models]"      # or minimal: pip install -e .
copy .env.example .env           # fill in local values; never commit .env
pytest -q                        # full offline suite must pass
python -m btc5m.cli check-live-disabled
```

Python 3.11+ (tested on 3.13). Optional ML deps (numpy/pandas/sklearn/lightgbm)
are checked by `python -m btc5m.cli dependency-check`; everything degrades to a
pure-stdlib fallback if they are absent. Pushover notification creds are
optional (`PUSHOVER_*` in `.env`); missing creds fall back to a Noop notifier
(`python -m btc5m.cli notify-test` to verify).

> The legacy Polymarket BTC 5m sections that used to live here were removed on
> 2026-06-10 along with the code (git history has both).

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
