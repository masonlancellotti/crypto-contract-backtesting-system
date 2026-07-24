# Last existing-data stones: print microstructure, cross-sectional reversion, speed (2026-06-15)

> "Run everything" + the speed question. All READ-ONLY, gauntlet-disciplined.

## Print-level microstructure — `scripts/research/print_microstructure_mine.py`
From the 3.2M BTC prints, per-window large-print / sweep / toxicity features over the pre-decision
120s (intensity, signed imbalance, max size, signed LARGE-print volume, longest same-side sweep run).
- `p_large_signed` (whale signed-volume) has a **real but tiny** residual IC of **+0.063** (slightly
  above the aggregate CVD) — the only print feature to surface; the rest were weaker.
- Best rule = the same distance artifact; **DSR 0.525, plateau spike → NO EDGE.** Order flow, even at
  print level, is already in the price.

## Cross-sectional reversion — `scripts/research/crosssectional_reversion.py`
Fade each alt's idiosyncratic deviation from the BTC factor (alt distance-z − concurrent BTC distance-z).
- The deviation features did **not** surface in the top residual-IC list — the dislocation carries no
  tradeable predictive power. Best rule overfit (**PBO 0.73**, DSR 0.184, spike) → **NO EDGE.**

## Speed / latency value — `kalshi-reprice-lag-report --hires` (1.37M rows, 475 windows, 7 days)
Does faster execution unlock the reprice-lag (stale-quote) edge?
- Sub-second observation is covered: **+250ms / +500ms = 89% / 89%** (WS book).
- **Net −0.027c/contract, win 23%, profit factor 0.82 → NEGATIVE**; negative across every shock
  threshold (3/5/8/12 bps).
- **Why speed can't help:** when BTC moves, the Kalshi quote follows in the expected direction only
  **58%** of the time with a **median lag of 0.13c** — one-eighth of a cent, far below the ~2.5c cost.
  The quote is *barely stale*. The edge isn't latency-gated; it's **absent**. Faster observation than
  250ms changes nothing because there is nothing of size to capture.

## Speed verdict — taker vs maker (the honest nuance)
- **Taker / reprice-lag:** speed does **not** help. Proven negative at 250ms; the lag is 0.13c.
- **Maker / market-making:** speed (fast cancel/requote + queue priority) is the **one** place it could
  plausibly matter — static maker quoting died to adverse selection (#14) and the textbook fix is exactly
  fast cancel/requote. We **cannot** validate that offline (it needs live quoting), so it is the only
  speed bet not ruled out — and the only one that would require building real low-latency infra.

## Bottom line
Existing data is now exhausted across every angle — single features, combinations, regimes, cross-coin
(lead-lag + reversion), cross-horizon arb, settlement mechanics, print microstructure, and the latency
dimension. **All negative, with proof.** The only threads not closed are ones existing data *cannot*
close: (1) **KXETH15M** following BTC (already ~break-even, needs forward windows for significance);
(2) a **fast maker** with queue priority (needs live infra); (3) **new inputs** the price lacks (alt-data,
faster/deeper feeds, a less-efficient venue/structure).
