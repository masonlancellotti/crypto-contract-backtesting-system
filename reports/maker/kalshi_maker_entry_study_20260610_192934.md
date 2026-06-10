# Kalshi maker-entry feasibility study — KXBTC15M (fill model: prints-front)

> READ-ONLY research. REAL trade prints, FRONT-OF-QUEUE assumption: a resting bid counts as filled when the tape traded AT or through the level. OPTIMISTIC upper bound — real queue position would forfeit some at-level fills. No orders, no paper, no promotion; live disabled.

- windows: 787  decision points: 9905  (one per market-minute; sides×modes per point)
- cost to cross today: spread mean/median/p90 = 0.009/0.010/0.010  taker fee mean = 0.0155
- maker fee rate: 0.07 (ASSUMED); taker rate 0.07 (ASSUMED). Fee-sensitivity table below charges makers the full taker schedule.

## Cohorts (side/mode/rest-horizon)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/60 | 9905 | 9413 | 95.0% | 0.4 | 44.7% | 66.3% | -2.76 | -2.62 | -3.20 | 786 |
| YES/join/180 | 9905 | 9567 | 96.6% | 0.4 | 44.6% | 79.3% | -2.81 | -2.71 | -3.20 | 786 |
| YES/join/300 | 9905 | 9613 | 97.1% | 0.4 | 44.5% | 86.3% | -2.84 | -2.76 | -3.20 | 786 |
| YES/join/close | 9905 | 9647 | 97.4% | 0.4 | 44.4% | 94.2% | -2.90 | -2.83 | -3.20 | 786 |
| YES/improve/60 | 836 | 779 | 93.2% | 0.4 | 47.5% | 50.9% | -5.06 | -4.72 | -6.10 | 469 |
| YES/improve/180 | 836 | 795 | 95.1% | 0.4 | 47.4% | 53.7% | -5.09 | -4.84 | -6.10 | 477 |
| YES/improve/300 | 836 | 798 | 95.5% | 0.4 | 47.5% | 52.6% | -5.03 | -4.80 | -6.10 | 478 |
| YES/improve/close | 836 | 806 | 96.4% | 0.4 | 47.4% | 56.7% | -5.07 | -4.89 | -6.10 | 479 |
| NO/join/60 | 9905 | 9361 | 94.5% | 0.4 | 53.0% | 75.0% | -0.46 | -0.44 | -0.81 | 786 |
| NO/join/180 | 9905 | 9515 | 96.1% | 0.4 | 53.0% | 84.4% | -0.45 | -0.43 | -0.81 | 786 |
| NO/join/300 | 9905 | 9562 | 96.5% | 0.4 | 53.0% | 89.5% | -0.46 | -0.45 | -0.81 | 786 |
| NO/join/close | 9905 | 9610 | 97.0% | 0.4 | 52.9% | 100.0% | -0.57 | -0.56 | -0.81 | 786 |
| NO/improve/60 | 836 | 785 | 93.9% | 0.4 | 50.8% | 74.5% | 0.40 | 0.37 | -0.20 | 471 |
| NO/improve/180 | 836 | 798 | 95.5% | 0.4 | 50.9% | 81.6% | 0.34 | 0.33 | -0.20 | 477 |
| NO/improve/300 | 836 | 801 | 95.8% | 0.4 | 50.8% | 85.7% | 0.29 | 0.27 | -0.20 | 477 |
| NO/improve/close | 836 | 809 | 96.8% | 0.4 | 50.7% | 100.0% | 0.19 | 0.18 | -0.20 | 479 |

## Fee sensitivity (maker pays FULL taker schedule)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/close | 9905 | 9647 | 97.4% | 0.4 | 44.4% | 94.2% | -2.90 | -2.83 | -3.20 | 786 |
| NO/join/close | 9905 | 9610 | 97.0% | 0.4 | 52.9% | 100.0% | -0.57 | -0.56 | -0.81 | 786 |

## By limit-price bucket (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/[0c,10c) | 1817 | 1809 | 99.6% | 0.6 | 3.6% | 75.0% | -0.95 | -0.95 | -1.01 | 412 |
| YES/[10c,20c) | 913 | 906 | 99.2% | 0.3 | 12.8% | 100.0% | -2.65 | -2.63 | -3.19 | 387 |
| YES/[20c,30c) | 899 | 881 | 98.0% | 0.3 | 22.5% | 27.8% | -3.92 | -3.84 | -5.19 | 408 |
| YES/[30c,40c) | 848 | 833 | 98.2% | 0.4 | 32.5% | 100.0% | -4.03 | -3.95 | -4.05 | 417 |
| YES/[40c,50c) | 883 | 871 | 98.6% | 0.4 | 40.8% | 100.0% | -5.73 | -5.65 | -6.16 | 451 |
| YES/[50c,60c) | 917 | 897 | 97.8% | 0.4 | 48.6% | 100.0% | -7.64 | -7.47 | -7.84 | 440 |
| YES/[60c,70c) | 789 | 766 | 97.1% | 0.3 | 61.2% | 100.0% | -5.39 | -5.23 | -5.35 | 372 |
| YES/[70c,80c) | 694 | 674 | 97.1% | 0.3 | 71.8% | 100.0% | -4.65 | -4.51 | -5.00 | 336 |
| YES/[80c,90c) | 746 | 721 | 96.6% | 0.3 | 86.7% | 100.0% | 0.69 | 0.67 | 0.12 | 310 |
| YES/[90c,100c) | 1399 | 1289 | 92.1% | 0.6 | 98.4% | 100.0% | 1.20 | 1.10 | 0.98 | 325 |
| NO/[0c,10c) | 1412 | 1409 | 99.8% | 0.6 | 1.3% | 100.0% | -3.19 | -3.18 | -3.35 | 332 |
| NO/[10c,20c) | 743 | 740 | 99.6% | 0.3 | 12.7% | 100.0% | -2.75 | -2.74 | -3.76 | 318 |
| NO/[20c,30c) | 696 | 680 | 97.7% | 0.3 | 26.0% | 100.0% | -0.41 | -0.41 | 0.09 | 341 |
| NO/[30c,40c) | 797 | 788 | 98.9% | 0.3 | 37.2% | 100.0% | 0.76 | 0.75 | 0.29 | 380 |
| NO/[40c,50c) | 909 | 893 | 98.2% | 0.4 | 49.6% | 100.0% | 2.99 | 2.94 | 2.61 | 437 |
| NO/[50c,60c) | 890 | 859 | 96.5% | 0.4 | 57.6% | 100.0% | 1.24 | 1.20 | 1.31 | 440 |
| NO/[60c,70c) | 846 | 818 | 96.7% | 0.3 | 65.0% | 100.0% | -1.34 | -1.29 | -1.32 | 407 |
| NO/[70c,80c) | 890 | 866 | 97.3% | 0.3 | 76.3% | 100.0% | -0.22 | -0.21 | -0.69 | 399 |
| NO/[80c,90c) | 921 | 897 | 97.4% | 0.3 | 86.5% | 100.0% | 0.51 | 0.49 | -0.13 | 384 |
| NO/[90c,100c) | 1801 | 1660 | 92.2% | 0.6 | 95.7% | 100.0% | -1.34 | -1.23 | -1.39 | 404 |

## By seconds-to-close (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/180-420s | 3116 | 3040 | 97.6% | 0.4 | 44.7% | 94.7% | -1.44 | -1.40 | -1.70 | 782 |
| YES/420-660s | 3010 | 2956 | 98.2% | 0.4 | 45.1% | 92.6% | -3.53 | -3.47 | -3.91 | 769 |
| YES/<180s | 1979 | 1875 | 94.7% | 0.5 | 44.0% | 95.2% | -1.00 | -0.95 | -0.92 | 772 |
| YES/>=660s | 1800 | 1776 | 98.7% | 0.4 | 43.4% | 91.7% | -6.37 | -6.28 | -7.11 | 610 |
| NO/180-420s | 3116 | 3042 | 97.6% | 0.4 | 52.9% | 100.0% | -1.84 | -1.80 | -1.90 | 783 |
| NO/420-660s | 3010 | 2947 | 97.9% | 0.4 | 53.1% | 100.0% | -0.18 | -0.17 | -0.51 | 771 |
| NO/<180s | 1979 | 1853 | 93.6% | 0.5 | 50.1% | 100.0% | -2.04 | -1.91 | -2.01 | 767 |
| NO/>=660s | 1800 | 1768 | 98.2% | 0.4 | 55.2% | 100.0% | 2.48 | 2.44 | 1.90 | 610 |

## By UTC day (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/2026-06-01 | 315 | 309 | 98.1% | 0.6 | 40.8% | 100.0% | -8.31 | -8.15 | -8.91 | 23 |
| YES/2026-06-02 | 1270 | 1241 | 97.7% | 0.4 | 36.9% | 100.0% | -6.57 | -6.42 | -6.90 | 90 |
| YES/2026-06-03 | 1232 | 1202 | 97.6% | 0.4 | 41.2% | 96.7% | -6.35 | -6.20 | -6.76 | 87 |
| YES/2026-06-04 | 839 | 802 | 95.6% | 0.5 | 41.1% | 100.0% | -4.61 | -4.40 | -3.90 | 74 |
| YES/2026-06-05 | 979 | 962 | 98.3% | 0.4 | 46.2% | 100.0% | 0.80 | 0.79 | 0.50 | 73 |
| YES/2026-06-06 | 1044 | 1016 | 97.3% | 0.4 | 45.0% | 96.4% | -4.30 | -4.19 | -4.83 | 76 |
| YES/2026-06-07 | 1231 | 1195 | 97.1% | 0.3 | 55.0% | 63.9% | 4.98 | 4.84 | 3.94 | 95 |
| YES/2026-06-08 | 1128 | 1112 | 98.6% | 0.4 | 44.7% | 100.0% | -3.26 | -3.21 | -3.60 | 96 |
| YES/2026-06-09 | 1039 | 998 | 96.1% | 0.4 | 48.5% | 100.0% | 0.04 | 0.04 | 0.36 | 96 |
| YES/2026-06-10 | 828 | 810 | 97.8% | 0.4 | 42.0% | 100.0% | -5.82 | -5.69 | -6.20 | 76 |
| NO/2026-06-01 | 315 | 305 | 96.8% | 0.5 | 56.7% | 100.0% | 5.08 | 4.92 | 4.60 | 23 |
| NO/2026-06-02 | 1270 | 1228 | 96.7% | 0.4 | 60.3% | 100.0% | 3.24 | 3.13 | 2.87 | 90 |
| NO/2026-06-03 | 1232 | 1183 | 96.0% | 0.5 | 55.7% | 100.0% | 2.97 | 2.85 | 2.59 | 87 |
| NO/2026-06-04 | 839 | 810 | 96.5% | 0.5 | 54.7% | 100.0% | 0.38 | 0.37 | 0.14 | 74 |
| NO/2026-06-05 | 979 | 948 | 96.8% | 0.4 | 51.4% | 100.0% | -4.46 | -4.31 | -4.42 | 73 |
| NO/2026-06-06 | 1044 | 1019 | 97.6% | 0.4 | 52.5% | 100.0% | 1.16 | 1.13 | 0.73 | 76 |
| NO/2026-06-07 | 1231 | 1193 | 96.9% | 0.4 | 43.0% | 100.0% | -8.19 | -7.94 | -8.03 | 95 |
| NO/2026-06-08 | 1128 | 1102 | 97.7% | 0.3 | 53.4% | 100.0% | 0.25 | 0.24 | -0.21 | 96 |
| NO/2026-06-09 | 1039 | 1007 | 96.9% | 0.3 | 47.9% | 100.0% | -4.36 | -4.22 | -4.34 | 96 |
| NO/2026-06-10 | 828 | 815 | 98.4% | 0.4 | 56.1% | 100.0% | 2.54 | 2.50 | 2.14 | 76 |

## Both-sides quoting (double fill of YES-join + NO-join)

- quote points: 9905  double fills: 9367 (94.6%) across 786 windows
- mean pair cost: 0.9911  mean locked net per pair: -0.0221  total locked net: -207.455
- **FULL both-sides P&L (drift-neutral): -3.38c per quote point** over 9905 points (outcomes: {'double': 9367, 'yes_only': 280, 'no_only': 243, 'none': 15}; total net -335.02); positive days 0/10: {'2026-06-01': -3.23, '2026-06-02': -3.285, '2026-06-03': -3.345, '2026-06-04': -4.038, '2026-06-05': -3.524, '2026-06-06': -3.059, '2026-06-07': -3.105, '2026-06-08': -2.969, '2026-06-09': -4.186, '2026-06-10': -3.189}

## Verdict

- sides with POSITIVE conservative maker EV: []
- sides where maker(lower bound) beats taker: ['YES', 'NO']
- The conservative lower bound on maker EV is negative or under-sampled: trade-through fills are adversely selected and the spread saved did not cover the adverse selection measured this way. This does NOT prove maker entries lose (fills are undercounted and the counted ones are the worst subset) — resolving it needs trade prints or sub-second WS book data.

## Honest caveats

- Fill model sees only quote crossings at the recorder cadence (~1-4s): real passive fills from sells into the bid are invisible (undercount), and counted fills are the most adverse subset (price traded through). Both biases make maker EV look WORSE than reality.
- No queue model: assumes our 1 contract is at the front at the limit. At Kalshi's typical depth this is optimistic per-fill but does not change the conditional-outcome estimate.
- Maker fee assumed; verify the current Kalshi fee schedule before any live consideration.
- One snapshot cadence; cancel/replace latency not modeled. Next iteration needs trade prints (public /trades) or authenticated WS book deltas.

## Safety
- READ-ONLY study; no orders, no paper fills, no promotion, no manifest changes; live_submission_allowed=false.
