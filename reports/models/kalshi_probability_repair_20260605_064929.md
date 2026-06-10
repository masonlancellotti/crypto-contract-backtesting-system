# Kalshi probability repair — KXBTC15M

> STAGED / report-only. Tests whether better-calibrated or market-shrunk probabilities honestly reduce the edge-policy calibration buffer. No promotion; no manifest change; live disabled.

- split (windows): {'n_windows': 301, 'train_windows': 150, 'calib_windows': 75, 'test_windows': 74, 'embargo_windows': 1}  gate_windows: 301  base_rate(TEST): 0.4294
- runtime state UNCHANGED after all work: **True** (preservation: C:\Users\mason\Downloads\polymarket-btc-five-mins\reports\models\kalshi_runtime_preservation_20260605_064651.json)

## Calibration comparison (held-out window ECE; lower=better)
- best source: **market_implied**  (full table: C:\Users\mason\Downloads\polymarket-btc-five-mins\reports\calibration\kalshi_calibration_compare_20260605_064727.md)
  - raw_model: ECE_window=0.0500 brier=0.1068 YES_overpred=-0.56c
  - identity: ECE_window=0.0500 brier=0.1068 YES_overpred=-0.56c
  - staged_platt: ECE_window=0.0500 brier=0.1108 YES_overpred=-2.45c
  - staged_isotonic: ECE_window=0.0669 brier=0.1109 YES_overpred=-1.85c
  - market_implied: ECE_window=0.0301 brier=0.1040 YES_overpred=0.93c
  - current_promoted_calibrator: ECE_window=0.1040 brier=0.1216 YES_overpred=7.77c

## Market-shrink recommendation
- base=platt alpha=0.5 beats_market=True stable=True

## Executable backtest (held-out TEST; asks/fees/depth/gates)
  - raw_model: trades=73 windows=73 net_pnl=4.3580 hit_rate=0.6575 dd=-2.1100
  - staged_platt: trades=73 windows=73 net_pnl=6.1270 hit_rate=0.6164 dd=-2.6700
  - staged_isotonic: trades=71 windows=71 net_pnl=4.3580 hit_rate=0.6056 dd=-2.8100
  - market_implied: trades=0 windows=0 net_pnl=0.0000 hit_rate=None dd=0.0000
  - market_shrunk: trades=73 windows=73 net_pnl=1.0150 hit_rate=0.4658 dd=-2.2660
  - current_promoted_calibrator: trades=72 windows=72 net_pnl=-7.4500 hit_rate=0.2778 dd=-8.0700

## Candidate-cohort repair
- any REPAIRED source passes full edge policy: **False** (best repaired final Nonec; promoted-reference passes 0 row(s))  (detail: C:\Users\mason\Downloads\polymarket-btc-five-mins\reports\edge\kalshi_candidate_repair_audit_20260605_064928.md)
  - current_promoted_calibrator: +unc_adj=0/0 pass=0 med_final=Nonec med_calib_buf=Nonec
  - raw_model: +unc_adj=0/0 pass=0 med_final=Nonec med_calib_buf=Nonec
  - identity: +unc_adj=0/0 pass=0 med_final=Nonec med_calib_buf=Nonec
  - staged_platt: +unc_adj=0/0 pass=0 med_final=Nonec med_calib_buf=Nonec
  - staged_isotonic: +unc_adj=0/0 pass=0 med_final=Nonec med_calib_buf=Nonec
  - market_implied: +unc_adj=0/0 pass=0 med_final=Nonec med_calib_buf=Nonec
  - market_shrunk: +unc_adj=0/0 pass=0 med_final=Nonec med_calib_buf=Nonec

## Staged artifacts (NON-PROMOTED; data/models/staged/ only)
- platt: {'calibrator_file': 'C:\\Users\\mason\\Downloads\\polymarket-btc-five-mins\\data\\models\\staged\\kalshi_repair_platt_20260605_064929.pkl', 'summary_file': 'C:\\Users\\mason\\Downloads\\polymarket-btc-five-mins\\data\\models\\staged\\kalshi_repair_platt_20260605_064929.json', 'staged': True, 'tradable_status': 'STAGED_NON_PROMOTED', 'method': 'platt'}
- market_shrink: {'artifact_file': 'C:\\Users\\mason\\Downloads\\polymarket-btc-five-mins\\data\\models\\staged\\kalshi_repair_market_shrink_20260605_064929.pkl', 'summary_file': 'C:\\Users\\mason\\Downloads\\polymarket-btc-five-mins\\data\\models\\staged\\kalshi_repair_market_shrink_20260605_064929.json', 'method': 'market_shrink', 'tradable_status': 'DIAGNOSTIC_ONLY', 'tradable_status_for_check': 'DIAGNOSTIC_ONLY'}

## Safety
- All artifacts STAGED_NON_PROMOTED / DIAGNOSTIC_ONLY; runtime cannot auto-load them.
- Promoted manifest + artifacts + active pointers UNCHANGED: True.
- No paper/live enabled; no gates weakened; no buffers removed; live_submission_allowed=false.
