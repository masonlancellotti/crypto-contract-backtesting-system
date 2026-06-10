# Kalshi maker-entry feasibility study — KXBTC15M (fill model: prints-through)

> READ-ONLY research. REAL trade prints, CERTAIN fills only: a resting bid counts as filled when the tape traded strictly THROUGH the level (queue-position-free). Conservative on fill count, but fills/outcomes come from actual flow. No orders, no paper, no promotion; live disabled.

- windows: 787  decision points: 9905  (one per market-minute; sides×modes per point)
- cost to cross today: spread mean/median/p90 = 0.009/0.010/0.010  taker fee mean = 0.0155
- maker fee rate: 0.07 (ASSUMED); taker rate 0.07 (ASSUMED). Fee-sensitivity table below charges makers the full taker schedule.

## Cohorts (side/mode/rest-horizon)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/60 | 9905 | 7546 | 76.2% | 3.0 | 41.8% | 58.5% | -4.45 | -3.39 | -3.20 | 784 |
| YES/join/180 | 9905 | 8209 | 82.9% | 3.6 | 41.4% | 66.6% | -4.42 | -3.66 | -3.20 | 784 |
| YES/join/300 | 9905 | 8355 | 84.4% | 3.8 | 41.4% | 69.4% | -4.49 | -3.78 | -3.20 | 784 |
| YES/join/close | 9905 | 8457 | 85.4% | 3.9 | 41.3% | 71.5% | -4.50 | -3.84 | -3.20 | 784 |
| YES/improve/60 | 836 | 741 | 88.6% | 0.6 | 47.0% | 53.7% | -5.43 | -4.81 | -6.10 | 459 |
| YES/improve/180 | 836 | 777 | 92.9% | 0.6 | 46.7% | 61.0% | -5.56 | -5.17 | -6.10 | 470 |
| YES/improve/300 | 836 | 784 | 93.8% | 0.6 | 46.8% | 61.5% | -5.44 | -5.10 | -6.10 | 472 |
| YES/improve/close | 836 | 793 | 94.9% | 0.7 | 46.5% | 69.8% | -5.64 | -5.35 | -6.10 | 472 |
| NO/join/60 | 9905 | 7368 | 74.4% | 3.0 | 50.2% | 66.0% | -1.93 | -1.44 | -0.81 | 784 |
| NO/join/180 | 9905 | 8031 | 81.1% | 3.6 | 49.9% | 73.0% | -1.98 | -1.61 | -0.81 | 784 |
| NO/join/300 | 9905 | 8196 | 82.7% | 3.8 | 49.9% | 75.3% | -1.98 | -1.64 | -0.81 | 784 |
| NO/join/close | 9905 | 8319 | 84.0% | 4.0 | 49.7% | 78.2% | -2.10 | -1.76 | -0.81 | 784 |
| NO/improve/60 | 836 | 756 | 90.4% | 0.5 | 50.3% | 71.2% | -0.04 | -0.04 | -0.20 | 459 |
| NO/improve/180 | 836 | 784 | 93.8% | 0.6 | 50.4% | 80.8% | -0.01 | -0.01 | -0.20 | 471 |
| NO/improve/300 | 836 | 790 | 94.5% | 0.6 | 50.1% | 89.1% | -0.25 | -0.24 | -0.20 | 471 |
| NO/improve/close | 836 | 798 | 95.5% | 0.6 | 50.0% | 100.0% | -0.35 | -0.33 | -0.20 | 473 |

## Fee sensitivity (maker pays FULL taker schedule)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/join/close | 9905 | 8457 | 85.4% | 3.9 | 41.3% | 71.5% | -4.50 | -3.84 | -3.20 | 784 |
| NO/join/close | 9905 | 8319 | 84.0% | 4.0 | 49.7% | 78.2% | -2.10 | -1.76 | -0.81 | 784 |

## By limit-price bucket (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/[0c,10c) | 1817 | 1403 | 77.2% | 8.7 | 4.1% | 3.4% | -1.42 | -1.09 | -1.01 | 400 |
| YES/[10c,20c) | 913 | 898 | 98.4% | 4.6 | 12.0% | 100.0% | -3.41 | -3.35 | -3.19 | 383 |
| YES/[20c,30c) | 899 | 862 | 95.9% | 3.2 | 20.8% | 64.9% | -5.64 | -5.41 | -5.19 | 399 |
| YES/[30c,40c) | 848 | 817 | 96.3% | 2.6 | 31.2% | 100.0% | -5.37 | -5.17 | -4.05 | 409 |
| YES/[40c,50c) | 883 | 846 | 95.8% | 2.8 | 39.0% | 100.0% | -7.47 | -7.16 | -6.16 | 438 |
| YES/[50c,60c) | 917 | 862 | 94.0% | 2.8 | 46.5% | 100.0% | -9.70 | -9.12 | -7.84 | 425 |
| YES/[60c,70c) | 789 | 732 | 92.8% | 2.6 | 59.4% | 100.0% | -7.19 | -6.67 | -5.35 | 355 |
| YES/[70c,80c) | 694 | 629 | 90.6% | 2.9 | 69.8% | 100.0% | -6.70 | -6.08 | -5.00 | 318 |
| YES/[80c,90c) | 746 | 645 | 86.5% | 3.8 | 85.1% | 100.0% | -0.89 | -0.77 | 0.12 | 286 |
| YES/[90c,100c) | 1399 | 763 | 54.5% | 5.5 | 97.2% | 100.0% | 1.32 | 0.72 | 0.98 | 275 |
| NO/[0c,10c) | 1412 | 1060 | 75.1% | 9.1 | 1.4% | 2.0% | -4.18 | -3.14 | -3.35 | 312 |
| NO/[10c,20c) | 743 | 732 | 98.5% | 4.1 | 11.7% | 100.0% | -3.71 | -3.65 | -3.76 | 315 |
| NO/[20c,30c) | 696 | 662 | 95.1% | 3.3 | 24.0% | 100.0% | -2.41 | -2.29 | 0.09 | 334 |
| NO/[30c,40c) | 797 | 765 | 96.0% | 2.7 | 35.3% | 100.0% | -1.12 | -1.08 | 0.29 | 368 |
| NO/[40c,50c) | 909 | 856 | 94.2% | 2.7 | 47.4% | 100.0% | 0.82 | 0.77 | 2.61 | 423 |
| NO/[50c,60c) | 890 | 819 | 92.0% | 3.2 | 55.6% | 100.0% | -0.79 | -0.73 | 1.31 | 422 |
| NO/[60c,70c) | 846 | 769 | 90.9% | 3.3 | 62.8% | 100.0% | -3.53 | -3.21 | -1.32 | 388 |
| NO/[70c,80c) | 890 | 806 | 90.6% | 3.0 | 74.6% | 100.0% | -1.95 | -1.77 | -0.69 | 374 |
| NO/[80c,90c) | 921 | 816 | 88.6% | 3.3 | 85.2% | 100.0% | -0.80 | -0.71 | -0.13 | 361 |
| NO/[90c,100c) | 1801 | 1034 | 57.4% | 6.9 | 93.1% | 100.0% | -2.89 | -1.66 | -1.39 | 366 |

## By seconds-to-close (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/180-420s | 3116 | 2752 | 88.3% | 4.1 | 40.6% | 86.5% | -2.64 | -2.33 | -1.70 | 770 |
| YES/420-660s | 3010 | 2851 | 94.7% | 4.3 | 43.1% | 97.5% | -4.79 | -4.54 | -3.91 | 768 |
| YES/<180s | 1979 | 1137 | 57.5% | 3.2 | 38.7% | 57.5% | -2.90 | -1.67 | -0.92 | 576 |
| YES/>=660s | 1800 | 1717 | 95.4% | 3.2 | 41.4% | 97.6% | -8.04 | -7.67 | -7.11 | 603 |
| NO/180-420s | 3116 | 2679 | 86.0% | 4.4 | 48.5% | 88.3% | -3.40 | -2.92 | -1.90 | 769 |
| NO/420-660s | 3010 | 2793 | 92.8% | 4.3 | 50.5% | 99.5% | -1.91 | -1.77 | -0.51 | 768 |
| NO/<180s | 1979 | 1154 | 58.3% | 3.0 | 45.3% | 64.5% | -3.88 | -2.26 | -2.01 | 568 |
| NO/>=660s | 1800 | 1693 | 94.1% | 3.5 | 53.2% | 100.0% | 0.85 | 0.80 | 1.90 | 601 |

## By UTC day (join, rest-to-close)

| cohort | eligible | fills | fill_rate | med_s_to_fill | win|fill | win|no-fill | maker EV c/fill | maker EV c/decision | taker EV c/decision | windows |
|---|---|---|---|---|---|---|---|---|---|---|
| YES/2026-06-01 | 315 | 275 | 87.3% | 6.5 | 38.2% | 67.5% | -10.90 | -9.51 | -8.91 | 23 |
| YES/2026-06-02 | 1270 | 1092 | 86.0% | 3.8 | 34.5% | 61.8% | -8.31 | -7.15 | -6.90 | 90 |
| YES/2026-06-03 | 1232 | 1049 | 85.1% | 3.9 | 37.7% | 70.5% | -8.59 | -7.32 | -6.76 | 87 |
| YES/2026-06-04 | 839 | 665 | 79.3% | 3.7 | 36.7% | 70.7% | -6.52 | -5.17 | -3.90 | 73 |
| YES/2026-06-05 | 979 | 849 | 86.7% | 3.2 | 43.8% | 68.5% | -0.49 | -0.43 | 0.50 | 73 |
| YES/2026-06-06 | 1044 | 917 | 87.8% | 3.4 | 41.9% | 78.7% | -5.91 | -5.19 | -4.83 | 76 |
| YES/2026-06-07 | 1231 | 1056 | 85.8% | 4.4 | 51.6% | 77.1% | 3.91 | 3.36 | 3.94 | 95 |
| YES/2026-06-08 | 1128 | 947 | 84.0% | 4.2 | 40.2% | 72.9% | -5.06 | -4.25 | -3.60 | 96 |
| YES/2026-06-09 | 1039 | 890 | 85.7% | 3.7 | 46.3% | 75.8% | -1.11 | -0.95 | 0.36 | 95 |
| YES/2026-06-10 | 828 | 717 | 86.6% | 3.9 | 39.2% | 69.4% | -7.15 | -6.19 | -6.20 | 76 |
| NO/2026-06-01 | 315 | 272 | 86.3% | 4.0 | 54.0% | 83.7% | 4.75 | 4.10 | 4.60 | 23 |
| NO/2026-06-02 | 1270 | 1033 | 81.3% | 4.1 | 56.2% | 85.2% | 1.42 | 1.16 | 2.87 | 90 |
| NO/2026-06-03 | 1232 | 1019 | 82.7% | 4.1 | 53.0% | 78.9% | 1.62 | 1.34 | 2.59 | 87 |
| NO/2026-06-04 | 839 | 652 | 77.7% | 4.7 | 50.3% | 77.0% | -1.43 | -1.11 | 0.14 | 72 |
| NO/2026-06-05 | 979 | 815 | 83.2% | 3.2 | 46.6% | 84.1% | -6.49 | -5.40 | -4.42 | 73 |
| NO/2026-06-06 | 1044 | 915 | 87.6% | 3.6 | 50.9% | 72.9% | 0.07 | 0.06 | 0.73 | 76 |
| NO/2026-06-07 | 1231 | 1066 | 86.6% | 4.7 | 40.3% | 73.3% | -10.18 | -8.82 | -8.03 | 95 |
| NO/2026-06-08 | 1128 | 944 | 83.7% | 3.8 | 50.4% | 75.5% | -1.07 | -0.90 | -0.21 | 96 |
| NO/2026-06-09 | 1039 | 884 | 85.1% | 3.8 | 44.5% | 78.1% | -5.89 | -5.01 | -4.34 | 96 |
| NO/2026-06-10 | 828 | 719 | 86.8% | 3.8 | 54.5% | 71.6% | 1.87 | 1.63 | 2.14 | 76 |

## Both-sides quoting (double fill of YES-join + NO-join)

- quote points: 9905  double fills: 7513 (75.9%) across 783 windows
- mean pair cost: 0.9902  mean locked net per pair: -0.0228  total locked net: -171.393
- **FULL both-sides P&L (drift-neutral): -5.60c per quote point** over 9905 points (outcomes: {'double': 7513, 'yes_only': 944, 'none': 642, 'no_only': 806}; total net -555.06); positive days 0/10: {'2026-06-01': -5.409, '2026-06-02': -5.989, '2026-06-03': -5.982, '2026-06-04': -6.277, '2026-06-05': -5.828, '2026-06-06': -5.128, '2026-06-07': -5.46, '2026-06-08': -5.15, '2026-06-09': -5.963, '2026-06-10': -4.561}

## Verdict

- sides with POSITIVE conservative maker EV: []
- sides where maker(lower bound) beats taker: []
- The conservative lower bound on maker EV is negative or under-sampled: trade-through fills are adversely selected and the spread saved did not cover the adverse selection measured this way. This does NOT prove maker entries lose (fills are undercounted and the counted ones are the worst subset) — resolving it needs trade prints or sub-second WS book data.

## Honest caveats

- Fill model sees only quote crossings at the recorder cadence (~1-4s): real passive fills from sells into the bid are invisible (undercount), and counted fills are the most adverse subset (price traded through). Both biases make maker EV look WORSE than reality.
- No queue model: assumes our 1 contract is at the front at the limit. At Kalshi's typical depth this is optimistic per-fill but does not change the conditional-outcome estimate.
- Maker fee assumed; verify the current Kalshi fee schedule before any live consideration.
- One snapshot cadence; cancel/replace latency not modeled. Next iteration needs trade prints (public /trades) or authenticated WS book deltas.

## Safety
- READ-ONLY study; no orders, no paper fills, no promotion, no manifest changes; live_submission_allowed=false.
