# Kalshi BTC 15m — command cheat sheet

Copy-paste PowerShell. Venue: **Kalshi KXBTC15M** (legacy Polymarket leg removed 2026-06-10).
**Live trading is disabled by default and impossible without a separate future
enable step.** All commands below are prefixed with the repo venv python:

```powershell
cd C:\Users\mason\Downloads\polymarket-btc-five-mins
$PY = ".\.venv\Scripts\python.exe"
```

Tags: **[RO]** read-only · **[W]** writes data · **[NET]** uses network ·
**[PAPER]** paper-only · **[LIVE-OFF]** live always disabled · **[LONG]** long-running.

## Collection (run in their own PowerShell windows)
```powershell
# Continuous Kalshi collector (coinbase+binance)         [W][NET][LONG][PAPER]
$PY -m btc5m.cli kalshi-collect-continuous --series KXBTC15M --sources coinbase,binance --seconds-per-cycle 900 --interval 1 --max-markets 4 --readiness-every 1 --backfill-every 1
# ... with Deribit (optional native vol/options source)  [W][NET][LONG][PAPER]
$env:DERIBIT_ENABLED="true"; $PY -m btc5m.cli kalshi-collect-continuous --series KXBTC15M --sources coinbase,binance,deribit --seconds-per-cycle 900 --interval 1 --max-markets 4 --readiness-every 1 --backfill-every 1
# Deribit one-shot smoke (public; no creds)              [W][NET]
$env:DERIBIT_ENABLED="true"; $PY -m btc5m.cli record-deribit --currency BTC --seconds 60 --interval 15
# Deribit MODEL-feature inclusion is a SEPARATE switch from collection (default off);
# disabled Deribit's historical deribit_* columns are never silently fed to the model:
#   $env:DERIBIT_ENABLED="true"; $env:DERIBIT_INCLUDE_IN_MODEL_FEATURES="true"
# Then kalshi-build-model-dataset / kalshi-train-dry-run report candidate_feature_group_status
# (INCLUDED | EXCLUDED_BY_CONFIG | UNAVAILABLE | STALE). Recording obeys
# DERIBIT_RECORD_RAW / DERIBIT_RECORD_NORMALIZED.
```

## Daily operations (SAFE while collectors run)
```powershell
$PY -m btc5m.cli dependency-check                              # optional ML/data deps + degraded features [RO]
$PY -m btc5m.cli kalshi-ops-status --series KXBTC15M            # unified dashboard      [RO]
$PY -m btc5m.cli kalshi-collector-status --series KXBTC15M      # fresh/stale feeds      [RO]
$PY -m btc5m.cli kalshi-gate-progress --series KXBTC15M         # window gate + ETA      [RO]
$PY -m btc5m.cli kalshi-data-readiness --series KXBTC15M        # authoritative gate     [RO]
$PY -m btc5m.cli kalshi-label-audit --series KXBTC15M           # orphan vs feature-backed [RO]
$PY -m btc5m.cli source-health --series KXBTC15M               # LIVENESS (alive?) vs DECISION (trade-fresh?) per source [RO]
$PY -m btc5m.cli kalshi-source-freshness-smoke --series KXBTC15M --seconds 60   # DECISION-fresh fraction over 60s [RO]
# If VERDICT=ALIVE_BUT_DECISION_STALE: the collector is recording the underlying too slowly for decisions.
# Restart the collector (it now flushes features incrementally + re-polls Coinbase/Binance every 1-2s):
#   $PY -m btc5m.cli kalshi-collect-continuous --series KXBTC15M --sources coinbase,binance --interval 1 --max-markets 1
# Then re-run the smoke; underlying_decision_fresh_fraction should rise. Do NOT loosen the 5s decision threshold.
# Source freshness: a collector can be ALIVE (loose ~60s liveness) while DECISION-stale (strict ~1s book / ~5s
# underlying). Trading uses the DECISION thresholds; stale data NEVER produces a PAPER_CANDIDATE. Binance is the
# Coinbase fallback only when UNDERLYING_ALLOW_BINANCE_FALLBACK and itself fresh. Thresholds: KALSHI_BOOK_DECISION_MAX_AGE_MS,
# COINBASE/BINANCE_DECISION_MAX_AGE_MS, UNDERLYING_*, KALSHI_REJECT_PAPER_IF_* (see .env.example).
$PY -m btc5m.cli kalshi-doctor --series KXBTC15M                # pass/warn/fail health  [RO]
$PY -m btc5m.cli kalshi-eod-summary --series KXBTC15M --write-report   # EOD report      [RO][W report]
# helper scripts: .\scripts\ops_status.ps1  .\scripts\check_sources.ps1  .\scripts\check_readiness.ps1  .\scripts\doctor.ps1  .\scripts\eod_summary.ps1  .\scripts\safety_check.ps1
```

## Model dataset + training (gated; sklearn when installed, else pure-stdlib DIAGNOSTIC-ONLY)
```powershell
# Install the serious ML stack into the LOCAL .venv (not global). LightGBM optional.
$PY -m pip install -e ".[models,data,live,dev]"
$PY -m btc5m.cli dependency-check                              # serious_training_available + features [RO]
$PY -m btc5m.cli kalshi-train-dry-run --series KXBTC15M         # join+purge/embargo, REFUSES below gate [RO]
# STAGING is the safe default: --staged writes to data/models/staged/ (runtime NEVER scans it);
# the dataset latest pointers are left UNCHANGED unless --update-latest is passed. No promotion here.
$PY -m btc5m.cli kalshi-build-model-dataset --series KXBTC15M --format parquet --staged   # [W staged]
$PY -m btc5m.cli kalshi-split-report --series KXBTC15M          # purged/embargoed splits [RO]
$PY -m btc5m.cli kalshi-train-baselines --series KXBTC15M --staged   # sklearn baselines -> STAGED_NON_PROMOTED [W staged]
$PY -m btc5m.cli kalshi-train-model --series KXBTC15M --model lightgbm --staged  # optional challenger (gated) [W staged]
$PY -m btc5m.cli kalshi-model-health --series KXBTC15M          # ACTIVE model/calibration/backtest status [RO]
# Prove no active runtime artifact changed (compare to a prior manifest):
$PY scripts\artifact_manifest.py --label check --compare reports\models\pre_ml_upgrade_artifact_manifest_*.json
```

## Calibration + executable backtest (research evidence; gated)
```powershell
$PY -m btc5m.cli kalshi-calibration-report --series KXBTC15M --staged          # before/after on HELD-OUT TEST [RO/W]
$PY -m btc5m.cli kalshi-calibrate-model --series KXBTC15M --method isotonic --staged  # calibrator -> STAGED [W staged]
$PY -m btc5m.cli kalshi-backtest-baselines --series KXBTC15M --staged           # uses the STAGED model [W]
$PY -m btc5m.cli kalshi-threshold-sweep --series KXBTC15M --staged              # gate grid; no auto-select [W]
# --staged routes model/calibrator selection to data/models/staged/; reports are EVIDENCE only, no promotion.
$PY -m btc5m.cli kalshi-backtest-summary --series KXBTC15M                       # latest backtest reports [RO]
```

## Paper policy + lock-profit (paper-only; gated; never live)
```powershell
$PY -m btc5m.cli kalshi-policy-dry-run --series KXBTC15M        # WATCH/MANUAL_REVIEW/REJECTED/PAPER_CANDIDATE [RO][PAPER]
$PY -m btc5m.cli kalshi-policy-report --series KXBTC15M         # decisions + validity + blockers [RO][PAPER]
$PY -m btc5m.cli kalshi-paper-policy-sim --series KXBTC15M --limit 100   # paper fills (none until model approved) [W][PAPER]
$PY -m btc5m.cli kalshi-paper-summary --series KXBTC15M         # signals/fills/P&L by state [RO][PAPER]
$PY -m btc5m.cli kalshi-lock-dry-run --series KXBTC15M          # post-entry lock on OPEN positions [RO][PAPER]
$PY -m btc5m.cli kalshi-lock-summary --series KXBTC15M          # locked vs naked exposure [RO][PAPER]
```

## Paper-ONLY artifact promotion + shadow/paper runtime (explicit; NEVER live)
```powershell
# Runtime loads model/calibrator ONLY from the paper-promotion manifest (never newest-by-mtime,
# never staged/diagnostic). Promotion COPIES staged artifacts into data/models/paper_promoted/.
$PY -m btc5m.cli kalshi-paper-runtime-status --series KXBTC15M                    # mode + manifest validity [RO]
$PY -m btc5m.cli kalshi-paper-promotion-review --series KXBTC15M --model <staged.pkl> --calibrator <staged.pkl>  # eligibility [RO]
$PY -m btc5m.cli kalshi-promote-paper-artifacts --series KXBTC15M --model <m.pkl> --calibrator <c.pkl> --reason "..."          # DRY-RUN (default)
$PY -m btc5m.cli kalshi-promote-paper-artifacts --series KXBTC15M --model <m.pkl> --calibrator <c.pkl> --reason "..." --write   # writes PAPER_ONLY manifest
$PY -m btc5m.cli kalshi-shadow-run --series KXBTC15M --seconds 60                 # score+log only; no fills [W report/ledger]
$PY -m btc5m.cli kalshi-demote-paper-artifacts --series KXBTC15M --write          # rollback (preserves artifacts)
# Enable paper candidates WITHOUT editing .env (explicit, conservative gates):
$env:KALSHI_MODEL_RUNTIME_MODE="paper"; $env:KALSHI_PAPER_POLICY_ENABLED="true"
# Shadow collector (does NOT paper-fill); set the env above to "shadow" first:
$PY -m btc5m.cli kalshi-collect-continuous --series KXBTC15M --sources coinbase,binance --paper-policy-enabled
# Or set the in-process runtime mode without editing .env (never live):
$PY -m btc5m.cli kalshi-collect-continuous --series KXBTC15M --sources coinbase,binance --runtime-mode shadow
```

## Controlled PAPER experiment (shadow first, paper only after preflight; NEVER live)
```powershell
# Disciplined experiment harness over the PROMOTED paper model. Shadow = score+log (no fills);
# Paper = gated fills (settle vs OFFICIAL label) ONLY if preflight passes + a shadow run happened.
$PY -m btc5m.cli kalshi-paper-experiment-preflight --series KXBTC15M                       # can we shadow/paper? [RO]
# --minutes N => LIVE LOOP: runs ~N min, re-reading the LATEST feature rows every
#   --poll-interval s (default 5). Filters COLLECTION rows (every discovered market:
#   open/upcoming/closed) down to executable ACTIVE rows (in-window, book+start-ref+depth,
#   fresh) before scoring; non-executable rows are counted by reason but NEVER scored. Output
#   shows the funnel: rows_read -> active_window/book_backed/start_reference -> executable.
$PY -m btc5m.cli kalshi-paper-experiment-start --series KXBTC15M --experiment-mode shadow --minutes 1 --poll-interval 5 --name run1  # [W] live loop
# Omit --minutes (or pass --max-iterations 1) for a SINGLE batch pass over the most recent stored rows:
$PY -m btc5m.cli kalshi-paper-experiment-start --series KXBTC15M --experiment-mode shadow --max-iterations 1     # [W] single pass
$PY -m btc5m.cli kalshi-paper-experiment-status --series KXBTC15M                          # decisions/fills/abort/safety [RO]
$PY -m btc5m.cli kalshi-paper-experiment-report --series KXBTC15M                          # markdown report + recommendation [W]
# Paper mode (only after a shadow run + green preflight; still NEVER live):
$PY -m btc5m.cli kalshi-paper-experiment-start --series KXBTC15M --experiment-mode paper --minutes 1 --poll-interval 5
#   (use --skip-shadow-warning to bypass the shadow-first guard — still never live)
$PY -m btc5m.cli kalshi-paper-experiment-stop --series KXBTC15M --reason "manual"          # STOP flag + mark ABORTED
# Abort criteria: unexpected live, source stale, hash mismatch, model/policy error, loss/drawdown limit.
# Shadow NEVER fills or emits PAPER_CANDIDATE; live_submission_allowed is always false.
```

## Position lifecycle + trade-frequency analysis (research/paper-only; never live)
```powershell
$PY -m btc5m.cli kalshi-position-monitor-dry-run --series KXBTC15M  # post-entry sell/lock/ride decisions [RO][PAPER]
$PY -m btc5m.cli kalshi-position-summary --series KXBTC15M          # open-position exposure + paper P&L [RO][PAPER]
# Trade-frequency frontier / overtrading analysis (score constantly, trade selectively):
$PY -m btc5m.cli kalshi-frequency-sweep --series KXBTC15M --diagnostic-only  # frequency-policy frontier [RO]
$PY -m btc5m.cli kalshi-frequency-report --series KXBTC15M          # frontier+marginal+ttc+overtrading+suggestion [RO]
$PY -m btc5m.cli kalshi-marginal-trade-curve --series KXBTC15M      # where marginal trades stop adding value [RO]
$PY -m btc5m.cli kalshi-time-to-close-analysis --series KXBTC15M    # performance by time-to-close bucket [RO]
$PY -m btc5m.cli kalshi-within-window-frequency --series KXBTC15M   # within-window overtrading/concentration [RO]
# Reports -> reports/frequency/ ; staged paper-policy suggestion JSON is promoted=false (manual review).
# Confidence-aware EDGE THRESHOLD / reservation-price policy (conservative; no promotion):
$PY -m btc5m.cli kalshi-edge-policy-report --series KXBTC15M       # funnel + calibration buckets + suggestion [RO]
$PY -m btc5m.cli kalshi-edge-threshold-sweep --series KXBTC15M --diagnostic-only  # threshold/buffer sweep [RO]
# Reports -> reports/edge/ ; edge = conservative-bound edge minus fees+uncertainty+regime+overtrading+min-profit.
```

## Live-readiness (DRY-RUN ONLY; never submits) and safety
```powershell
$PY -m btc5m.cli kalshi-safety-status --series KXBTC15M         # LIVE TRADING DISABLED summary [RO][LIVE-OFF]
$PY -m btc5m.cli kalshi-live-blockers --series KXBTC15M         # every live blocker + next steps [RO][LIVE-OFF]
$PY -m btc5m.cli kalshi-live-readiness --series KXBTC15M        # full readiness report (no secrets) [RO][LIVE-OFF]
$PY -m btc5m.cli kalshi-live-dry-run-order --series KXBTC15M --ticker SOME_TICKER --side YES --action buy --qty 1 --price 55 --tif fill_or_kill   # sanitized dry-run payload; NEVER sent [RO][LIVE-OFF]
$PY -m btc5m.cli check-live-disabled                            # both adapters refuse [RO][LIVE-OFF]
$PY -m btc5m.cli kalshi-notify-test --series KXBTC15M           # Noop unless Pushover configured [RO]
```

## Tests
```powershell
$PY -m pytest -q                                               # full offline suite [RO]
```

## How to read the gate counts
- **gate_windows** (authoritative) = distinct OFFICIAL-labeled 15-minute windows with
  ≥1 *usable executable book-backed* feature row. **Orphan labels (official result, no
  features) are EXCLUDED** and never inflate the gate.
- Backtest diagnostic gate = 60 windows; training/calibration gate = 150 windows (≥500 rows).
- `kalshi-collector-status` infers ACTIVE / DEGRADED / STALLED from file freshness +
  source-health — it never stops or restarts a collector. If STALLED, check the
  collector's PowerShell window and restart at a natural 15-minute boundary.


<!-- HIRES-MEASUREMENT-LAYER -->

## High-resolution measurement layer (READ-ONLY; no orders/paper/live)

Sub-second Coinbase/Binance public WebSocket + fast Kalshi active-book REST polling, for
repricing-lag v2 testing. Measurement only — never emits paper candidates or live orders.

```powershell
# 30-second read-only smoke (rows/source, source ages, v2 usability)
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-hires-smoke --series KXBTC15M --seconds 30

# Freshness/counts of already-recorded hires files (no collection)
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-hires-status --series KXBTC15M

# 60-second read-only record (Coinbase/Binance WS + Kalshi REST 500ms + joined snapshots)
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-hires-record --series KXBTC15M --seconds 60 `
    --kalshi-source rest --kalshi-poll-ms 500 --joined

# Plan only (no network, no files):
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-hires-record --series KXBTC15M --seconds 60 --dry-run
```

Options (kalshi-hires-record): `--kalshi-source rest|websocket|auto`, `--kalshi-poll-ms`,
`--coinbase-source websocket|rest|off`, `--binance-source ...`, `--joined`, `--raw`,
`--normalized`, `--max-markets 1`, `--output-dir`, `--verbose`, `--dry-run`, `--json`.

Outputs: `data/raw/hires/`, `data/normalized/hires/` (`hires_coinbase_ticker-*`,
`hires_binance_book_ticker-*`, `hires_binance_trade-*`, `kalshi_active_book-*`),
`data/features/hires/kalshi_hires_joined_snapshots-*`, reports under `reports/hires/`.

`kalshi-reprice-lag-study --hires` is a v2 placeholder: it blocks clearly until sub-second
data is sufficient and the v2 study is implemented (the ~4s-cadence v1 runs without `--hires`).


<!-- HIRES-HARDENING-1.5 -->

## High-res recorder hardening (Prompt 1.5; READ-ONLY)

Threaded bounded writer (LOW-priority raw/aggTrade drop first; Kalshi active-book + joined
NEVER dropped), 15-min rotation + gzip of closed segments + retention. Measurement only.

```powershell
# Bounded repeated sessions (graceful Ctrl+C); each session rotates/flushes.
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-hires-record-loop --series KXBTC15M --session-seconds 900

# Compress CLOSED segments (dry-run first); retention deletion needs BOTH --write --retention.
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-hires-compact --dry-run
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-hires-compact --write
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-hires-compact --write --retention

# Heavy Binance aggTrade is opt-in; sync writer is available for debugging.
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-hires-record --series KXBTC15M --seconds 60 --aggtrade
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-hires-record --series KXBTC15M --seconds 60 --writer-mode sync
```

`kalshi-hires-status` now reports per-stream sizes/rates, last-session queue depth/drops/writer
lag, and `reprice_lag_v2_ready`. Files segment under `data/{raw,normalized,features}/hires/YYYYMMDD/`.


<!-- KALSHI-WS-FEASIBILITY -->

## Kalshi market-data WebSocket feasibility (READ-ONLY; no orders)

Probe whether read-only sub-second Kalshi book updates are possible (needed because REST
polling is RTT-bound ~1.1s). Auth-gated; blocks cleanly (env-var NAMES only) if credentials
are absent. Never prints secrets; never places orders.

```powershell
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-ws-feasibility --series KXBTC15M
```

If it reports `BLOCKED_MISSING_CREDENTIALS`, set READ-ONLY market-data creds
(`KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`, optional `KALSHI_PRIVATE_KEY_PASSPHRASE`) and
`KALSHI_USE_WEBSOCKET=true`, then rerun. To use the WS book in the hi-res recorder (REST stays
fallback) set `KALSHI_HIRES_BOOK_SOURCE=websocket`. Every run prints
`READ-ONLY MARKET DATA ONLY - NO ORDERS.`
