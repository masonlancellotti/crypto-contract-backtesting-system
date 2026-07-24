# Alpha Discovery Engine — first mine (2026-06-14)

> `kalshi-ade-mine --series KXBTC15M --mine-lead-seconds 180`. READ-ONLY; live disabled.
> Milestone-2 integration run: feature factory → screen → search → gauntlet → (sealed holdout).

## Setup
- 952 labeled windows → **702 search / 236 holdout** (hash-pinned sealed vault `c071f4a0…`).
- Feature factory `ff1:1c4cdedd5afe` (35 screened of 42 base+derived), decision snapshot @180 s-to-close.
- 200 after-cost entry-rule trials (feature × tail × side × threshold), real Kalshi fee.

## What it found — and why the gauntlet rejected it
Top features by **market-residual IC** (predicting `y − mkt_p`, i.e. what the price misses):

| feature | IC_resid | IC_outcome | OOS sign-stab |
|---|---|---|---|
| distance_to_line_vol_normalized | **+0.401** | +0.793 | 1.00 |
| distance_to_start | **+0.400** | +0.790 | 1.00 |
| spot_return_since_window_start | **+0.386** | +0.773 | 1.00 |
| spot_return_180s | +0.160 | +0.323 | 1.00 |

Best trial: **`distance_to_start` hi-tail q0.75 → buy YES** (thr ≈ $77): n=164, **per-trade +1.37c,
t = +5.55**, win 56% at ~54c entry, window-Sharpe +0.196.

**GAUNTLET VERDICT: NO EDGE (rejected).**
- **Deflated Sharpe = 0.127** (≪ 0.95): the raw window-Sharpe 0.196 is *below* E[maxSR under 200
  trials] = 0.219 — i.e. across the search you'd expect a best-trial Sharpe this big by luck alone.
- **Parameter plateau = SPIKE** (ratio −0.01): the threshold is fragile, not a robust plateau.
- (PBO = 0.00: the rule *is* internally consistent IS→OOS — see tension below.)

## Interpretation — the engine found the dataset's most seductive trap
A residual IC of **+0.40** directly contradicts the project's established market calibration
(window-ECE ≈ 0.02; market-implied is the best forecaster measured). When a feature appears to
predict "what the market misses" that strongly, the prior is **artifact, not alpha**:
- The signal is the *distance / return-since-window-start* family — exactly the **stale-quote /
  reprice-lag** effect (ledger #8/#23), concluded **net-negative after realistic execution**. The
  rule monetizes "spot just moved up, the Kalshi quote hasn't repriced yet," but the recorded
  `executable_yes_buy_price` is not actually transactable at the instant of the spot reading, so
  the +1.37c is a measurement/timing artifact.
- **Not a code leak:** features are point-in-time (`as_of_ms < close_ms`), and the settled label is
  used only as the target. It is an *execution-realism* artifact.

**Tension worth noting (a refinement, not a reversal):** PBO=0 (robust IS→OOS) vs DSR-reject + plateau-
spike. The 200 trials are *highly correlated* (tail-rules over overlapping momentum features), so the
effective number of independent trials ≪ 200 and DSR's E[maxSR] is somewhat over-stated → DSR is
*conservative* here. Even so the raw Sharpe didn't clear it, and the economics point to quote-lag.

## Conclusion
The engine works end-to-end and did exactly its job: it surfaced the single most tempting pattern in
the data (t=5.5!) and the multiple-testing/robustness gauntlet **stopped us from chasing it**. This is
the intended outcome on a near-efficient market — *no edge, with proof*.

## CORRECTION (2026-06-15) — execution-realism fix refuted the reprice-lag story
The reprice-lag attribution above was a hypothesis, and the M3 execution-realism fix tested it
and **refuted it.** Fills are now priced at the executable quote sampled `exec_lag_seconds` AFTER
the decision snapshot (`panel.build_panel`, default 3s, CLI `--exec-lag-seconds`). A/B + sweep:

| exec_lag | best rule | per-trade (t) | win | window-Sharpe | DSR | verdict |
|---|---|---|---|---|---|---|
| 0s | distance→YES | +1.57c (5.94) | 58% | 0.205 | — | artifact |
| 3s | ret-since-start→YES | +1.80c (3.42) | 55% | 0.130 | 0.083 | REJECT |
| 10s | distance→YES | +1.65c (5.34) | 56% | 0.188 | 0.247 | REJECT |
| 30s | ret-since-start→YES | +2.07c (3.74) | 49% | 0.136 | 0.000 | REJECT |

The candidate **survives a 30 s execution lag** — Kalshi reprices in ~1–4 s, so this is **NOT**
reprice-lag/stale-quote. The leading (still-unverified) explanation is the documented **YES-favorite/
side directional bias** (#15), which already failed forward validation. Either way the **gauntlet
rejects it at every lag** (DSR 0.00–0.25, plateau spike) — the false-positive control held even though
my first human diagnosis (reprice-lag) was wrong. Lesson logged: don't label the artifact class before
the engine tests it.

## Next (M3 — effective-N + the candidate's autopsy)
- Execution-realistic pricing: **DONE** (above).
- Candidate autopsy: is the distance/momentum→YES "edge" just the #15 side-bias? (e.g. compare to a
  side-only rule; split by regime/day; forward-only). It failed forward before — likely the same.
1. **Execution-realistic pricing:** re-price trials against a quote sampled with a realistic post-
   signal latency (or the next-snapshot ask), which should collapse the distance/return-since-start
   "edge" to the known-negative reprice-lag result — and immunize the engine against this artifact class.
2. **Effective-N deflation:** estimate the effective number of independent trials (cluster correlated
   rules) so DSR isn't over/under-deflated.
3. Then widen the feature factory (cross-asset leads, KXBTCD implied-CDF moments once recorded) and
   re-mine — the artifact-hardened engine is the prerequisite.

Artifacts: `src/btc5m/discovery/` (engine/feature_factory/panel/screen/search), CLI `kalshi-ade-mine`,
registry `data/discovery/trial_registry.jsonl`, vault `data/discovery/vault_KXBTC15M_*.json`.
