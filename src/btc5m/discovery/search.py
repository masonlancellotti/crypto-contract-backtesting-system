"""Stage 3 — strategy search over screened signals, scored after-cost and executable.

A trial = a non-parametric entry rule (feature, tail, side, threshold): trade `side` (YES/NO)
at the executable ask when the feature is in its upper/lower tail past `threshold`, hold to
settlement, net cents after the real Kalshi fee. Every trial is counted (the budget that
deflates the Sharpe). Trials are evaluated as full per-window return vectors (0 when flat) so
the gauntlet (DSR/PBO/CSCV) sees the strategy's actual P&L stream; per-trade stats are also
reported for the tradability read."""
from __future__ import annotations

import numpy as np

from . import metrics

TAILS = ("hi", "lo")
SIDES = ("YES", "NO")
HI_Q = (0.55, 0.65, 0.75, 0.85, 0.92)
LO_Q = (0.45, 0.35, 0.25, 0.15, 0.08)


def _net_vectors(panel, fee):
    """Per-observation after-cost net cents for taking YES vs NO at that window."""
    ny, nn = [], []
    for o in panel:
        ny.append(100.0 * (o.y - o.exec_yes) - fee.taker_fee(o.exec_yes, 1) * 100.0)
        nn.append(100.0 * ((1 - o.y) - o.exec_no) - fee.taker_fee(o.exec_no, 1) * 100.0)
    return np.array(ny), np.array(nn)


def _feature_col(panel, name):
    return np.array([(o.feats.get(name) if o.feats.get(name) is not None else np.nan)
                     for o in panel], dtype=float)


def generate_trials(panel, feature_names, fee, *, min_trades: int = 25,
                    min_trade_frac: float = 0.05) -> dict:
    """Build the trials × windows return matrix and per-trial metadata for `feature_names`."""
    n = len(panel)
    net_y, net_n = _net_vectors(panel, fee)
    cols, meta = [], []
    for name in feature_names:
        fv = _feature_col(panel, name)
        valid = ~np.isnan(fv)
        if valid.sum() < min_trades:
            continue
        qsrc = fv[valid]
        for tail in TAILS:
            qs = HI_Q if tail == "hi" else LO_Q
            for q in qs:
                thr = float(np.quantile(qsrc, q))
                trade = valid & ((fv >= thr) if tail == "hi" else (fv <= thr))
                if trade.sum() < min_trades or trade.sum() / n < min_trade_frac:
                    continue
                for side in SIDES:
                    base = net_y if side == "YES" else net_n
                    vec = np.where(trade, base, 0.0)
                    cols.append(vec)
                    meta.append({"feature": name, "tail": tail, "q": q, "thr": thr,
                                 "side": side, "n_trades": int(trade.sum()),
                                 "trade_idx": np.where(trade)[0]})
    if not cols:
        return {"matrix": np.zeros((n, 0)), "meta": [], "n_trials": 0,
                "net_yes": net_y, "net_no": net_n}
    M = np.column_stack(cols)
    return {"matrix": M, "meta": meta, "n_trials": len(meta),
            "net_yes": net_y, "net_no": net_n}


def trial_stats(trial: dict, M: np.ndarray, col: int, net_yes, net_no) -> dict:
    """Per-window-vector Sharpe (gauntlet unit) + per-TRADE after-cost stats (tradability)."""
    vec = M[:, col]
    sharpe = metrics.sharpe(vec.tolist())
    idx = trial["trade_idx"]
    base = net_yes if trial["side"] == "YES" else net_no
    per_trade = base[idx]
    return {**{k: v for k, v in trial.items() if k != "trade_idx"},
            "window_sharpe": sharpe,
            "per_window_mean_c": float(vec.mean()),
            "per_trade_mean_c": float(per_trade.mean()) if len(per_trade) else float("nan"),
            "per_trade_t": metrics.tstat(per_trade.tolist()),
            "win_rate": float((per_trade > 0).mean()) if len(per_trade) else float("nan")}


def rank_trials(res: dict) -> list[dict]:
    """All trials ranked by per-window-vector Sharpe (the gauntlet's selection unit)."""
    M, meta = res["matrix"], res["meta"]
    stats = [trial_stats(meta[j], M, j, res["net_yes"], res["net_no"]) for j in range(len(meta))]
    stats.sort(key=lambda s: (s["window_sharpe"] if s["window_sharpe"] == s["window_sharpe"]
                              else -9), reverse=True)
    return stats
