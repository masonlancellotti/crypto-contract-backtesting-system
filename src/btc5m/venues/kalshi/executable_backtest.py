"""Executable Kalshi backtest engine (RESEARCH EVIDENCE ONLY — never trades).

Simulates the real decision at each eligible feature row: model P(YES) → executable
YES/NO **ask** (never midpoint) → fees → depth → staleness/source/spread/window
gates → trade only if net edge exceeds the threshold → settle against the OFFICIAL
binary label → P&L. One position per window by default. Evaluates on HELD-OUT
validation windows (purged/embargoed); baselines are re-fit on train and evaluated
on val (leakage-safe). Uncalibrated/diagnostic inputs ⇒ the report is stamped
NON_TRADABLE / diagnostic. No order is ever submitted; no PAPER_CANDIDATE.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ...models import pure_ml
from .calibrate import Calibrator, load_calibrator
from .feature_schema import (
    DISTANCE_TIME_VOL_FEATURES, MICROSTRUCTURE_FEATURES, MODEL_SCHEMA_VERSION, feature_vector,
)
from .fees import KalshiFeeModel
from .model_artifacts import is_tradable, load_artifact
from .model_dataset import build_model_dataset
from .splits import split_indices, walk_forward_indices


@dataclass
class BacktestParams:
    size: float = 1.0
    min_net_edge_cents: float = 2.0
    max_book_age_ms: int = 1000
    max_underlying_age_ms: int = 2000
    min_seconds_to_close: int = 5
    max_seconds_to_close: int = 900
    max_spread: float = 1.0
    min_depth: float = 1.0
    uncertainty_buffer_cents: float = 0.0
    one_per_window: bool = True
    max_trades_per_window: int = 1

    @classmethod
    def from_config(cls, config, **over) -> "BacktestParams":
        bt = config.backtest
        base = cls(size=bt.default_size, min_net_edge_cents=bt.min_net_edge_cents,
                   max_book_age_ms=bt.max_book_age_ms, max_underlying_age_ms=bt.max_underlying_age_ms,
                   min_seconds_to_close=bt.min_seconds_to_close,
                   max_seconds_to_close=bt.max_seconds_to_close, max_spread=bt.max_spread,
                   min_depth=bt.min_depth, uncertainty_buffer_cents=bt.uncertainty_buffer_cents)
        for k, v in over.items():
            if v is not None and hasattr(base, k):
                setattr(base, k, v)
        return base


def evaluate_row(row: dict, p_yes: Optional[float], params: BacktestParams,
                 fee_model: KalshiFeeModel) -> dict:
    """Gate a single row and compute executable per-side edges. No midpoint."""
    reasons: list[str] = []
    yes_ask = row.get("yes_ask")
    no_ask = row.get("no_ask")
    secs = row.get("seconds_to_close")
    spread = max(row.get("yes_spread") or 0.0, row.get("no_spread") or 0.0)
    book_age = row.get("book_age_ms")
    und_age = row.get("underlying_age_ms")
    depth = row.get("top_depth")
    out = {"tradeable": False, "side": None, "entry_price": None, "reasons": reasons,
           "raw_edge": None, "net_edge": None, "fee_per_contract": None,
           "p_yes": p_yes, "yes_ask": yes_ask, "no_ask": no_ask}

    if p_yes is None:
        reasons.append("NO_MODEL_PROB"); return out
    if not bool(row.get("book_ok")):
        reasons.append("INVALID_OR_INCOMPLETE_BOOK"); return out
    if yes_ask is None or no_ask is None:
        reasons.append("NO_EXECUTABLE_ASK"); return out
    if row.get("label_yes_resolved") is None:
        reasons.append("MISSING_LABEL"); return out
    if row.get("reference_start_price") is None:
        reasons.append("MISSING_START_REFERENCE"); return out
    if secs is not None and secs <= 0:
        reasons.append("WINDOW_CLOSED"); return out
    if secs is not None and secs < params.min_seconds_to_close:
        reasons.append("TOO_CLOSE_TO_CLOSE"); return out
    if secs is not None and secs > params.max_seconds_to_close:
        reasons.append("TOO_FAR_FROM_CLOSE"); return out
    if book_age is not None and book_age > params.max_book_age_ms:
        reasons.append("STALE_BOOK"); return out
    if und_age is not None and und_age > params.max_underlying_age_ms:
        reasons.append("STALE_UNDERLYING"); return out
    if row.get("coinbase_stale") and row.get("binance_stale"):
        reasons.append("STALE_UNDERLYING"); return out
    if spread > params.max_spread:
        reasons.append("SPREAD_TOO_WIDE"); return out
    if depth is not None and depth < params.min_depth:
        reasons.append("INSUFFICIENT_DEPTH"); return out

    buf = (params.uncertainty_buffer_cents or 0.0) / 100.0
    fee_yes = fee_model.per_contract_fee(yes_ask)
    fee_no = fee_model.per_contract_fee(no_ask)
    net_yes = (p_yes - yes_ask) - fee_yes - buf
    net_no = ((1.0 - p_yes) - no_ask) - fee_no - buf
    if net_yes >= net_no:
        side, entry, raw, net, fee = "YES", yes_ask, p_yes - yes_ask, net_yes, fee_yes
    else:
        side, entry, raw, net, fee = "NO", no_ask, (1.0 - p_yes) - no_ask, net_no, fee_no

    # depth at the chosen side's ask
    side_size = row.get("yes_ask_size") if side == "YES" else row.get("no_ask_size")
    if side_size is not None and side_size < params.size:
        reasons.append("INSUFFICIENT_DEPTH")
        out.update(side=side, entry_price=entry, raw_edge=raw, net_edge=net, fee_per_contract=fee)
        return out

    out.update(side=side, entry_price=entry, raw_edge=raw, net_edge=net, fee_per_contract=fee)
    if net * 100.0 >= params.min_net_edge_cents:
        out["tradeable"] = True
    else:
        reasons.append("EDGE_BELOW_MIN")
    return out


def settle_trade(side: str, entry_price: float, size: float, label_yes: int,
                 fee_total: float) -> dict:
    win = (label_yes == 1) if side == "YES" else (label_yes == 0)
    settle_val = 1.0 if win else 0.0
    gross = size * (settle_val - entry_price)
    return {"win": win, "payout": size * settle_val, "gross_pnl": gross,
            "net_pnl": gross - fee_total}


def _prob_for(row: dict) -> Optional[float]:
    p = row.get("calibrated_probability_yes")
    return p if p is not None else row.get("model_probability_yes")


def simulate_backtest(eval_rows: list[dict], *, params: BacktestParams,
                      fee_model: KalshiFeeModel, diagnostic: bool = True,
                      model_version: str = "unknown", calibration_version: str = "none") -> dict:
    """Run the EV simulation over held-out rows (one position per window)."""
    by_window: dict = defaultdict(list)
    for r in eval_rows:
        by_window[r.get("ticker")].append(r)

    trades: list[dict] = []
    rejections: Counter = Counter()
    candidate_rows = len(eval_rows)
    for tk, rws in by_window.items():
        rws = sorted(rws, key=lambda r: (r.get("as_of_ts_ms") or 0))
        opened = 0
        for r in rws:
            if params.one_per_window and opened >= params.max_trades_per_window:
                break
            p = _prob_for(r)
            dec = evaluate_row(r, p, params, fee_model)
            if not dec["tradeable"]:
                if dec["reasons"]:
                    rejections[dec["reasons"][-1]] += 1
                continue
            fee_total = fee_model.taker_fee(dec["entry_price"], params.size)
            s = settle_trade(dec["side"], dec["entry_price"], params.size,
                             int(r["label_yes_resolved"]), fee_total)
            trades.append({
                "row_id": r.get("row_id"), "ticker": tk, "series": r.get("series"),
                "as_of_ts_ms": r.get("as_of_ts_ms"), "market_close_ts_ms": r.get("market_close_ts_ms"),
                "seconds_to_close": r.get("seconds_to_close"), "side": dec["side"],
                "model_probability_yes": r.get("model_probability_yes"),
                "calibrated_probability_yes": r.get("calibrated_probability_yes"),
                "executable_yes_price": r.get("yes_ask"), "executable_no_price": r.get("no_ask"),
                "selected_entry_price": dec["entry_price"], "fee_estimate": fee_total,
                "raw_edge": dec["raw_edge"], "net_edge": dec["net_edge"],
                "min_edge_threshold": params.min_net_edge_cents / 100.0,
                "size": params.size, "notional": dec["entry_price"] * params.size,
                "settlement_label": int(r["label_yes_resolved"]), "payout": s["payout"],
                "gross_pnl": s["gross_pnl"], "net_pnl": s["net_pnl"], "win": s["win"],
                "distance_to_start": r.get("distance_to_start"),
                "spot_sigma_per_sqrt_s": r.get("spot_sigma_per_sqrt_s"),
                "deribit_regime": r.get("deribit_regime"),
                "coinbase_stale": r.get("coinbase_stale"), "binance_stale": r.get("binance_stale"),
                "feature_set_version": r.get("feature_set_version"),
                "model_version": model_version, "calibration_version": calibration_version,
                "tradable": (not diagnostic),
            })
            opened += 1
    agg = _aggregate(trades, candidate_rows, rejections)
    agg.update(diagnostic=diagnostic, model_version=model_version,
               calibration_version=calibration_version)
    return agg


def _aggregate(trades: list[dict], candidate_rows: int, rejections: Counter) -> dict:
    n = len(trades)
    gross = sum(t["gross_pnl"] for t in trades)
    net = sum(t["net_pnl"] for t in trades)
    wins = sum(1 for t in trades if t["win"])
    pos = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    neg = sum(-t["net_pnl"] for t in trades if t["net_pnl"] < 0)
    # drawdown over chronological cumulative net P&L
    cum = peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: (x.get("as_of_ts_ms") or 0)):
        cum += t["net_pnl"]
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)
    return {
        "total_candidate_rows": candidate_rows,
        "total_simulated_trades": n,
        "fillable_trades": n,
        "windows_touched": len({t["ticker"] for t in trades}),
        "rejected_rows_by_reason": dict(rejections),
        "gross_pnl": round(gross, 6),
        "net_pnl": round(net, 6),
        "avg_net_edge": (sum(t["net_edge"] for t in trades) / n) if n else None,
        "realized_pnl_per_contract": (net / sum(t["size"] for t in trades)) if n else None,
        "hit_rate": (wins / n) if n else None,
        "avg_entry_price": (sum(t["selected_entry_price"] for t in trades) / n) if n else None,
        "avg_fee": (sum(t["fee_estimate"] for t in trades) / n) if n else None,
        "max_drawdown": round(max_dd, 6),
        "profit_factor": (pos / neg) if neg > 0 else None,
        "pnl_by_side": _group_pnl(trades, lambda t: t["side"]),
        "pnl_by_seconds_to_close": _group_pnl(trades, _bucket_secs),
        "pnl_by_distance_sign": _group_pnl(trades, _bucket_dist),
        "pnl_by_vol_regime": _group_pnl(trades, _bucket_vol),
        "pnl_by_source_health": _group_pnl(trades, _bucket_health),
        "pnl_by_prob_bucket": _group_pnl(trades, _bucket_prob),
        "pnl_by_net_edge_bucket": _group_pnl(trades, _bucket_edge),
        "trades": trades,
    }


def _group_pnl(trades, keyfn) -> dict:
    out: dict = {}
    for t in trades:
        k = keyfn(t)
        g = out.setdefault(str(k), {"trades": 0, "net_pnl": 0.0, "wins": 0})
        g["trades"] += 1
        g["net_pnl"] = round(g["net_pnl"] + t["net_pnl"], 6)
        g["wins"] += 1 if t["win"] else 0
    return out


def _bucket_secs(t):
    s = t.get("seconds_to_close")
    if s is None:
        return "na"
    return "<60s" if s < 60 else "60-300s" if s < 300 else "300-600s" if s < 600 else ">=600s"


def _bucket_dist(t):
    d = t.get("distance_to_start")
    return "na" if d is None else ("yes_side" if d >= 0 else "no_side")


def _bucket_vol(t):
    if t.get("deribit_regime"):
        return t["deribit_regime"]
    s = t.get("spot_sigma_per_sqrt_s")
    return "na" if s is None else ("low" if s < 5e-5 else "mid" if s < 1.5e-4 else "high")


def _bucket_health(t):
    return f"cb_stale={bool(t.get('coinbase_stale'))},bn_stale={bool(t.get('binance_stale'))}"


def _bucket_prob(t):
    p = t.get("calibrated_probability_yes")
    if p is None:
        p = t.get("model_probability_yes")
    return "na" if p is None else f"[{int(p*10)/10:.1f},{(int(p*10)+1)/10:.1f})"


def _bucket_edge(t):
    e = t.get("net_edge")
    if e is None:
        return "na"
    c = e * 100.0
    return "<0c" if c < 0 else "0-2c" if c < 2 else "2-5c" if c < 5 else "5-10c" if c < 10 else ">=10c"


# --------------------------------------------------------------------------- #
# Probability assignment helpers
# --------------------------------------------------------------------------- #
def predict_from_artifact(artifact: dict, rows: list[dict], idx: list[int]) -> list[float]:
    """Predict probs for rows[idx] from a saved artifact (sklearn pipeline or pure_ml)."""
    feats = artifact.get("feature_names", [])
    X = [feature_vector(rows[i], feats) for i in idx]
    # Serious sklearn-backed artifact carries a picklable pipeline.
    if artifact.get("model_backend") == "sklearn" and artifact.get("sklearn_pipeline") is not None:
        from ...models.sklearn_models import predict_proba_pipeline
        return predict_proba_pipeline(artifact["sklearn_pipeline"], X)
    # Pure-stdlib fallback artifact (diagnostic-only path).
    model = pure_ml.LogisticRegression.from_dict(artifact.get("model", {}))
    imp = pure_ml.StandardImputer()
    imp.means = artifact.get("imputer", {}).get("means", [])
    imp.stds = artifact.get("imputer", {}).get("stds", [])
    imp.n_features = artifact.get("imputer", {}).get("n_features", len(imp.means))
    return model.predict_proba(imp.transform(X))


def market_implied_probs(rows: list[dict], idx: list[int]) -> list[float]:
    out = []
    for i in idx:
        ya, na = rows[i].get("yes_ask"), rows[i].get("no_ask")
        if ya is None:
            out.append(None)
        elif na is not None and (ya + na) > 0:
            out.append(max(0.0, min(1.0, ya / (ya + na))))
        else:
            out.append(max(0.0, min(1.0, ya)))
    return out


def _attach(rows, idx, probs, calibrator: Optional[Calibrator] = None) -> list[dict]:
    """Return copies of rows[idx] with model_probability_yes + calibrated_probability_yes."""
    cal = (calibrator.transform(probs) if calibrator is not None else list(probs))
    out = []
    for j, i in enumerate(idx):
        r = dict(rows[i])
        r["model_probability_yes"] = probs[j]
        r["calibrated_probability_yes"] = cal[j]
        out.append(r)
    return out


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _f(x):
    return f"{x:.4f}" if isinstance(x, (int, float)) else "None"


def latest_model_artifact_path(config) -> Optional[str]:
    d = config.data_path() / "models"
    if not d.exists():
        return None
    cands = [p for p in d.glob("kalshi_*.pkl")
             if "calibrator" not in p.name and "dataset" not in p.name]
    if not cands:
        return None
    return str(sorted(cands, key=lambda p: p.stat().st_mtime)[-1])


def latest_staged_model_artifact_path(config) -> Optional[str]:
    """Newest STAGED model artifact (data/models/staged/). For --staged backtests only;
    the runtime never scans this directory."""
    d = config.data_path() / "models" / "staged"
    if not d.exists():
        return None
    cands = [p for p in d.glob("kalshi_*.pkl")
             if "calibrator" not in p.name and "dataset" not in p.name]
    if not cands:
        return None
    return str(sorted(cands, key=lambda p: p.stat().st_mtime)[-1])


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #
def run_backtest_baselines(config, *, series: str = "KXBTC15M", diagnostic_only: bool = False,
                           embargo_windows: int = 1, model_path: Optional[str] = None) -> dict:
    """Backtest no-trade / market-implied / distance-time-vol / microstructure (+ model
    if an artifact exists), leakage-safe (fit on train, eval on held-out val)."""
    from .calibration_report import calibration_summary  # local import (no cycle)
    from .train_baselines import fit_predict_logistic

    bt = config.backtest
    ds = build_model_dataset(config, series=series)
    rows = ds["rows"]
    gate_windows = ds["distinct_windows"]
    gate_met = gate_windows >= bt.min_windows
    diagnostic = bool(diagnostic_only or bt.allow_diagnostic or not gate_met)
    report = {"series": series, "gate_windows": gate_windows, "gate_min_windows": bt.min_windows,
              "gate_met": gate_met, "diagnostic": diagnostic, "n_rows": len(rows),
              "results": {}, "blockers": []}

    if not gate_met and not (diagnostic_only or bt.allow_diagnostic):
        report["refused"] = True
        report["blockers"].append(
            f"backtest gate {gate_windows}/{bt.min_windows} not met; pass --diagnostic-only "
            "for a NON-TRADABLE diagnostic backtest.")
        return report

    train_idx, val_idx = split_indices(rows, embargo_windows=embargo_windows)
    if not val_idx or not train_idx:
        report["refused"] = True
        report["blockers"].append("not enough windows for a held-out train/val split.")
        return report
    params = BacktestParams.from_config(config)
    fee_model = KalshiFeeModel.from_config(config)
    report["split"] = {"train_rows": len(train_idx), "val_rows": len(val_idx)}

    # A. no-trade floor
    report["results"]["no_trade"] = {"net_pnl": 0.0, "total_simulated_trades": 0,
                                     "note": "floor baseline"}

    # B. market-implied (+ its calibration)
    mi = market_implied_probs(rows, val_idx)
    mi_rows = _attach(rows, val_idx, mi)
    y_val = [int(rows[i]["label_yes_resolved"]) for i in val_idx]
    report["results"]["market_implied"] = {
        **simulate_backtest(mi_rows, params=params, fee_model=fee_model, diagnostic=diagnostic,
                            model_version="market_implied"),
        "calibration": {k: calibration_summary(y_val, [p for p in mi if p is not None]).get(k)
                        for k in ("brier", "log_loss", "ece")},
    }

    # C/D. fitted logistic baselines (leakage-safe)
    for name, feats in (("distance_time_vol", DISTANCE_TIME_VOL_FEATURES),
                        ("microstructure", MICROSTRUCTURE_FEATURES)):
        probs, _, _ = fit_predict_logistic(rows, feats, train_idx, val_idx)
        brows = _attach(rows, val_idx, probs)
        agg = simulate_backtest(brows, params=params, fee_model=fee_model, diagnostic=diagnostic,
                                model_version=name)
        agg["calibration"] = {k: calibration_summary(y_val, probs).get(k)
                              for k in ("brier", "log_loss", "ece")}
        agg["walk_forward"] = _walk_forward_pnl(rows, feats, params, fee_model, embargo_windows)
        report["results"][name] = agg

    # E. main model artifact, if present (in-sample => diagnostic). ``model_path``
    # (e.g. a STAGED artifact via --staged) overrides the active runtime selection.
    mp = model_path or latest_model_artifact_path(config)
    if mp:
        try:
            art = load_artifact(mp)
            probs = predict_from_artifact(art, rows, val_idx)
            arows = _attach(rows, val_idx, probs)
            report["results"]["main_model"] = {
                **simulate_backtest(arows, params=params, fee_model=fee_model, diagnostic=True,
                                    model_version=art.get("model_name", "model")),
                "artifact": mp, "tradable_artifact": is_tradable(art)}
        except Exception as exc:  # noqa: BLE001
            report["results"]["main_model"] = {"error": f"{type(exc).__name__}: {exc}"}

    report["reports"] = _write_baseline_comparison(config, report)
    return report


def run_backtest_model(config, *, series: str = "KXBTC15M", model: str = "latest",
                       calibrator: str = "latest", diagnostic_only: bool = False,
                       embargo_windows: int = 1) -> dict:
    """Backtest a saved model artifact (+ optional calibrator) on held-out val."""
    from .calibrate import latest_calibrator_path

    bt = config.backtest
    mp = latest_model_artifact_path(config) if model in ("latest", None, "") else model
    if not mp:
        return {"series": series, "refused": True,
                "blockers": ["no model artifact found — run kalshi-train-baselines "
                             "(or --diagnostic-only) first, or use kalshi-backtest-baselines."]}
    art = load_artifact(mp)
    ds = build_model_dataset(config, series=series)
    rows = ds["rows"]
    gate_windows = ds["distinct_windows"]
    gate_met = gate_windows >= bt.min_windows
    # a pre-trained artifact is in-sample over the dataset -> always diagnostic here
    diagnostic = True
    report = {"series": series, "model_artifact": mp, "gate_windows": gate_windows,
              "gate_min_windows": bt.min_windows, "gate_met": gate_met, "diagnostic": diagnostic,
              "tradable_artifact": is_tradable(art), "blockers": []}
    if not gate_met and not (diagnostic_only or bt.allow_diagnostic):
        report["refused"] = True
        report["blockers"].append(f"backtest gate {gate_windows}/{bt.min_windows} not met; "
                                  "pass --diagnostic-only for a NON-TRADABLE report.")
        return report

    train_idx, val_idx = split_indices(rows, embargo_windows=embargo_windows)
    if not val_idx:
        report["refused"] = True
        report["blockers"].append("not enough windows for a held-out val split.")
        return report

    cal_obj = None
    cal_ver = "none"
    cpath = latest_calibrator_path(config) if calibrator in ("latest", None, "") else calibrator
    if calibrator not in ("none", "off") and cpath:
        try:
            cart = load_calibrator(cpath)
            cal_obj = Calibrator.from_dict(cart.get("calibrator", {}))
            cal_ver = cpath
        except Exception:  # noqa: BLE001
            cal_obj = None

    probs = predict_from_artifact(art, rows, val_idx)
    arows = _attach(rows, val_idx, probs, calibrator=cal_obj)
    params = BacktestParams.from_config(config)
    agg = simulate_backtest(arows, params=params, fee_model=KalshiFeeModel.from_config(config),
                            diagnostic=diagnostic, model_version=art.get("model_name", "model"),
                            calibration_version=cal_ver)
    report["result"] = agg
    report["reports"] = _write_backtest_report(config, "model", agg, report)
    return report


def _walk_forward_pnl(rows, feats, params, fee_model, embargo_windows) -> list[dict]:
    from .train_baselines import fit_predict_logistic
    out = []
    for k, (tr, vl) in enumerate(walk_forward_indices(rows, n_splits=3, embargo_windows=embargo_windows), 1):
        probs, _, _ = fit_predict_logistic(rows, feats, tr, vl)
        agg = simulate_backtest(_attach(rows, vl, probs), params=params, fee_model=fee_model,
                                diagnostic=True, model_version=f"fold{k}")
        out.append({"fold": k, "trades": agg["total_simulated_trades"],
                    "net_pnl": agg["net_pnl"], "hit_rate": agg["hit_rate"]})
    return out


# --------------------------------------------------------------------------- #
# Report writers
# --------------------------------------------------------------------------- #
def _hdr(report: dict) -> list[str]:
    return [
        f"- gate_windows: {report.get('gate_windows')} / backtest gate {report.get('gate_min_windows')}  "
        f"(met={report.get('gate_met')})",
        f"- diagnostic_only / NON_TRADABLE: **{report.get('diagnostic')}**",
        f"- model_schema_version: {MODEL_SCHEMA_VERSION}",
        "- executable ask prices (NEVER midpoint); fees + depth + staleness modeled.",
        "- RESEARCH EVIDENCE ONLY — not a profitability claim; no orders; live disabled.",
    ]


def _agg_lines(name: str, a: dict) -> list[str]:
    return [
        f"### {name}",
        f"- trades: {a.get('total_simulated_trades')}  windows_touched: {a.get('windows_touched')}  "
        f"candidate_rows: {a.get('total_candidate_rows')}",
        f"- net_pnl: {a.get('net_pnl')}  gross_pnl: {a.get('gross_pnl')}  "
        f"realized_pnl_per_contract: {_f(a.get('realized_pnl_per_contract'))}",
        f"- hit_rate: {_f(a.get('hit_rate'))}  avg_net_edge: {_f(a.get('avg_net_edge'))}  "
        f"avg_entry: {_f(a.get('avg_entry_price'))}  avg_fee: {_f(a.get('avg_fee'))}",
        f"- max_drawdown: {a.get('max_drawdown')}  profit_factor: {_f(a.get('profit_factor'))}",
        f"- pnl_by_side: {a.get('pnl_by_side')}",
        f"- rejected_rows_by_reason: {a.get('rejected_rows_by_reason')}",
    ]


def _write_baseline_comparison(config, report: dict) -> dict:
    d = config.reports_path() / "backtests"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    path = d / f"kalshi_baseline_comparison_{stamp}.md"
    lines = [f"# Kalshi executable backtest — baseline comparison ({report['series']})", ""]
    lines += _hdr(report)
    lines += ["", f"- split: {report.get('split')}", ""]
    for name, a in report["results"].items():
        if "error" in a:
            lines += [f"### {name}", f"- error: {a['error']}", ""]
            continue
        if name == "no_trade":
            lines += ["### no_trade", "- net_pnl: 0.0 (floor)", ""]
            continue
        lines += _agg_lines(name, a)
        if a.get("calibration"):
            lines.append(f"- calibration: {a['calibration']}")
        if a.get("walk_forward"):
            lines.append(f"- walk_forward_stability: {a['walk_forward']}")
        lines.append("")
    lines += ["## Note",
              "- Backtest EVIDENCE only. Do not select a production policy by max in-sample P&L;",
              "  require later paper validation. Diagnostic reports are NON-TRADABLE."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # JSON sidecar (trade-level omitted for size)
    js = d / f"kalshi_baseline_comparison_{stamp}.json"
    slim = {n: {k: v for k, v in a.items() if k != "trades"} for n, a in report["results"].items()}
    with js.open("w", encoding="utf-8") as fh:
        json.dump({"meta": {k: report[k] for k in ("series", "gate_windows", "gate_met", "diagnostic")},
                   "results": slim}, fh, indent=2, default=str)
    return {"comparison_md": str(path), "comparison_json": str(js)}


def _write_backtest_report(config, name: str, agg: dict, report: dict) -> dict:
    d = config.reports_path() / "backtests"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _ts()
    path = d / f"kalshi_executable_backtest_{stamp}.md"
    lines = [f"# Kalshi executable backtest — {name} ({report['series']})", ""]
    lines += _hdr(report)
    lines += ["", f"- model_artifact: {report.get('model_artifact')}",
              f"- tradable_artifact: {report.get('tradable_artifact')}",
              f"- calibration_version: {agg.get('calibration_version')}", ""]
    lines += _agg_lines(name, agg)
    for grp in ("pnl_by_seconds_to_close", "pnl_by_distance_sign", "pnl_by_vol_regime",
                "pnl_by_source_health", "pnl_by_prob_bucket", "pnl_by_net_edge_bucket"):
        lines.append(f"- {grp}: {agg.get(grp)}")
    lines += ["", "## Note", "- EVIDENCE only; executable asks/fees/depth/staleness; no orders; live disabled."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"backtest_md": str(path)}
