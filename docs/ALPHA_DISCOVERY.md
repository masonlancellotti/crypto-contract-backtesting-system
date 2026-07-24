# Alpha Discovery Engine

An automated, leakage-safe, multiple-testing-aware search for a tradeable edge in
the Kalshi 15-minute crypto binary markets. It is read-only and never touches
`live_submission_allowed`. Source: `src/btc5m/discovery/`.

## Why the rigor comes first
These markets have survived a dozen hypothesis-driven attacks with no edge after
cost (see `RESEARCH_LEDGER.md`). Pointing an *automated* search at a near-efficient
market manufactures false positives: search 10,000 strategies and roughly 50 clear
p < 0.005 by chance alone. The engine's defining feature is therefore not breadth of
search but an **overfitting / multiple-testing gauntlet** that decides whether any
discovery is real. The most likely honest output is "still no edge — here is the
deflated-significance proof." The value is searching a much larger space than manual
hypotheses (especially the least-mined data: the KXBTCD strike ladder, cross-asset
leads, sub-second combinations) without self-deception.

The search target is the tradeable **15-minute binary outcome after cost**; the
feature factory spans all data sources, so cross-horizon and cross-asset data enter
as features.

## Pipeline
```
Stage 0  Holdout vault     hash-pinned, sealed; no search ever sees it until final validation
Stage 1  Feature factory   versioned, point-in-time-correct feature library
Stage 2  Screening         combinatorial purged CV (purge + embargo on windows); IC / Brier-skill
Stage 3  Strategy search   entry rules over screened signals, scored after-cost executable
Stage 4  Gauntlet          Deflated Sharpe Ratio + PBO (CSCV) + parameter-plateau + replication
Stage 5  Vault validation  the few survivors tested once on the sealed holdout
Stage 6  Registry          cumulative trial budget across runs -> honest DSR deflation
```

## The rigor spine (`src/btc5m/discovery/`)
- **`metrics.py`** — per-**window** (never per-row, which leaks) scoring: Sharpe /
  t-stat, skew and kurtosis (Deflated-Sharpe inputs), Brier-skill vs the market,
  Spearman IC; a local normal cdf/ppf (no scipy import at load).
- **`gauntlet.py`** — the core false-discovery control:
  - *Probabilistic Sharpe Ratio* — skew/kurtosis-adjusted significance of a Sharpe
    against a benchmark.
  - *Expected maximum Sharpe* under N trials — the bar a "best of N" must clear by
    luck alone.
  - *Deflated Sharpe Ratio (DSR)* — the PSR against that benchmark; DSR > 0.95
    survives multiple testing.
  - *PBO* via Combinatorially Symmetric CV — does the in-sample best stay above the
    out-of-sample median? PBO → 0 is good, → 0.5 is overfit.
  - *parameter plateau* (robust plateau vs fragile spike) and a combined PASS/FAIL
    verdict requiring DSR, PBO, plateau, and cross-asset replication (≥3 of 5)
    together.
- **`cpcv.py`** — combinatorial purged CV and purged walk-forward over distinct,
  non-overlapping 15-minute windows (index-adjacency equals time-adjacency, so
  purge + embargo is exact).
- **`holdout.py`** — `HoldoutVault`: a forward block (most-recent windows) plus a few
  contiguous random mid-blocks, embargo-separated from the search set; a SHA-256
  fingerprint pins the data so `verify()` refuses to validate on shifted data. The
  search uses only the sealed `search_keys`.
- **`registry.py`** — an append-only `TrialRegistry`; `cumulative_trials` sums the
  trial budget across all runs so repeated re-mining cannot silently inflate
  significance.
- **`selfcheck.py`** — proves the gauntlet **rejects** the in-sample best of
  pure-noise strategies (DSR ≤ 0.95, PBO ≈ 0.5) and **accepts** a genuine edge
  (DSR > 0.95, PBO ≈ 0). Verified: a noise best raw Sharpe 0.122 → DSR 0.512
  (E[maxSR] 0.120), PBO 0.58 → rejected; a planted Sharpe 0.410 → DSR 1.000,
  PBO 0.00 → accepted.

## Feature factory + search
`feature_factory.py` (versioned point-in-time signals plus principled derived
interactions), `panel.py` (one observation per window at a decision snapshot; market
probability from asks; fills priced at an executable quote `exec_lag_seconds` after
the signal to model execution realism), `screen.py` (ranks features by
**market-residual** IC `y − p_market` plus out-of-sample sign stability — a feature
that predicts the outcome but not the residual is already in the price), `search.py`
(after-cost executable entry-rule trials → a windows × trials matrix), and
`engine.py` (the orchestrator: vault → screen → search → gauntlet → sealed holdout).

CLI: `kalshi-ade-selfcheck`, `kalshi-ade-vault`, `kalshi-ade-mine` and the
domain-specific mines (`-pooled`, `-maker`, `-crosscoin`, `-conditional`, `-combo`).

## What the engine found
The engine works as designed: it repeatedly surfaces the dataset's most seductive
patterns and the gauntlet rejects them with a deflated-significance proof.

- **First mine (BTC):** the distance/return-since-start → buy-favorite rule looked
  strong (+1.37c/trade, t = 5.55) and the gauntlet rejected it (DSR 0.127 ≪ 0.95;
  parameter spike). An execution-lag sweep {0, 3, 10, 30 s} refuted the initial
  guess that it was a stale-quote artifact — it survives a 30 s lag — and the
  gauntlet still rejects it at every lag. The engine, not a human, classified the
  artifact correctly.
- **Maker domain:** the single candidate ever to clear DSR 0.998 + PBO 0.00 (rest
  YES bid on 96c+ favorites, persisting on the sealed holdout) is characterized in
  ledger leg 15 as short-vol favorite-capture — roughly 2–4c collected against a
  −96c single-loss tail. The Deflated Sharpe Ratio is blind to an unrealized left
  tail, so the plateau/payoff gate rejects it. It is real and out-of-sample
  persistent, but not bankable.
- **Cross-asset, conditional-regime, and multi-feature-combination** mines all
  reject: the combination mine reproduces the market price almost exactly, direct
  evidence that the price sits at the information frontier of the whole feature
  library.

## Invariants
- Window-level scoring only (never per-row); purge + embargo on every split.
- After-cost, executable prices for any P&L (`KalshiFeeModel`).
- Every trial is counted; DSR is deflated by the **cumulative** registry budget.
- The vault is sealed; survivors touch it exactly once.
- Nothing here enables paper or live trading.
