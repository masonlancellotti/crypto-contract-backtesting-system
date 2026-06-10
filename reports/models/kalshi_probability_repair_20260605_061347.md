# Kalshi probability repair — KXBTC15M

> STAGED / report-only. Tests whether better-calibrated or market-shrunk probabilities honestly reduce the edge-policy calibration buffer. No promotion; no manifest change; live disabled.

- split (windows): {'n_windows': 298, 'train_windows': 149, 'calib_windows': 74, 'test_windows': 73, 'embargo_windows': 1}  gate_windows: 298  base_rate(TEST): 0.4364
- runtime state UNCHANGED after all work: **True** (preservation: C:\Users\mason\Downloads\polymarket-btc-five-mins\reports\models\kalshi_runtime_preservation_20260605_061110.json)

## Calibration comparison (held-out window ECE; lower=better)
- best source: **market_implied**  (full table: C:\Users\mason\Downloads\polymarket-btc-five-mins\reports\calibration\kalshi_calibration_compare_20260605_061147.md)
  - raw_model: ECE_window=0.0458 brier=0.0994 YES_overpred=-1.15c
  - identity: ECE_window=0.0458 brier=0.0994 YES_overpred=-1.15c
  - staged_platt: ECE_window=0.0533 brier=0.1058 YES_overpred=-4.24c
  - staged_isotonic: ECE_window=0.0755 brier=0.1060 YES_overpred=-3.45c
  - market_implied: ECE_window=0.0224 brier=0.0981 YES_overpred=-0.12c
  - current_promoted_calibrator: ECE_window=0.0956 brier=0.1131 YES_overpred=6.54c

## Market-shrink recommendation
- base=platt alpha=0.4 beats_market=True stable=True

## Executable backtest (held-out TEST; asks/fees/depth/gates)
  - raw_model: trades=71 windows=71 net_pnl=4.5180 hit_rate=0.6761 dd=-2.1600
  - staged_platt: trades=72 windows=72 net_pnl=5.2120 hit_rate=0.5833 dd=-2.8300
  - staged_isotonic: trades=70 windows=70 net_pnl=3.9650 hit_rate=0.6000 dd=-2.7900
  - market_implied: trades=0 windows=0 net_pnl=0.0000 hit_rate=None dd=0.0000
  - market_shrunk: trades=70 windows=70 net_pnl=0.8630 hit_rate=0.4571 dd=-2.5570
  - current_promoted_calibrator: trades=71 windows=71 net_pnl=-7.1700 hit_rate=0.2676 dd=-8.4200

## Candidate-cohort repair
- any source PASSES full edge policy on cohort: **True**  (detail: C:\Users\mason\Downloads\polymarket-btc-five-mins\reports\edge\kalshi_candidate_repair_audit_20260605_061347.md)
  - current_promoted_calibrator: +unc_adj=2/137 pass=1 med_final=-13.94c med_calib_buf=15.79c
  - raw_model: +unc_adj=16/137 pass=0 med_final=-6.34c med_calib_buf=6.03c
  - identity: +unc_adj=16/137 pass=0 med_final=-6.34c med_calib_buf=6.03c
  - staged_platt: +unc_adj=7/137 pass=0 med_final=-8.92c med_calib_buf=10.00c
  - staged_isotonic: +unc_adj=2/137 pass=0 med_final=-6.47c med_calib_buf=0.00c
  - market_implied: +unc_adj=0/137 pass=0 med_final=-4.74c med_calib_buf=0.00c
  - market_shrunk: +unc_adj=0/137 pass=0 med_final=-4.02c med_calib_buf=0.96c

## Staged artifacts (NON-PROMOTED; data/models/staged/ only)
- platt: {'calibrator_file': 'C:\\Users\\mason\\Downloads\\polymarket-btc-five-mins\\data\\models\\staged\\kalshi_repair_platt_20260605_061347.pkl', 'summary_file': 'C:\\Users\\mason\\Downloads\\polymarket-btc-five-mins\\data\\models\\staged\\kalshi_repair_platt_20260605_061347.json', 'staged': True, 'tradable_status': 'STAGED_NON_PROMOTED', 'method': 'platt'}
- market_shrink: {'artifact_file': 'C:\\Users\\mason\\Downloads\\polymarket-btc-five-mins\\data\\models\\staged\\kalshi_repair_market_shrink_20260605_061347.pkl', 'summary_file': 'C:\\Users\\mason\\Downloads\\polymarket-btc-five-mins\\data\\models\\staged\\kalshi_repair_market_shrink_20260605_061347.json', 'method': 'market_shrink', 'tradable_status': 'DIAGNOSTIC_ONLY', 'tradable_status_for_check': 'DIAGNOSTIC_ONLY'}

## Safety
- All artifacts STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY; runtime cannot auto-load them.
- Promoted manifest + artifacts + active pointers UNCHANGED: True.
- No paper/live enabled; no gates weakened; no buffers removed; live_submission_allowed=false.
