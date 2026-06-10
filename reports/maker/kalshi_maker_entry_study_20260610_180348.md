# Kalshi maker-entry feasibility study — KXBTC15M (fill model: prints-through)

> READ-ONLY research. REAL trade prints, CERTAIN fills only: a resting bid counts as filled when the tape traded strictly THROUGH the level (queue-position-free). Conservative on fill count, but fills/outcomes come from actual flow. No orders, no paper, no promotion; live disabled.

- windows: 585  decision points: 7675  (one per market-minute; sides×modes per point)
- cost to cross today: spread mean/median/p90 = 0.009/0.010/0.010  taker fee mean = 0.0154
- maker fee rate: 0.0 (ASSUMED_ZERO_MAKER_FEE); taker rate 0.07 (ASSUMED). Fee-sensitivity table below charges makers the full taker schedule.

## Cohorts (side/mode/rest-horizon)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/60 | 7675 | 5815 | 75.8% | 3.1 | 40.2% | 58.9% | -3.75 | -2.84 | -3.90 | 582 |
| YES/join/180 | 7675 | 6322 | 82.4% | 3.8 | 39.9% | 67.1% | -3.79 | -3.12 | -3.90 | 582 |
| YES/join/300 | 7675 | 6444 | 84.0% | 3.9 | 39.9% | 70.0% | -3.83 | -3.22 | -3.90 | 582 |
| YES/join/close | 7675 | 6528 | 85.1% | 4.0 | 39.9% | 72.2% | -3.82 | -3.25 | -3.90 | 582 |
| YES/improve/60 | 612 | 529 | 86.4% | 0.6 | 44.8% | 51.8% | -5.30 | -4.58 | -7.69 | 339 |
| YES/improve/180 | 612 | 555 | 90.7% | 0.7 | 44.1% | 61.4% | -5.82 | -5.28 | -7.69 | 349 |
| YES/improve/300 | 612 | 560 | 91.5% | 0.7 | 44.3% | 61.5% | -5.67 | -5.19 | -7.69 | 350 |
| YES/improve/close | 612 | 570 | 93.1% | 0.8 | 44.0% | 69.0% | -5.78 | -5.38 | -7.69 | 352 |
| NO/join/60 | 7675 | 5620 | 73.2% | 3.1 | 51.3% | 66.1% | 0.39 | 0.29 | -0.11 | 582 |
| NO/join/180 | 7675 | 6156 | 80.2% | 3.8 | 50.8% | 73.3% | 0.27 | 0.22 | -0.11 | 582 |
| NO/join/300 | 7675 | 6294 | 82.0% | 4.0 | 50.8% | 75.6% | 0.27 | 0.22 | -0.11 | 582 |
| NO/join/close | 7675 | 6397 | 83.3% | 4.1 | 50.6% | 78.6% | 0.12 | 0.10 | -0.11 | 582 |
| NO/improve/60 | 612 | 540 | 88.2% | 0.6 | 51.7% | 73.6% | 2.78 | 2.45 | 1.11 | 338 |
| NO/improve/180 | 612 | 561 | 91.7% | 0.7 | 51.9% | 80.4% | 3.02 | 2.76 | 1.11 | 350 |
| NO/improve/300 | 612 | 568 | 92.8% | 0.7 | 51.4% | 90.9% | 2.58 | 2.39 | 1.11 | 351 |
| NO/improve/close | 612 | 575 | 94.0% | 0.7 | 51.3% | 100.0% | 2.52 | 2.37 | 1.11 | 353 |

## Fee sensitivity (maker pays FULL taker schedule)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/close | 7675 | 6528 | 85.1% | 4.0 | 39.9% | 72.2% | -5.42 | -4.61 | -3.90 | 582 |
| NO/join/close | 7675 | 6397 | 83.3% | 4.1 | 50.6% | 78.6% | -1.49 | -1.24 | -0.11 | 582 |

## By limit-price bucket (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/[0c,10c) | 1428 | 1111 | 77.8% | 9.2 | 4.3% | 3.5% | -0.22 | -0.17 | -0.86 | 314 |
| YES/[10c,20c) | 717 | 705 | 98.3% | 4.9 | 10.9% | 100.0% | -3.37 | -3.32 | -4.26 | 298 |
| YES/[20c,30c) | 714 | 684 | 95.8% | 3.4 | 18.6% | 56.7% | -5.82 | -5.57 | -7.61 | 311 |
| YES/[30c,40c) | 648 | 624 | 96.3% | 2.6 | 27.4% | 100.0% | -7.15 | -6.89 | -7.71 | 308 |
| YES/[40c,50c) | 671 | 634 | 94.5% | 2.7 | 34.9% | 100.0% | -9.67 | -9.13 | -9.32 | 335 |
| YES/[50c,60c) | 730 | 686 | 94.0% | 3.3 | 46.2% | 100.0% | -7.88 | -7.40 | -8.05 | 331 |
| YES/[60c,70c) | 606 | 556 | 91.7% | 2.7 | 59.0% | 100.0% | -5.63 | -5.16 | -5.32 | 266 |
| YES/[70c,80c) | 510 | 463 | 90.8% | 3.1 | 71.5% | 100.0% | -2.98 | -2.70 | -3.45 | 231 |
| YES/[80c,90c) | 554 | 476 | 85.9% | 3.7 | 86.3% | 100.0% | 1.65 | 1.42 | 1.27 | 211 |
| YES/[90c,100c) | 1097 | 589 | 53.7% | 6.3 | 97.3% | 100.0% | 2.35 | 1.26 | 1.06 | 207 |
| NO/[0c,10c) | 1103 | 825 | 74.8% | 9.6 | 1.5% | 1.8% | -3.17 | -2.37 | -3.37 | 231 |
| NO/[10c,20c) | 553 | 544 | 98.4% | 4.8 | 10.5% | 100.0% | -3.76 | -3.70 | -4.87 | 230 |
| NO/[20c,30c) | 515 | 485 | 94.2% | 3.5 | 21.4% | 100.0% | -2.97 | -2.80 | -1.61 | 246 |
| NO/[30c,40c) | 613 | 585 | 95.4% | 2.7 | 34.9% | 100.0% | 0.44 | 0.42 | 0.22 | 279 |
| NO/[40c,50c) | 724 | 680 | 93.9% | 2.9 | 47.8% | 100.0% | 3.11 | 2.93 | 2.96 | 329 |
| NO/[50c,60c) | 679 | 613 | 90.3% | 3.2 | 58.2% | 100.0% | 3.92 | 3.54 | 4.45 | 322 |
| NO/[60c,70c) | 644 | 581 | 90.2% | 3.4 | 66.6% | 100.0% | 2.25 | 2.03 | 2.35 | 288 |
| NO/[70c,80c) | 706 | 638 | 90.4% | 3.1 | 77.0% | 100.0% | 2.41 | 2.18 | 1.50 | 287 |
| NO/[80c,90c) | 722 | 630 | 87.3% | 3.3 | 86.3% | 100.0% | 1.66 | 1.45 | 1.13 | 281 |
| NO/[90c,100c) | 1416 | 816 | 57.6% | 7.4 | 92.8% | 100.0% | -2.25 | -1.30 | -1.60 | 287 |

## By seconds-to-close (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/180-420s | 2312 | 2010 | 86.9% | 4.7 | 38.6% | 86.1% | -2.26 | -1.97 | -2.48 | 569 |
| YES/420-660s | 2264 | 2133 | 94.2% | 4.4 | 41.7% | 96.9% | -4.22 | -3.98 | -4.78 | 567 |
| YES/<180s | 1427 | 791 | 55.4% | 3.5 | 36.0% | 57.4% | -1.66 | -0.92 | -0.81 | 411 |
| YES/>=660s | 1672 | 1594 | 95.3% | 3.2 | 41.0% | 97.4% | -6.32 | -6.02 | -7.32 | 537 |
| NO/180-420s | 2312 | 1951 | 84.4% | 4.9 | 49.2% | 87.5% | -1.29 | -1.09 | -1.00 | 571 |
| NO/420-660s | 2264 | 2084 | 92.0% | 4.4 | 51.3% | 99.4% | 0.49 | 0.45 | 0.41 | 568 |
| NO/<180s | 1427 | 789 | 55.3% | 3.2 | 46.4% | 64.4% | -3.10 | -1.71 | -2.06 | 399 |
| NO/>=660s | 1672 | 1573 | 94.1% | 3.5 | 53.6% | 100.0% | 2.98 | 2.80 | 2.09 | 538 |

## By UTC day (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/2026-06-01 | 212 | 185 | 87.3% | 7.1 | 38.4% | 66.7% | -10.23 | -8.93 | -10.19 | 15 |
| YES/2026-06-02 | 1270 | 1092 | 86.0% | 3.8 | 34.5% | 61.8% | -6.71 | -5.77 | -6.90 | 90 |
| YES/2026-06-03 | 1232 | 1049 | 85.1% | 3.9 | 37.7% | 70.5% | -6.97 | -5.94 | -6.76 | 87 |
| YES/2026-06-04 | 839 | 665 | 79.3% | 3.7 | 36.7% | 70.7% | -4.99 | -3.96 | -3.90 | 73 |
| YES/2026-06-05 | 979 | 849 | 86.7% | 3.2 | 43.8% | 68.5% | 1.10 | 0.95 | 0.50 | 73 |
| YES/2026-06-06 | 934 | 829 | 88.8% | 3.4 | 40.0% | 80.0% | -5.14 | -4.56 | -5.79 | 68 |
| YES/2026-06-07 | 1181 | 1008 | 85.4% | 4.4 | 49.3% | 76.9% | 2.98 | 2.54 | 1.79 | 91 |
| YES/2026-06-08 | 660 | 545 | 82.6% | 4.8 | 39.3% | 77.4% | -4.35 | -3.59 | -3.91 | 56 |
| YES/2026-06-09 | 221 | 173 | 78.3% | 4.7 | 39.3% | 87.5% | -0.84 | -0.65 | 1.85 | 19 |
| YES/2026-06-10 | 147 | 133 | 90.5% | 8.1 | 25.6% | 78.6% | -16.86 | -15.26 | -16.68 | 10 |
| NO/2026-06-01 | 212 | 180 | 84.9% | 5.0 | 53.3% | 84.4% | 7.50 | 6.37 | 5.90 | 15 |
| NO/2026-06-02 | 1270 | 1033 | 81.3% | 4.1 | 56.2% | 85.2% | 3.04 | 2.48 | 2.87 | 90 |
| NO/2026-06-03 | 1232 | 1019 | 82.7% | 4.1 | 53.0% | 78.9% | 3.24 | 2.68 | 2.59 | 87 |
| NO/2026-06-04 | 839 | 652 | 77.7% | 4.7 | 50.3% | 77.0% | 0.08 | 0.07 | 0.14 | 72 |
| NO/2026-06-05 | 979 | 815 | 83.2% | 3.2 | 46.6% | 84.1% | -4.88 | -4.06 | -4.42 | 73 |
| NO/2026-06-06 | 934 | 822 | 88.0% | 3.5 | 52.9% | 74.1% | 2.80 | 2.46 | 1.65 | 68 |
| NO/2026-06-07 | 1181 | 1017 | 86.1% | 4.9 | 42.3% | 73.8% | -6.22 | -5.36 | -5.86 | 91 |
| NO/2026-06-08 | 660 | 555 | 84.1% | 4.0 | 50.5% | 73.3% | 1.03 | 0.87 | 0.17 | 56 |
| NO/2026-06-09 | 221 | 180 | 81.4% | 4.6 | 46.7% | 65.9% | -7.75 | -6.31 | -5.60 | 20 |
| NO/2026-06-10 | 147 | 124 | 84.4% | 7.0 | 67.7% | 78.3% | 13.77 | 11.62 | 12.42 | 10 |

## Both-sides quoting (double fill of YES-join + NO-join)

- quote points: 7675  double fills: 5752 (74.9%) across 581 windows
- mean pair cost: 0.9903  mean locked net per pair: 0.0097  total locked net: 55.812
- **FULL both-sides P&L (drift-neutral): -3.15c per quote point** over 7675 points (outcomes: {'double': 5752, 'yes_only': 776, 'none': 502, 'no_only': 645}; total net -241.94); positive days 0/10: {'2026-06-01': -2.557, '2026-06-02': -3.29, '2026-06-03': -3.254, '2026-06-04': -3.892, '2026-06-05': -3.108, '2026-06-06': -2.101, '2026-06-07': -2.815, '2026-06-08': -2.721, '2026-06-09': -6.969, '2026-06-10': -3.637}

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
