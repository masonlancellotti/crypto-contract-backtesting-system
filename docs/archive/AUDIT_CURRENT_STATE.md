# AUDIT_CURRENT_STATE.md

**Audit type:** read-only repo + data state lock-in (PROMPT 0).
**Snapshot:** 2026-06-02 ~02:34 local (Europe/Dublin). Repo
`C:\Users\mason\Downloads\polymarket-btc-five-mins`.
**Auditor scope/guarantees:** I did **not** edit source/config/docs (this file is the
only artifact), did **not** read `.env`, did **not** print secrets, did **not**
start/stop/restart collectors, did **not** run collection or long pipelines, did
**not** submit orders, did **not** enable live trading, did **not** make Polymarket
primary, did **not** reintroduce Pusher. This file overwrites the prior
`AUDIT_CURRENT_STATE.md` snapshot with freshly re-verified numbers.

Commands run (all read-only):
`status`, `kalshi-data-readiness`, `kalshi-label-audit`, `source-health`,
`kalshi-train-dry-run`, `check-live-disabled`, `pytest -q` (252 passed in 3.23s).
Note: this tree is **not a git checkout** (`git status` → `fatal: not a git
repository`), so there is no version history to diff Codex's partial work against;
all conclusions are from current file state + live command output.

---

## 1. Executive summary

- **Kalshi `KXBTC15M` is clearly the PRIMARY venue.** `status` prints
  `PRIMARY venue : kalshi`; config runtime `primary_venue=kalshi`; CLI, Kalshi
  modules, readiness, and safety checks all center on it.
- **Polymarket BTC 5m is clearly DORMANT/reference.** `polymarket_dormant=True`;
  guarded by `venues/polymarket/require_polymarket_enabled`; legacy code present
  but not in the default path. **Caveat:** legacy Polymarket raw files were still
  being written at 02:32 (see §18) — a separate legacy collector appears to be
  running. It does not make Polymarket primary, but it is confusing.
- **Live trading is DISABLED.** `check-live-disabled` → both adapters refuse;
  `live_permitted=False`; kill switch on; manual-confirm on; no Kalshi auth.
- **Data collection is ACTIVE and fresh.** Kalshi raw/normalized orderbook +
  Coinbase + Binance underlying all updated within the last ~1–2 minutes of the
  snapshot. Kalshi feature rows / labels / paper ledger are batch-written each
  cycle (last ~02:29–02:31).
- **Repo is READY for the next development prompts** that do **not** require a
  trained model or live trading. Model fit + executable backtest remain correctly
  **data-gated**: authoritative `gate_windows=42` (< 60 backtest, < 150 train).
- Tests: **252 passed**. No Pusher anywhere. No lock-profit/hedge module anywhere.

---

## 2. Current project identity

- **Target probability:** calibrated `P(Kalshi YES/Up resolves to 1 at the 15-minute
  window close)` for series `KXBTC15M` ("BTC price up in next 15 mins?").
- **Primary market:** Kalshi `KXBTC15M`, 15-minute Up/Down binary.
- **Dormant market:** Polymarket BTC 5m (`btc-updown-5m-*`), reference only.
- **Settlement rule:** YES if the 60-second-average **CF Benchmarks BRTI** at close
  ≥ at open (GTE, tie→YES). **BRTI, not Chainlink** (Chainlink is Polymarket-legacy).
- **Core data sources:** Kalshi public REST (book/discovery/metadata; required for
  features), Coinbase spot REST (primary BTC reference), Binance USDT-M REST (perp +
  spot fallback), Deribit public REST (optional vol/options; disabled, not in
  features).
- **Paper/live distinction:** default is paper/record-only; uncalibrated models are
  capped at WATCH/MANUAL_REVIEW (can never emit PAPER_CANDIDATE); live adapters are
  refusal stubs.
- **Decision flow (as designed):**
  `model probability + executable price + fees/depth/staleness/risk gates = decision`.
  Executable asks are derived from the opposite side's bids
  (`yes_ask = 1 − best_no_bid`, `no_ask = 1 − best_yes_bid`) — **never midpoint**.

---

## 3. Repo map (with implementation status)

Status legend: **IMPL** implemented · **PARTIAL** partially implemented · **SCAF**
scaffold/stub (raises `NotImplementedError` or no real logic) · **LEGACY** dormant
Polymarket · **N/A**.

**Top-level docs/state**
- `KALSHI_PIVOT_STATE.md` — IMPL, authoritative pivot doc (accurate; counts stale
  because collectors run).
- `PROJECT_STATE.md`, `NEXT_STEPS.md` — IMPL; Kalshi banner current, lower sections
  explicitly marked LEGACY/dormant Polymarket.
- `README.md` — Kalshi-first (one stale quick-start mention of
  `feature_backed_official_windows` as the gate; code's gate is `gate_windows`).
- `RUNBOOK.md` — IMPL; Kalshi daily run current, lower Polymarket ops legacy.
- `AUDIT_CURRENT_STATE.md` — this file.

**Config**
- `.env.example` — IMPL, Kalshi-primary template; safe defaults
  (`TRADING_MODE=paper`, `LIVE_TRADING_ENABLED=false`, `KILL_SWITCH_ENABLED=true`,
  `POLYMARKET_DORMANT=true`, `DERIBIT_ENABLED=false`).
- `config/default.yaml` — **PARTIAL/STALE**: still `contract.duration_seconds: 300`
  (5-min) and `sources.polymarket.enabled: true`; runtime `config.py` overrides to
  Kalshi. Does not affect safety but is misleading.
- `config/paper.yaml` — IMPL safe overlay. `config/live.example.yaml` — stale
  Polymarket-credential comments.
- `pyproject.toml` — **STALE description** ("BTC 5-minute Polymarket …"). Deps split
  into `[data]`/`[models]` extras; core runs on stdlib + pyyaml + dotenv.
- `requirements.txt` — IMPL (core only; data/model deps commented as extras).

**CLI** — `src/btc5m/cli.py` (~2030 lines): IMPL command surface (35 subcommands;
see §4). `src/btc5m/config.py` — IMPL safe config + live blockers. `schemas.py` —
IMPL dataclasses/enums (`CandidateAction = TRADE/WATCH/MANUAL_REVIEW/REJECT`; some
docstrings still Polymarket-flavored).

**Kalshi venue — `src/btc5m/venues/kalshi/`** (all IMPL unless noted)
- `client.py` — public REST + discovery + phase classification + ticker/URL parse.
- `orderbook.py` — Decimal yes/no-bid → executable asks + depth walk + validity.
- `fees.py` — configurable taker fee `round_up_cent(rate·n·p·(1−p))`, status
  OFFICIAL/ASSUMED/UNKNOWN (default ASSUMED rate 0.07; UNKNOWN uses 0.10 upper bound).
- `settlement.py` — OFFICIAL `result`; BRTI reference; rules/Target-Price parse;
  MANUAL_REVIEW on disagreement.
- `readiness.py` — authoritative `gate_windows`, orphan accounting, gate thresholds
  (`MIN_BACKTEST_WINDOWS=60`, `MIN_TRAIN_WINDOWS=150`, `MIN_TRAIN_ROWS=500`).
- `labels_audit.py` — dedup (OFFICIAL>PROVISIONAL>MANUAL>UNKNOWN, latest-wins),
  orphan detection, safe separate-file compaction.
- `features.py` — IMPL `UnderlyingMicrostructureState` (rich point-in-time features,
  `feature_set_version=2`).
- `source_health.py` — IMPL per-source health.
- `collector.py` — IMPL continuous single-process loop.
- `paper.py` — IMPL rich feature row + fee-aware decision + Kalshi ledger + summary.
- `train_prep.py` — **IMPL** (not a stub): join usable rows ↔ OFFICIAL labels, group
  by window, purge/embargo demo, missingness/balance report, then REFUSE. Backs
  `kalshi-train-dry-run`.

**Data — `src/btc5m/data/`**
- `underlying.py`, `recorder.py`, `book_builder.py`, `line_capture.py`,
  `polymarket_client.py`, `chainlink.py` — IMPL (REST polling + recording; Polymarket
  client is LEGACY but functional; chainlink client gated/legacy).
- `deribit_client.py` — IMPL public REST client + parsers, OPTIONAL/disabled.
- `coinbase_ws.py`, `binance_futures.py`, `polymarket_ws.py` — **SCAF** (WS adapters
  raise `NotImplementedError`; REST polling is the working path).

**Features — `src/btc5m/features/`** — mixed. The **real** Kalshi features are in
`venues/kalshi/features.py`. The generic modules `microstructure.py`,
`regimes.py`, `ofi.py` (`multilevel_ofi`), `queue_imbalance.py`
(`weighted_imbalance`) are **SCAF** (`NotImplementedError`). `window.py`,
`duration.py`, `microprice.py`, `feature_builder.py`, `feature_store.py`,
`contract_features.py`, `replay.py` — IMPL/PARTIAL (used by legacy path + tests).

**Labels/readiness — `src/btc5m/labels/`** — `settlement.py`,
`settlement_backfill.py`, `time_to_cross.py`, `executable_ev.py` — IMPL (legacy +
shared). `labeling.py` — `purge_embargo_indices` IMPL (used by Kalshi dry-run);
`build_labeled_dataset` + `purge_embargo_split` are **SCAF**.

**Models — `src/btc5m/models/`**
- `baseline.py` — IMPL (uncalibrated neutral baseline by design).
- `calibration.py` — IMPL (isotonic).
- `lightgbm_model.py`, `quantile_model.py`, `linear_microstructure.py`,
  `ensemble.py` — **SCAF** (all `fit`/`predict` raise `NotImplementedError`).

**Backtest — `src/btc5m/backtest/`**
- `execution_sim.py`, `metrics.py`, `paper_backtest.py` — IMPL/PARTIAL (executable
  fill sim + metrics; gated, no real model yet).
- `event_replay.py`, `reports.py`, `validation.py` (`walk_forward_splits`) — **SCAF**.

**Execution/risk — `src/btc5m/execution/`**
- `live_kalshi.py` — IMPL refusal adapter + `kalshi_auth_smoke` ("live order
  placement not implemented — safe by design").
- `live_polymarket.py` — SCAF/LEGACY refusal adapter.
- `paper.py`, `risk.py`, `base.py` — IMPL.

**Notifications — `src/btc5m/notifications/`** — `pushover.py` (stdlib urllib),
`noop.py`, `base.py`, `eod_summary.py` — IMPL. Provider `auto`→noop when unconfigured.

**Paper — `src/btc5m/paper/`** — `ledger.py`, `session.py`, `pipeline.py`,
`simulate.py`, `readiness.py` — IMPL (legacy + shared paper plumbing).

**Scripts — `scripts/`** — `collect_kalshi_continuous.ps1` (current),
`collect*.ps1`/`collect_loop.ps1` (legacy), `build_features.py`, `build_labels.py`,
`backtest.py`, `train_models.py`, `run_paper.py`, `run_live.py`,
`record_live_data.py`, `send_eod_summary.py`.

**Tests — `tests/`** — 40 test files, **252 passing**; strong Kalshi coverage
(rich features, label audit/orphans, gate consistency, train dry-run, source health,
CLI safety, Deribit parsers). Network tests skip offline.

---

## 4. Current command inventory

All commands below are `.\.venv\Scripts\python.exe -m btc5m.cli <cmd>`.
Classification: **RO** read-only · **W** writes data · **LIVE** live-risk.

| Command | Class | Safe now? | Notes |
|---|---|---|---|
| `status` | RO | ✅ | config + feeds + blockers |
| `check-live-disabled` | RO | ✅ | confirms both adapters refuse |
| `notify-test` | RO* | ✅ | noop unless Pushover configured (then sends 1 msg) |
| `kalshi-discover --series KXBTC15M [--status][--max-markets]` | RO (net) | ✅ | public API |
| `kalshi-inspect --ticker/--url` | RO (net) | ✅ | metadata + normalized book |
| `kalshi-record --series … --seconds N` | **W (net)** | ⚠️ short only | records books |
| `record-underlying --seconds N --sources` | **W (net)** | ⚠️ short only | BTC feeds |
| `record-deribit --currency BTC --seconds N` | **W (net)** | ⚠️ short only | no-op if disabled |
| `kalshi-backfill-settlements --series` | **W** | ✅ | labels settled windows |
| `kalshi-data-readiness --series` | RO | ✅ | **authoritative `gate_windows`** |
| `kalshi-label-audit --series` | RO | ✅ | label dedup/orphan/gate |
| `kalshi-clean-orphan-labels --series [--dry-run|--write]` | RO / **W** | ✅ (dry-run) | `--write` emits SEPARATE compacted + clean files; never deletes raw |
| `source-health --series` | RO | ✅ | per-source freshness |
| `kalshi-train-dry-run --series [--embargo-windows N]` | RO | ✅ | joins+purge/embargo, REFUSES to train |
| `kalshi-auth-smoke` | RO | ✅ | no secrets printed |
| `kalshi-collect-continuous …` | **W (net), long** | ❌ do not run | perpetual collector |
| `run-kalshi-paper-pipeline --seconds N` | **W (net), long** | ❌ (this prompt) | end-to-end paper loop |
| Legacy Polymarket: `discover-markets`, `debug-discovery`, `inspect-market`, `record-market`, `record`, `backfill-settlements`, `backfill-official-chainlink`, `build-features`, `decide`, `data-readiness`, `label-status`, `paper-backtest`, `run-paper-pipeline`, `eod`, `smoke`, `init` | mixed | dormant | run only if `POLYMARKET_DORMANT=false` |

No CLI command can place a live order (no live execution implemented).

---

## 5. Current data collection status (live counts)

From `kalshi-data-readiness` (cumulative across files) unless noted.

**Markets:** seen 51 · open 1 · upcoming 2 · closed 48 · settled 0.
**Recorded rows (cumulative):** Kalshi raw orderbook 27,620 · normalized 27,616 ·
underlying (Coinbase+Binance) 37,478.
**Rows today (from `source-health`, raw/norm):** Kalshi 13,020 / 13,014 ·
Coinbase 6,612 / 6,636 · Binance 6,580 / 6,625 · Deribit 17 / 17.
**Feature rows:** total 26,626 · underlying-only 21,121 · book-backed 5,505 ·
with start reference 5,458 · without start reference 21,168.
**Rejections:** missing book 21,121 · missing underlying 0 ·
window-closed/bad-book 370 · no-official-label 312.
**Usable rows:** binary model 5,135 · line-distance model 1,940 ·
training-eligible (usable executable ∩ OFFICIAL) 4,823.

> Note: there is no longer a separate `usable_rows_for_backtest` scalar — the
> backtest gate is now **window-based** (`gate_windows`), not row-based. Mason's
> remembered `usable_rows_for_backtest≈3927` is from the old row-gated scheme.

**Latest file timestamps (local):** Kalshi raw orderbook + markets **02:34:42**;
underlying Binance 02:33:46, Coinbase 02:33:39; normalized Kalshi 02:34:42,
Coinbase 02:34:28, Binance 02:34:24; Kalshi feature rows 02:29:48; Kalshi labels
02:29:52; Kalshi paper ledger 02:29:52. **Data is actively updating** (raw within
seconds; features/labels batch each ~15m cycle).

---

## 6. Readiness and gates

- **Authoritative gate count: `gate_windows = 42`** = distinct OFFICIAL-labeled 15m
  windows with ≥1 **usable executable book-backed** feature row (predicate
  `readiness.feature_row_usable`; purge/embargo on 15m windows).
- **Backtest gate:** 42 / **60** → `allowed=False` (need **18** more windows).
- **Training gate:** 42 / **150** windows **AND** 4,823 / **500** rows →
  `allowed=False`. The **rows** threshold is already met; **distinct windows** are
  the bottleneck.
- **Bottleneck:** distinct settled windows, not rows. Overlapping rows within a
  window do not count as independent samples.
- **Purge/embargo:** EXISTS and is exercised (`purge_embargo_indices`,
  `embargo_windows=1`/900,000 ms). 15m windows don't overlap, so window-level
  purge/embargo keeps each window independent.
- **Readiness uses feature-backed official windows** narrowing to *usable* windows;
  **orphan labels are excluded** from the gate.

**Metric reconciliation (the old "38 vs 35" is resolved):**
- `official_binary_labels = 1019` — every settled OFFICIAL result (incl. orphans).
- `feature_backed_official_windows = 45` — official windows with **any** feature row
  (presence).
- `feature_backed_unusable_windows = 3` — of those 45, windows whose only rows are
  post-close / empty / invalid book.
- `gate_windows = 42` (AUTHORITATIVE) = 45 − 3.
- `orphan_labels = 974` — official results with **no** feature rows; excluded.
- **`kalshi-data-readiness` and `kalshi-label-audit` now print the SAME
  `gate_windows=42`** and both explain the 45→42 gap, so the previous
  cross-command inconsistency is fixed. No remaining count inconsistencies observed.

---

## 7. Label integrity (from `kalshi-label-audit`)

- total_label_rows 1,151 · deduped 1,019 · duplicate_label_rows 132.
- official 1,019 · provisional 0 · manual_review 0 · unknown 0.
- labels_with_feature_rows 45 · official_feature_backed 45 ·
  feature_backed_unusable 3.
- orphan_labels 974 · orphan_official_labels 974.
- labels_rejected_no_feature_rows 974 · labels_rejected_unusable_features 3.
- Dedup precedence OFFICIAL>PROVISIONAL>MANUAL>UNKNOWN, latest-wins.
- **Orphans CANNOT unlock training/backtesting** — the gate counts only windows with
  a usable executable feature row; orphans (no features) are excluded by construction.
- `kalshi-clean-orphan-labels` **EXISTS**. `--dry-run` is read-only; `--write` emits
  **separate** files (`*_compacted-*` tagged `is_orphan`/`gate_eligible`, plus a clean
  `kalshi_training_labels-*` of gate-eligible OFFICIAL labels only) and **never
  deletes/edits raw label files**.

---

## 8. Source health (live, from `source-health`)

| Source | enabled | impl | required | in features | rows today (raw/norm) | latest age | stale? | latest px |
|---|---|---|---|---|---|---|---|---|
| Kalshi | ✅ | impl | **required** | ✅ | 13,020/13,014 | 4,137 ms | No (thr 60 s) | n/a (book) |
| Coinbase | ✅ | impl | optional | ✅ | 6,612/6,636 | 17,632 ms | **No** | 70,211.2 |
| Binance | ✅ | impl | optional | ✅ | 6,580/6,625 | 22,048 ms | No | 70,296.9 |
| Deribit | ❌ | stubbed | optional | ❌ | 17/17 | 3,816,846 ms | Yes (disabled) | n/a |
| Notifications | provider=noop, pushover_enabled=False, configured=False | | | | | | | |

- **Roles:** Kalshi = executable YES/NO book (REQUIRED; no book → no executable
  example). Coinbase = PRIMARY spot reference (returns/realized-vol/basis/
  distance-to-line). Binance = perp (basis/microprice/OFI/queue-imbalance) **+ spot
  fallback** (`can_serve_as_spot_fallback=True`). Deribit = optional vol/options
  regime, not required for MVP.
- **Coinbase staleness investigation:** **At this snapshot Coinbase is FRESH**
  (age 17.6 s < 60 s source threshold; latest price present). The "Coinbase stale"
  Mason saw is a **transient REST hiccup**, not a chronic collector failure
  (Coinbase row count ≈ Binance row count). **Binance fallback exists**
  (`can_serve_as_spot_fallback`). Feature rows flag `coinbase_stale` at a tighter
  **5 s per-tick** threshold, so stale spot ticks are visible, not silently used.
  `underlying_ok=True` requires ≥1 fresh underlying feed.
  - **Open caveat:** the *live ref-selection* auto spot→perp failover is a future
    add (KALSHI_PIVOT_STATE "Known blockers"); a stale-Coinbase tick currently
    surfaces as a flagged/missing feature (it contributes to the high
    `spot_*`/`distance_to_line` missingness in the dry-run), it does not silently
    poison rows. Stale Coinbase reduces usable spot features for that tick but does
    not, by itself, block the gate (Binance can cover).

---

## 9. Current feature schema

Per-row `feature_set_version=2`; **86 feature columns** in the training-eligible set
(~92 keys per row). Representative groups (verified present via `kalshi-train-dry-run`
+ `features.py`):

- **Kalshi contract/orderbook:** `yes_bid/no_bid`, `yes_ask/no_ask` (from opposite
  bids), spread, `depth_imbalance`, quote age, validity flags, `seconds_to_close`,
  `has_orderbook`, `close_ms`, `as_of_ms`.
- **Coinbase spot:** `spot_return_30s/60s/since_window_start`, `realized_vol_60s`,
  `spot_sigma_per_sqrt_s`, distance-to-start.
- **Binance perp:** `spot_perp_basis`, `binance_microprice`,
  `binance_queue_imbalance`, `binance_ofi_best`, `perp_cvd_60s`.
- **Time/duration:** `seconds_to_close`, since-window-start returns.
- **Volatility:** `realized_vol_60s`, `spot_sigma_per_sqrt_s`,
  `distance_to_line_vol_normalized`.
- **Microstructure:** microprice, queue imbalance, OFI (best level), CVD,
  depth imbalance.
- **Source-health/staleness:** per-feed freshness/staleness flags + reason codes.
- **Label/settlement:** `market_ticker`, `label_yes_resolved`,
  `label_source_status`.
- **Decision/risk:** computed downstream in `paper.py` (not stored as raw features).

**Presence check:** OFI ✅ (best level; **multilevel OFI = SCAF**), CVD ✅,
microprice ✅, queue imbalance ✅, spot/perp basis ✅, trade intensity ✅
(signed-trade imbalance/intensity), distance-to-line ✅, distance-to-line
vol-normalized ✅ (but **91.75% missing**), quote age ✅, source freshness ✅,
**Deribit IV/DVOL/options ❌ not joined into Kalshi rows**.

**Old vs new rows COEXIST:** the 2026-06-02 Kalshi feature file is **all v2**
(12,348 rows tagged `feature_set_version=2`); the 2026-06-01 Kalshi feature file has
**no version tag and lacks the rich columns** (e.g. `binance_microprice` count = 0).
This is why the dry-run shows ~48% missingness on `spot_return_*`/basis/microprice
and 91.75% on `distance_to_line_vol_normalized` over the training-eligible set —
roughly half the eligible rows predate v2. Training should filter to
`feature_set_version==2` (or accept the missingness explicitly).

---

## 10. Current model/training state

- **Model files:** `baseline.py` (IMPL, uncalibrated neutral by design),
  `calibration.py` (IMPL isotonic). `lightgbm_model.py`, `quantile_model.py`,
  `linear_microstructure.py`, `ensemble.py` — **all SCAF** (`NotImplementedError`).
- **Any model actually trained?** **No.** No model artifact on disk; no model card.
- **Calibration exists?** Code yes (isotonic), **not fitted** (no calibrated artifact).
- **Training dry-run exists?** **Yes** (`train_prep.py` / `kalshi-train-dry-run`),
  functional and currently REFUSES (gate 42 < 150).
- **LightGBM/XGBoost:** LightGBM scaffolded only; XGBoost not present.
- **Logistic/ridge baseline:** the neutral baseline exists; a fitted logistic/ridge
  microstructure model is SCAF (`linear_microstructure.py`).
- **Market-implied baseline:** implied prob from executable ask/bid is computed in
  features/paper (used as comparison), but a packaged "market-implied baseline model"
  is not a separate fitted artifact.
- **Distance/time/vol baseline:** features exist; no fitted baseline model.
- **Quantile/distance-to-line model:** SCAF.
- **Model artifacts saved / model cards:** none.
- **Paper candidates emittable yet?** **No** — uncalibrated ⇒ capped at
  MANUAL_REVIEW (PAPER_CANDIDATE unreachable). Correct by design.

**Summary:** *Implemented:* baseline + isotonic code + functional dry-run path.
*Blocked by data:* fitting + calibration (need `gate_windows≥150`, rows already
met). *Not implemented:* LightGBM/quantile/linear/ensemble fits, artifact
persistence, model cards.

---

## 11. Backtest/evaluation state

- **Executable backtest:** PARTIAL — `backtest/execution_sim.py` +
  `paper_backtest.py` model executable fills; gated off until a real model + enough
  windows exist.
- **No-midpoint fills:** ENFORCED (`assume_midpoint_fills=false`; asks from opposite
  bids; `slippage_model=depth_walk`).
- **Fees modeled:** YES (`KalshiFeeModel`, always subtracted; UNKNOWN→upper bound).
- **Depth walking:** YES (orderbook depth walk + sim size / `no_depth`).
- **Threshold sweep:** not present as a packaged report (future).
- **Calibration report:** SCAF (`backtest/reports.py` raises NotImplemented;
  `reports/calibration/` empty).
- **Reliability/Brier/log-loss/ECE:** not yet produced (no fitted model to score;
  `metrics.py` is a scaffold pending real fills).
- **P&L by bucket:** scaffold (no real fills yet).
- **Market-implied baseline comparison:** implied prob is captured per row, but a
  formal model-vs-market evaluation report is future work.
- **Purged walk-forward validation:** the **window-level purge/embargo IS
  implemented** (`purge_embargo_indices`, used by the dry-run). The generic
  `backtest/validation.walk_forward_splits` and `labels.purge_embargo_split` are
  still SCAF, but the Kalshi path does not depend on them.

---

## 12. Paper decision and execution state

- **Paper ledger:** IMPL (`data/paper/kalshi_paper_ledger-YYYYMMDD.jsonl`, last
  written 02:29).
- **Session summaries:** IMPL (`reports/paper/kalshi_session_summary-YYYYMMDD.md`).
- **Decision states (Kalshi `paper.py`):** `NO_ACTION`, `WATCH`, `MANUAL_REVIEW`,
  `PAPER_CANDIDATE`, `REJECTED`. Generic enum `CandidateAction` =
  `TRADE/WATCH/MANUAL_REVIEW/REJECT`.
  - **`PAPER_FILLED` / `PAPER_REJECTED` / `LIVE_CANDIDATE` do NOT exist as states.**
    Fills are tracked via a separate `fill_status` field:
    `not_traded` / `simulated_filled` / `no_depth`. There is intentionally **no
    LIVE_CANDIDATE path** in the paper module.
- **Risk checks:** `execution/risk.py` IMPL (limits None by default → live blocked).
- **Fee handling:** every decision subtracts the configured fee; `min_net_edge_cents`
  gate before PAPER_CANDIDATE.
- **Quote-age handling:** quote age captured + gated (`max_quote_age_ms`).
- **Depth handling:** depth walk; `no_depth` when size unfillable.
- **Untrained models blocked from PAPER_CANDIDATE:** YES (capped at MANUAL_REVIEW).
- **Any live-risk path:** NONE reachable from paper.

---

## 13. Live safety state (from `check-live-disabled` + `status`)

- **Kalshi live adapter refuses:** ✅ True. Blockers: mode is `paper`;
  `LIVE_TRADING_ENABLED=false`; kill switch on; Kalshi auth not configured; manual
  confirmation required but no handler set.
- **Polymarket live adapter:** refuses (venue dormant).
- **Live requires:** explicit flags (`TRADING_MODE=live`, `LIVE_TRADING_ENABLED=true`,
  kill switch off) **AND** Kalshi auth (KEY_ID + RSA key) **AND** all risk limits set
  **AND** a manual-confirmation handler. None are present.
- **Kill switch:** active.
- **Could anything accidentally submit orders?** **No** — live order placement is not
  implemented (refusal stubs); no CLI path reaches it.

---

## 14. Notifications state

- **Provider:** `auto` → **Noop** (Pushover disabled/unconfigured). `notify-test`
  works as a no-op.
- **Required env (optional):** `PUSHOVER_ENABLED`, `PUSHOVER_APP_TOKEN`,
  `PUSHOVER_USER_KEY` (+ optional device/priority/sound). Missing creds **never
  break** anything (Noop fallback).
- **Pusher references:** **NONE** (grep for `pusher` across `src/` → 0 matches).
- **Events that can notify:** paper decisions/heartbeat + EOD summary (via provider).
- **EOD summary:** IMPL (`notifications/eod_summary.py`, `send_eod_summary.py`,
  `cmd_eod`). `NOTIFY_EVENT_PREFIX=btc15m_kalshi`.

---

## 15. Deribit status

- **Implemented vs stubbed:** client + pure parsers (DVOL, index, historical vol,
  options OI/volume/near-expiry IV/skew) are **implemented** in
  `data/deribit_client.py`; as a *feature source* it is **stubbed/not wired**.
- **Enabled by default:** **No** (`DERIBIT_ENABLED=false`).
- **CLI:** `record-deribit --currency BTC --seconds N` (no-op blocker when disabled).
- **Raw data recorded:** DVOL/index/historical-vol/option-summary JSONL
  (`data/normalized/deribit_btc-*.jsonl`; 17 rows today, last 01:30, now stale —
  expected since disabled).
- **Normalized features created:** none joined into Kalshi rows.
- **Joins into Kalshi feature rows:** **No** (`not-in-features`).
- **Source-health reports it:** **Yes** (as disabled/stubbed/stale).
- **Model/training uses it:** **No.**
- **To make Deribit native:** enable + run recorder on a cadence; add point-in-time
  IV/DVOL/skew/term-structure join into `venues/kalshi/features.py` with missingness
  flags; surface in readiness/source-health as in-features; keep it a vol/uncertainty
  widener, **never a directional signal**.
- **Clarification:** Deribit is an **optional auxiliary** vol/options/regime source,
  **not a trading venue and not an MVP blocker**.

---

## 16. Low-latency architecture state

| Capability | State |
|---|---|
| Kalshi WebSocket local book | **Missing** (WS scaffold only; needs RSA-signed auth) |
| REST polling | **Present** (the working ingestion path) |
| Async ingestion | **Missing** (synchronous REST poll loop) |
| Event-driven scoring | **Missing** (cycle/batch scoring) |
| In-memory hot path | **Missing** (reads JSONL from disk) |
| Preloaded model/calibrator | **Missing** (no model yet) |
| No pandas/file reads in hot path | **Not satisfied** (file-read based) |
| Quote-age gates | **Present** (`max_quote_age_ms`, per-tick freshness flags) |
| Latency metrics | **Minimal** (`quote_age_ms`/clock-skew diagnostics; no e2e latency) |
| Profiling/benchmark command | **Missing** |
| Limit/IOC/FOK planning | **Missing** (no order-type modeling yet) |

Net: the current system is a **correct, file-based, REST-polling research/paper
pipeline**, not a low-latency trading loop. Low-latency is a clean greenfield prompt.

---

## 17. Post-entry lock-profit module state

**Does not exist.** Grep for `lock.?profit`, `lock_pair`, `opposite.?leg`, `hedge`
across `src/` → **0 matches**. This is **entirely future work**. (And the audit
confirms there is **no** flat-position same-market arb scanner — good, that's what we
*don't* want.) Future module (paper-only first) would: after a YES buy, monitor NO
(and vice-versa) for a lock; compute max opposite-leg price after fees for a minimum
locked profit; decide lock-vs-ride; simulate limit/FOK/IOC; track locked pairs vs
remaining naked exposure.

---

## 18. Known issues / risks / confusing areas (blunt)

1. **A legacy Polymarket collector appears to be running.** `data/raw/polymarket_*`
   and legacy `feature_rows.jsonl`/`settlement_labels-*.jsonl` were written ~02:28–
   02:32, alongside the Kalshi collector. Polymarket is *supposed* to be dormant.
   This doesn't make it primary, but it wastes I/O and is confusing. Recommend
   identifying/stopping that window (a future prompt; not touched here).
2. **Stale config/docs:** `config/default.yaml` (`duration_seconds: 300`,
   `polymarket.enabled: true`), `pyproject.toml` description, `config/live.example.yaml`
   Polymarket comments, and a README quick-start line citing
   `feature_backed_official_windows` as the gate (code uses `gate_windows`).
3. **Old v1 feature rows coexist with v2** (the 06-01 Kalshi file lacks rich
   columns). High microstructure missingness in the dry-run is an artifact of this;
   training must filter to v2 or handle missingness explicitly.
4. **Fee schedule is ASSUMED** (rate 0.07), not OFFICIAL — edge claims must stay
   conservative until verified.
5. **Distance-to-line vol-normalized 91.75% missing** even among eligible rows —
   needs investigation before it's used as a model feature.
6. **WS / low-latency entirely absent** (REST polling only); not executable-latency
   realistic for live yet.
7. **Orphan-label clutter:** 974 orphans correctly excluded, but they inflate raw
   files; `kalshi-clean-orphan-labels --write` is the intended hygiene step (not run).
8. **Tests pass but do not prove live functionality** — they prove offline logic,
   refusal behavior, and data plumbing; there is no live execution to test.
9. **Live ref auto spot→perp failover not implemented** — stale Coinbase shows as
   missing features rather than auto-substituting Binance in the reference path.
10. **Not a git repo** — no history; partial Codex work can only be judged from
    current file state (notably `train_prep.py`, which is complete and working).

---

## 19. What is ready for next prompts

| Next prompt | Prerequisites | Start now? | Likely files |
|---|---|---|---|
| Deribit native source | recorder/parsers exist; needs cadence + feature join | **Yes** (independent of gate) | `data/deribit_client.py`, `venues/kalshi/features.py`, `source_health.py`, `cli.py` |
| Low-latency Kalshi arch | greenfield; needs WS auth (RSA) design | **Yes** (design/scaffold; no live) | new `venues/kalshi/ws.py`, hot-path scorer, `client.py` |
| Model dataset/training pipeline | code paths exist; **data-gated** for *fitting* (windows 42<150) | **Partial** — can build dataset assembler + v2 filtering now; fitting waits | `train_prep.py`, `models/*`, `labels/labeling.py` |
| Calibration/executable backtest | execution sim exists; **gated** (windows 42<60) | **Partial** — wire reports/metrics now; run when gate clears | `backtest/*`, `models/calibration.py` |
| Paper-candidate policy engine | decision path exists; needs calibrated model | **Partial** — policy/threshold scaffolding now; arm after calibration | `venues/kalshi/paper.py`, `decision/decision_layer.py` |
| Post-entry lock-profit (paper) | nothing exists; depends on paper fills | **Yes** (design + paper sim) | new `venues/kalshi/lock_profit.py`, `paper.py` |
| Live-readiness scaffolding | refusal adapters exist; keep disabled | **Yes** (scaffold only) | `execution/live_kalshi.py`, `risk.py` |
| Monitoring/ops polish | health/readiness exist | **Yes** | `source_health.py`, `cli.py`, scripts |

---

## 20. Final recommendation

**Working:** Kalshi public data pipeline (discovery → book/underlying recording →
v2 rich features → OFFICIAL labeling → readiness/label-audit/source-health →
gated paper decision/ledger/summary); executable (no-midpoint) pricing + fee model
+ depth walk; window-level purge/embargo; functional training **dry-run**; full
safety posture (live disabled, kill switch, refusal adapters); 252 tests; no Pusher;
no lock-profit/arb scanner.

**Blocked only by more data:** model fitting + calibration + executable backtest +
PAPER_CANDIDATE emission — all waiting on `gate_windows` (42 → 60 backtest, → 150
train; rows already sufficient at 4,823/500).

**Blocked by code (not data):** LightGBM/quantile/linear/ensemble fits + artifact
persistence + model cards; calibration/backtest report generation
(Brier/log-loss/ECE/reliability); Deribit feature join; WS/low-latency hot path;
lock-profit module; live ref auto-failover.

**Do not touch yet:** running collectors (Kalshi *and* the stray legacy Polymarket
window); `.env`/credentials; live settings; raw data/label files.

**Authoritative gate count:** `gate_windows = 42`.
**Distance to backtest threshold:** 18 more distinct usable windows (≈4–5 h at the
theoretical max of 4 settled 15m windows/hour, **likely longer** — historical yield
is well under 1 usable gate-window per wall-clock window; measure the real per-hour
growth rate before estimating).
**Distance to training threshold:** 108 more windows (≈27 h at theoretical max,
again likely longer).
**Collectors healthy?** **Yes** — Kalshi/Coinbase/Binance all fresh and writing
within seconds of the snapshot; ≥1 underlying feed fresh (`underlying_ok=True`).

**Exact next 3 actions:**
1. Keep the single Kalshi continuous collector running and **measure the real
   per-hour growth of `gate_windows`** via periodic `kalshi-data-readiness` /
   `kalshi-train-dry-run` (do not start a second collector; resolve the stray
   legacy Polymarket writer separately).
2. Start the **data-independent** prompts now (Deribit native source and/or
   low-latency WS scaffolding and/or dataset assembler with `feature_set_version==2`
   filtering) — none require the gate to clear.
3. When `gate_windows ≥ 60`, run `kalshi-clean-orphan-labels --write`, then fit +
   calibrate on purged/embargoed v2 windows and produce the calibration/backtest
   report **before** trusting any PAPER_CANDIDATE; keep live disabled.
