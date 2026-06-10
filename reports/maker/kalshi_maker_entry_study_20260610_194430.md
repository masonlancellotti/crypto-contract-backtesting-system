# Kalshi maker-entry feasibility study — KXBTC15M (fill model: prints-through)

> READ-ONLY research. REAL trade prints, CERTAIN fills only: a resting bid counts as filled when the tape traded strictly THROUGH the level (queue-position-free). Conservative on fill count, but fills/outcomes come from actual flow. No orders, no paper, no promotion; live disabled.

- date filter: start=20260610 end=none (inclusive UTC window-start days)  windows before/after filter: 788/77
- windows: 77  decision points: 842  (one per market-minute; sides×modes per point)
- cost to cross today: spread mean/median/p90 = 0.009/0.010/0.020  taker fee mean = 0.0156
- maker fee rate: 0.07 (ASSUMED); taker rate 0.07 (ASSUMED). Fee-sensitivity table below charges makers the full taker schedule.

## Cohorts (side/mode/rest-horizon)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/60 | 842 | 633 | 75.2% | 3.0 | 41.1% | 53.6% | -6.08 | -4.57 | -5.21 | 77 |
| YES/join/180 | 842 | 708 | 84.1% | 3.9 | 40.5% | 63.4% | -5.96 | -5.01 | -5.21 | 77 |
| YES/join/300 | 842 | 721 | 85.6% | 3.9 | 40.5% | 66.1% | -5.85 | -5.01 | -5.21 | 77 |
| YES/join/close | 842 | 729 | 86.6% | 4.0 | 40.2% | 69.9% | -6.10 | -5.28 | -5.21 | 77 |
| YES/improve/60 | 107 | 99 | 92.5% | 0.4 | 50.5% | 37.5% | -3.55 | -3.28 | -5.74 | 50 |
| YES/improve/180 | 107 | 105 | 98.1% | 0.5 | 49.5% | 50.0% | -4.59 | -4.51 | -5.74 | 52 |
| YES/improve/300 | 107 | 106 | 99.1% | 0.5 | 49.1% | 100.0% | -4.84 | -4.80 | -5.74 | 52 |
| YES/improve/close | 107 | 106 | 99.1% | 0.5 | 49.1% | 100.0% | -4.84 | -4.80 | -5.74 | 52 |
| NO/join/60 | 842 | 667 | 79.2% | 3.3 | 54.6% | 60.6% | 1.30 | 1.03 | 1.14 | 77 |
| NO/join/180 | 842 | 713 | 84.7% | 3.7 | 54.0% | 65.9% | 1.03 | 0.87 | 1.14 | 77 |
| NO/join/300 | 842 | 725 | 86.1% | 3.7 | 53.7% | 69.2% | 0.86 | 0.74 | 1.14 | 77 |
| NO/join/close | 842 | 733 | 87.1% | 3.9 | 53.5% | 71.6% | 0.75 | 0.65 | 1.14 | 77 |
| NO/improve/60 | 107 | 102 | 95.3% | 0.3 | 50.0% | 60.0% | 1.04 | 0.99 | 0.23 | 52 |
| NO/improve/180 | 107 | 106 | 99.1% | 0.4 | 50.0% | 100.0% | 0.76 | 0.75 | 0.23 | 52 |
| NO/improve/300 | 107 | 106 | 99.1% | 0.4 | 50.0% | 100.0% | 0.76 | 0.75 | 0.23 | 52 |
| NO/improve/close | 107 | 106 | 99.1% | 0.4 | 50.0% | 100.0% | 0.76 | 0.75 | 0.23 | 52 |

## Fee sensitivity (maker pays FULL taker schedule)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/close | 842 | 729 | 86.6% | 4.0 | 40.2% | 69.9% | -6.10 | -5.28 | -5.21 | 77 |
| NO/join/close | 842 | 733 | 87.1% | 3.9 | 53.5% | 71.6% | 0.75 | 0.65 | 1.14 | 77 |

## By limit-price bucket (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/[0c,10c) | 148 | 113 | 76.4% | 6.4 | 4.4% | 2.9% | -1.17 | -0.89 | -0.93 | 35 |
| YES/[10c,20c) | 70 | 69 | 98.6% | 3.8 | 14.5% | 100.0% | -0.80 | -0.79 | -0.79 | 31 |
| YES/[20c,30c) | 69 | 68 | 98.6% | 3.3 | 25.0% | 100.0% | -1.47 | -1.45 | -1.62 | 38 |
| YES/[30c,40c) | 83 | 81 | 97.6% | 3.4 | 39.5% | 100.0% | 3.15 | 3.07 | 3.45 | 41 |
| YES/[40c,50c) | 93 | 92 | 98.9% | 5.8 | 41.3% | 100.0% | -5.18 | -5.13 | -5.81 | 45 |
| YES/[50c,60c) | 75 | 72 | 96.0% | 2.7 | 36.1% | 100.0% | -20.57 | -19.75 | -19.19 | 36 |
| YES/[60c,70c) | 65 | 64 | 98.5% | 3.0 | 43.8% | 100.0% | -22.41 | -22.06 | -22.85 | 33 |
| YES/[70c,80c) | 60 | 54 | 90.0% | 2.4 | 59.3% | 100.0% | -16.85 | -15.17 | -14.17 | 29 |
| YES/[80c,90c) | 60 | 54 | 90.0% | 4.1 | 81.5% | 100.0% | -4.85 | -4.37 | -3.95 | 25 |
| YES/[90c,100c) | 119 | 62 | 52.1% | 4.2 | 98.4% | 100.0% | 2.39 | 1.24 | 1.53 | 24 |
| NO/[0c,10c) | 121 | 89 | 73.6% | 7.8 | 0.0% | 3.1% | -5.52 | -4.06 | -4.06 | 30 |
| NO/[10c,20c) | 60 | 59 | 98.3% | 3.5 | 15.3% | 100.0% | -0.02 | -0.02 | -0.00 | 29 |
| NO/[20c,30c) | 60 | 57 | 95.0% | 2.8 | 35.1% | 100.0% | 8.26 | 7.85 | 10.10 | 30 |
| NO/[30c,40c) | 66 | 64 | 97.0% | 2.5 | 54.7% | 100.0% | 17.73 | 17.20 | 17.92 | 32 |
| NO/[40c,50c) | 74 | 69 | 93.2% | 2.7 | 58.0% | 100.0% | 11.46 | 10.69 | 13.18 | 35 |
| NO/[50c,60c) | 91 | 89 | 97.8% | 3.3 | 57.3% | 100.0% | 0.90 | 0.88 | 0.66 | 45 |
| NO/[60c,70c) | 84 | 80 | 95.2% | 4.0 | 56.2% | 100.0% | -10.33 | -9.83 | -9.33 | 41 |
| NO/[70c,80c) | 68 | 63 | 92.6% | 4.3 | 73.0% | 100.0% | -3.32 | -3.07 | -2.56 | 35 |
| NO/[80c,90c) | 73 | 68 | 93.2% | 4.3 | 83.8% | 100.0% | -2.37 | -2.21 | -2.31 | 30 |
| NO/[90c,100c) | 145 | 95 | 65.5% | 5.4 | 93.7% | 100.0% | -2.50 | -1.64 | -1.68 | 33 |

## By seconds-to-close (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/180-420s | 308 | 287 | 93.2% | 3.6 | 41.5% | 100.0% | -2.53 | -2.36 | -2.47 | 77 |
| YES/420-660s | 254 | 246 | 96.9% | 4.4 | 42.7% | 100.0% | -6.17 | -5.97 | -5.99 | 77 |
| YES/<180s | 210 | 126 | 60.0% | 3.3 | 35.7% | 59.5% | -7.65 | -4.59 | -3.68 | 62 |
| YES/>=660s | 70 | 70 | 100.0% | 8.1 | 34.3% | None | -17.71 | -17.71 | -19.03 | 19 |
| NO/180-420s | 308 | 285 | 92.5% | 4.2 | 52.3% | 82.6% | -1.85 | -1.72 | -1.61 | 77 |
| NO/420-660s | 254 | 243 | 95.7% | 3.7 | 53.5% | 100.0% | 0.27 | 0.26 | 1.39 | 77 |
| NO/<180s | 210 | 137 | 65.2% | 3.5 | 50.4% | 63.0% | 0.57 | 0.37 | 0.65 | 68 |
| NO/>=660s | 70 | 68 | 97.1% | 3.7 | 64.7% | 100.0% | 13.74 | 13.34 | 13.80 | 19 |

## By UTC day (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/2026-06-10 | 842 | 729 | 86.6% | 4.0 | 40.2% | 69.9% | -6.10 | -5.28 | -5.21 | 77 |
| NO/2026-06-10 | 842 | 733 | 87.1% | 3.9 | 53.5% | 71.6% | 0.75 | 0.65 | 1.14 | 77 |

## Both-sides quoting (double fill of YES-join + NO-join)

- quote points: 842  double fills: 672 (79.8%) across 77 windows
- mean pair cost: 0.9895  mean locked net per pair: -0.0224  total locked net: -15.069
- **FULL both-sides P&L (drift-neutral): -4.63c per quote point** over 842 points (outcomes: {'double': 672, 'none': 52, 'yes_only': 57, 'no_only': 61}; total net -38.97); positive days 0/1: {'2026-06-10': -4.628}

## Verdict

- sides with POSITIVE conservative maker EV: ['NO']
- sides where maker(lower bound) beats taker: []
- POSITIVE lower bound: even counting only adverse trade-through fills, resting at the bid earned more than it cost on: NO. Worth a deeper study with real trade prints / WS book data before any paper or live step.

## Honest caveats

- Fill model sees only quote crossings at the recorder cadence (~1-4s): real passive fills from sells into the bid are invisible (undercount), and counted fills are the most adverse subset (price traded through). Both biases make maker EV look WORSE than reality.
- No queue model: assumes our 1 contract is at the front at the limit. At Kalshi's typical depth this is optimistic per-fill but does not change the conditional-outcome estimate.
- Maker fee assumed; verify the current Kalshi fee schedule before any live consideration.
- One snapshot cadence; cancel/replace latency not modeled. Next iteration needs trade prints (public /trades) or authenticated WS book deltas.

## Safety
- READ-ONLY study; no orders, no paper fills, no promotion, no manifest changes; live_submission_allowed=false.
