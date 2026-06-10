"""Kalshi BTC repricing-lag / stale-quote STRUCTURAL-EDGE event study (READ-ONLY research).

Question (NOT "will BTC finish up?"): after a Coinbase/Binance move, does Kalshi's
EXECUTABLE binary book lag enough that a YES/NO ask is temporarily stale *after fees,
spread, depth, and a conservative uncertainty buffer*?

Method: operate on the recorded, point-in-time ``kalshi_feature_rows-*.jsonl`` (the
collector already joins the Kalshi book + Coinbase/Binance microstructure + start
reference + Deribit regime per ``as_of_ms`` with no look-ahead). For each in-window
row we (A) detect a BTC shock from precomputed returns/flow, (B) measure how the
Kalshi book moves over later horizons, (C) flag a stale executable quote using ONLY
shock-time information vs a transparent underlying-implied probability proxy (D),
(E) de-duplicate to distinct micro-opportunities/windows, and (F) score realized
outcomes from OFFICIAL settlement labels (used for EVALUATION ONLY, never as signal).

DATA-RESOLUTION CAVEAT (surfaced in every report): all recorded streams — Coinbase,
Binance AND the Kalshi book — are polled on the SAME ~4-second clock. There is no
sub-4s data, so a 1-3s repricing lag is NOT directly measurable here; sub-cadence
horizons (+1s/+2s) will not resolve. This study measures what the ~4s cadence allows
and is explicit about that ceiling.

SAFETY: reads recorded data only; writes reports/CSVs under reports/reprice_lag/ only.
Never trades, never enables paper/live, never submits orders, never promotes/demotes,
never touches model/calibrator/policy pointers or the promotion manifest, never weakens
a gate or removes a buffer. ``live_submission_allowed`` is always False. No profitability
or alpha is asserted — outputs are an event-study diagnostic.
"""

from __future__ import annotations

import bisect
import csv
import glob
import json
import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from ...models.baseline import BaselineInputs, normal_prob_yes
from ...schemas import Comparison
from .edge_policy import EdgePolicyConfig
from .fees import KalshiFeeModel

# --------------------------------------------------------------------------- #
# Defaults (configurable; the report ships a sensitivity grid, not one number)
# --------------------------------------------------------------------------- #
PRE_HORIZONS_S = (-30, -15, -5)
POST_HORIZONS_S = (1, 2, 5, 10, 15, 30, 60)          # +1/+2 won't resolve at ~4s cadence
DEFAULT_RETURN_BPS = {5: 5.0, 15: 8.0, 30: 12.0, 60: 16.0}
PERMISSIVE_RETURN_BPS = {5: 3.0, 15: 4.0, 30: 6.0, 60: 8.0}   # superset detection floor
SENSITIVITY_BPS_GRID = (3.0, 5.0, 8.0, 12.0, 16.0, 20.0)
DEFAULT_VOLNORM_SIGMA = 1.0
DEFAULT_BASIS_JUMP_USD = 5.0
DEFAULT_OFI_PCTILE = 0.95
DEFAULT_NEAR_LINE_USD = 25.0
DEDUP_WINDOW_S = 20.0
HORIZON_TOL_S = 2.5                                   # nearest-row tolerance (~4s grid)
MOVE_DETECT_CENTS = 2.0                               # "time until Kalshi moves >= X cents"
SAMPLING_CADENCE_S = 4.0                              # observed recorded poll cadence


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _f(x, nd=4) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "None"


def _pct(x) -> str:
    return "n/a" if x is None else f"{x*100:.0f}%"


def _median(xs):
    v = sorted(x for x in xs if isinstance(x, (int, float)))
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _mean(xs):
    v = [x for x in xs if isinstance(x, (int, float))]
    return (sum(v) / len(v)) if v else None


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass
class ShockConfig:
    return_bps: dict = field(default_factory=lambda: dict(DEFAULT_RETURN_BPS))
    volnorm_sigma: float = DEFAULT_VOLNORM_SIGMA
    basis_jump_usd: float = DEFAULT_BASIS_JUMP_USD
    ofi_pctile: float = DEFAULT_OFI_PCTILE
    near_line_usd: float = DEFAULT_NEAR_LINE_USD
    ofi_abs_thr: Optional[float] = None              # computed per-day from population


@dataclass
class StudyConfig:
    min_depth: float = 1.0                            # min executable ask size (contracts)
    min_seconds_to_close: float = 60.0               # avoid settlement race
    max_seconds_to_close: Optional[float] = None
    max_book_age_ms: float = 5000.0                   # ~one poll at the ~4s cadence
    conservative_buffer_cents: float = 3.0           # mirrors edge_policy fixed buffer (added, never removed)
    min_opp_edge_cents: float = 0.0
    dedup_window_s: float = DEDUP_WINDOW_S
    include_deribit: bool = True
    include_polymarket: bool = False

    @classmethod
    def from_app(cls, config, **over) -> "StudyConfig":
        c = cls()
        ep = EdgePolicyConfig.from_app(config)
        # tie the conservative buffer + min-profit to the REAL policy (consistency, not weakening)
        c.conservative_buffer_cents = float(ep.fixed_uncertainty_buffer_cents)
        c.min_opp_edge_cents = 0.0
        for k, v in over.items():
            if v is not None and hasattr(c, k):
                setattr(c, k, v)
        return c


# Slim projection of the feature-row fields this study uses.
_FIELDS = (
    "market_ticker", "series_ticker", "event_ticker", "as_of_ms", "seconds_to_close", "status",
    "yes_bid", "yes_ask", "no_bid", "no_ask", "yes_ask_size", "no_ask_size", "top_depth",
    "depth_imbalance", "executable_yes_buy_price", "executable_no_buy_price", "spread_yes",
    "book_age_ms", "quote_age_ms", "mkt_implied_yes_from_ask", "reference_price",
    "reference_start_price", "distance_to_start", "distance_to_line_vol_normalized",
    "has_start_reference", "has_orderbook", "incomplete_book", "thin_book", "feed_health_ok",
    "spot_sigma_per_sqrt_s", "spot_return_5s", "spot_return_15s", "spot_return_30s",
    "spot_return_60s", "spot_perp_basis", "spot_perp_basis_change_60s", "binance_ofi_best",
    "binance_queue_imbalance", "perp_cvd_60s", "perp_signed_trade_imbalance_60s",
    "realized_vol_60s", "realized_vol_180s", "coinbase_stale", "binance_stale",
    "fee_estimate_per_contract", "fee_status", "deribit_available", "deribit_used",
    "deribit_stale", "deribit_regime", "deribit_dvol", "deribit_atm_iv",
    "deribit_iv_minus_realized_vol_60s", "deribit_skew_proxy", "deribit_age_ms",
)


# --------------------------------------------------------------------------- #
# Loading (per-day; tickers never span days, so memory stays bounded)
# --------------------------------------------------------------------------- #
def _date_in_range(day: str, date, start, end) -> bool:
    if date:
        return day == str(date)
    if start and day < str(start):
        return False
    if end and day > str(end):
        return False
    return True


def feature_files(config, *, date=None, start_date=None, end_date=None) -> list[str]:
    d = config.data_path() / "features"
    out = []
    for p in sorted(glob.glob(str(d / "kalshi_feature_rows-*.jsonl"))):
        day = os.path.basename(p).replace("kalshi_feature_rows-", "").replace(".jsonl", "")
        if _date_in_range(day, date, start_date, end_date):
            out.append(p)
    return out


def _day_of(path: str) -> str:
    return os.path.basename(path).replace("kalshi_feature_rows-", "").replace(".jsonl", "")


def load_day_rows(path: str, series: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if series and o.get("series_ticker") not in (series, None):
                continue
            if o.get("as_of_ms") is None or o.get("market_ticker") is None:
                continue
            rows.append({k: o.get(k) for k in _FIELDS})
    return rows


def load_labels(config, tickers: set[str]) -> dict:
    out = {}
    for lf in glob.glob(str(config.data_path() / "labels" / "kalshi_settlement_labels-*.jsonl")):
        with open(lf, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mt = o.get("market_ticker")
                if mt in tickers and o.get("label_yes_resolved") is not None:
                    out[mt] = {"label_yes_resolved": int(o["label_yes_resolved"]),
                               "reference_start_price": o.get("reference_start_price"),
                               "close_ms": o.get("close_ms")}
    return out


# --------------------------------------------------------------------------- #
# Probabilities
# --------------------------------------------------------------------------- #
def market_implied_yes(row) -> Optional[float]:
    m = row.get("mkt_implied_yes_from_ask")
    if isinstance(m, (int, float)):
        return float(m)
    ya, na = row.get("yes_ask"), row.get("no_ask")
    if ya is None:
        return None
    if na is not None and (ya + na) > 0:
        return max(0.0, min(1.0, ya / (ya + na)))
    return max(0.0, min(1.0, ya))


def baseline_p_yes(row) -> Optional[float]:
    """Transparent underlying-implied PROXY (driftless lognormal). NOT a true probability."""
    S, L = row.get("reference_price"), row.get("reference_start_price")
    if S is None or L is None:
        return None
    return normal_prob_yes(BaselineInputs(
        reference_price=S, line=L, seconds_to_expiry=row.get("seconds_to_close"),
        sigma_per_sqrt_s=row.get("spot_sigma_per_sqrt_s"), comparison=Comparison.GTE))


def entry_price(side: str, row) -> Optional[float]:
    if side == "YES":
        return row.get("executable_yes_buy_price") or row.get("yes_ask")
    return row.get("executable_no_buy_price") or row.get("no_ask")


def avail_size(side: str, row) -> Optional[float]:
    return row.get("yes_ask_size") if side == "YES" else row.get("no_ask_size")


# --------------------------------------------------------------------------- #
# Part A — shock detection (uses only fields in the row; no look-ahead)
# --------------------------------------------------------------------------- #
def _percentile(values, q) -> Optional[float]:
    v = sorted(values)
    if not v:
        return None
    k = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[k]


def detect_shock(row, scfg: ShockConfig) -> Optional[dict]:
    """Return shock descriptor for a row if any momentum/flow signal fires, else None."""
    sigs = []
    sigma = row.get("spot_sigma_per_sqrt_s")
    best_bps = 0.0
    best_sig_dir = None
    volnorm_max = 0.0
    abs_ret_bps = 0.0                                  # raw max |return| over horizons (threshold-free)
    for h, thr in scfg.return_bps.items():
        ret = row.get(f"spot_return_{h}s")
        if ret is None:
            continue
        bps = ret * 1e4
        abs_ret_bps = max(abs_ret_bps, abs(bps))
        if abs(bps) >= thr:
            sigs.append(f"ret_{h}s")
            if abs(bps) > abs(best_bps):
                best_bps = bps
                best_sig_dir = "up" if bps > 0 else "down"
        if sigma and sigma > 0:
            sn = ret / (sigma * math.sqrt(h))
            if abs(sn) >= scfg.volnorm_sigma:
                sigs.append(f"volnorm_{h}s")
                volnorm_max = max(volnorm_max, abs(sn))
                if best_sig_dir is None:
                    best_sig_dir = "up" if sn > 0 else "down"
    basis_ch = row.get("spot_perp_basis_change_60s")
    if basis_ch is not None and abs(basis_ch) >= scfg.basis_jump_usd:
        sigs.append("basis_jump")
    ofi = row.get("binance_ofi_best")
    if ofi is not None and scfg.ofi_abs_thr is not None and abs(ofi) >= scfg.ofi_abs_thr:
        sigs.append("ofi_impulse")
        if best_sig_dir is None:
            best_sig_dir = "up" if ofi > 0 else "down"
    cvd = row.get("perp_cvd_60s")
    if cvd is not None and best_sig_dir is None and abs(cvd) > 0:
        # CVD only sets direction when nothing else did (kept conservative)
        pass
    if not sigs or best_sig_dir is None:
        return None
    dist = row.get("distance_to_start")
    near_line = (dist is not None and abs(dist) <= scfg.near_line_usd)
    return {
        "direction": best_sig_dir, "signals": sigs, "ret_bps": best_bps,
        "abs_ret_bps": abs_ret_bps, "volnorm_max": volnorm_max, "near_line": near_line,
        "distance_to_start": dist,
    }


# --------------------------------------------------------------------------- #
# Part B/D — Kalshi response + underlying-implied proxy over horizons
# --------------------------------------------------------------------------- #
class _TickerSeries:
    """Time-ordered rows for one ticker with nearest-by-time lookup."""

    def __init__(self, rows: list[dict]):
        self.rows = sorted(rows, key=lambda r: r["as_of_ms"])
        self.ts = [r["as_of_ms"] for r in self.rows]

    def nearest(self, target_ms: float, tol_ms: float) -> Optional[dict]:
        if not self.ts:
            return None
        i = bisect.bisect_left(self.ts, target_ms)
        best, bestd = None, None
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(self.ts):
                d = abs(self.ts[j] - target_ms)
                if bestd is None or d < bestd:
                    best, bestd = self.rows[j], d
        if best is not None and bestd is not None and bestd <= tol_ms:
            return best
        return None


def measure_response(series: _TickerSeries, shock_row: dict, *, tol_ms=HORIZON_TOL_S * 1000) -> dict:
    t0 = shock_row["as_of_ms"]
    mkt0 = market_implied_yes(shock_row)
    base0 = baseline_p_yes(shock_row)
    out = {"mkt0": mkt0, "base0": base0, "horizons": {}}
    for h in (*PRE_HORIZONS_S, 0, *POST_HORIZONS_S):
        r = shock_row if h == 0 else series.nearest(t0 + h * 1000, tol_ms)
        if r is None:
            out["horizons"][h] = None
            continue
        mkt = market_implied_yes(r)
        base = baseline_p_yes(r)
        out["horizons"][h] = {
            "offset_s": round((r["as_of_ms"] - t0) / 1000.0, 1),
            "mkt": mkt, "base": base,
            "yes_ask": r.get("yes_ask"), "no_ask": r.get("no_ask"),
            "spread_yes": r.get("spread_yes"), "top_depth": r.get("top_depth"),
            "mkt_change_c": ((mkt - mkt0) * 100.0) if (mkt is not None and mkt0 is not None) else None,
            "base_change_c": ((base - base0) * 100.0) if (base is not None and base0 is not None) else None,
        }
    # time until Kalshi market-implied moves >= MOVE_DETECT_CENTS (signed toward shock dir)
    tmove = None
    for h in POST_HORIZONS_S:
        hz = out["horizons"].get(h)
        if hz and hz["mkt_change_c"] is not None and abs(hz["mkt_change_c"]) >= MOVE_DETECT_CENTS:
            tmove = hz["offset_s"]
            break
    out["time_to_move_s"] = tmove
    # lag at the first resolved post-horizon: how much baseline moved that the market did not
    lag = None
    for h in POST_HORIZONS_S:
        hz = out["horizons"].get(h)
        if hz and hz["base_change_c"] is not None and hz["mkt_change_c"] is not None:
            lag = hz["base_change_c"] - hz["mkt_change_c"]
            out["lag_horizon_s"] = hz["offset_s"]
            break
    out["lag_cents"] = lag
    return out


# --------------------------------------------------------------------------- #
# Part C — stale executable opportunity (qualified using ONLY shock-time info)
# --------------------------------------------------------------------------- #
def qualify_opportunity(shock_row: dict, shock: dict, scfg_unused, study: StudyConfig,
                        fee_model: KalshiFeeModel) -> Optional[dict]:
    side = "YES" if shock["direction"] == "up" else "NO"
    stc = shock_row.get("seconds_to_close")
    ask = entry_price(side, shock_row)
    size = avail_size(side, shock_row)
    bp = baseline_p_yes(shock_row)
    reasons = []
    if shock_row.get("status") not in ("active", None):
        reasons.append("not_active")
    if stc is None or stc <= 0:
        reasons.append("not_in_window")
    if not shock_row.get("has_start_reference") or shock_row.get("reference_start_price") is None:
        reasons.append("no_start_reference")
    if ask is None or not (0.0 < ask < 1.0):
        reasons.append("no_executable_ask")
    if bp is None:
        reasons.append("no_baseline_proxy")
    if size is None or size < study.min_depth:
        reasons.append("insufficient_depth")
    ba = shock_row.get("book_age_ms")
    if ba is None or ba > study.max_book_age_ms:
        reasons.append("book_stale")
    if shock_row.get("coinbase_stale") or shock_row.get("binance_stale") or shock_row.get("feed_health_ok") is False:
        reasons.append("underlying_stale")
    if shock_row.get("incomplete_book"):
        reasons.append("incomplete_book")
    if stc is not None and stc < study.min_seconds_to_close:
        reasons.append("settlement_race")
    if study.max_seconds_to_close is not None and stc is not None and stc > study.max_seconds_to_close:
        reasons.append("outside_ttc_window")

    p_side = (bp if side == "YES" else (1.0 - bp)) if bp is not None else None
    fee = fee_model.per_contract_fee(ask) if (ask is not None and 0.0 < ask < 1.0) else None
    gross_edge_c = ((p_side - ask) * 100.0) if (p_side is not None and ask is not None) else None
    net_edge_c = (gross_edge_c - fee * 100.0) if (gross_edge_c is not None and fee is not None) else None
    cons_edge_c = (net_edge_c - study.conservative_buffer_cents) if net_edge_c is not None else None
    if cons_edge_c is None or cons_edge_c < study.min_opp_edge_cents:
        reasons.append("no_fee_buffer_edge")
    if reasons:
        return {"qualified": False, "reasons": reasons, "side": side}
    return {
        "qualified": True, "side": side, "entry_price": ask, "avail_size": size,
        "baseline_p_yes": bp, "p_side": p_side, "market_implied_yes": market_implied_yes(shock_row),
        "fee_cents": fee * 100.0, "gross_edge_cents": gross_edge_c,
        "net_edge_cents": net_edge_c, "conservative_edge_cents": cons_edge_c,
    }


# --------------------------------------------------------------------------- #
# Buckets / regime tags
# --------------------------------------------------------------------------- #
def time_bucket(stc) -> str:
    if stc is None:
        return "unknown"
    if stc >= 720:
        return "near-open"
    if stc <= 180:
        return "near-close"
    return "mid"


def line_bucket(dist) -> str:
    if dist is None:
        return "unknown"
    a = abs(dist)
    if a <= 25:
        return "near-line"
    if a <= 100:
        return "mid"
    return "far-line"


def vol_bucket(sig, lo, hi) -> str:
    if sig is None or lo is None or hi is None:
        return "unknown"
    if sig <= lo:
        return "low-vol"
    if sig >= hi:
        return "high-vol"
    return "mid-vol"


# --------------------------------------------------------------------------- #
# Part E — de-duplication into distinct micro-opportunities
# --------------------------------------------------------------------------- #
def dedup_events(events: list[dict], window_s: float) -> list[dict]:
    """Collapse events sharing (ticker, side/direction) within window_s into one opportunity."""
    by = defaultdict(list)
    for e in events:
        by[(e["ticker"], e["direction"])].append(e)
    opps = []
    for key, evs in by.items():
        evs.sort(key=lambda e: e["as_of_ms"])
        cur = None
        for e in evs:
            if cur and (e["as_of_ms"] - cur["_last_ts"]) <= window_s * 1000:
                cur["n_obs"] += 1
                cur["_last_ts"] = e["as_of_ms"]
                continue
            cur = dict(e)
            cur["n_obs"] = 1
            cur["_last_ts"] = e["as_of_ms"]
            opps.append(cur)
    return opps


# --------------------------------------------------------------------------- #
# Core per-day processing -> superset of detected shock events with response + t0 edge
# --------------------------------------------------------------------------- #
def _process_day(rows: list[dict], labels: dict, study: StudyConfig, fee_model: KalshiFeeModel,
                 *, detect_cfg: ShockConfig) -> list[dict]:
    by_ticker = defaultdict(list)
    for r in rows:
        by_ticker[r["market_ticker"]].append(r)
    # per-day OFI population threshold
    ofis = [abs(r["binance_ofi_best"]) for r in rows if isinstance(r.get("binance_ofi_best"), (int, float))]
    detect_cfg.ofi_abs_thr = _percentile(ofis, detect_cfg.ofi_pctile)
    # per-day vol terciles for regime tagging
    sigs = sorted(r["spot_sigma_per_sqrt_s"] for r in rows if isinstance(r.get("spot_sigma_per_sqrt_s"), (int, float)))
    vlo = _percentile(sigs, 1 / 3) if sigs else None
    vhi = _percentile(sigs, 2 / 3) if sigs else None

    events = []
    for ticker, trows in by_ticker.items():
        series = _TickerSeries(trows)
        lab = labels.get(ticker, {})
        for r in series.rows:
            shock = detect_shock(r, detect_cfg)
            if shock is None:
                continue
            resp = measure_response(series, r)
            opp = qualify_opportunity(r, shock, detect_cfg, study, fee_model)
            ev = {
                "day": None, "ticker": ticker, "window_et": ticker.split("-")[1][7:] if "-" in ticker else ticker,
                "as_of_ms": r["as_of_ms"],
                "timestamp_utc": datetime.fromtimestamp(r["as_of_ms"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "seconds_to_close": r.get("seconds_to_close"), "direction": shock["direction"],
                "signals": "|".join(shock["signals"]), "ret_bps": shock["ret_bps"],
                "abs_ret_bps": shock["abs_ret_bps"],
                "volnorm_max": shock["volnorm_max"], "near_line": shock["near_line"],
                "distance_to_start": r.get("distance_to_start"),
                "time_bucket": time_bucket(r.get("seconds_to_close")),
                "line_bucket": line_bucket(r.get("distance_to_start")),
                "vol_bucket": vol_bucket(r.get("spot_sigma_per_sqrt_s"), vlo, vhi),
                "yes_ask": r.get("yes_ask"), "no_ask": r.get("no_ask"),
                "book_age_ms": r.get("book_age_ms"),
                "mkt_implied_yes": resp["mkt0"], "baseline_p_yes": resp["base0"],
                "time_to_move_s": resp["time_to_move_s"], "lag_cents": resp["lag_cents"],
                "lag_horizon_s": resp.get("lag_horizon_s"),
                "resp_p5": (resp["horizons"].get(5) or {}).get("mkt_change_c"),
                "resp_p10": (resp["horizons"].get(10) or {}).get("mkt_change_c"),
                "resp_p30": (resp["horizons"].get(30) or {}).get("mkt_change_c"),
                # Deribit regime (already point-in-time in the row)
                "deribit_available": r.get("deribit_available"), "deribit_regime": r.get("deribit_regime"),
                "deribit_dvol": r.get("deribit_dvol"),
                "deribit_iv_minus_realized_vol_60s": r.get("deribit_iv_minus_realized_vol_60s"),
                "deribit_skew_proxy": r.get("deribit_skew_proxy"),
                # opportunity (t0-only) qualification
                "opp_qualified": opp.get("qualified", False),
                "opp_reasons": "" if opp.get("qualified") else "|".join(opp.get("reasons", [])),
                "opp_side": opp.get("side"),
                "entry_price": opp.get("entry_price"), "avail_size": opp.get("avail_size"),
                "fee_cents": opp.get("fee_cents"), "gross_edge_cents": opp.get("gross_edge_cents"),
                "net_edge_cents": opp.get("net_edge_cents"),
                "conservative_edge_cents": opp.get("conservative_edge_cents"),
                # outcome (EVALUATION ONLY)
                "settle_label_yes": lab.get("label_yes_resolved"),
            }
            events.append(ev)
    return events


def _attach_outcomes(opps: list[dict], fee_model: KalshiFeeModel) -> None:
    for o in opps:
        lab = o.get("settle_label_yes")
        if lab is None or not o.get("opp_qualified"):
            o["win"] = None
            o["pnl_net"] = None
            continue
        side = o["opp_side"]
        win = int((side == "YES") == (lab == 1))
        entry = o["entry_price"]
        fee = fee_model.per_contract_fee(entry) if entry else 0.0
        gross = (1.0 - entry) if win else (-entry)
        o["win"] = win
        o["pnl_gross"] = gross
        o["pnl_net"] = gross - fee


# --------------------------------------------------------------------------- #
# Aggregation helpers
# --------------------------------------------------------------------------- #
def _group_stats(opps, keyfn):
    g = defaultdict(lambda: {"n": 0, "win": 0, "loss": 0, "pnl": [], "windows": set()})
    for o in opps:
        if not o.get("opp_qualified"):
            continue
        k = keyfn(o)
        d = g[k]
        d["n"] += 1
        d["windows"].add(o["ticker"])
        if o.get("win") == 1:
            d["win"] += 1
        elif o.get("win") == 0:
            d["loss"] += 1
        if isinstance(o.get("pnl_net"), (int, float)):
            d["pnl"].append(o["pnl_net"])
    return {k: {"n": v["n"], "win": v["win"], "loss": v["loss"],
                "windows": len(v["windows"]),
                "win_rate": (v["win"] / (v["win"] + v["loss"])) if (v["win"] + v["loss"]) else None,
                "avg_pnl_net": _mean(v["pnl"])} for k, v in g.items()}


# --------------------------------------------------------------------------- #
# Polymarket comparability (Part H — reference only)
# --------------------------------------------------------------------------- #
def classify_polymarket_comparability(config, *, date=None, start_date=None, end_date=None) -> dict:
    files = []
    for p in sorted(glob.glob(str(config.data_path() / "normalized" / "polymarket_book-*.jsonl"))):
        day = os.path.basename(p).replace("polymarket_book-", "").replace(".jsonl", "")
        if _date_in_range(day, date, start_date, end_date):
            files.append(p)
    present = bool(files)
    reasons = [
        "window length differs: Kalshi KXBTC15M = 15-minute vs Polymarket btc-updown-5m = 5-minute",
        "settlement source differs: Kalshi BRTI 60s-average (GTE) vs Polymarket Chainlink stream",
        "start-reference/line capture differs (kalshi_target_price vs coinbase provisional)",
        "different venue book microstructure and tick/fee model",
    ]
    return {
        "data_present": present, "files": [os.path.basename(f) for f in files],
        "classification": "not_comparable" if present else "not_available",
        "reasons": reasons,
        "note": ("Polymarket book exists but is a different instrument; usable only as a loose "
                 "reference for whether a venue reprices around BTC moves, NOT for cross-venue "
                 "trading. No cross-venue logic implemented (out of scope)."),
    }


# --------------------------------------------------------------------------- #
# Report writers
# --------------------------------------------------------------------------- #
def _reports_dir(config) -> Path:
    d = config.reports_path() / "reprice_lag"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_events_csv(path: Path, events: list[dict]) -> None:
    cols = ["day", "ticker", "window_et", "timestamp_utc", "as_of_ms", "seconds_to_close",
            "time_bucket", "line_bucket", "vol_bucket", "direction", "signals", "ret_bps",
            "volnorm_max", "near_line", "distance_to_start", "yes_ask", "no_ask", "book_age_ms",
            "mkt_implied_yes", "baseline_p_yes", "time_to_move_s", "lag_cents", "lag_horizon_s",
            "resp_p5", "resp_p10", "resp_p30", "deribit_available", "deribit_regime", "deribit_dvol",
            "opp_qualified", "opp_reasons", "opp_side", "entry_price", "avail_size", "fee_cents",
            "gross_edge_cents", "net_edge_cents", "conservative_edge_cents", "settle_label_yes"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for e in events:
            w.writerow(e)


def _write_opps_csv(path: Path, opps: list[dict]) -> None:
    cols = ["day", "ticker", "window_et", "timestamp_utc", "seconds_to_close", "time_bucket",
            "line_bucket", "vol_bucket", "direction", "opp_side", "n_obs", "entry_price",
            "avail_size", "baseline_p_yes", "mkt_implied_yes", "fee_cents", "gross_edge_cents",
            "net_edge_cents", "conservative_edge_cents", "time_to_move_s", "lag_cents",
            "deribit_regime", "settle_label_yes", "win", "pnl_net"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for o in opps:
            w.writerow(o)


def _write_deribit_csv(path: Path, opps: list[dict]) -> dict:
    stats = _group_stats(opps, lambda o: str(o.get("deribit_regime")))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["deribit_regime", "opportunities", "distinct_windows", "win", "loss",
                    "win_rate", "avg_pnl_net"])
        for k, v in sorted(stats.items()):
            w.writerow([k, v["n"], v["windows"], v["win"], v["loss"], _f(v["win_rate"], 3),
                        _f(v["avg_pnl_net"], 4)])
    return stats


def _write_sensitivity_csv(path: Path, grid: list[dict]) -> None:
    cols = ["shock_threshold_bps", "raw_shock_rows", "dedup_events", "distinct_windows",
            "qualified_opps", "qualified_windows", "opp_win_rate", "avg_net_pnl"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in grid:
            w.writerow(row)


# --------------------------------------------------------------------------- #
# Top-level study
# --------------------------------------------------------------------------- #
def run_reprice_lag_study(config, *, series: str = "KXBTC15M", date=None, start_date=None,
                          end_date=None, shock_threshold_bps=None, min_depth=None,
                          min_seconds_to_close=None, max_seconds_to_close=None,
                          include_deribit=True, include_polymarket=False,
                          write_md=True, write_csv=True) -> dict:
    base = {"series": series, "live_submission_allowed": False, "mode": "event_study",
            "sampling_cadence_s": SAMPLING_CADENCE_S}
    files = feature_files(config, date=date, start_date=start_date, end_date=end_date)
    if not files:
        return {**base, "status": "NO_DATA",
                "note": "no kalshi_feature_rows-*.jsonl matched the date filter"}

    study = StudyConfig.from_app(config, min_depth=min_depth,
                                 min_seconds_to_close=min_seconds_to_close,
                                 max_seconds_to_close=max_seconds_to_close,
                                 include_deribit=include_deribit,
                                 include_polymarket=include_polymarket)
    fee_model = KalshiFeeModel.from_config(config)
    # detect with a PERMISSIVE superset; the requested/default thresholds are applied as a filter
    detect_cfg = ShockConfig(return_bps=dict(PERMISSIVE_RETURN_BPS))
    default_bps = dict(DEFAULT_RETURN_BPS)
    if shock_threshold_bps is not None:
        # scale all horizon thresholds to the requested 5s-equivalent floor
        default_bps = {5: float(shock_threshold_bps), 15: float(shock_threshold_bps) * 1.6,
                       30: float(shock_threshold_bps) * 2.4, 60: float(shock_threshold_bps) * 3.2}

    all_events = []
    days = []
    for p in files:
        day = _day_of(p)
        days.append(day)
        rows = load_day_rows(p, series)
        if not rows:
            continue
        labels = load_labels(config, {r["market_ticker"] for r in rows})
        evs = _process_day(rows, labels, study, fee_model, detect_cfg=ShockConfig(
            return_bps=dict(PERMISSIVE_RETURN_BPS), volnorm_sigma=detect_cfg.volnorm_sigma,
            basis_jump_usd=detect_cfg.basis_jump_usd, ofi_pctile=detect_cfg.ofi_pctile,
            near_line_usd=detect_cfg.near_line_usd))
        for e in evs:
            e["day"] = day
        all_events.extend(evs)

    # apply the requested/default shock threshold as a filter over the superset
    def passes_default(e):
        return abs(e["ret_bps"]) >= default_bps[5] or e["volnorm_max"] >= study_volnorm()

    def study_volnorm():
        return DEFAULT_VOLNORM_SIGMA

    shock_events = [e for e in all_events if passes_default(e)]
    # opportunities: qualified shock events, then de-duplicated to distinct micro-opportunities
    qualified = [e for e in shock_events if e["opp_qualified"]]
    opps = dedup_events(qualified, study.dedup_window_s)
    _attach_outcomes(opps, fee_model)

    # ---- aggregates
    distinct_windows_shocks = len({e["ticker"] for e in shock_events})
    distinct_windows_opps = len({o["ticker"] for o in opps})
    distinct_days = len({e["day"] for e in shock_events})
    labelled = [o for o in opps if o.get("win") is not None]
    wins = sum(o["win"] for o in labelled)
    by_side = _group_stats(opps, lambda o: o["opp_side"])
    by_regime_dir = _group_stats(opps, lambda o: o["direction"])
    by_ttc = _group_stats(opps, lambda o: o["time_bucket"])
    by_line = _group_stats(opps, lambda o: o["line_bucket"])
    by_vol = _group_stats(opps, lambda o: o["vol_bucket"])
    by_day = _group_stats(opps, lambda o: o["day"])

    # response/lag distribution (study-level)
    lags = [e["lag_cents"] for e in shock_events if isinstance(e.get("lag_cents"), (int, float))]
    tmoves = [e["time_to_move_s"] for e in shock_events if isinstance(e.get("time_to_move_s"), (int, float))]
    resolved_p5 = sum(1 for e in shock_events if isinstance(e.get("resp_p5"), (int, float)))

    summary = {
        "files": [os.path.basename(f) for f in files], "days": sorted(set(days)),
        "raw_shock_rows": len(shock_events), "superset_rows": len(all_events),
        "dedup_events": len(dedup_events(shock_events, study.dedup_window_s)),
        "qualified_opp_rows": len(qualified), "qualified_opportunities": len(opps),
        "distinct_windows_with_shocks": distinct_windows_shocks,
        "distinct_windows_with_opps": distinct_windows_opps, "distinct_days": distinct_days,
        "up_shocks": sum(1 for e in shock_events if e["direction"] == "up"),
        "down_shocks": sum(1 for e in shock_events if e["direction"] == "down"),
        "near_line_shocks": sum(1 for e in shock_events if e["near_line"]),
        "opp_labelled": len(labelled), "opp_wins": wins,
        "opp_win_rate": (wins / len(labelled)) if labelled else None,
        "opp_avg_net_pnl": _mean([o["pnl_net"] for o in labelled]),
        "median_lag_cents": _median(lags), "median_time_to_move_s": _median(tmoves),
        "post5s_resolved_rows": resolved_p5,
        "by_side": by_side, "by_direction": by_regime_dir, "by_time_to_close": by_ttc,
        "by_line_distance": by_line, "by_vol_regime": by_vol, "by_day": by_day,
    }

    # ---- Deribit + Polymarket
    deribit_present = any(e.get("deribit_available") for e in shock_events)
    poly = classify_polymarket_comparability(config, date=date, start_date=start_date,
                                             end_date=end_date) if include_polymarket else {
        "classification": "skipped", "note": "pass --include-polymarket to classify"}

    # ---- write reports
    reports = {}
    d = _reports_dir(config)
    stamp = _ts()
    if write_csv:
        ev_csv = d / f"kalshi_reprice_lag_events_{stamp}.csv"
        op_csv = d / f"kalshi_reprice_lag_opportunities_{stamp}.csv"
        _write_events_csv(ev_csv, shock_events)
        _write_opps_csv(op_csv, opps)
        reports["events_csv"] = str(ev_csv)
        reports["opportunities_csv"] = str(op_csv)
        der_csv = d / f"kalshi_reprice_lag_deribit_regime_{stamp}.csv"
        der_stats = _write_deribit_csv(der_csv, opps)
        reports["deribit_regime_csv"] = str(der_csv)
        summary["by_deribit_regime"] = der_stats
    if write_md:
        md = d / f"kalshi_reprice_lag_study_{stamp}.md"
        md.write_text(_render_md(series, summary, study, deribit_present, poly), encoding="utf-8")
        reports["study_md"] = str(md)

    return {**base, "status": "OK", "summary": summary, "deribit_present": deribit_present,
            "polymarket": poly, "reports": reports, "study_config": {
                "min_depth": study.min_depth, "min_seconds_to_close": study.min_seconds_to_close,
                "max_seconds_to_close": study.max_seconds_to_close,
                "max_book_age_ms": study.max_book_age_ms,
                "conservative_buffer_cents": study.conservative_buffer_cents,
                "default_shock_bps": default_bps, "dedup_window_s": study.dedup_window_s}}


def run_shock_scan(config, *, series: str = "KXBTC15M", date=None, start_date=None, end_date=None,
                   shock_threshold_bps=None) -> dict:
    """Lightweight: detect + de-dup shocks only (no opportunity economics, no files)."""
    r = run_reprice_lag_study(config, series=series, date=date, start_date=start_date,
                              end_date=end_date, shock_threshold_bps=shock_threshold_bps,
                              write_md=False, write_csv=False)
    if r.get("status") != "OK":
        return r
    s = r["summary"]
    return {"series": series, "status": "OK", "live_submission_allowed": False,
            "days": s["days"], "raw_shock_rows": s["raw_shock_rows"],
            "dedup_events": s["dedup_events"], "distinct_windows": s["distinct_windows_with_shocks"],
            "distinct_days": s["distinct_days"], "up_shocks": s["up_shocks"],
            "down_shocks": s["down_shocks"], "near_line_shocks": s["near_line_shocks"],
            "median_lag_cents": s["median_lag_cents"], "median_time_to_move_s": s["median_time_to_move_s"]}


def run_sensitivity(config, *, series: str = "KXBTC15M", date=None, start_date=None, end_date=None,
                    write_csv=True) -> dict:
    """Sweep the 5s shock threshold; report event/opportunity economics per cell."""
    base = {"series": series, "live_submission_allowed": False}
    files = feature_files(config, date=date, start_date=start_date, end_date=end_date)
    if not files:
        return {**base, "status": "NO_DATA"}
    study = StudyConfig.from_app(config)
    fee_model = KalshiFeeModel.from_config(config)
    # build superset once
    superset = []
    for p in files:
        day = _day_of(p)
        rows = load_day_rows(p, series)
        if not rows:
            continue
        labels = load_labels(config, {r["market_ticker"] for r in rows})
        evs = _process_day(rows, labels, study, fee_model,
                           detect_cfg=ShockConfig(return_bps=dict(PERMISSIVE_RETURN_BPS)))
        for e in evs:
            e["day"] = day
        superset.extend(evs)
    grid = []
    for thr in SENSITIVITY_BPS_GRID:
        evs = [e for e in superset if (e.get("abs_ret_bps") or 0.0) >= thr]
        ded = dedup_events(evs, study.dedup_window_s)
        qual = dedup_events([e for e in evs if e["opp_qualified"]], study.dedup_window_s)
        _attach_outcomes(qual, fee_model)
        lab = [o for o in qual if o.get("win") is not None]
        grid.append({
            "shock_threshold_bps": thr, "raw_shock_rows": len(evs), "dedup_events": len(ded),
            "distinct_windows": len({e["ticker"] for e in evs}),
            "qualified_opps": len(qual), "qualified_windows": len({o["ticker"] for o in qual}),
            "opp_win_rate": _f((sum(o["win"] for o in lab) / len(lab)) if lab else None, 3),
            "avg_net_pnl": _f(_mean([o["pnl_net"] for o in lab]), 4)})
    reports = {}
    if write_csv:
        d = _reports_dir(config)
        sp = d / f"kalshi_reprice_lag_sensitivity_{_ts()}.csv"
        _write_sensitivity_csv(sp, grid)
        reports["sensitivity_csv"] = str(sp)
    return {**base, "status": "OK", "grid": grid, "reports": reports}


# --------------------------------------------------------------------------- #
# Markdown rendering + the 8 study questions
# --------------------------------------------------------------------------- #
def study_answers(summary: dict) -> dict:
    s = summary
    lag = s.get("median_lag_cents")
    ttm = s.get("median_time_to_move_s")
    opp_n = s.get("qualified_opportunities", 0)
    win = s.get("opp_win_rate")
    dw = s.get("distinct_windows_with_opps", 0)
    up = s.get("by_side", {}).get("YES", {})
    dn = s.get("by_side", {}).get("NO", {})
    return {
        "q1_shocks_lead_repricing": (
            f"Measurable only at the ~{int(SAMPLING_CADENCE_S)}s recording cadence. Median underlying-vs-Kalshi "
            f"lag at first resolved post-horizon = {_f(lag,2)}c (proxy). Sub-4s lead/lag is NOT observable in this data."),
        "q2_lag_seconds": (
            f"Cannot be resolved below ~{int(SAMPLING_CADENCE_S)}s (all streams co-sampled). "
            f"Median time-to-first-Kalshi-move(>= {MOVE_DETECT_CENTS}c) = {_f(ttm,1)}s (in cadence multiples)."),
        "q3_executable_stale_after_fees": (
            f"{opp_n} distinct stale-quote opportunities survived fees + depth + a conservative buffer."),
        "q4_spread_across_windows": (
            f"{dw} distinct windows across {s.get('distinct_days')} day(s); "
            + ("too concentrated to trust." if dw < 10 else "moderate spread; inspect concentration.")),
        "q5_up_and_down_both_viable": (
            f"YES(up): n={up.get('n',0)} win_rate={_pct(up.get('win_rate'))}; "
            f"NO(down): n={dn.get('n',0)} win_rate={_pct(dn.get('win_rate'))}."),
        "q6_persists_across_days_regimes": (
            f"opportunities span {s.get('distinct_days')} day(s); see by_day / by_vol_regime tables."),
        "q7_killed_by_fees_spread": (
            f"qualified opps after fees/buffer = {opp_n} of {s.get('qualified_opp_rows',0)} raw qualifying rows; "
            "fees/spread remove most candidates."),
        "q8_worth_staged_shadow": (
            "Likely NO yet: needs sub-second data and many more distinct windows/regimes." if (opp_n < 20 or dw < 10)
            else "Maybe, but only as a STAGED shadow study with finer data; not paper/live."),
        "opp_win_rate": win,
    }


def _table(stats: dict, label: str) -> list[str]:
    out = [f"**{label}**", "", "| bucket | opps | windows | win | loss | win_rate | avg_net_pnl |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for k, v in sorted(stats.items(), key=lambda kv: str(kv[0])):
        out.append(f"| {k} | {v['n']} | {v['windows']} | {v['win']} | {v['loss']} | "
                   f"{_pct(v['win_rate'])} | {_f(v['avg_pnl_net'],4)} |")
    out.append("")
    return out


def _render_md(series: str, summary: dict, study: StudyConfig, deribit_present: bool, poly: dict) -> str:
    a = study_answers(summary)
    s = summary
    L = [
        f"# Kalshi {series} — repricing-lag / stale-quote event study (READ-ONLY)",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC. Event-study diagnostic — "
        "NOT a trading permission slip. No paper/live, no orders, no promotion, no pointer/manifest/gate/buffer "
        "changes. Settlement labels used for EVALUATION ONLY (never as signal). No profitability/alpha claimed._",
        "",
        f"> **DATA-RESOLUTION CEILING:** all recorded streams (Coinbase, Binance, Kalshi book) are polled on the "
        f"same ~{int(SAMPLING_CADENCE_S)}s clock. A 1-3s repricing lag is **not directly observable** in this data; "
        "the +1s/+2s horizons do not resolve. Everything below is bounded by that ceiling.",
        "",
        "## Data scanned",
        f"- files: {len(s['files'])}  days: {', '.join(s['days'])}",
        f"- shock signals: spot returns 5/15/30/60s, vol-normalized, spot-perp basis jump, Binance OFI impulse "
        "(per-day p95), near-line; opportunity proxy: driftless-lognormal baseline P(YES) vs executable ask.",
        f"- study config: min_depth={study.min_depth}, min_seconds_to_close={study.min_seconds_to_close}, "
        f"max_book_age_ms={study.max_book_age_ms}, conservative_buffer={study.conservative_buffer_cents}c "
        "(mirrors edge-policy fixed buffer; added, never removed).",
        "",
        "## Aggregate: raw rows vs deduped opportunities vs distinct windows",
        f"- raw shock rows: **{s['raw_shock_rows']}**  → deduped shock events: **{s['dedup_events']}**",
        f"- qualifying rows (after fees/depth/buffer): {s['qualified_opp_rows']}  → "
        f"**distinct micro-opportunities: {s['qualified_opportunities']}**",
        f"- distinct windows (shocks): {s['distinct_windows_with_shocks']}  | "
        f"distinct windows (opps): **{s['distinct_windows_with_opps']}**  | distinct days: {s['distinct_days']}",
        f"- up-shocks: {s['up_shocks']}  down-shocks: {s['down_shocks']}  near-line: {s['near_line_shocks']}",
        f"- opportunity win rate (labelled): {_pct(s['opp_win_rate'])} ({s['opp_wins']}/{s['opp_labelled']})  "
        f"avg net P&L/contract: {_f(s['opp_avg_net_pnl'],4)}",
        "",
        "## Core findings — does Kalshi lag BTC repricing?",
        f"1. **Shocks lead repricing?** {a['q1_shocks_lead_repricing']}",
        f"2. **Lag seconds?** {a['q2_lag_seconds']}",
        f"3. **Executable stale quotes after fees/depth?** {a['q3_executable_stale_after_fees']}",
        f"4. **Spread across windows?** {a['q4_spread_across_windows']}",
        f"5. **Up & down both viable?** {a['q5_up_and_down_both_viable']}",
        f"6. **Persists across days/regimes?** {a['q6_persists_across_days_regimes']}",
        f"7. **Killed by fees/spreads?** {a['q7_killed_by_fees_spread']}",
        f"8. **Worth a staged shadow strategy later?** {a['q8_worth_staged_shadow']}",
        "",
        "## Regime / side breakdown (deduped opportunities)",
        "",
    ]
    L += _table(s["by_side"], "By side (YES=up-shock / NO=down-shock)")
    L += _table(s["by_time_to_close"], "By time-to-close")
    L += _table(s["by_line_distance"], "By line distance")
    L += _table(s["by_vol_regime"], "By volatility regime (spot sigma terciles)")
    L += _table(s["by_day"], "By day/session")
    if "by_deribit_regime" in s:
        L += _table(s["by_deribit_regime"], "By Deribit regime")
    L += [
        "## Deribit regime integration",
        f"- Deribit point-in-time fields present in events: **{deribit_present}** "
        + ("(joined per row)" if deribit_present else "(optional; missing/disabled for these days — core study unaffected)"),
        "",
        "## Polymarket reference (optional)",
        f"- classification: **{poly.get('classification')}** — {poly.get('note','')}",
    ]
    for r in poly.get("reasons", []):
        L.append(f"  - {r}")
    L += [
        "",
        "## Recommendation",
        _recommendation(s),
        "",
        "## Safety status",
        "- No paper, no live, no orders; `live_submission_allowed=false`.",
        "- No promotion/demotion; no model/calibrator/policy pointer change; promotion manifest untouched.",
        "- No gate weakened, no buffer removed (a conservative buffer was ADDED for opportunity qualification).",
        "- Labels used for evaluation only; reads recorded data; writes only under reports/reprice_lag/.",
        "",
        "## Next 3 actions",
        "1. Add a sub-second (tick or <=500ms) collector for Coinbase/Binance AND the Kalshi book — without it the "
        "core lag hypothesis is untestable; this is the binding constraint.",
        "2. Re-run this event study on the finer data with the +1s/+2s horizons and `time_to_move` at sub-second "
        "resolution; require opportunities across many distinct windows and both up/down regimes.",
        "3. Keep this STAGED/report-only; do not build any shadow/paper strategy until (1)-(2) show a fee-surviving, "
        "diversified effect — current data cannot justify it.",
    ]
    return "\n".join(L) + "\n"


def _recommendation(s: dict) -> str:
    opp = s.get("qualified_opportunities", 0)
    dw = s.get("distinct_windows_with_opps", 0)
    if opp < 20 or dw < 10:
        return ("**DO NOT do (yet).** The recorded ~4s cadence cannot resolve a few-second repricing lag, and the "
                f"qualified opportunities ({opp} across {dw} windows) are too few/concentrated to be structural. "
                "DO LATER only after a sub-second collector exists and the effect survives fees across many "
                "distinct windows and both regimes. Do not enable paper/live; do not promote anything.")
    return ("**DO LATER (staged shadow only).** A fee-surviving, multi-window effect is suggested but must be "
            "re-validated on sub-second data before any shadow strategy. No paper/live; no promotion.")
