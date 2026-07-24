# Kalshi executable backtest — baseline comparison (KXBTC15M)

- gate_windows: 95 / backtest gate 60  (met=True)
- diagnostic_only / NON_TRADABLE: **True**
- model_schema_version: 1
- executable ask prices (NEVER midpoint); fees + depth + staleness modeled.
- RESEARCH EVIDENCE ONLY — not a profitability claim; no orders; live disabled.

- split: {'train_rows': 264, 'val_rows': 112}

### no_trade
- net_pnl: 0.0 (floor)

### market_implied
- trades: 0  windows_touched: 0  candidate_rows: 112
- net_pnl: 0  gross_pnl: 0  realized_pnl_per_contract: None
- hit_rate: None  avg_net_edge: None  avg_entry: None  avg_fee: None
- max_drawdown: 0.0  profit_factor: None
- pnl_by_side: {}
- rejected_rows_by_reason: {'EDGE_BELOW_MIN': 97, 'STALE_UNDERLYING': 10, 'TOO_CLOSE_TO_CLOSE': 5}
- calibration: {'brier': 0.16180630503950424, 'log_loss': 0.45645601022675014, 'ece': 0.09430588050809866}

### distance_time_vol
- trades: 27  windows_touched: 27  candidate_rows: 112
- net_pnl: -2.058  gross_pnl: -1.588  realized_pnl_per_contract: -0.0762
- hit_rate: 0.4815  avg_net_edge: 0.0732  avg_entry: 0.5403  avg_fee: 0.0174
- max_drawdown: -2.866  profit_factor: 0.6313
- pnl_by_side: {'YES': {'trades': 18, 'net_pnl': -0.778, 'wins': 9}, 'NO': {'trades': 9, 'net_pnl': -1.28, 'wins': 4}}
- rejected_rows_by_reason: {'STALE_UNDERLYING': 9, 'EDGE_BELOW_MIN': 17}
- calibration: {'brier': 0.1767828394233347, 'log_loss': 0.5108546737671511, 'ece': 0.1170918716614956}
- walk_forward_stability: [{'fold': 1, 'trades': 22, 'net_pnl': 2.121, 'hit_rate': 0.5454545454545454}, {'fold': 2, 'trades': 23, 'net_pnl': 0.928, 'hit_rate': 0.7391304347826086}, {'fold': 3, 'trades': 22, 'net_pnl': -3.248, 'hit_rate': 0.45454545454545453}]

### microstructure
- trades: 26  windows_touched: 26  candidate_rows: 112
- net_pnl: -3.613  gross_pnl: -3.143  realized_pnl_per_contract: -0.1390
- hit_rate: 0.4615  avg_net_edge: 0.0760  avg_entry: 0.5824  avg_fee: 0.0181
- max_drawdown: -5.093  profit_factor: 0.4766
- pnl_by_side: {'YES': {'trades': 12, 'net_pnl': -1.734, 'wins': 6}, 'NO': {'trades': 14, 'net_pnl': -1.879, 'wins': 6}}
- rejected_rows_by_reason: {'STALE_UNDERLYING': 9, 'EDGE_BELOW_MIN': 16, 'TOO_CLOSE_TO_CLOSE': 1}
- calibration: {'brier': 0.16905735774181566, 'log_loss': 0.48411624491039706, 'ece': 0.12041168102290464}
- walk_forward_stability: [{'fold': 1, 'trades': 22, 'net_pnl': 2.121, 'hit_rate': 0.5454545454545454}, {'fold': 2, 'trades': 23, 'net_pnl': 1.404, 'hit_rate': 0.6956521739130435}, {'fold': 3, 'trades': 21, 'net_pnl': -2.87, 'hit_rate': 0.5238095238095238}]

## Note
- Backtest EVIDENCE only. Do not select a production policy by max in-sample P&L;
  require later paper validation. Diagnostic reports are NON-TRADABLE.
