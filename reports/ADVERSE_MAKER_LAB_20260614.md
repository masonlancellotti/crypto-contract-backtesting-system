# Adverse-selection-aware maker — results (2026-06-14)

> Strategy ① (the maker bridge). READ-ONLY backtest; **live disabled throughout**.
> Harness: `scripts/research/adverse_maker_lab.py`. Data: KXBTC15M, 6 days
> (06-08→06-14), 362–364 labeled windows with both joined sub-second snapshots
> **and** real trade prints. Maker fee assumed 0 (ASSUMED_ZERO_MAKER_FEE).

## The question
The only place edge ever appeared in this project is the **maker** lens (#13/#15:
resting entries save the spread+fee), but **static** quoting dies to adverse selection
(#14: naked legs ≈ −21c when the market runs through one side). `maker_entry.py:589`
flags the gap: *"cancel/replace latency not modeled."* EXP2 (#22) proved sub-second
momentum (`mom_1s`) carries **real** predictive structure for the next 1–5 s underlying
move (IC +0.195) but does **not** bridge to a TAKER edge on the 15 m binary (EXP1/EXP3).
**Untested until now:** can that real signal let a MAKER *cancel* adversely-selected
resting quotes before they fill — turning the negative static-maker result positive?

## Method
Post one resting bid per side per window at a decision snapshot (join level = best bid
= `1 − no_ask`). Fill via the **real trade tape**, `queue="through"` (fill only when the
tape trades strictly through the level — the adverse subset, and the only model that
leaves a resting window to cancel within; front-of-queue fills ~instantly, 98%, no cancel
window). **Cancel rule:** walk joined snapshots in (t0, t_fill); if 1 s momentum is
adverse (YES bid: `mom_1s ≤ −θ`; NO bid: `≥ +θ`) before the fill, cancel → no trade.
Decision uses only trailing-1 s info; outcome is the window label → no lookahead.
**Crux diagnostic:** do *cancelled* fills realize worse EV than *survived* fills? If yes,
the signal selects losers and the rule adds maker value. θ = 1 bp (1e-4 log-return).

## Results (θ=1 bp, through-queue)

| lead→close | quotes | filled | cancelled | baseline EV/fill | survived EV/fill | **cancelled-fill EV** | naked-leg EV (t) |
|---|---|---|---|---|---|---|---|
| 120 s | 714 | 467 (65%) | 31% | −1.71c (t−1.2) | −1.86c | −1.37c ❌ | −8.41c (−5.2) |
| 240 s | 727 | 612 (84%) | 33% | −1.17c (t−0.9) | −1.70c | −0.12c ❌ | −11.15c (−6.4) |
| 360 s | 724 | 659 (91%) | 39% | −1.64c (t−1.1) | −2.30c | −0.61c ❌ | −21.58c (−7.2) |
| **450 s** | 724 | 688 (95%) | 34% | −1.03c (t−0.7) | **+1.08c (t+0.55)** | **−5.05c (t−2.03)** ✅ | −28.80c (−7.4) |

(θ=3 bp: too few cancels (4%) to move anything — confirms the effect is not robust to
threshold. `/tmp/adv_maker_through.txt`, `/tmp/adv_maker_leadsweep.txt`.)

## Verdict — NEGATIVE (one underpowered watch corner)
1. **The cancel rule does not work in general.** The crux fails at 3 of 4 decision points:
   cancelled-fill EV is **not** worse than survived, and cancel-aware EV ≤ baseline. The
   sub-second momentum signal — real on the underlying — does **not** identify which maker
   through-fills lose at the 15 m binary outcome. Same bridge failure as EXP1/EXP3, now
   confirmed for the **maker** lens.
2. **Robust, monotonic, the opposite of an edge:** maker through-fill adverse selection
   *grows* with earlier entry — naked single legs −8.4 → −11.2 → −21.6 → −28.8c, **all
   t < −6** — and the momentum-cancel makes naked legs **worse** at every lead (it removes
   winners, e.g. deep-favorite dips that still resolve favorite). Strong confirmation of
   #13/#14: static/passive maker entries are adversely selected and the signal does not
   rescue them.
3. **The one positive corner is a multiple-comparisons artifact, not an edge.** Only at the
   earliest entry (~window-open, lead 450 s — the most contested point, where the idea
   *should* work best if at all) does the crux flip: survived EV **+1.08c** with cancelled
   fills a significant −5.05c (t−2.03). But **survived EV t=+0.55 (insignificant)**, it is
   1 of 4 leads (the other 3 negative), it is not robust to θ, and the per-band deltas are
   sign-inconsistent. Three negatives + one insignificant positive at the most-swept corner
   ≠ edge.

## What this closes / leaves open
- **CLOSES** the "sub-second signal rescues the maker via cancellation" hope for momentum.
  Combined with EXP1/EXP2/EXP3, the sub-second signal has now failed to bridge to Kalshi
  P&L as a taker forecast, a stale-quote snipe, **and** a maker adverse-selection filter.
- **Watch (low confidence):** the lead≈450 s (window-open) corner. A real test needs (a)
  ≥1–2 weeks of forward windows, (b) a non-momentum cancel signal (size_imb / basis / |z|),
  and (c) a day-split to rule out regime. Escalate only if survived EV holds > 0 with t > 2.
- Untouched maker variant: dynamic *re-quote/skew* (not just cancel) with inventory — but
  #14 already showed static both-sides dies, and cancellation (the cheaper half of
  cancel/requote) does not help, so the prior is now strongly negative.

## Reusable artifact
`scripts/research/adverse_maker_lab.py` — modes via `--lead-sweep`, `--theta-sweep`,
`--queue {front,through}`; loads heavy inputs once and sweeps in-memory. BTC only (alts
have no backfilled prints). READ-ONLY; `live_submission_allowed=False`.
