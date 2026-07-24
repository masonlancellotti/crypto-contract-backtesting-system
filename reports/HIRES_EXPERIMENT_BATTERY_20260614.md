# Sub-second (hi-res / WS) experiment battery — 2026-06-14

> Exploiting Strategy ⑤ (sub-second WS data usable end-to-end). Everything here is
> READ-ONLY backtest/measurement; **live trading disabled throughout**. Discipline:
> market-implied probability is the bar every strategy must beat after cost; we judge
> on out-of-sample, walk-forward (purge+embargo), with multiple-comparison and
> regime-luck skepticism, and we distinguish genuine sub-second edge from re-skinned
> favorite/YES bias.

Reusable harness: `scripts/research/hires_microstructure_lab.py` (modes: `model`,
`ic`, `favorite`, `favorite-pool`). Reprice-lag: `kalshi-reprice-lag-report --hires`.

Data: BTC 382 windows / ~1.0M joined snapshots (6 days, 06-08→06-14); ETH/SOL/DOGE/XRP
~160 labelled windows each / ~0.28–0.47M snapshots (4 days, 06-10→06-14). Decision
snapshot = the joined row nearest 120 s-to-close, one per window (independent samples).
**Honest n: 146–349 windows per series.** Most joined data predates today's WS-book
recorders, so the Kalshi book leg is still largely REST-cadence (~1.1 s); truly
sub-second Kalshi book is only ~1 day thin — a caveat for the reprice-lag family.

---

## EXP1 — Hires-cadence model vs market (15m binary outcome, after-cost OOS)

Walk-forward logistic (expanding window, 5 folds, 1-window embargo, L2 C=0.5) on three
feature sets, vs the market-implied baseline, evaluated on Brier/ECE/logloss and an
after-real-fee divergence-taker (trade when |model_p − mkt_p| ≥ 0.03).

| Series | n_win | Market Brier / ECE | best model ΔBrier (model−mkt) | best after-cost net c/trade (t) | verdict |
|---|---|---|---|---|---|
| KXBTC15M | 349 | 0.0676 / 0.0242 | +0.0056 (worse) | −0.26 (t −0.12) | no edge |
| KXETH15M | 161 | 0.0585 / 0.0401 | +0.0094 | +0.26 (t +0.09 = noise) | no edge |
| KXSOL15M | 161 | 0.0474 / 0.0541 | +0.0120 | −2.49 (t −0.98); fair_z −6.30 (t −2.75) | no edge |
| KXDOGE15M | 161 | 0.0823 / 0.0338 | +0.0132 | −1.06 (t −0.36) | no edge |
| KXXRP15M | 146 | 0.0587 / 0.0570 | +0.0100 | −0.92 (t −0.27) | no edge |

- The market-implied probability is the **best-calibrated forecaster on every asset**
  (ECE 0.024–0.057). Every learned model — including the market+microstructure-residual
  set — is **worse out-of-sample** (ΔBrier strictly positive). Adding sub-second
  microstructure to the market's own forecast changes calibration by ≤0.006 Brier and
  the divergence trades still lose.
- The Φ(z) physics fair value (Φ of standardized distance-to-line using sub-second
  realized vol) **ties the market on Brier** for BTC (0.0664 vs 0.0676) and ETH
  (0.0558 vs 0.0585) but with worse ECE and **no tradeable divergence** — it re-derives
  what the market already prices.
- After-cost taker is **negative on all 5 assets**; SOL's is significantly negative
  (t −2.75), i.e. trading model-vs-market divergence actively destroys money.

**Verdict EXP1: NO EDGE.** Sub-second microstructure does not sharpen the 15-minute
binary forecast beyond the market price. **Confidence this is not regime luck: HIGH** —
five independent assets, consistent sign, walk-forward OOS.

---

## EXP2 — Sub-second information coefficients (does sub-second predict the next move?)

Spearman IC of each signal vs the **forward underlying log-return** at +1 s / +5 s
(diagnostic target B). n ≈ 0.28–1.0M snapshots (heavily autocorrelated → effective n
far smaller, but effects are large and p≈0).

| Signal (BTC, +1 s) | IC | | Signal (DOGE, +1 s) | IC |
|---|---|---|---|---|
| mom_1s | +0.195 | | basis_chg_5s | +0.169 |
| mom_250ms | +0.189 | | mom_5s | +0.146 |
| size_imb (Kalshi book) | −0.126 | | mom_1s | +0.146 |
| mom_5s | +0.124 | | mom_250ms | +0.115 |
| basis_chg_5s | +0.099 | | basis_chg_1s | +0.115 |
| perp_lead | +0.062 | | perp_lead | +0.095 |

- Sub-second **momentum continuation**, **CEX basis-change lead-lag**, and **Kalshi
  book-size imbalance** all carry strong, robust, highly-significant predictive
  structure for the next 1–5 s **underlying** move. This is real and replicates across
  assets.
- BUT this is predictivity of the **liquid CEX spot/perp move**, which you cannot trade
  through a Kalshi 15-minute binary; and `z_fair` (the only feature that maps to the
  binary outcome) has IC ≈ 0 on the forward move. The structure decays in seconds and
  EXP1 shows it does **not** bridge to a 15m binary edge after cost.

**Verdict EXP2: STRUCTURE REAL, NOT TRADEABLE HERE.** The sub-second world is
predictable on the underlying; the only bridge to Kalshi P&L is reprice-lag/sniping
(EXP3), which is net-negative after cost. **Confidence: HIGH** (huge n, cross-asset).

---

## EXP3 — Reprice-lag (sub-second) + order-flow side-selection re-test

Reprice-lag v2 already consumes the joined snapshots; re-run on fresh data now that the
WS book source is live.

**KXDOGE15M** (`kalshi-reprice-lag-report --hires`, 281k rows / 174 windows):
- Coverage of short horizons **massively improved**: +250 ms / +500 ms now **86% / 97%**
  observable (memory recorded ~0% under pure REST polling) — the WS book *did* unblock
  the sub-second horizons.
- Stale-quote opportunities: 2542 raw shocks → 344 candidates → 120 dedup opps across
  54 windows / 4 days. **win_rate 19%, avg net −0.065 c/contract, profit_factor 0.55**,
  negative at every threshold (3/5/8/12 bps). Time-to-first Kalshi ≥1 c move median
  2106 ms (still book-cadence bound). Verdict **no_edge**.
- Order-flow side-selection (③): the sub-second order-flow signals (size_imb, momentum)
  are exactly the EXP1 `micro` features — the after-cost divergence taker that uses them
  loses on all 5 assets, so signed-flow side-selection on the **taker** side does not
  rescue it. (Maker side untestable here without resting-quote print matching.)

**KXBTC15M** (`kalshi-reprice-lag-report --hires`, 1.03M rows / 387 windows, 6 days):
- Coverage +250 ms / +500 ms = **87% / 87%** observable. 146 dedup opps across 76
  windows / 6 days. **win_rate 24%, avg net −0.0016 c/contract, profit_factor 0.99** —
  essentially **break-even, slightly negative**. Time-to-first ≥1 c Kalshi move median
  4927 ms.
- Threshold sensitivity: 3 bps **+0.0064**, 5 bps −0.0016, 8 bps −0.119, 12 bps −0.151.
  The lone marginally-positive cell (3 bps, +0.6 hundredths-of-a-cent/contract) is tiny,
  not robust across thresholds, and inside noise. Verdict **no_edge**.
- BTC is the **closest to break-even** of any reprice-lag run (tightest 1 c spread,
  best WS coverage) — but still does not clear cost.

**Verdict EXP3: NO EDGE (BTC at break-even, alts worse).** The WS book genuinely
unblocked the sub-second horizons (coverage 0%→~87%), but the stale-quote opportunities
remain net-negative-to-break-even after fees+depth+buffer. **Caveat worth tracking:** the
joined corpus is still mostly REST-cadence Kalshi book; only ~1 day is truly sub-second
WS book. BTC sitting exactly at profit_factor 0.99 is the single result most worth a
re-test once a week+ of pure WS-book data accumulates. **Confidence it's not luck: HIGH
for the negative; the break-even proximity on BTC is the one "watch" item.**

---

## EXP4 — Deep-favorite cell (④ re-test) under sub-second

Pooled 1002 decision windows across 5 series; favorite = the side with implied ≥ 0.50;
taker buys the favorite at its ask, real Kalshi fee, by implied band and |z_fair| split.

| band | z | n | fav_imp | realwin | calib_gap_c | net_c (t) | yes% |
|---|---|---|---|---|---|---|---|
| 0.80–0.90 | all | 101 | 0.856 | 0.881 | +2.5 | +0.10 (0.0) | 48% |
| 0.90–0.95 | all | 97 | 0.928 | 0.907 | −2.1 | −3.98 (−1.3) | 51% |
| 0.95–0.98 | all | 124 | 0.968 | 0.976 | +0.7 | −0.90 (−0.6) | 48% |
| 0.98–1.01 | all | 450 | 0.992 | 0.991 | −0.1 | −1.31 (−3.0) | 47% |
| 0.80–0.90 | hi&#124;z&#124; | 41 | 0.861 | 0.902 | +4.2 | +1.73 (+0.4) | 27% |
| 0.90–0.95 | hi&#124;z&#124; | 79 | 0.930 | 0.899 | −3.2 | −5.04 (−1.5) | 49% |
| 0.95–0.98 | hi&#124;z&#124; | 121 | 0.968 | 0.975 | +0.7 | −0.95 (−0.7) | 46% |
| 0.98–1.01 | hi&#124;z&#124; | 449 | 0.992 | 0.991 | −0.1 | −1.31 (−3.0) | 47% |

- The bulk band 0.98–1.01 (n=450) is **well-calibrated** (realwin 0.991 vs implied
  0.992) and the **taker loses the fee** significantly (t −3.0) — you cannot taker-buy a
  99 c favorite and profit.
- The 0.90–0.95 band shows favorites **mildly OVERpriced** (realwin 0.907 < implied
  0.928), the opposite of a favorite-longshot edge — taker net −3.98 c.
- The only positive cell is 0.80–0.90 **hi|z|** (+1.73 c) but **t = 0.4, n = 41** — inside
  noise — and it is **73% NO-favorites** (yes% 27%), so it is *not* a "deep-favorite YES
  bias" at all. Favorite yes% sits ~47–51% across bands → **no directional YES tilt** at
  the 120 s decision point.
- This reconciles with ④: the earlier deep-favorite positive was a **maker** effect
  (capturing the spread on passive fills), not a **calibration** mispricing. Sub-second
  data confirms there is **no taker edge** in the favorite bands, and the |z| split does
  not sharpen one into significance.

**Verdict EXP4: NO TAKER EDGE; ④ was spread-capture, not mispricing.** Sub-second neither
sharpens nor confirms a tradeable deep-favorite taker cell. The maker lens (resting-quote
print matching) is the only place ④ could still live, and that is outside what the joined
snapshots alone can test. **Confidence it's not luck: HIGH** (n=450 in the key band).

---

## Conclusions & ranked shortlist

**Headline:** Strategy ⑤ delivered the capability and let us ask the sub-second questions
properly. The answer is the project's recurring one, now confirmed at sub-second
resolution across 5 assets: **the market-implied probability is the edge; nothing we
engineered from sub-second data beats it after cost.** The sub-second world is *richly
predictable on the underlying* (EXP2 ICs up to 0.20) but that predictability does not
survive translation into a 15-minute Kalshi binary after the spread + fee.

**Ranked shortlist (what, if anything, is worth pursuing — and the forward data it needs):**

1. **BTC reprice-lag on pure WS-book data** — the only result at break-even
   (profit_factor 0.99; 3 bps cell marginally +). *Not actionable now* (inside noise, and
   the corpus is mostly REST-cadence book). **Needs:** ≥1–2 weeks of joined data collected
   entirely under today's live WS book recorders, then re-run `kalshi-reprice-lag-report
   --hires`. If profit_factor crosses ~1.1 with t>2 and holds across thresholds, escalate
   to shadow. **Confidence of real edge: LOW but non-zero.**
2. **Maker (passive) capture in the 0.80–0.95 favorite band** — EXP4 shows positive
   calibration gaps in some favorite cells that a *maker* (not taker) could harvest; ledger
   #13/④ already saw maker +2 c there. **Needs:** resting-quote ↔ trade-print fill matching
   on the fresh prints, not joinable from snapshots alone. **Confidence: LOW** (drift-
   confounded, multiple-comparison risk).
3. **Everything else — CLOSED.** Hires-cadence outcome model (EXP1), microstructure
   side-selection / order-flow taker (EXP2/③), deep-favorite taker (EXP4): **no edge,
   high confidence, do not re-roll on more of the same data.**

**Regime-luck audit:** EXP1/EXP2/EXP4 verdicts replicate across 5 independent assets
and/or n≥350 with consistent sign — these are robust, not regime artifacts. The only
result with genuine regime/luck ambiguity is the BTC reprice-lag break-even (single asset,
one marginal threshold cell, thin true-WS data) — explicitly flagged as "watch, not act."

**Reusable artifacts:**
- `scripts/research/hires_microstructure_lab.py` — modes `model` / `ic` / `favorite` /
  `favorite-pool` (per-series via `--data-dir`, BTC via `--start-date/--end-date`).
- `kalshi-reprice-lag-report --hires` (existing) — sub-second stale-quote study.
- Reports under `reports/.../reprice_lag/hires/` (per-series sensitivity CSV + study MD).

