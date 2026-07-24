# Regime-conditional mine + cross-coin tradability gap (2026-06-15)

> The "anything with existing data?" pass: (1) does the market mis-price in any REGIME, and
> (2) exactly how far from tradeable is the one real signal? Volume + Deribit brought in.
> READ-ONLY; gauntlet-disciplined.

## 1. Regime-conditional mine — `kalshi-ade-mine-conditional`
Tag each window by regime (vol / spread / depth / volume / Kalshi-top-size / trend / time-of-day
/ options-IV terciles), run the full screen→search→gauntlet PER cell, with **DSR deflated by the
TOTAL trials across ALL 21 cells** (so slicing many regimes cannot manufacture a false pocket).

- 923 windows (680 search), **21 regime cells, 3,988 total trials**.
- **Volume/liquidity fully mined** (the priority ask): `yes/no_ask_size` 100%, `kalshi_top_size`
  100%, `top_depth` 97%, `trade_intensity` 92–97% coverage — no volume regime/feature edge.
- **Deribit 18% covered** (a real collection window exists, not zero) — participated where present,
  surfaced nothing (consistent with the prior null ablation #17). Full use needs forward collection.
- **Every cell: DSR 0.00 → NO conditional edge.** The seductive pockets the slicing threw up —
  `tod=h00` +17.84c, `spread=hi` +15.11c — are textbook multiple-comparison mirages, and the
  global deflation rejected all of them. The market is efficient not just on average but **across
  vol, liquidity, volume, trend, and time-of-day regimes.**

## 2. Cross-coin tradability gap — `scripts/research/crosscoin_gap.py`
The one REAL signal is BTC leading the alts (#29, residual IC +0.28). This quantifies, per alt,
the after-cost EV of simply following the BTC lead, and the spread tightening that would flip it.

| alt | n | btc_p IC_resid | after-cost net | t | spread | gap to tradeable |
|---|---|---|---|---|---|---|
| **KXETH15M** | 143 | **+0.335** | **+1.23c** | +0.56 | 1.0c | **already +EV** |
| KXSOL15M | 133 | +0.298 | −1.08c | −0.45 | 1.0c | +2.2c tighter |
| KXDOGE15M | 134 | +0.287 | −2.70c | −1.05 | 1.9c | +5.4c tighter |
| KXXRP15M | 136 | +0.173 | −3.77c | −1.45 | 2.7c | +7.5c tighter |

- The gap scales cleanly with spread. **ETH wins on both axes** — strongest residual IC *and*
  tightest spread — and is **already nominally +1.23c/trade after real cost.**
- **But not an edge yet:** t=+0.56 (inside noise), and this signal already failed the pooled
  gauntlet (PBO 0.59). It is the one cell a coin-flip from being real, gated on **more ETH windows
  for significance**, not on a better signal or a liquidity change.

## Bottom line
With existing data: **no conditional edge anywhere** (efficiency confirmed across all regimes,
multiple-testing-honest), and the single most promising thread is precisely located —
**KXETH15M following the BTC lead, already ~break-even-to-+1.2c after cost but statistically
indistinguishable from zero.** The actionable next step is not more analysis but **accumulating
ETH forward windows** and re-testing that one cell through the gauntlet; if +1.23c holds with t>2,
it is the project's first real edge candidate. (Enabling Deribit forward collection is the only
way to actually use the options data — 18% historical coverage is too thin to conclude on.)

Artifacts: `src/btc5m/discovery/{regimes,conditional}.py` + volume/Deribit features in
`feature_factory.py`, CLI `kalshi-ade-mine-conditional`; `scripts/research/crosscoin_gap.py`.
