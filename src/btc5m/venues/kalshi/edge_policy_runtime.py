"""Edge-policy runtime: build a leakage-safe eval set + calibration buckets, run the
conservative edge funnel, sweep thresholds, and write reports under reports/edge/.

READ-ONLY: no orders, no policy promotion, no live. When no tradable calibrated
model exists the report is stamped NON_TRADABLE_DIAGNOSTIC_ONLY; the edge funnel is
then computed in *study mode* (assuming a calibrated model) purely to characterize
how thresholds behave — the live policy still rejects all (uncalibrated).
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from .edge_policy import EdgePolicyConfig, EdgeInputs, evaluate_edge
from .executable_backtest import _prob_for, market_implied_probs, settle_trade
from .fees import KalshiFeeModel
from .trade_frequency_runtime import build_eval_set
from .uncertainty import build_calibration_buckets

NON_TRADABLE = "NON_TRADABLE_DIAGNOSTIC_ONLY"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _edge_dir(config):
    d = config.reports_path() / "edge"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _inputs_for_row(row: dict, buckets: list, *, study_calibrated: bool, ev_tradable: bool) -> EdgeInputs:
    p = _prob_for(row)
    ya, na = row.get("yes_ask"), row.get("no_ask")
    ens = {}
    if p is not None:
        ens["model"] = p
        if ya is not None and na is not None and (ya + na) > 0:
            ens["market_implied"] = max(0.0, min(1.0, ya / (ya + na)))
    spread = max(row.get("yes_spread") or 0.0, row.get("no_spread") or 0.0)
    return EdgeInputs(
        p_yes_hat=p, p_yes_lower=row.get("model_p_yes_lower"), p_yes_upper=row.get("model_p_yes_upper"),
        yes_ask=ya, no_ask=na, yes_ask_size=row.get("yes_ask_size"), no_ask_size=row.get("no_ask_size"),
        seconds_to_close=row.get("seconds_to_close"), spread_cents=(spread * 100.0) if spread else None,
        book_age_ms=row.get("book_age_ms"), underlying_age_ms=row.get("underlying_age_ms"),
        coinbase_stale=bool(row.get("coinbase_stale")), binance_stale=bool(row.get("binance_stale")),
        deribit_regime=row.get("deribit_regime"), sigma_per_sqrt_s=row.get("spot_sigma_per_sqrt_s"),
        overtrading=False, calibration_buckets=buckets, ensemble_probs=ens,
        model_calibrated=bool(study_calibrated or ev_tradable),
        model_tradable=bool(study_calibrated or ev_tradable), backtest_valid=True)


def _funnel_and_decisions(rows, buckets, cfg, fee_model, *, study_calibrated, ev_tradable):
    funnel = Counter()
    reasons = Counter()
    edges = {"raw": [], "cost": [], "final": []}
    ok_rows = []
    for r in rows:
        d = evaluate_edge(_inputs_for_row(r, buckets, study_calibrated=study_calibrated,
                                          ev_tradable=ev_tradable), cfg, fee_model)
        funnel["candidates"] += 1
        rc = set(d.reason_codes)
        if "RAW_EDGE_BELOW_MIN" not in rc:
            funnel["survived_raw_edge"] += 1
        if "COST_ADJUSTED_EDGE_BELOW_MIN" not in rc:
            funnel["survived_cost_adjusted"] += 1
        if "UNCERTAINTY_ADJUSTED_EDGE_BELOW_MIN" not in rc:
            funnel["survived_uncertainty_adjusted"] += 1
        if "EDGE_BELOW_MIN" not in rc:
            funnel["survived_final_edge"] += 1
        if "PRICE_ABOVE_RESERVATION" not in rc:
            funnel["survived_reservation"] += 1
        if "INSUFFICIENT_DEPTH" not in rc:
            funnel["survived_depth"] += 1
        if d.state == "EDGE_OK":
            funnel["edge_ok"] += 1
            ok_rows.append((r, d))
        for code in d.reason_codes:
            reasons[code] += 1
        if d.raw_edge_cents is not None:
            edges["raw"].append(d.raw_edge_cents)
        if d.cost_adjusted_edge_cents is not None:
            edges["cost"].append(d.cost_adjusted_edge_cents)
        if d.final_policy_edge_cents is not None:
            edges["final"].append(d.final_policy_edge_cents)
    return funnel, reasons, edges, ok_rows


def _settle_ok(ok_rows, fee_model, size=1.0) -> dict:
    net = 0.0
    wins = 0
    windows = set()
    for r, d in ok_rows:
        if r.get("label_yes_resolved") is None or d.side is None or d.executable_price is None:
            continue
        fee = fee_model.taker_fee(d.executable_price, size)
        s = settle_trade(d.side, d.executable_price, size, int(r["label_yes_resolved"]), fee)
        net += s["net_pnl"]
        wins += 1 if s["win"] else 0
        windows.add(r.get("ticker"))
    n = len(ok_rows)
    return {"edge_ok_trades": n, "distinct_windows": len(windows), "net_pnl": round(net, 6),
            "hit_rate": (wins / n) if n else None}


def _eval_context(config, series, source, diagnostic_only, embargo):
    ev = build_eval_set(config, series=series, source=source, diagnostic_only=diagnostic_only, embargo=embargo)
    rows = ev["rows"]
    buckets = []
    if rows:
        y = [int(r["label_yes_resolved"]) for r in rows if r.get("label_yes_resolved") is not None]
        p = [_prob_for(r) for r in rows if r.get("label_yes_resolved") is not None]
        yp = [(yy, pp) for yy, pp in zip(y, p) if pp is not None]
        if yp:
            buckets = build_calibration_buckets([a for a, _ in yp], [b for _, b in yp])
    return ev, rows, buckets


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #
def run_edge_policy_report(config, *, series="KXBTC15M", source="auto", diagnostic_only=False, embargo=1) -> dict:
    cfg = EdgePolicyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    ev, rows, buckets = _eval_context(config, series, source, diagnostic_only, embargo)
    out = {"series": series, "prob_source": ev["prob_source"], "diagnostic": ev["diagnostic"],
           "tradable": ev["tradable"], "gate_windows": ev["gate_windows"], "promoted": False,
           "live_submission_allowed": False, "blockers": list(ev["blockers"]),
           "stamp": (NON_TRADABLE if ev["diagnostic"] else "TRADABLE"),
           "config": {k: getattr(cfg, k) for k in ("enabled", "require_confidence_bounds",
                      "min_raw_edge_cents", "min_final_edge_cents", "base_min_profit_cents",
                      "fixed_uncertainty_buffer_cents", "min_calibration_bucket_n",
                      "confidence_level", "max_prob_interval_width_cents")}}
    if not rows:
        out["status"] = "BLOCKED"
        out["reports"] = _write_report_md(config, out, None, None, None, None, buckets)
        return out
    # study mode (assume calibrated) so the funnel characterizes thresholds; the live
    # policy still rejects all when uncalibrated (see validity note in the report).
    funnel, reasons, edges, ok_rows = _funnel_and_decisions(
        rows, buckets, cfg, fee_model, study_calibrated=True, ev_tradable=ev["tradable"])
    out["status"] = "OK"
    out["funnel"] = dict(funnel)
    out["rejection_reasons"] = dict(reasons.most_common())
    out["edge_distribution"] = {k: ({"n": len(v), "mean": round(sum(v) / len(v), 3),
                                     "min": round(min(v), 3), "max": round(max(v), 3)} if v else None)
                                for k, v in edges.items()}
    out["edge_ok_settlement"] = _settle_ok(ok_rows, fee_model)
    out["calibration_buckets"] = [{"range": f"[{b.lo:.1f},{b.hi:.1f})", "n": b.count,
                                   "mean_pred": round(b.mean_pred, 4), "realized": round(b.mean_actual, 4),
                                   "wilson": [round(b.wilson_low, 4), round(b.wilson_high, 4)]}
                                  for b in buckets]
    out["recommended_settings"] = _conservative_settings(cfg, out)
    out["reports"] = _write_report_md(config, out, funnel, reasons, edges, ok_rows, buckets)
    out["reports"].update(_write_rejection_csv(config, reasons))
    return out


def run_edge_threshold_sweep(config, *, series="KXBTC15M", source="auto", diagnostic_only=False, embargo=1) -> dict:
    cfg = EdgePolicyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    ev, rows, buckets = _eval_context(config, series, source, diagnostic_only, embargo)
    out = {"series": series, "prob_source": ev["prob_source"], "diagnostic": ev["diagnostic"],
           "tradable": ev["tradable"], "gate_windows": ev["gate_windows"], "promoted": False,
           "live_submission_allowed": False, "blockers": list(ev["blockers"]),
           "stamp": (NON_TRADABLE if ev["diagnostic"] else "TRADABLE")}
    if not rows:
        out["status"] = "BLOCKED"
        return out
    import dataclasses
    configs = []
    grid = [
        ("fixed_min_raw", "min_raw_edge_cents", [2, 3, 5, 7, 10]),
        ("confidence_level", "confidence_level", [0.70, 0.80, 0.90, 0.95]),
        ("min_bucket_n", "min_calibration_bucket_n", [10, 20, 30, 50]),
        ("max_interval_width", "max_prob_interval_width_cents", [8, 12, 16, 20]),
        ("fixed_uncertainty_buffer", "fixed_uncertainty_buffer_cents", [1, 2, 3, 5]),
        ("overtrading_buffer", "overtrading_buffer_cents", [0, 1, 2]),
        ("high_vol_buffer", "high_vol_regime_buffer_cents", [0, 2, 4]),
    ]
    for axis, attr, values in grid:
        for v in values:
            scfg = dataclasses.replace(cfg, **{attr: v})
            funnel, reasons, _edges, ok_rows = _funnel_and_decisions(
                rows, buckets, scfg, fee_model, study_calibrated=True, ev_tradable=ev["tradable"])
            settle = _settle_ok(ok_rows, fee_model)
            configs.append({"axis": axis, attr: v, "edge_ok": funnel.get("edge_ok", 0),
                            "distinct_windows": settle["distinct_windows"], "net_pnl": settle["net_pnl"],
                            "hit_rate": settle["hit_rate"]})
    out["status"] = "OK"
    out["configs"] = configs
    out["reports"] = _write_sweep_reports(config, out, configs)
    return out


# --------------------------------------------------------------------------- #
# Conservative settings (NOT promoted)
# --------------------------------------------------------------------------- #
def _conservative_settings(cfg: EdgePolicyConfig, out: dict) -> dict:
    return {
        "min_raw_edge_cents": 5, "min_final_edge_cents": 2, "base_min_profit_cents": 2,
        "fixed_uncertainty_buffer_cents": 3, "min_calibration_bucket_n": 30,
        "confidence_level": 0.80, "max_prob_interval_width_cents": 12,
        "rationale": ("Conservative defaults: require a calibrated+backtested model, a >=5c raw edge, "
                      "and a >=2c final edge AFTER fees + model/calibration/regime/overtrading buffers. "
                      "Reservation price uses the conservative probability bound, not the point estimate."),
        "diagnostic_only": bool(out.get("diagnostic", True)),
        "requires_manual_review": True, "promoted": False, "live_submission_allowed": False,
    }


# --------------------------------------------------------------------------- #
# Report writers
# --------------------------------------------------------------------------- #
def _safety() -> list:
    return ["", "## Safety",
            "- RESEARCH/REPORTING ONLY: no orders, no PAPER_CANDIDATE, no live trading.",
            "- No policy/model promoted; recommendations require manual review + paper validation.",
            "- Edge is NOT model_prob - price: it is conservative-bound edge minus fees + uncertainty",
            "  + regime + overtrading + minimum-profit buffers; reservation uses the conservative bound.",
            "- Uncalibrated/diagnostic model => the live policy rejects ALL candidates."]


def _write_report_md(config, out, funnel, reasons, edges, ok_rows, buckets) -> dict:
    d = _edge_dir(config)
    stamp = _ts()
    md = d / f"kalshi_edge_policy_report_{stamp}.md"
    lines = [f"# Kalshi edge-policy report — {out['series']}", "",
             f"- prob_source: {out.get('prob_source')}  diagnostic/NON_TRADABLE: **{out.get('diagnostic')}**  "
             f"({out.get('stamp')})",
             f"- gate_windows: {out.get('gate_windows')}  promoted: False  live_submission_allowed: False",
             f"- config: {json.dumps(out.get('config', {}))}"]
    for b in (out.get("blockers") or []):
        lines.append(f"  - blocker: {b}")
    if out.get("status") == "BLOCKED":
        lines += ["", "## BLOCKED — no eval rows."] + _safety()
        md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"edge_policy_report_md": str(md)}
    lines += ["", "## Validity",
              f"- model tradable/calibrated: **{out.get('tradable')}** — if False, the LIVE policy rejects all",
              "  (UNCALIBRATED_MODEL_REJECTED); the funnel below is STUDY MODE (assumes a calibrated model).",
              "", "## Candidate survival funnel (study mode)"]
    fn = out["funnel"]
    for k in ("candidates", "survived_raw_edge", "survived_cost_adjusted", "survived_uncertainty_adjusted",
              "survived_final_edge", "survived_reservation", "survived_depth", "edge_ok"):
        lines.append(f"- {k}: {fn.get(k, 0)}")
    lines += ["", "## Edge distribution (cents)"]
    for k, v in (out.get("edge_distribution") or {}).items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Rejection reasons", f"- {json.dumps(out.get('rejection_reasons', {}))}",
              "", "## EDGE_OK settlement (diagnostic)", f"- {json.dumps(out.get('edge_ok_settlement', {}))}",
              "", "## Calibration buckets (held-out; Wilson interval)",
              "| range | n | mean_pred | realized | wilson |", "|---|---|---|---|---|"]
    for b in (out.get("calibration_buckets") or []):
        lines.append(f"| {b['range']} | {b['n']} | {b['mean_pred']} | {b['realized']} | {b['wilson']} |")
    sug = out.get("recommended_settings", {})
    lines += ["", "## Recommended conservative settings (NOT promoted; manual review)",
              f"- {json.dumps({k: sug[k] for k in ('min_raw_edge_cents', 'min_final_edge_cents', 'base_min_profit_cents', 'fixed_uncertainty_buffer_cents', 'min_calibration_bucket_n', 'confidence_level', 'max_prob_interval_width_cents')})}",
              f"- rationale: {sug.get('rationale')}"]
    lines += _safety()
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"edge_policy_report_md": str(md)}


def _write_rejection_csv(config, reasons: Counter) -> dict:
    d = _edge_dir(config)
    path = d / f"kalshi_edge_rejection_breakdown_{_ts()}.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["reason_code", "count"])
        for k, v in reasons.most_common():
            w.writerow([k, v])
    return {"rejection_breakdown_csv": str(path)}


def _write_sweep_reports(config, out, configs) -> dict:
    d = _edge_dir(config)
    stamp = _ts()
    csv_path = d / f"kalshi_edge_threshold_sweep_{stamp}.csv"
    json_path = d / f"kalshi_edge_threshold_sweep_{stamp}.json"
    cols = ["axis", "edge_ok", "distinct_windows", "net_pnl", "hit_rate"]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols + ["param_value"])
        for c in configs:
            pv = next((c[k] for k in c if k not in cols + ["axis"]), None)
            w.writerow([c.get(x) for x in cols] + [pv])
    json_path.write_text(json.dumps(configs, indent=2, default=str), encoding="utf-8")
    return {"edge_threshold_sweep_csv": str(csv_path), "edge_threshold_sweep_json": str(json_path)}
