"""Data layer for the research dashboard.

Loads and lightly parses the committed artifacts that back every dashboard view:
  - docs/research_ledger.json      (Research Map)
  - docs/results/headline.json     (Overview tiles)
  - sample_data/features + labels  (live-computed market-implied reliability)
  - sample_data/expected/*.md,*.csv (Calibration + Backtest, the committed reports)
  - sample_data/replay_window/*    (Replay)

Pure reads of committed files. No network, no keys, no model training. Functions
return plain dicts/lists ready for JSON serialization, and degrade to a documented
empty shape (never raise) when an artifact is missing, so the UI can show an honest
empty state.
"""
from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path

# repo root: src/btc5m/dashboard/data.py -> parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / "docs"
SAMPLE = REPO_ROOT / "sample_data"
EXPECTED = SAMPLE / "expected"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Overview + Research Map (direct committed JSON)                             #
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def load_headline() -> dict:
    return _read_json(DOCS / "results" / "headline.json") or {"tiles": [], "missing": True}


@lru_cache(maxsize=1)
def load_ledger() -> dict:
    return _read_json(DOCS / "research_ledger.json") or {"legs": [], "missing": True}


def verdict_breakdown() -> list[dict]:
    legs = load_ledger().get("legs", [])
    order = ["NEGATIVE", "OPEN", "INFRA", "RESOLVED", "PARKED"]
    counts: dict[str, int] = {}
    for leg in legs:
        v = leg.get("verdict", "OTHER")
        counts[v] = counts.get(v, 0) + 1
    return [{"verdict": v, "count": counts[v]} for v in order if v in counts]


# --------------------------------------------------------------------------- #
# Calibration                                                                 #
# --------------------------------------------------------------------------- #
def _iter_sample_rows():
    feats = sorted((SAMPLE / "features").glob("*.jsonl"))
    labels_by_ticker: dict[str, int] = {}
    for lf in sorted((SAMPLE / "labels").glob("*.jsonl")):
        for line in _read_text(lf).splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            mt = obj.get("market_ticker")
            if mt is not None and obj.get("label_yes_resolved") is not None:
                labels_by_ticker[mt] = int(obj["label_yes_resolved"])
    for ff in feats:
        for line in _read_text(ff).splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            mt = obj.get("market_ticker")
            if mt in labels_by_ticker:
                yield obj, labels_by_ticker[mt]


def market_reliability(nbins: int = 10) -> dict:
    """Reliability of the recorded market-implied YES probability against the
    OFFICIAL label, computed live from committed sample_data (hermetic, no model)."""
    bins = [{"lo": i / nbins, "hi": (i + 1) / nbins, "n": 0, "sum_pred": 0.0, "sum_actual": 0}
            for i in range(nbins)]
    n_total = 0
    ece_num = 0.0
    for obj, y in _iter_sample_rows():
        p = obj.get("mkt_implied_yes_from_ask")
        if p is None:
            p = obj.get("executable_yes_buy_price")
        if p is None:
            continue
        p = max(0.0, min(1.0, float(p)))
        idx = min(int(p * nbins), nbins - 1)
        b = bins[idx]
        b["n"] += 1
        b["sum_pred"] += p
        b["sum_actual"] += y
        n_total += 1
    points = []
    for b in bins:
        if b["n"] == 0:
            continue
        mp = b["sum_pred"] / b["n"]
        ma = b["sum_actual"] / b["n"]
        points.append({"mean_pred": round(mp, 4), "mean_actual": round(ma, 4), "count": b["n"]})
        ece_num += b["n"] * abs(mp - ma)
    ece = (ece_num / n_total) if n_total else None
    return {"series": "market_implied", "n": n_total,
            "ece_sample": round(ece, 4) if ece is not None else None, "points": points}


def market_reliability_by_coin() -> list[dict]:
    """Per-coin market-implied ECE from the committed multi-coin sample — shows the
    market price is the best-calibrated forecaster on every coin, not just BTC."""
    agg: dict[str, dict] = {}
    for obj, y in _iter_sample_rows():
        mt = obj.get("market_ticker") or ""
        coin = mt.split("-")[0].replace("KX", "").replace("15M", "") or "?"
        p = obj.get("mkt_implied_yes_from_ask")
        if p is None:
            p = obj.get("executable_yes_buy_price")
        if p is None:
            continue
        p = max(0.0, min(1.0, float(p)))
        a = agg.setdefault(coin, {"n": 0, "bins": {}})
        a["n"] += 1
        idx = min(int(p * 10), 9)
        b = a["bins"].setdefault(idx, {"n": 0, "sp": 0.0, "sa": 0})
        b["n"] += 1; b["sp"] += p; b["sa"] += y
    out = []
    for coin, a in agg.items():
        ece = sum(b["n"] * abs(b["sp"] / b["n"] - b["sa"] / b["n"]) for b in a["bins"].values())
        out.append({"coin": coin, "n": a["n"], "ece": round(ece / a["n"], 4) if a["n"] else None,
                    "windows": None})
    order = {"BTC": 0, "ETH": 1, "SOL": 2, "DOGE": 3, "XRP": 4}
    out.sort(key=lambda r: order.get(r["coin"], 9))
    return out


def isotonic_reliability() -> dict:
    """The committed model raw-vs-calibrated reliability buckets (sample isotonic)."""
    path = EXPECTED / "kalshi_reliability_table.csv"
    before, after = [], []
    txt = _read_text(path)
    if not txt:
        return {"before": [], "after": [], "missing": True}
    for row in csv.DictReader(txt.splitlines()):
        pt = {"bucket": row["bucket"], "mean_pred": float(row["mean_pred"]),
              "mean_actual": float(row["mean_actual"]), "count": int(row["count"])}
        (before if row["phase"] == "before" else after).append(pt)
    return {"before": before, "after": after,
            "source": "sample_data/expected/kalshi_reliability_table.csv"}


def _parse_backtest_report() -> dict:
    """Parse the committed executable-backtest report into per-model stats."""
    txt = _read_text(EXPECTED / "kalshi_baseline_backtest.md")
    if not txt:
        return {"models": [], "missing": True}
    models = []
    # split on "### <name>" sections
    for block in re.split(r"\n### ", "\n" + txt)[1:]:
        lines = block.splitlines()
        name = lines[0].strip()
        body = "\n".join(lines[1:])

        def num(pattern, cast=float):
            m = re.search(pattern, body)
            if not m:
                return None
            try:
                return cast(m.group(1))
            except Exception:
                return None

        rec = {
            "model": name,
            "trades": num(r"trades:\s*([\-\d.]+)", int),
            "net_pnl": num(r"net_pnl:\s*([\-\d.]+)"),
            "gross_pnl": num(r"gross_pnl:\s*([\-\d.]+)"),
            "per_contract": num(r"realized_pnl_per_contract:\s*([\-\d.]+)"),
            "hit_rate": num(r"hit_rate:\s*([\-\d.]+)"),
            "avg_fee": num(r"avg_fee:\s*([\-\d.]+)"),
            "max_drawdown": num(r"max_drawdown:\s*([\-\d.]+)"),
            "profit_factor": num(r"profit_factor:\s*([\-\d.]+)"),
            "ece": num(r"'ece':\s*([\-\d.]+)"),
            "brier": num(r"'brier':\s*([\-\d.]+)"),
        }
        # fee decomposition: gross -> fees -> net (fees = gross - net)
        if rec["net_pnl"] is not None and rec["gross_pnl"] is not None:
            rec["fee_burden"] = round(rec["gross_pnl"] - rec["net_pnl"], 3)
        # walk-forward folds
        wf = re.search(r"walk_forward_stability:\s*(\[.*\])", body)
        if wf:
            try:
                rec["walk_forward"] = json.loads(wf.group(1).replace("'", '"'))
            except Exception:
                rec["walk_forward"] = None
        # rejections
        rj = re.search(r"rejected_rows_by_reason:\s*(\{.*\})", body)
        if rj:
            try:
                rec["rejections"] = json.loads(rj.group(1).replace("'", '"'))
            except Exception:
                rec["rejections"] = None
        if name != "no_trade":
            models.append(rec)
    split = re.search(r"split:\s*(\{.*\})", txt)
    gate = re.search(r"gate_windows:\s*(\d+)\s*/\s*backtest gate\s*(\d+)", txt)
    return {
        "models": models,
        "gate_windows": int(gate.group(1)) if gate else None,
        "backtest_gate": int(gate.group(2)) if gate else None,
        "diagnostic_only": True,
        "source": "sample_data/expected/kalshi_baseline_backtest.md",
    }


def _parse_calibration_report() -> dict:
    txt = _read_text(EXPECTED / "kalshi_calibration_report.md")
    if not txt:
        return {"missing": True}
    out = {"source": "sample_data/expected/kalshi_calibration_report.md"}
    method = re.search(r"method:\s*(\w+)", txt)
    out["method"] = method.group(1) if method else None
    # metrics table rows: | metric | before | after |
    metrics = {}
    for m in re.finditer(r"\|\s*(brier|log_loss|ECE|slope|intercept|n)\s*\|\s*([\-\d.]+)\s*\|\s*([\-\d.]+)\s*\|", txt):
        metrics[m.group(1).lower()] = {"before": float(m.group(2)), "after": float(m.group(3))}
    out["metrics"] = metrics
    return out


def calibration_view() -> dict:
    return {
        "market_reliability": market_reliability(),
        "market_by_coin": market_reliability_by_coin(),
        "isotonic": isotonic_reliability(),
        "calibration_report": _parse_calibration_report(),
        "backtest_calibration": [
            {"model": m["model"], "ece": m.get("ece"), "brier": m.get("brier")}
            for m in _parse_backtest_report().get("models", [])
        ],
        "headline_ece": {
            "market_implied": load_headline().get("tiles", [{}])[0].get("value"),
            "best_model": next((t["value"] for t in load_headline().get("tiles", [])
                                if t.get("key") == "best_model_window_ece"), None),
        },
    }


def backtest_view() -> dict:
    return _parse_backtest_report()


# --------------------------------------------------------------------------- #
# Replay                                                                       #
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def load_replay() -> dict:
    frames = _read_json(SAMPLE / "replay_window" / "frames.json")
    meta = _read_json(SAMPLE / "replay_window" / "meta.json")
    if not frames or not meta:
        return {"frames": [], "meta": {}, "missing": True}
    return {"frames": frames.get("frames", []), "meta": meta}


def health() -> dict:
    """Which committed artifacts are present (for the empty-state UI + tests)."""
    return {
        "ledger": bool(load_ledger().get("legs")),
        "headline": bool(load_headline().get("tiles")),
        "sample_features": any((SAMPLE / "features").glob("*.jsonl")),
        "backtest_report": (EXPECTED / "kalshi_baseline_backtest.md").exists(),
        "replay": bool(load_replay().get("frames")),
    }
