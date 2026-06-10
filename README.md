# btc5m — Kalshi BTC 15-Minute Up/Down Probability & Execution System

> ## ⚑ PRIMARY: Kalshi BTC 15-minute Up/Down (series **KXBTC15M**)
> A live-ready but **live-disabled** system that estimates the calibrated
> settlement probability **P(Kalshi YES/Up resolves to 1 at the 15-minute window
> close)** and evaluates whether YES/NO is mispriced after executable bid/ask,
> depth, **Kalshi fees**, staleness, latency, and risk gates. Markets are
> discovered dynamically via the Kalshi APIs. **Polymarket BTC 5m is PARKED /
> DORMANT** (reference only; runs only with `POLYMARKET_DORMANT=false`).
> Authoritative state: **`KALSHI_PIVOT_STATE.md`**.
>
> Quick start:
> ```powershell
> python -m btc5m.cli kalshi-discover --series KXBTC15M --status open
> # continuous (preferred; Ctrl-C safe) — records books+underlying, rich features, backfill, readiness
> python -m btc5m.cli kalshi-collect-continuous --series KXBTC15M --sources coinbase,binance --seconds-per-cycle 900
> python -m btc5m.cli kalshi-data-readiness            # gate = feature_backed_official_windows (not orphans)
> python -m btc5m.cli kalshi-label-audit --series KXBTC15M
> python -m btc5m.cli source-health --series KXBTC15M
> python -m btc5m.cli check-live-disabled
> ```
> Feature rows now carry rich Coinbase/Binance microstructure (returns, realized
> vol, spot-perp basis, microprice, queue imbalance, OFI, CVD, trade intensity)
> with explicit missingness flags + `feature_set_version`. **Deribit is a native
> OPTIONAL vol/options/regime source** (`DERIBIT_ENABLED=false` by default; NOT a
> trading venue): public REST snapshot (index, DVOL, hist-vol, near-expiry/ATM IV,
> OI + put/call split, volume, put/call ratios, skew) **joined point-in-time** into
> v3 feature rows as `deribit_*` with freshness/missingness flags. If Deribit is
> disabled/stale/missing the Kalshi pipeline continues unaffected. **Collection and
> model-feature inclusion are separate switches:** `DERIBIT_INCLUDE_IN_MODEL_FEATURES`
> (default false) decides whether `deribit_*` columns enter the model candidate
> feature group, independent of `DERIBIT_ENABLED` — leftover historical columns are
> never silently fed to the model. `source-health` / `kalshi-build-model-dataset` /
> `kalshi-train-dry-run` distinguish column presence from selection and report
> `candidate_feature_group_status` (INCLUDED / EXCLUDED_BY_CONFIG / UNAVAILABLE / STALE).
>
> **Paper-only promotion + shadow runtime:** trained artifacts are STAGED + inactive. The
> runtime never loads "newest `.pkl` by mtime" — shadow/paper mode loads ONLY an explicit,
> SHA-pinned PAPER promotion manifest (`data/models/paper_promoted/`), created by the
> `kalshi-promote-paper-artifacts --write` command after `kalshi-paper-promotion-review`.
> `KALSHI_MODEL_RUNTIME_MODE` (disabled|shadow|paper) gates use; `kalshi-shadow-run` scores
> but never fills; `kalshi-demote-paper-artifacts` rolls back. `live_approved`/
> `live_submission_allowed` are always false; promotion is NOT proof of profitability.
>
> **Controlled paper experiment:** `kalshi-paper-experiment-preflight` →
> `kalshi-paper-experiment-start --experiment-mode shadow` (log-only) →
> `…-status` / `…-report` → `--experiment-mode paper` (gated fills, settle vs OFFICIAL label,
> requires a prior shadow run). Per-run manifest + abort criteria (unexpected live, source
> stale, hash mismatch, loss/drawdown limit); `…-stop` writes a STOP flag. Never live.
>
> **Kalshi orderbook note:** Kalshi returns YES/NO **bids** only. Executable asks
> are derived (verified against Kalshi's own): `yes_ask = 1 - best_no_bid`,
> `no_ask = 1 - best_yes_bid`. No midpoint fills; depth is walked; fees subtracted.
> Settlement uses Kalshi's OFFICIAL `result` — never a BTC proxy or Chainlink logic.

> **Safety default:** record-only / paper mode. Live trading is **disabled by
> default** behind multiple flags, credential checks, and risk gates.

---

## (LEGACY / DORMANT — Polymarket BTC 5m) What this system is

This project estimates whether a Polymarket **5-minute BTC binary contract** is
mispriced, and (eventually) paper- or live-trades the executable edge.

The model target is:

> **P(BTC finishes above the contract line at expiry)** — i.e. **P(YES resolves to 1)**

It is **not** a generic "BTC up/down" bot. It estimates whether a specific
Polymarket 5-minute BTC binary contract is mispriced **after** accounting for:

- bid/ask spread
- order-book depth and executable size
- slippage / non-midpoint fills
- quote freshness / staleness
- latency
- fees
- settlement wording and exact expiry timestamp
- model uncertainty and calibration

## What this system does

- Discovers active Polymarket BTC 5-minute "Up or Down" markets + metadata
  (**implemented**, public Gamma API) and records real CLOB books to `data/`.
- Ingests BTC market data: Coinbase spot, Binance futures, Deribit vol/options
  (native optional, disabled by default).
- Builds a local normalized order book and records raw + normalized events.
- Builds microstructure + contract features (scaffold).
- Builds **settlement labels** from the exact line, expiry, and comparison
  semantics, with explicit reason codes (**implemented**).
- Estimates **calibrated** YES/NO settlement probabilities (scaffold).
- Evaluates executable expected value **after costs** (scaffold).
- Paper-trades candidates and tracks PnL.
- Sends **Pushover** notifications (with Noop fallback).
- Supports **gated** live trading later.

### How BTC 5-minute markets settle (important)

Polymarket's BTC 5-minute contracts are **"Bitcoin Up or Down"** markets
(slugs like `btc-updown-5m-<unix_ts>`, outcomes `Up`/`Down`). They resolve to
**Up** if the Chainlink BTC/USD price at the window **end** is **greater than or
equal to** the price at the window **start** — i.e. the "line" is the
window-start price (a tie resolves **Up**), not a fixed strike. Settlement is
read from the explicit market description, **never** from title similarity.

The slug's `<unix_ts>` is the window **start** in epoch seconds, aligned to 300s
(verified live against Gamma: slug `…-1780288800` ↔ `eventStartTime
2026-06-01T04:40:00Z`, end = start + 300s). Each window is listed ~24h ahead and
accepts orders the whole time, so discovery is **clock-driven**: it enumerates the
5-minute slug grid around *now* and batch-fetches by slug. The previous
sort-by-creation query only saw the far-future batch and missed every live window
— use `debug-discovery` to see the routes, classification, and any UI mismatch.

**OFFICIAL vs PROVISIONAL.** Gamma exposes the official **binary outcome** once a
market is resolved (`outcomePrices`), which is settlement-grade. It does **not**
expose the numeric Chainlink start/end prices. So the captured **line**, **final
reference price**, and **settlement_distance** are **PROVISIONAL_REFERENCE**
proxies derived from Coinbase/Binance — useful for diagnostics, but never treated
as settlement-grade. When a provisional computed label disagrees with the
official outcome (common near ties), the backfill flags the window
**MANUAL_REVIEW** and keeps both values rather than overwriting silently.

## What this system does NOT do (yet / by design)

- It does **not** submit live orders by default.
- It does **not** claim arbitrage, alpha, or profitability.
- It does **not** assume midpoint fills.
- It does **not** ignore spread, depth, slippage, fees, quote age, or latency.
- It does **not** treat title similarity as settlement equivalence.
- It does **not** ship a trained model yet — only baseline scaffolds.

---

## Data sources

| Source                | Purpose                              | Status                     |
|-----------------------|--------------------------------------|----------------------------|
| Polymarket Gamma API  | Market discovery + metadata + outcome| **Implemented** (public)   |
| Polymarket CLOB REST  | Order books (`/book`)                | **Implemented** (public)   |
| Polymarket WS         | Streaming book / quote updates       | Scaffold (REST polling now)|
| Coinbase REST         | BTC-USD spot ticker/trades/candles   | **Implemented** (public)   |
| Binance USDT-M REST   | BTCUSDT futures bookTicker/trades    | **Implemented** (public)   |
| Coinbase / Binance WS | Streaming microstructure             | Scaffold (REST polling now)|
| Deribit (public REST) | index/DVOL/hist-vol/IV/OI/skew snapshot, point-in-time joined | **Native optional** (disabled by default; `DERIBIT_ENABLED`) |

Polymarket discovery + book reads use **public** endpoints over the standard
library (no credentials, no third-party deps). Remaining adapters are scaffolds
that import cleanly and raise a clear `NotImplementedError` until wired up.

### Low-latency hot path (5-minute-grade architecture; paper-only)

An in-memory, event-driven Kalshi decision layer is built to 5-minute-grade so
the current 15m system benefits now (fresher decisions, stricter quote-age/
freshness gates, fast feature updates, latency instrumentation) and future 5m
markets need **no architectural rewrite** (horizon is config-driven). Pipeline:
`book/underlying update → in-memory state → incremental features → preloaded
scorer → executable-ask EV → quote-age/depth/source-health/fees/model gates →
WATCH / MANUAL_REVIEW / REJECTED`. The hot path uses **no pandas, no file reads,
no per-tick model load**; research/backtest code may still use files/pandas.

- WebSocket is optional and requires Kalshi auth; otherwise REST polling fallback.
- The model is uncalibrated, so the hot path can **never** emit `PAPER_CANDIDATE`,
  and **no live order can be submitted** (order planner is plan-only).

```powershell
# Safe paper-only hot-path smoke (degrades to synthetic ticks if offline)
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-hotpath-smoke --series KXBTC15M --seconds 30 --max-markets 1 --sources coinbase,binance
# Offline latency benchmark (p50/p90/p99 for feature/score/decision)
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-latency-benchmark --series KXBTC15M --samples 1000
```
All `KALSHI_LOW_LATENCY_*` settings are safe/off by default (see `.env.example`).

### Model dataset + training pipeline (gated; pure-stdlib)

A dependency-free training foundation (no numpy/sklearn/pandas required — they are
optional extras and not installed). It uses **feature-backed OFFICIAL labels only**
(orphan labels — official results with no features — can never enter), joins with
**no look-ahead** (`as_of_ms < close_ms`), excludes leakage columns explicitly
(label/result/post-close/P&L and non-stationary price levels), and gates on
**distinct 15-minute windows, not rows** (train 150 / backtest 60, ≥500 rows) with
**mandatory purge/embargo** at split time.

```powershell
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-build-model-dataset --series KXBTC15M   # -> data/models/ + reports/models/
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-split-report        --series KXBTC15M   # purged/embargoed window splits
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-train-baselines     --series KXBTC15M   # REFUSES below the gate
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-train-baselines     --series KXBTC15M --diagnostic-only  # NON-TRADABLE sanity fit
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-train-model         --series KXBTC15M --model lightgbm   # blocks (dep not installed)
```

Baselines: market-implied probability (benchmark), distance/time/vol logistic, and
microstructure logistic. A **hard Up/Down class is diagnostic only** — trade
decisions require probability + executable EV + calibration + gates. Every model is
**UNCALIBRATED**, so artifacts are stamped non-tradable / not usable by the
paper-live policy and **`PAPER_CANDIDATE` stays blocked** until trained + calibrated
+ backtested. LightGBM/XGBoost are challenger paths that block on the missing
optional dependency (never faked).

### Calibration + executable backtest (gated; research evidence)

The proof pipeline: is the probability **calibrated**, and is any signal **tradable
after executable Kalshi ask prices + fees + depth + staleness**? It uses executable
**ask** prices (never midpoint), held-out purged/embargoed window splits, and
reports evidence — never a profitability claim. Calibration is **mandatory before
any `PAPER_CANDIDATE`**.

```powershell
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-calibration-report --series KXBTC15M
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-calibrate-model    --series KXBTC15M --method isotonic   # gated; --diagnostic-only below gate
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-backtest-baselines --series KXBTC15M --diagnostic-only
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-backtest-model     --series KXBTC15M --model latest --calibrator latest --diagnostic-only
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-threshold-sweep    --series KXBTC15M --diagnostic-only
```

Baselines compared: no-trade (floor), market-implied, distance/time/vol,
microstructure (+ a saved model if present). Threshold sweeps are **research only**
and never auto-select a policy (max in-sample P&L overfits → require later paper
validation). Below the gate (60 backtest / 150 train+calib windows) real runs refuse
unless `--diagnostic-only`, and diagnostic outputs are stamped non-tradable. Reports
land in `reports/calibration/` and `reports/backtests/`.

### Paper-candidate policy engine (strict; gated; never live)

The operational layer that decides when a model output may become a
`PAPER_CANDIDATE`. It uses the **calibrated probability + executable YES/NO ask EV**
(never midpoint) and emits `WATCH / MANUAL_REVIEW / REJECTED / PAPER_CANDIDATE` with
reason codes + a human summary. `PAPER_CANDIDATE` is **only** possible when the policy
is enabled **and** a trained + calibrated + non-diagnostic + sufficiently-backtested
model passes every gate (model/calibration/backtest validity, freshness, depth,
spread, reservation price, time-to-close, risk limits). A hard Up/Down class alone
never trades; there is **no `LIVE_CANDIDATE`** and `live_submission_allowed` is always
False.

```powershell
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-policy-dry-run     --series KXBTC15M
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-policy-report      --series KXBTC15M
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-paper-policy-sim   --series KXBTC15M --limit 100
```

Disabled by default (`KALSHI_PAPER_POLICY_ENABLED=false`; see
`config/kalshi_paper_policy.example.yaml`). In the current state it REJECTS (the only
model is diagnostic-only, the calibrator is diagnostic, and the backtest is below
gate), so no `PAPER_CANDIDATE` is reachable. The paper ledger carries
`opposite_side_ask` + position metadata so the upcoming post-entry lock-profit module
can monitor open paper positions. The next step after a clean, calibrated, profitable
backtest is this paper policy — **not** live trading.

### Post-entry lock-profit module (paper-only; post-entry only; never live)

**Position management after a paper entry — not a flat-position arb scanner.** Once a
model/policy has opened a paper directional position, this module monitors the
**opposite** leg (held YES → monitor NO; held NO → monitor YES) and decides whether
buying it locks guaranteed profit after fees: `NO_POSITION / ALREADY_FULLY_LOCKED /
WATCH / RIDE / LOCK_FULL / LOCK_PARTIAL / REJECTED`. It compares the **guaranteed**
locked profit (`1 − yes_total_cost − no_total_cost` per pair) against the **naked**
continue-EV (only when a calibrated model is available), under depth/staleness/time
gates. It never opens directional positions, never scans flat markets for YES+NO<1,
and never submits a live order (`live_submission_allowed=false`; FOK by default, IOC
partials only with `--allow-partial`).

```powershell
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-lock-dry-run --series KXBTC15M
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-lock-sim     --series KXBTC15M --limit 100
# Post-entry POSITION LIFECYCLE (orchestrates same-leg sell vs opposite-leg lock vs continue EV):
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-position-monitor-dry-run --series KXBTC15M
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-position-summary  --series KXBTC15M
```

The **position lifecycle manager** (`position_lifecycle.py`) is post-entry only:
for an EXISTING paper position it compares same-leg sell value, opposite-leg lock
value, and updated continue/ride EV (using the *current* calibrated probability,
not the entry-time belief) and decides HOLD/RIDE, SELL_SAME_LEG,
LOCK_WITH_OPPOSITE_LEG, PARTIAL_LOCK, RISK_EXIT, or WATCH. It reuses the lock
module, uses executable bids/asks only, reasons every decision, and never scans
flat markets, opens positions, or submits a live order (`KALSHI_POSITION_LIFECYCLE_ENABLED=false`).

The **trade-frequency frontier** (`trade_frequency.py`) is research/reporting only:
**score constantly, trade selectively.** It measures the relationship between trade
frequency and net performance on a leakage-safe held-out set — a frequency-policy
frontier, a marginal-trade curve (where extra trades stop adding value), time-to-close
buckets, and within-window concentration (distinct windows matter more than raw trade
count; ten trades in one 15-minute window are not ten independent samples). It includes
fees + executable prices (never midpoint), is stamped NON_TRADABLE until a calibrated
model exists, and **never promotes a policy or enables live** — conservative suggestions
are written as staged JSON (`promoted=false`, manual review). Commands:
`kalshi-frequency-report` / `-sweep` / `kalshi-marginal-trade-curve` /
`kalshi-time-to-close-analysis` / `kalshi-within-window-frequency` → `reports/frequency/`.

The **confidence-aware edge policy** (`edge_policy.py` + `uncertainty.py`) decides
whether a candidate is worth paper-trading. It does **not** trade just because
`model_prob > price`: it uses a **conservative probability bound** (YES → lower
bound; NO → `1 − upper bound`), then subtracts fees, depth/slippage, stale-quote,
source-health, model + calibration (Wilson interval on reliability buckets),
regime, and overtrading buffers plus a minimum-profit buffer to get a
**final policy edge** and a **reservation price** (`ask ≤ max_acceptable`). The
required edge rises automatically when the model is uncalibrated, samples are thin,
the book is stale/thin, vol is high, or trading is concentrated. Conservative by
default (`KALSHI_EDGE_MIN_RAW_EDGE_CENTS=5`, `KALSHI_EDGE_REQUIRE_CONFIDENCE_BOUNDS=true`),
**never promotes** a config, no live. Commands: `kalshi-edge-policy-report` /
`kalshi-edge-threshold-sweep` → `reports/edge/`.

Disabled by default (`KALSHI_LOCK_MODULE_ENABLED=false`). Both commands currently
report `NO_POSITION` because the policy emits no `PAPER_CANDIDATE` yet — the lock
module only activates once a real (calibrated, backtested) model opens a paper
position. Locked profit is guaranteed **only after the opposite leg fills**; partial
fills leave residual naked exposure (tracked).

### Live-readiness scaffolding (dry-run only; the plane stays in the hangar)

The live path is **inspectable but locked**. This layer validates live-readiness,
builds **sanitized dry-run order payloads**, and proves submission is impossible — it
never submits, cancels, or issues any order HTTP. `live_submission_allowed` is
hard-False on the config, the readiness result, the payload, and the live adapter;
`submit()`/`cancel()` always refuse with structured blockers; the kill switch, manual
confirmation (absent by default), model/calibrator/backtest/paper-evidence, and risk
gates are all required and never bypassed. Market orders are disallowed (limit + FOK/IOC
only). Credentials are checked for presence/readability only — no key material is ever
read or printed. Paper evidence is **never auto-approved** (manual
`data/models/kalshi_live_approval.json`, default false).

```powershell
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-live-blockers   --series KXBTC15M
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-live-readiness  --series KXBTC15M
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-live-dry-run-order --series KXBTC15M --ticker SOME_TICKER --side YES --action buy --qty 1 --price 55 --tif fill_or_kill
.\.venv\Scripts\python.exe -m btc5m.cli check-live-disabled
```

Every dry-run attempt is recorded (sanitized, no secrets) to
`data/audit/kalshi_live_readiness_*.jsonl`. **Enabling live trading is a separate,
explicit future step that requires real paper evidence** — Prompt 7 only builds the
safe, inspectable runway.

### Ops / monitoring (read-only; run beside the collectors)

A unified, read-only operations layer for daily use while collectors run. Nothing
here collects, trades, or prints secrets.

```powershell
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-ops-status        --series KXBTC15M   # one dashboard
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-collector-status  --series KXBTC15M   # ACTIVE/DEGRADED/STALLED
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-gate-progress     --series KXBTC15M   # window gate + ETA
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-model-health      --series KXBTC15M
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-paper-summary     --series KXBTC15M
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-safety-status     --series KXBTC15M   # LIVE TRADING DISABLED
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-doctor            --series KXBTC15M   # pass/warn/fail
.\.venv\Scripts\python.exe -m btc5m.cli kalshi-eod-summary       --series KXBTC15M --write-report
```

All support `--json` / `--markdown` / `--write-report` (→ `reports/ops`, `reports/eod`).
`kalshi-collector-status` infers freshness from file ages + source-health and **never
stops or restarts a collector** — it only recommends checking the collector window.
See **`COMMANDS.md`** for the full copy-paste cheat sheet and `scripts/` for one-line
PowerShell helpers (`ops_status.ps1`, `check_sources.ps1`, `doctor.ps1`, …).

---

## Local setup

Requires **Python 3.11+** (tested on 3.13).

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

# 2. Install (editable) with dependencies
pip install -e .
# or: pip install -r requirements.txt

# 3. Copy the env template and fill in values locally
copy .env.example .env      # Windows
# cp .env.example .env       # macOS/Linux
```

## Environment variable setup

All credentials and tunables are read from environment variables (or `.env`).
**Never commit `.env`.** See `.env.example` for the full template and
`RUNBOOK.md` for what each value means. Secrets are never requested in chat.

---

## Safe smoke-test commands

These run **without** any private keys:

```bash
# Validate config + create data/report directories
python -m btc5m.cli init

# Show current resolved config and safety status
python -m btc5m.cli status

# Run a dummy candidate through the risk manager + paper adapter
python -m btc5m.cli smoke

# Confirm the live adapter refuses to trade by default
python -m btc5m.cli check-live-disabled

# Send a test notification (Noop unless Pushover is enabled + configured)
python -m btc5m.cli notify-test

# Notification queue + provider health (offline self-test; no network, no secrets)
python -m btc5m.cli notification-health

# Discover current/upcoming Polymarket BTC 5-minute markets (public, read-only)
python -m btc5m.cli discover-markets --asset BTC --duration 5m

# Explain discovery: routes, window classification, UI-mismatch check
python -m btc5m.cli debug-discovery --asset BTC --duration 5m --lookahead-hours 2

# Manual override: inspect / record one market by slug or URL (read-only / record-only)
python -m btc5m.cli inspect-market --url "<paste current Polymarket BTC 5m URL>"
python -m btc5m.cli record-market  --slug "btc-updown-5m-<unix_ts>" --seconds 300

# Record real CLOB books (+ provisional window-start line) to data/ (read-only)
python -m btc5m.cli record --asset BTC --duration 5m --seconds 60

# Continuous rolling collection (single process; preferred for long runs)
python -m btc5m.cli collect-continuous --asset BTC --duration 5m --max-markets 0

# Record Coinbase + Binance BTC underlying feeds to data/ (read-only)
python -m btc5m.cli record-underlying --seconds 60 --sources coinbase,binance

# Backfill settlement labels for completed recorded windows
python -m btc5m.cli backfill-settlements --asset BTC --duration 5m
python -m btc5m.cli label-status

# (Optional, gated) Upgrade lines to OFFICIAL via Chainlink Data Streams
python -m btc5m.cli backfill-official-chainlink --asset BTC --duration 5m

# Build point-in-time feature rows, then run the gated decision loop
python -m btc5m.cli build-features --asset BTC --duration 5m
python -m btc5m.cli decide --asset BTC --duration 5m

# Full record-only/paper pipeline: record -> label -> features -> decide ->
# paper ledger -> session summary (each step fails safe). --no-network reuses
# already-recorded data.
python -m btc5m.cli run-paper-pipeline --seconds 600 --sources coinbase,binance

# Is there enough data to train/backtest? (stays blocked until enough)
python -m btc5m.cli data-readiness --asset BTC --duration 5m
python -m btc5m.cli paper-backtest --asset BTC --duration 5m

# Run the test suite
pytest -q
```

### Paper trading (record-only/paper)

`run-paper-pipeline` is the one-shot entrypoint. It writes a **persistent paper
ledger** (`data/paper/paper_ledger-YYYYMMDD.jsonl`) — every decision with side,
model probability, the **executable** ask used (never midpoint), costs, net edge,
reason codes, line/label source status, simulated fill price/size, and the known
official outcome + realized **paper** PnL once settled — and a **session summary**
(`reports/paper/session_summary-YYYYMMDD.md`). Fills depth-walk the ask ladder and
charge fees; there are **no real orders**. `data-readiness` keeps model training
and `paper-backtest` **blocked** until enough non-leaky, OFFICIALLY-labeled rows
exist — paper numbers are never reported as real profit.

### Pipeline & model (this stage)

`discover-markets → record (+line) / record-underlying → backfill-settlements →
build-features → decide`. The **baseline** is a driftless normal approximation of
P(final ≥ line) from the BTC price, line, time-to-expiry and recent volatility —
it is **uncalibrated by design**, so the decision layer keeps every output at
**WATCH / MANUAL_REVIEW** until a calibration layer is fit on real labels. The
**decision layer** compares the model probability against the **executable** YES/NO
ask (never midpoint), nets out costs, and emits a Candidate with reason codes;
**LIVE is never reachable by default**. The **Chainlink Data Streams** OFFICIAL
numeric source is implemented but credential-gated and OFF by default, so numeric
lines/distances stay **PROVISIONAL_REFERENCE** until you configure it locally.

---

## Current limitations

- Polymarket discovery + CLOB books, Coinbase/Binance underlying recording,
  window-start line capture, and settlement backfill are implemented. WS streams
  are still scaffolds. Deribit is a native OPTIONAL source (public REST snapshot +
  point-in-time `deribit_*` feature join, disabled by default); its per-strike IV
  term-structure/smile beyond the near-expiry + ATM-proxy summary is future work.
- Numeric lines, final prices, and `settlement_distance` are
  **PROVISIONAL_REFERENCE** (Coinbase/Binance proxy) — the official Chainlink
  numeric prices are not public. Only the **binary** Up/Down outcome is
  settlement-grade. Provisional/official disagreements → MANUAL_REVIEW.
- No trained model — baseline only.
- No real backtest data — execution simulator is a scaffold.
- Calibration is not yet implemented.
- See `PROJECT_STATE.md` for the authoritative current state.

---

## Anti-fake-edge reminders

Read these before trusting any "edge":

- **Do not** claim arbitrage.
- **Do not** claim profit from stale quotes.
- **Do not** assume midpoint fills.
- **Do not** treat a detected price mismatch as tradable edge.
- **Do not** ignore spread, depth, slippage, fees, quote age, or latency.
- **Do not** ignore settlement wording or the exact expiry timestamp.
- **Do not** use title similarity as settlement equivalence.
- **Do not** allow live trading before backtest **plus** paper evidence.
- **Do not** judge models only by accuracy — calibration matters.
- **Do not** skip calibration or ablations.
- **Do not** use overlapping labels without purging/embargo.
- Keep uncertain outputs as **WATCH** or **MANUAL_REVIEW**.

> **Hard rule:** Read `PROJECT_STATE.md` before continuing any major work.
> Do not continue coding blindly if `PROJECT_STATE.md` contradicts current
> assumptions.


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
