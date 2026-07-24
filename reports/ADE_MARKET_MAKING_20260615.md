# Round-trip market-making + the value of speed (2026-06-15)

> "Chase the next viable option." The next viable option was the fast MAKER — the one strategy
> class with a non-zero prior, and the user's stated interest in speed. Every prior maker study
> was buy-and-hold-to-settlement; this is the first spread-capturing round-trip MM, with a
> cancel/requote-latency sweep. READ-ONLY. `scripts/research/market_making_sim.py`.

## Model
Quote both sides of the YES contract (bid B, ask A = 1−no_bid), buy when a taker SELLS into the
bid, sell when a taker BUYS the ask, settle residual inventory at close. One resting contract per
side (refills on requote = queue proxy); inventory skew (long → shift quotes down,
Avellaneda-Stoikov-lite). Requote to the live book only every `cancel_latency_ms`. Fills are still
optimistic (no real queue size) → an UPPER BOUND. BTC, 1031 windows, maker fee 0.

## Result (cancel-latency sweep)
| cancel latency | mean P&L/win | per-fill | fills/win | naked-end% |
|---|---|---|---|---|
| 250 ms | −717c | −0.64c | 1113 | 99% |
| 1 s | −460c | −0.76c | 604 | 98% |
| 4 s | −201c | −0.92c | 219 | 95% |
| static (#14) | **−1.76c** | −0.93c | 1.9 | 8% |

- Static baseline −1.76c reproduces ledger #14 (the model is calibrated).
- **Every maker fill is ~0.6–0.9c adversely selected** — the spread captured does NOT cover the
  toxicity of the fill. More quoting / faster requoting just multiplies toxic fills → bigger total
  loss. **Speed makes a naive maker WORSE, not better.**

## Why — and why this is the deepest "efficient" result
Market-making profits only if you have a **fair-value edge** to skew/cancel on, so your fills aren't
toxic. This entire project has proven there is **no fair-value edge** — the market price is the best
forecaster measured (ECE 0.02), and a full combination of every signal just re-derives it (#34).
Without alpha, every counterparty is at least as informed as you; **every fill is adverse, and speed
only lets you get adversely selected faster.** The absence of predictive edge doesn't just kill
takers — it kills market-making too.

## Caveats (honest)
- Fills are optimistic (no real queue depth); a true queue model makes MM *worse*, not better.
- A *real* MM edge would need a micro-alpha the book lacks. The sub-second momentum (EXP2) is real on
  the underlying but does not bridge to the 15m binary (#21/#22), so it cannot supply the fair value.
- Kalshi pays **no maker rebate** (taker-fee model), so there is no rebate to offset adverse selection.

## Verdict
**Round-trip market-making is not viable here, and speed has negative value for an alpha-less maker.**
This closes the fast-maker thread on the merits (the part testable offline): faster cancel/requote
only helps an MM that already has a fair-value edge to avoid toxic fills — and there is none. The only
maker positive ever found (deep-favorite spread capture #15) is the short-vol, tail-risky exception,
not a scalable MM. Speed/infra would pay ONLY if paired with a genuine fair-value signal the market
lacks — i.e., a *new input*, not faster execution of the same (efficient) information.
