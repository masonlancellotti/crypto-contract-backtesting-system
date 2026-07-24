# Efficiency After Costs in Kalshi 15-Minute Cryptocurrency Binary Markets

**A negative-result study with multiple-testing control**

Mason Lancellotti
2026-07-24

---

## Abstract

KXBTC15M, the Kalshi 15-minute Bitcoin up/down binary (together with the parallel ETH, SOL, DOGE, and XRP series), is efficient after transaction costs at retail latency. Across 38 tested strategy hypotheses spanning direct outcome models, market-residual models, stale-quote event studies, passive maker entries, round-trip market making, cross-asset relative value, and regime-conditional search, no strategy clears the roughly 2.5-cent round-trip cost (approximately 1c spread plus approximately 1.5c fee) out of sample. The market-implied probability is the best-calibrated forecaster measured: distinct-window expected calibration error (ECE) is approximately 0.020, against 0.031 or worse for every model trained. A single cell surfaced by an automated alpha-discovery engine survives the multiple-testing gauntlet (a passive YES bid on deep favorites, Deflated Sharpe Ratio 0.998, Probability of Backtest Overfitting 0.00, persisting on a sealed holdout), but it is short-volatility favorite capture: roughly 2 to 4 cents collected against an unrealized single-loss tail near negative 96 cents. The Deflated Sharpe Ratio is structurally blind to that unrealized left tail, so the survivor is not bankable, and the payoff-asymmetry gate rejects it. The honest negative result, obtained under leakage controls and false-discovery control strong enough to reject its own planted noise, is the contribution.

---

## 1. Introduction

Short-horizon binary prediction markets on cryptocurrency price direction have become liquid enough to ask a sharp empirical question: is the market-implied probability of a 15-minute up/down contract beatable, after realistic execution costs, by a systematic strategy built from public order-book and underlying-microstructure data? The prior from market-microstructure theory is unfavorable to the researcher. A tight, actively quoted binary on a heavily traded underlying should price direction close to a martingale over a 15-minute horizon, and any residual predictability should be no larger than the cost of capturing it.

This paper reports the result of testing that prior exhaustively. The programme comprises 38 pre-registered research legs, each recorded with its reproduction command and verdict in an append-only ledger, and a purpose-built alpha-discovery engine that searches a large strategy space under formal multiple-testing control. Every quantitative claim below traces to a committed artifact in the repository, cited inline beneath the relevant table.

The central finding is negative and robust: these markets are efficient after costs at the data resolution and latency available to a retail participant. The one statistically surviving pattern is a favorite-capture trade whose reported edge is an artifact of a small win-only sample rather than a repeatable source of return. We treat the negative result, and the discipline required to be confident it is a true negative rather than an under-powered one, as the object of interest.

---

## 2. Market and data

### 2.1 Contract mechanics

The primary instrument is Kalshi `KXBTC15M`: a binary contract that resolves YES if Bitcoin is up over a fixed 15-minute window and NO otherwise. Settlement references the 60-second-average CF Benchmarks BRTI (Bitcoin Real-Time Index) at the window close compared against the window open, using a greater-than-or-equal (GTE) comparison, with ties resolving to YES. The target modeled throughout is the calibrated probability that YES resolves to 1. The pipeline is series-parameterized: `KXETH15M`, `KXSOL15M`, `KXDOGE15M`, and `KXXRP15M` parse identically, each with its own spot and perpetual-futures underlying feeds.

Executable prices are always taken as asks, defined as the complement of the opposite side's best bid (`yes_ask = 1 - best_no_bid`), which is verified equal to the venue's own posted asks. No fill is ever simulated at the midpoint. The cost structure at typical quotes is a spread of approximately 1 cent plus a fee of approximately 1.5 cents per contract, for a round-trip cost of approximately 2.5 cents. The fee rate parameter is 0.07 and is stamped ASSUMED until verified against the official schedule (Section 8).

### 2.2 Underlying and microstructure feeds

Two underlying feeds are recorded point-in-time: Coinbase BTC-USD spot (the primary reference) and the Binance USDT-margined perpetual (used for basis, microprice, and order-flow imbalance, and as a spot fallback). Deribit volatility and options context is an optional, disabled-by-default source joined with freshness flags; it is never required and never used as a directional signal.

### 2.3 Data sizes

The full corpus provides 770 usable gate windows (distinct OFFICIAL-labeled 15-minute windows with at least one executable, book-backed feature row), approximately 240,000 order-book snapshots, approximately 700,000 underlying rows, and 3.2 million backfilled trade prints (roughly 17 percent of the entire Kalshi tape over the collection period, at approximately 600,000 to 700,000 KXBTC15M prints per day). The alpha-discovery holdout vault seals 961 labeled windows into 707 search and 240 holdout windows, hash-pinned so that search can never touch the holdout. Approximately 62 GB of raw and normalized data is retained locally and is not distributed.

*Source: RESEARCH_LEDGER.md legs 2, 19, 27; ARCHITECTURE.md.*

### 2.4 The committed zero-key sample

So that an outside reader can reproduce the pipeline offline, a curated sample of one BTC day, 95 OFFICIAL-labeled 15-minute windows (380 point-in-time feature rows), ships in the repository. It sits below the 150-window training gate by design and is stamped `NON_TRADABLE_DIAGNOSTIC_ONLY`; the backtest gate of 60 windows is met. All sample tables in Section 5 are computed on this 95-window subset and are labeled as such to keep them distinct from full-corpus figures.

*Source: sample_data/expected/kalshi_dataset_report.md.*

---

## 3. Methodology

### 3.1 Feature construction

Features are point-in-time by construction: every feature row carries `as_of_ms < close_ms`, so no information dated at or after the window close can enter a decision. Features fall into explicit, versioned groups: contract and time (seconds-to-close, fraction of window elapsed); Kalshi book microstructure (bids, asks, executable buy prices, spreads, top-of-book depth, depth imbalance); underlying spot and perpetual microstructure (Coinbase and Binance order-flow imbalance, cumulative volume delta, microprice, queue imbalance, signed-trade imbalance, trade intensity, spot-perp basis and its change); distance-to-start and volatility-normalized distance-to-line; realized volatility over multiple horizons; time-decay terms; and optional Deribit volatility and options fields.

### 3.2 Leakage controls

Training uses OFFICIAL settlement labels only. Orphan labels (an official result with no feature rows) are excluded and can never inflate the gate; underlying-only rows without a Kalshi book are never treated as executable examples. Non-stationary price levels (reference prices, raw bid and ask levels, microprice) and all settlement or post-close fields are held out of the training matrix and enforced by an explicit no-leakage assertion. The authoritative unit of account is the distinct 15-minute window, not the row.

### 3.3 Cross-validation

All splits are window-level, never row-level. Chronological train/validation and three-way train/calibration/test splits, and walk-forward folds, each impose a mandatory purge and embargo of at least one full 15-minute window between segments, with a leak check verifying that training horizons end before validation begins. Because 15-minute windows are non-overlapping, index adjacency equals time adjacency and the purge is exact.

### 3.4 Calibration

Probabilities are calibrated with pure-Python isotonic regression (pool-adjacent-violators) or Platt scaling, fit on held-out calibration windows and never on model-fit rows. Reported metrics are Brier score, log-loss, ECE, reliability buckets, and calibration slope and intercept, before and after. A model is stamped tradable only at or above the gate and only once a calibrator is attached; below-gate models remain diagnostic.

### 3.5 Executable-fee backtests

Each held-out decision is simulated at the executable ask (never the midpoint), with fees, depth, staleness, and spread gates applied, then settled against the OFFICIAL label. A hard up/down class is reported as a diagnostic and never trades. The market-implied baseline trades zero by construction, because it never disagrees with its own price by more than the minimum edge threshold; it therefore serves as the calibration benchmark rather than a strategy.

*Source: MODEL_PIPELINE.md; ARCHITECTURE.md.*

---

## 4. Alpha-discovery protocol

Pointing an automated search at a near-efficient market manufactures false positives: search ten thousand strategies and roughly fifty clear a p-value of 0.005 by chance alone. The alpha-discovery engine is therefore built around a false-discovery gauntlet rather than around breadth of search. It is read-only and cannot enable paper or live trading.

The gauntlet combines four independent controls, all computed on window-level (never per-row) statistics:

1. **Deflated Sharpe Ratio (DSR).** The Probabilistic Sharpe Ratio, adjusted for skew and kurtosis, evaluated against the expected maximum Sharpe under the trial budget. A candidate survives only if DSR exceeds 0.95, meaning its window-Sharpe exceeds what the best of N correlated trials would produce by luck alone.

2. **Probability of Backtest Overfitting (PBO)** via combinatorially symmetric cross-validation. PBO estimates how often the in-sample best strategy falls below the out-of-sample median across symmetric splits. PBO near 0 is healthy; PBO near 0.5 indicates overfitting.

3. **Parameter plateau.** A surviving rule must sit on a robust plateau in parameter space rather than a fragile spike; a spike indicates the threshold was tuned to noise.

4. **Cross-asset replication.** Genuine structure should replicate across the five independent series.

The holdout vault is a SHA-256-fingerprinted forward block plus a few embargo-separated random mid-blocks; `verify()` refuses to validate on shifted data, and survivors are tested against it exactly once. An append-only trial registry sums the cumulative trial budget across all runs, so repeated re-mining cannot silently inflate significance.

### 4.1 Engine self-validation

The engine is validated against its own null and its own planted signal. On a pure-noise strategy set it correctly rejects the in-sample best: raw Sharpe 0.122, expected maximum Sharpe 0.120, DSR 0.512, PBO 0.58. On a planted genuine edge it accepts: planted Sharpe 0.410, DSR 1.000, PBO 0.00. The gauntlet distinguishes luck from edge on data where the ground truth is known.

*Source: ALPHA_DISCOVERY.md; RESEARCH_LEDGER.md leg 27.*

### 4.2 First mine, as an illustration of the control working

The first mine on BTC surfaced the dataset's most seductive pattern: a distance-since-window-start rule that buys the favorite, reporting per-trade +1.37 cents at t = +5.55. The gauntlet rejected it (DSR 0.127, far below 0.95; parameter plateau a spike). An execution-lag sweep over {0, 3, 10, 30} seconds refuted the initial human guess that it was a stale-quote artifact, because the candidate survives a 30-second execution lag while Kalshi reprices in roughly 1 to 4 seconds; the gauntlet rejected it at every lag (DSR 0.00 to 0.25). The engine, not the analyst, classified the artifact correctly.

*Source: reports/ADE_FIRST_MINE_20260614.md; RESEARCH_LEDGER.md leg 27.*

---

## 5. Results

### 5.1 Calibration: the market price is the best forecaster

On the full corpus, the market-implied probability is the best-calibrated forecaster measured. No trained model improves on it out of sample.

| Forecaster | Distinct-window ECE |
|---|---|
| Market-implied probability | 0.020 |
| Best trained model | 0.031 or worse |

*Source: RESEARCH_LEDGER.md leg 3; README.md headline findings.*

The result holds across all five series at sub-second cadence. The market-implied probability is best-calibrated on every asset (ECE 0.024 to 0.057), and every learned model is worse out of sample (change in Brier of +0.006 to +0.047 relative to the market).

*Source: RESEARCH_LEDGER.md leg 21; reports/HIRES_EXPERIMENT_BATTERY_20260614.md (EXP1).*

On the committed 95-window sample, isotonic calibration improves the reliability of a diagnostic model but does not make it profitable. Note that Brier and log-loss are essentially flat while ECE falls and slope moves toward 1, the signature of a calibration fix rather than a discrimination gain.

| Metric | Before (raw) | After (isotonic) |
|---|---|---|
| n | 84 | 84 |
| Brier | 0.1741 | 0.1774 |
| Log-loss | 0.5012 | 0.5015 |
| ECE | 0.1474 | 0.1169 |
| Calibration slope | 0.8161 | 1.0193 |
| Calibration intercept | 0.1306 | 0.1091 |

*Source: sample_data/expected/kalshi_calibration_report.md (TEST windows; split train=48, calib=24, test=21, embargo=1).*

### 5.2 Executable backtest on the sample: every taker baseline loses after fees

On the same 95-window sample, the executable-fee backtest returns the no-edge result in miniature: the two fitted taker baselines are net-negative, and the market-implied baseline trades zero by construction.

| Baseline | Trades | Net P&L (c) | Per-contract (c) | Hit rate | Profit factor | Max drawdown (c) |
|---|---|---|---|---|---|---|
| no_trade (floor) | 0 | 0.0 | n/a | n/a | n/a | n/a |
| market_implied | 0 | 0 | n/a | n/a | n/a | 0.0 |
| distance_time_vol | 27 | -2.058 | -0.0762 | 0.4815 | 0.6313 | -2.866 |
| microstructure | 26 | -3.613 | -0.1390 | 0.4615 | 0.4766 | -5.093 |

*Source: sample_data/expected/kalshi_baseline_backtest.md (executable ask prices; fees, depth, staleness modeled; split train_rows=264, val_rows=112).*

### 5.3 The 38-leg outcome summary

The research programme is recorded as 38 legs. The dominant verdict is no edge after cost; a small set remain open pending forward data; a substantial fraction are infrastructure or measurement capability rather than edge claims.

| Status | Legs | Meaning |
|---|---|---|
| Concluded-negative (no edge after cost) | 17 | Tested honestly; no edge at the available data resolution. |
| Open / watch (blocking input named) | 5 | Promising or unresolved, gated on new forward data. |
| Infrastructure (measurement/safety) | 11 | Capability, not an edge claim. |
| Resolved / characterized (hygiene, not edge) | 5 | Corrected or precisely characterized; not tradeable. |
| **Total** | **38** | |

*Source: RESEARCH_LEDGER.md (full per-leg record).*

### 5.4 Reprice-lag / stale-quote event study

The stale-quote hypothesis, that Kalshi quotes lag the underlying enough to snipe, is the closest any taker result comes to break-even, and it does not cross the cost line. Sub-second WebSocket book data lifted short-horizon observability from essentially zero under REST polling to roughly 87 to 89 percent, so the hypothesis is now genuinely observable rather than merely untested.

| Series (data) | Windows | Win rate | Avg net (c/contract) | Profit factor | +250 / +500 ms coverage |
|---|---|---|---|---|---|
| KXBTC15M (1.03M rows) | 387 | 24% | -0.0016 | 0.99 | 87% / 87% |
| KXBTC15M (1.37M rows) | 475 | 23% | -0.027 | 0.82 | 89% / 89% |
| KXDOGE15M (281k rows) | 174 | 19% | -0.065 | 0.55 | 86% / 97% |

BTC threshold sensitivity is unstable in sign and tiny in magnitude (3 bps +0.0064, 5 bps -0.0016, 8 bps -0.119, 12 bps -0.151 cents per contract). The mechanism explains why speed cannot rescue this: when BTC moves, the Kalshi quote follows in the expected direction only 58 percent of the time, with a median lag of 0.13 cents, roughly one-eighth of the round-trip cost. The quote is barely stale; the edge is absent rather than latency-gated.

*Source: RESEARCH_LEDGER.md legs 23, 37; reports/HIRES_EXPERIMENT_BATTERY_20260614.md (EXP3); reports/ADE_FINAL_STONES_20260615.md.*

### 5.5 The one surviving cell: deep-favorite maker capture

The maker-mining domain produced the only candidate ever to clear both DSR and PBO. The rule rests a passive YES bid on deep favorites (a top-quartile volatility-normalized distance signal, mean bid near 0.96 to 0.98), and it persists on the sealed holdout.

| Set | Fill model | Fills | Per-fill (c) | t | Win (y=1) | Mean bid |
|---|---|---|---|---|---|---|
| Search | prints-through | 67 | +4.20 | +7.75 | 100% | 0.958 |
| Holdout | prints-through | 24 | +2.65 | +6.21 | 100% | 0.974 |
| Search | front-of-queue | 149 | +2.72 | +9.52 | 100% | 0.973 |
| Holdout | front-of-queue | 59 | +1.77 | +8.03 | 100% | 0.982 |

The candidate clears DSR 0.998 and PBO 0.00 and is rejected only by the parameter-plateau gate (spike 0.33). The reason it is not bankable is economic, not statistical. It is short-volatility favorite capture: the bid collects roughly 2 to 4 cents when a 96-cent favorite wins, against a single-loss tail near negative 96 cents (equivalent to roughly 25 to 35 wins). A 100 percent win rate on 67 search and 24 holdout fills means no tail event landed in a small sample, not that the tail is absent. The Deflated Sharpe Ratio is computed from realized skew and kurtosis and is structurally blind to an unrealized left tail, which is precisely why a payoff-asymmetry gate, not the DSR, must reject it. The fills are also optimistic (prints-through and front-of-queue are upper bounds on real queue position), and the effect is thin at the very top of book.

*Source: RESEARCH_LEDGER.md leg 15; reports/ADE_OTHER_PATHS_20260615.md.*

### 5.6 The combination mine reproduces the market price

The most informative single result is the multi-feature combination. A walk-forward logistic model over the top-5 market-residual-IC features, trading on divergence of at least 0.08, produces a per-trade result statistically indistinguishable from zero.

| Combination result | Value |
|---|---|
| Per-trade net | +0.60 c |
| t-statistic | +0.19 |
| Window-Sharpe | 0.007 |
| DSR | 0.182 |
| PBO | 0.53 |
| Parameter plateau | spike |

Unlike single-feature rules that manufacture a fake +1.5 to +4 cent artifact, the full combination reproduces the market price almost exactly (the model probability sits inside the divergence threshold of the market probability on most windows). This is direct evidence that the price already sits at the information frontier of the entire feature library; there is nothing left for a combination to extract.

*Source: RESEARCH_LEDGER.md leg 34.*

### 5.7 Market-making simulation: speed makes an alpha-less maker worse

A round-trip market-making simulation with a queue cap and inventory skew (an Avellaneda-Stoikov-lite quoting rule) is not viable, and faster quoting makes it worse. The static baseline reproduces the earlier static-quoting result at negative 1.76 cents.

| Cancel latency | Mean P&L per window (c) | Per-fill (c) | Fills per window | Naked-end % |
|---|---|---|---|---|
| 250 ms | -717 | -0.64 | 1113 | 99% |
| 1 s | -460 | -0.76 | 604 | 98% |
| 4 s | -201 | -0.92 | 219 | 95% |
| static | -1.76 | -0.93 | 1.9 | 8% |

Every maker fill is roughly 0.6 to 0.9 cents adversely selected: the spread captured does not cover the toxicity of the fill. Market making profits only with a fair-value edge to skew and cancel on. This programme has shown there is no fair-value edge (the price is the best forecaster, and the combination mine re-derives it), so every counterparty is at least as informed, every fill is adverse, and faster requoting simply multiplies toxic fills. The absence of predictive edge kills market making as surely as it kills the taker.

*Source: RESEARCH_LEDGER.md leg 38; reports/ADE_MARKET_MAKING_20260615.md.*

---

## 6. Robustness

### 6.1 Multiple-testing control across regimes

Slicing the market into regimes is the classic way to manufacture a false pocket, so the conditional mine deflates the DSR by the total trial count across all cells. Over 21 regime cells (volatility, spread, depth, volume, Kalshi top-size, trend, time-of-day, and options-implied-volatility terciles) and 3,988 total trials, every cell deflates to DSR 0.00. The most seductive pockets the slicing threw up (time-of-day hour-00 at +17.84 cents, high-spread at +15.11 cents) are textbook multiple-comparison mirages, and the global deflation rejected all of them. The market is efficient not only on average but across volatility, liquidity, volume, trend, and time-of-day regimes.

*Source: RESEARCH_LEDGER.md leg 32; reports/ADE_CONDITIONAL_AND_CROSSCOIN_GAP_20260615.md.*

### 6.2 Cross-asset agreement

The negative outcome-model result is not regime luck. Across all five independent series, the market-implied probability is the best-calibrated forecaster (ECE 0.024 to 0.057), every learned model is worse out of sample (change in Brier +0.006 to +0.047), and the after-cost divergence taker is negative on all five (SOL significantly so, at t = -2.75). Five independent assets agreeing in sign is strong evidence of a true negative.

*Source: RESEARCH_LEDGER.md leg 21; reports/HIRES_EXPERIMENT_BATTERY_20260614.md (EXP1).*

### 6.3 The cross-coin near-miss

The single most promising signal in the programme is a real cross-coin lead-lag: BTC's concurrent implied probability predicts an alt's market residual (residual IC up to +0.335). The tradability gap scales cleanly with spread. ETH, which combines the strongest residual IC with the tightest spread, is the only cell that is already nominally positive after cost, and it is still not an edge.

| Alt | Residual IC (btc_p) | After-cost net (c) | t | Spread | Gap to tradeable |
|---|---|---|---|---|---|
| KXETH15M | +0.335 | +1.23 | +0.56 | 1.0 c | already +EV nominally |
| KXSOL15M | +0.298 | -1.08 | -0.45 | 1.0 c | 2.2 c tighter |
| KXDOGE15M | +0.287 | -2.70 | -1.05 | 1.9 c | 5.4 c tighter |
| KXXRP15M | +0.173 | -3.77 | -1.45 | 2.7 c | 7.5 c tighter |

The ETH cell has t = +0.56, statistically indistinguishable from zero, and the pooled version of this signal failed the gauntlet (PBO 0.59). It is a coin-flip from being real, gated on accumulating more ETH forward windows for significance rather than on a better signal or a liquidity change.

*Source: RESEARCH_LEDGER.md legs 29, 33; reports/ADE_CONDITIONAL_AND_CROSSCOIN_GAP_20260615.md.*

---

## 7. Conclusion

Kalshi's 15-minute cryptocurrency binary markets are efficient after costs at retail latency. The market-implied probability is the best-calibrated forecaster measured, and a walk-forward combination of the entire feature library re-derives that price rather than beating it. Every taker strategy, every passive-maker configuration, and every round-trip market-making latency all fail to clear the roughly 2.5-cent round-trip cost out of sample, and the failures replicate across five independent assets and across every tested regime under formal multiple-testing control. The single cell that survives the statistical gauntlet is a favorite-capture trade whose reported edge is an artifact of a win-only small sample against an unrealized left tail, not a repeatable return.

Where remaining edge could theoretically live is now precisely located, and in every case it requires a new input rather than more of the same data. Three directions are not closed by the existing corpus: a genuinely sub-second WebSocket order book accumulated over weeks rather than days (the BTC reprice-lag result sits at profit factor 0.99 and is the one taker result worth re-testing on pure WS-book data); forward verification of the deep-favorite maker cell with a real queue model and an explicit tail budget; and a structural change, such as a cross-venue price comparison against Polymarket or a less liquid series whose wider spreads have not yet been arbitraged. None of these is a claim of edge. They are the only questions the existing data cannot answer.

---

## 8. Limitations

1. **Fees are an assumption.** The fee rate parameter (0.07) is stamped ASSUMED throughout and has not been verified against the official Kalshi schedule. All after-cost results inherit this assumption; a materially different fee would shift the cost line, though the taker results lose by margins larger than plausible fee revisions.

2. **The Deflated Sharpe Ratio is blind to an unrealized left tail.** The one surviving cell (Section 5.5) passes DSR and PBO precisely because its 100 percent win rate contains no realized tail event. DSR is computed from realized skew and kurtosis and cannot see the negative-96-cent loss that has not yet occurred. A payoff-asymmetry and maximum-single-loss gate is required and is what rejects the candidate; the DSR alone would have blessed it.

3. **Maker fills are optimistic.** Prints-through and front-of-queue fill models are upper bounds. Real queue position at the crowded top of book erodes the reported maker capture, and a true queue model makes market making worse rather than better.

4. **Maker-speed and forward deep-favorite verification need live infrastructure.** The one place execution speed could plausibly matter is a maker with fast cancel and requote plus queue priority. That cannot be validated offline; it requires live quoting, which this build does not implement.

5. **The distributed sample is 95 windows.** Full-corpus figures (770 gate windows, 961 vault windows, 3.2M prints) are computed on data retained locally and not distributed; a clean clone reproduces the pipeline and the sample-scale results but not the full-corpus tables. Sample-scale and full-corpus figures are labeled distinctly throughout.

---

*Research only. No live trading. Every figure in this paper traces to a committed artifact in this repository, cited inline beneath each results table.*
