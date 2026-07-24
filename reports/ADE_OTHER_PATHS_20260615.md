# Alpha Discovery Engine — the other mining paths (2026-06-15)

> Chasing the search domains not chosen at scoping: **cross-asset** and **execution/maker
> edges** (cross-horizon is data-blocked — no KXBTCD ladder history recorded yet). All
> READ-ONLY; live disabled. Each run through the same gauntlet (Deflated Sharpe + PBO +
> plateau + holdout). CLI: `kalshi-ade-mine-pooled`, `kalshi-ade-mine-maker`.

## Path A — cross-asset (pooled, 5 series)
`kalshi-ade-mine-pooled` — pool all 5 series (1524 windows: BTC 902 + alts ~145–164 each)
with **per-asset rank-normalized features** (so a "top-quartile" rule means the same thing per
asset), 1131 search / 379 holdout, 184 trials.

- Best rule: `realized_vol_window_to_date` hi → buy YES, +3.70c/trade but **t=+1.71**, window-Sharpe **0.051**.
- Per-asset breakdown: **positive mean on all 5 assets** (+2.5 to +8.2c) — but every per-asset
  t is < 1.2. "5/5 positive" is the near-miss that fools people.
- **GAUNTLET: NO EDGE** — DSR 0.001 (raw 0.051 ≪ E[maxSR|184] 0.139), plateau SPIKE. The
  cross-asset sign-agreement is real but the magnitudes are inside noise.

## Path B — execution / maker edges (BTC, prints-through)
`kalshi-ade-mine-maker` — observation = resting JOIN bid at the decision snapshot; fill = REAL
trade tape (prints-through); net = after-cost maker P&L. 993 windows w/ tape, 731 search / 248
holdout, 188 trials.

- Best rule: `distance_to_line_vol_normalized` top-quartile → **rest a YES bid**: fills=67,
  **+4.20c/fill, t=+7.75, win 100%**, window-Sharpe 0.214.
- **First candidate to clear DSR (0.998) AND PBO (0.00).** Rejected by the plateau gate only
  (spike 0.33) → verdict NO EDGE.

### Autopsy (`scripts/research/autopsy_maker_candidate.py`) — the decisive sealed-holdout test
| fill model | set | fills | per_fill | t | win(y=1) | mean_bid |
|---|---|---|---|---|---|---|
| prints-through | SEARCH | 67 | +4.20c | +7.75 | 100% | 0.958 |
| prints-through | **HOLDOUT** | 24 | **+2.65c** | +6.21 | 100% | 0.974 |
| front-of-queue | SEARCH | 149 | +2.72c | +9.52 | 100% | 0.973 |
| front-of-queue | **HOLDOUT** | 59 | **+1.77c** | +8.03 | 100% | 0.982 |

**It persists on the sealed holdout.** And `mean_bid ≈ 0.96–0.98` says exactly what it is: a
passive YES bid on **96c+ deep favorites** — the documented deep-favorite maker spread-capture
(ledger #13/#15), now confirmed to hold OOS. This is the single most real recurring effect in
the dataset.

### Why it is NOT a tradeable edge (rigorously, not dismissively)
1. **Short-vol / penny in front of a steamroller.** Collect ~2–4c when a 96c favorite wins;
   a *single* loss is **−96c** (≈ 25–35 wins). "Win 100%" on 67/24 fills = no tail event landed
   in a small sample, not a tail that doesn't exist. DSR passed *because* the unrealized left
   tail isn't in the empirical skew/kurtosis — a known DSR blind spot on favorite capture.
2. **Optimistic fills.** prints-through (+2.65c) and front-of-queue (+1.77c) are upper bounds;
   real queue position at the crowded top of book erodes below +1.77c (#13/#14).
3. **Plateau-fragile + thin capacity.** The effect lives only at the deep-favorite extreme;
   volume at the very top of the band is thin.

## Verdicts
- **Cross-asset: NO EDGE** (gauntlet rejected; 5/5-positive-but-underpowered near-miss).
- **Maker: NO tradeable edge, but the engine confirmed #15 persists OOS** and characterized it
  precisely as deep-favorite short-vol spread-capture — pennies vs a −96c tail, optimistic fills,
  plateau-fragile. The realest thing in the data, and the best-characterized reason it is not
  bankable.

## Engine lesson → roadmap
DSR/PBO are blind to an *unrealized* fat left tail (favorite capture looks great until the rare
loss). The plateau gate caught this one, but the engine should add an explicit **payoff-asymmetry
/ max-single-loss gate** (and model real queue position for maker fills) before any maker candidate
is trusted. Logged for the next iteration.

Artifacts: `src/btc5m/discovery/{engine,maker_mine,panel}.py`, CLI `kalshi-ade-mine-pooled` /
`-maker`, `scripts/research/autopsy_maker_candidate.py`, registry `data/discovery/trial_registry.jsonl`.
