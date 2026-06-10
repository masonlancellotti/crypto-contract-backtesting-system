# Kalshi maker-entry feasibility study — KXBTC15M (fill model: prints-front)

> READ-ONLY research. REAL trade prints, FRONT-OF-QUEUE assumption: a resting bid counts as filled when the tape traded AT or through the level. OPTIMISTIC upper bound — real queue position would forfeit some at-level fills. No orders, no paper, no promotion; live disabled.

- date filter: start=20260610 end=none (inclusive UTC window-start days)  windows before/after filter: 788/77
- windows: 77  decision points: 842  (one per market-minute; sides×modes per point)
- cost to cross today: spread mean/median/p90 = 0.009/0.010/0.020  taker fee mean = 0.0156
- maker fee rate: 0.07 (ASSUMED); taker rate 0.07 (ASSUMED). Fee-sensitivity table below charges makers the full taker schedule.

## Cohorts (side/mode/rest-horizon)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/60 | 842 | 797 | 94.7% | 0.4 | 43.0% | 64.4% | -4.75 | -4.50 | -5.21 | 77 |
| YES/join/180 | 842 | 814 | 96.7% | 0.4 | 42.9% | 82.1% | -4.93 | -4.77 | -5.21 | 77 |
| YES/join/300 | 842 | 820 | 97.4% | 0.4 | 42.8% | 95.5% | -4.96 | -4.83 | -5.21 | 77 |
| YES/join/close | 842 | 822 | 97.6% | 0.4 | 42.8% | 100.0% | -4.91 | -4.79 | -5.21 | 77 |
| YES/improve/60 | 107 | 102 | 95.3% | 0.3 | 50.0% | 40.0% | -4.00 | -3.81 | -5.74 | 50 |
| YES/improve/180 | 107 | 107 | 100.0% | 0.4 | 49.5% | None | -4.61 | -4.61 | -5.74 | 52 |
| YES/improve/300 | 107 | 107 | 100.0% | 0.4 | 49.5% | None | -4.61 | -4.61 | -5.74 | 52 |
| YES/improve/close | 107 | 107 | 100.0% | 0.4 | 49.5% | None | -4.61 | -4.61 | -5.74 | 52 |
| NO/join/60 | 842 | 804 | 95.5% | 0.4 | 55.1% | 71.1% | 1.51 | 1.44 | 1.14 | 77 |
| NO/join/180 | 842 | 821 | 97.5% | 0.4 | 55.3% | 76.2% | 1.60 | 1.56 | 1.14 | 77 |
| NO/join/300 | 842 | 825 | 98.0% | 0.4 | 55.2% | 88.2% | 1.49 | 1.46 | 1.14 | 77 |
| NO/join/close | 842 | 829 | 98.5% | 0.4 | 55.1% | 100.0% | 1.54 | 1.51 | 1.14 | 77 |
| NO/improve/60 | 107 | 103 | 96.3% | 0.3 | 50.5% | 50.0% | 1.40 | 1.35 | 0.23 | 52 |
| NO/improve/180 | 107 | 106 | 99.1% | 0.3 | 50.0% | 100.0% | 0.76 | 0.75 | 0.23 | 52 |
| NO/improve/300 | 107 | 106 | 99.1% | 0.3 | 50.0% | 100.0% | 0.76 | 0.75 | 0.23 | 52 |
| NO/improve/close | 107 | 106 | 99.1% | 0.3 | 50.0% | 100.0% | 0.76 | 0.75 | 0.23 | 52 |

## Fee sensitivity (maker pays FULL taker schedule)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/close | 842 | 822 | 97.6% | 0.4 | 42.8% | 100.0% | -4.91 | -4.79 | -5.21 | 77 |
| NO/join/close | 842 | 829 | 98.5% | 0.4 | 55.1% | 100.0% | 1.54 | 1.51 | 1.14 | 77 |

## By limit-price bucket (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/[0c,10c) | 148 | 147 | 99.3% | 0.7 | 3.4% | 100.0% | -1.18 | -1.17 | -0.93 | 38 |
| YES/[10c,20c) | 70 | 70 | 100.0% | 0.4 | 15.7% | None | 0.44 | 0.44 | -0.79 | 31 |
| YES/[20c,30c) | 69 | 68 | 98.6% | 0.5 | 25.0% | 100.0% | -1.47 | -1.45 | -1.62 | 38 |
| YES/[30c,40c) | 83 | 81 | 97.6% | 0.4 | 39.5% | 100.0% | 3.15 | 3.07 | 3.45 | 41 |
| YES/[40c,50c) | 93 | 93 | 100.0% | 0.5 | 41.9% | None | -4.57 | -4.57 | -5.81 | 46 |
| YES/[50c,60c) | 75 | 75 | 100.0% | 0.4 | 38.7% | None | -18.01 | -18.01 | -19.19 | 38 |
| YES/[60c,70c) | 65 | 64 | 98.5% | 0.4 | 43.8% | 100.0% | -22.41 | -22.06 | -22.85 | 33 |
| YES/[70c,80c) | 60 | 57 | 95.0% | 0.2 | 61.4% | 100.0% | -14.68 | -13.95 | -14.17 | 31 |
| YES/[80c,90c) | 60 | 58 | 96.7% | 0.2 | 82.8% | 100.0% | -3.40 | -3.28 | -3.95 | 28 |
| YES/[90c,100c) | 119 | 109 | 91.6% | 0.4 | 99.1% | 100.0% | 1.82 | 1.66 | 1.53 | 30 |
| NO/[0c,10c) | 121 | 120 | 99.2% | 0.5 | 0.0% | 100.0% | -4.43 | -4.39 | -4.06 | 34 |
| NO/[10c,20c) | 60 | 60 | 100.0% | 0.2 | 16.7% | None | 1.35 | 1.35 | -0.00 | 30 |
| NO/[20c,30c) | 60 | 59 | 98.3% | 0.3 | 37.3% | 100.0% | 10.47 | 10.30 | 10.10 | 31 |
| NO/[30c,40c) | 66 | 64 | 97.0% | 0.4 | 54.7% | 100.0% | 17.73 | 17.20 | 17.92 | 32 |
| NO/[40c,50c) | 74 | 72 | 97.3% | 0.5 | 59.7% | 100.0% | 13.21 | 12.85 | 13.18 | 35 |
| NO/[50c,60c) | 91 | 91 | 100.0% | 0.7 | 58.2% | None | 1.81 | 1.81 | 0.66 | 46 |
| NO/[60c,70c) | 84 | 82 | 97.6% | 0.2 | 57.3% | 100.0% | -9.27 | -9.05 | -9.33 | 41 |
| NO/[70c,80c) | 68 | 68 | 100.0% | 0.5 | 75.0% | None | -1.37 | -1.37 | -2.56 | 37 |
| NO/[80c,90c) | 73 | 73 | 100.0% | 0.3 | 84.9% | None | -1.27 | -1.27 | -2.31 | 31 |
| NO/[90c,100c) | 145 | 140 | 96.6% | 0.5 | 95.7% | 100.0% | -1.42 | -1.37 | -1.68 | 36 |

## By seconds-to-close (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/180-420s | 308 | 303 | 98.4% | 0.4 | 44.6% | 100.0% | -2.08 | -2.05 | -2.47 | 77 |
| YES/420-660s | 254 | 250 | 98.4% | 0.4 | 43.6% | 100.0% | -5.44 | -5.35 | -5.99 | 77 |
| YES/<180s | 210 | 199 | 94.8% | 0.4 | 42.2% | 100.0% | -4.04 | -3.82 | -3.68 | 76 |
| YES/>=660s | 70 | 70 | 100.0% | 0.6 | 34.3% | None | -17.71 | -17.71 | -19.03 | 19 |
| NO/180-420s | 308 | 306 | 99.4% | 0.4 | 54.2% | 100.0% | -0.97 | -0.97 | -1.61 | 77 |
| NO/420-660s | 254 | 252 | 99.2% | 0.5 | 55.2% | 100.0% | 2.00 | 1.98 | 1.39 | 77 |
| NO/<180s | 210 | 203 | 96.7% | 0.4 | 53.2% | 100.0% | 0.66 | 0.64 | 0.65 | 77 |
| NO/>=660s | 70 | 68 | 97.1% | 0.6 | 64.7% | 100.0% | 13.74 | 13.34 | 13.80 | 19 |

## By UTC day (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/2026-06-10 | 842 | 822 | 97.6% | 0.4 | 42.8% | 100.0% | -4.91 | -4.79 | -5.21 | 77 |
| NO/2026-06-10 | 842 | 829 | 98.5% | 0.4 | 55.1% | 100.0% | 1.54 | 1.51 | 1.14 | 77 |

## Both-sides quoting (double fill of YES-join + NO-join)

- quote points: 842  double fills: 809 (96.1%) across 77 windows
- mean pair cost: 0.9905  mean locked net per pair: -0.0218  total locked net: -17.617
- **FULL both-sides P&L (drift-neutral): -3.28c per quote point** over 842 points (outcomes: {'double': 809, 'no_only': 20, 'yes_only': 13}; total net -27.61); positive days 0/1: {'2026-06-10': -3.279}

## Verdict

- sides with POSITIVE conservative maker EV: ['NO']
- sides where maker(lower bound) beats taker: ['YES', 'NO']
- POSITIVE lower bound: even counting only adverse trade-through fills, resting at the bid earned more than it cost on: NO. Worth a deeper study with real trade prints / WS book data before any paper or live step.

## Honest caveats

- Fill model sees only quote crossings at the recorder cadence (~1-4s): real passive fills from sells into the bid are invisible (undercount), and counted fills are the most adverse subset (price traded through). Both biases make maker EV look WORSE than reality.
- No queue model: assumes our 1 contract is at the front at the limit. At Kalshi's typical depth this is optimistic per-fill but does not change the conditional-outcome estimate.
- Maker fee assumed; verify the current Kalshi fee schedule before any live consideration.
- One snapshot cadence; cancel/replace latency not modeled. Next iteration needs trade prints (public /trades) or authenticated WS book deltas.

## Safety
- READ-ONLY study; no orders, no paper fills, no promotion, no manifest changes; live_submission_allowed=false.
