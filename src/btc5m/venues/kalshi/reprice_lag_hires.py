"""High-resolution repricing-lag v2 (READ-ONLY research) on hires joined snapshots.

Answers, on the sub-second ``kalshi_hires_joined_snapshots`` stream: do Coinbase/Binance
shocks LEAD Kalshi active-book repricing at +250ms..+5s, does Kalshi leave EXECUTABLE stale
quotes after fees/depth/buffer, and are any such opportunities diversified across distinct
15-minute windows/days/sides/regimes? Shock detection uses the rows' sub-second underlying
returns; Kalshi response is measured across later rows of the SAME window with tolerance-
bounded nearest-row lookup. Because the Kalshi book is REST-polled (~1.1s cadence), the
+250ms/+500ms RESPONSE horizons are often unobservable - this is reported honestly, never
fabricated.

Conservative throughout: an underlying-implied PROXY (driftless lognormal distance-to-line,
the LESS-favourable of the Coinbase/Binance mids) is used only as a diagnostic - never called
truth; candidates require fee + depth + a conservative buffer; settlement labels are used for
EVALUATION only (and the window-open line, fixed at window start, is not look-ahead). No paper,
no live, no orders, no promotion. ``live_submission_allowed`` is always False.
"""

from __future__ import annotations

import bisect
import csv
import glob
import gzip
import json
import math
import os
import statistics
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ...models.baseline import BaselineInputs, normal_prob_yes
from ...schemas import Comparison
from .edge_policy import EdgePolicyConfig
from .fees import KalshiFeeModel

# Readiness thresholds (consistent with the --hires gate).
V2_MIN_ROWS = 2000
V2_MIN_WINDOWS = 20

PRE_HORIZONS = [-5000, 0]
POST_HORIZONS = [250, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000]
HORIZON_TOL = {-5000: 1500, 0: 0, 250: 300, 500: 500, 1000: 750, 2000: 1500,
               5000: 1500, 10000: 1500, 15000: 2000, 30000: 2500, 60000: 3000}
SHOCK_WINDOWS = {"250ms": 250, "500ms": 500, "1s": 1000, "2s": 2000, "5s": 5000, "15s": 15000}
DEFAULT_SHOCK_WINDOW = "1s"
SENS_BPS_GRID = [2, 3, 5, 8, 12, 16, 20]
SENS_HORIZONS = [250, 500, 1000, 2000, 5000]
MOVE_CENTS = [1, 2, 5]
REQUIRED_FIELDS = ("as_of_ms", "market_ticker", "seconds_to_close", "yes_ask", "no_ask",
                   "coinbase_mid", "binance_mid")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _f(x, nd=4) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "None"


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def _median(xs):
    v = [x for x in xs if isinstance(x, (int, float))]
    return statistics.median(v) if v else None


def _mean(xs):
    v = [x for x in xs if isinstance(x, (int, float))]
    return (sum(v) / len(v)) if v else None


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass
class V2Config:
    shock_window: str = DEFAULT_SHOCK_WINDOW
    shock_threshold_bps: float = 5.0
    min_depth: float = 1.0
    min_net_edge_cents: float = 0.0
    min_seconds_to_close: float = 30.0
    max_seconds_to_close: Optional[float] = 900.0
    near_line_only: bool = False
    near_line_usd: float = 25.0
    max_source_age_ms: float = 2000.0
    max_book_age_ms: float = 1500.0
    dedupe_seconds: float = 20.0
    conservative_buffer_cents: float = 3.0
    horizon_ms: Optional[int] = None          # optional single-horizon focus for reporting
    include_deribit: bool = True

    @classmethod
    def from_app(cls, config, **over) -> "V2Config":
        c = cls()
        ep = EdgePolicyConfig.from_app(config)
        c.conservative_buffer_cents = float(ep.fixed_uncertainty_buffer_cents)
        for k, v in over.items():
            if v is not None and hasattr(c, k):
                setattr(c, k, v)
        return c


# --------------------------------------------------------------------------- #
# Part B - loader
# --------------------------------------------------------------------------- #
def joined_files(config, *, date=None, start_date=None, end_date=None) -> list[str]:
    d = config.data_path() / "features" / "hires"
    pats = [str(d / "**" / "kalshi_hires_joined_snapshots*.jsonl"),
            str(d / "**" / "kalshi_hires_joined_snapshots*.jsonl.gz")]
    out = []
    for pat in pats:
        out.extend(glob.glob(pat, recursive=True))
    keep = []
    for p in out:
        # day token from path (date subdir or filename); accept if within filter
        m = "".join(ch for ch in os.path.basename(p) if ch.isdigit())[:8]
        sub = os.path.basename(os.path.dirname(p))
        day = sub if (sub.isdigit() and len(sub) == 8) else m
        if date and day != str(date):
            continue
        if start_date and day and day < str(start_date):
            continue
        if end_date and day and day > str(end_date):
            continue
        keep.append(p)
    return sorted(set(keep))


def _read_rows(path: str):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8", errors="ignore") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                yield json.loads(ln)
            except (ValueError, TypeError):
                continue


def _labels(config, tickers: set) -> dict:
    out = {}
    for lf in glob.glob(str(config.data_path() / "labels" / "kalshi_settlement_labels-*.jsonl")):
        for o in _read_rows(lf):
            mt = o.get("market_ticker")
            if mt in tickers:
                out[mt] = {"label_yes_resolved": o.get("label_yes_resolved"),
                           "reference_start_price": o.get("reference_start_price"),
                           "close_ms": o.get("close_ms")}
    return out


def _rolling_vol(rows_sorted) -> None:
    """Point-in-time realized vol per ticker from joined coinbase_mid (no look-ahead).
    Annotates each row with ``realized_vol_60s`` (sigma per sqrt-second)."""
    buf: deque = deque()        # (as_of_ms, ln(mid))
    for r in rows_sorted:
        mid = r.get("coinbase_mid")
        t = r.get("as_of_ms")
        if mid and mid > 0 and t is not None:
            buf.append((t, math.log(mid)))
            while buf and t - buf[0][0] > 60_000:
                buf.popleft()
        rets = []
        for (t0, l0), (t1, l1) in zip(buf, list(buf)[1:]):
            dt = (t1 - t0) / 1000.0
            if dt > 0:
                rets.append((l1 - l0) / math.sqrt(dt))
        r["realized_vol_60s"] = (statistics.pstdev(rets) if len(rets) >= 3 else None)


def load_joined(config, *, date=None, start_date=None, end_date=None) -> dict:
    files = joined_files(config, date=date, start_date=start_date, end_date=end_date)
    rows = []
    seen = set()
    missing = Counter()
    for p in files:
        for o in _read_rows(p):
            key = (o.get("market_ticker"), o.get("as_of_ms"))
            if key[0] is None or key[1] is None or key in seen:
                continue
            seen.add(key)
            for fld in REQUIRED_FIELDS:
                if o.get(fld) is None:
                    missing[fld] += 1
            rows.append(o)
    rows.sort(key=lambda r: (r["market_ticker"], r["as_of_ms"]))
    by_ticker = defaultdict(list)
    for r in rows:
        by_ticker[r["market_ticker"]].append(r)
    # enrich line from settlement labels (window-open target; fixed at start -> not look-ahead)
    labels = _labels(config, set(by_ticker))
    line_filled = 0
    for tk, trows in by_ticker.items():
        lab = labels.get(tk, {})
        ref = lab.get("reference_start_price")
        for r in trows:
            if r.get("reference_start_price") is None and ref is not None:
                r["reference_start_price"] = ref
                r["_line_provenance"] = "settlement_target"
                line_filled += 1
            elif r.get("reference_start_price") is not None:
                r["_line_provenance"] = "joined"
            # derive close_ms if absent
            if r.get("close_ms") is None and r.get("seconds_to_close") is not None:
                r["close_ms"] = int(r["as_of_ms"] + r["seconds_to_close"] * 1000)
        _rolling_vol(trows)
    days = sorted({datetime.fromtimestamp(r["as_of_ms"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                   for r in rows})
    return {"rows": rows, "by_ticker": by_ticker, "labels": labels, "files": files,
            "n_rows": len(rows), "n_windows": len(by_ticker), "days": days,
            "missingness": dict(missing), "line_filled": line_filled,
            "windows_with_label": sum(1 for tk in by_ticker
                                      if labels.get(tk, {}).get("label_yes_resolved") is not None)}


# --------------------------------------------------------------------------- #
# Part C - horizon nearest-row lookup
# --------------------------------------------------------------------------- #
class TickerSeries:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.ts = [r["as_of_ms"] for r in rows]

    def nearest(self, target_ms: float, tol_ms: float, *, after_ms: Optional[int] = None) -> Optional[dict]:
        """Nearest row to target within tol. If ``after_ms`` is given, only rows STRICTLY after
        it qualify - so a POST horizon never resolves to the shock row itself (offset 0)."""
        if not self.ts:
            return None
        i = bisect.bisect_left(self.ts, target_ms)
        best, bestd = None, None
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(self.ts):
                if after_ms is not None and self.ts[j] <= after_ms:
                    continue
                d = abs(self.ts[j] - target_ms)
                if bestd is None or d < bestd:
                    best, bestd = self.rows[j], d
        return best if (best is not None and bestd is not None and bestd <= tol_ms) else None


def market_implied_yes(r: dict) -> Optional[float]:
    ya, na = r.get("yes_ask"), r.get("no_ask")
    if ya is None:
        return None
    if na is not None and (ya + na) > 0:
        return max(0.0, min(1.0, ya / (ya + na)))
    return max(0.0, min(1.0, ya))


# --------------------------------------------------------------------------- #
# Part F - underlying-implied PROXY (conservative; never "truth")
# --------------------------------------------------------------------------- #
_VOL_FALLBACK = 1.0e-4          # per sqrt-second; used only when rolling vol is unavailable


def _proxy_one(S, L, T, sigma) -> Optional[float]:
    if S is None or L is None:
        return None
    return normal_prob_yes(BaselineInputs(reference_price=S, line=L, seconds_to_expiry=T,
                                          sigma_per_sqrt_s=sigma, comparison=Comparison.GTE))


def proxy_p_yes(r: dict, *, side: str) -> Optional[float]:
    """Conservative lognormal distance-to-line proxy: the LESS-favourable of the
    Coinbase/Binance mids for the proposed ``side``. Diagnostic only - not truth."""
    L = r.get("reference_start_price")
    T = r.get("seconds_to_close")
    sigma = r.get("realized_vol_60s") or _VOL_FALLBACK
    p_cb = _proxy_one(r.get("coinbase_mid"), L, T, sigma)
    p_bn = _proxy_one(r.get("binance_mid"), L, T, sigma)
    ps = [p for p in (p_cb, p_bn) if p is not None]
    if not ps:
        return None
    # conservative for the trade: YES wants the SMALLER P(YES); NO wants the LARGER P(YES)
    return min(ps) if side == "YES" else max(ps)


# --------------------------------------------------------------------------- #
# Part D - shock detection
# --------------------------------------------------------------------------- #
def detect_shock(r: dict, window: str) -> Optional[dict]:
    """Sub-second shock from the row's underlying returns; threshold-free magnitude."""
    sp = r.get(f"spot_return_{window}")
    pp = r.get(f"perp_return_{window}")
    sp_bps = (sp * 1e4) if sp is not None else None
    pp_bps = (pp * 1e4) if pp is not None else None
    cands = [(abs(b), b, src) for b, src in ((sp_bps, "coinbase"), (pp_bps, "binance")) if b is not None]
    if not cands:
        return None
    mag, signed, src = max(cands, key=lambda x: x[0])
    both = (sp_bps is not None and pp_bps is not None
            and (sp_bps > 0) == (pp_bps > 0) and abs(sp_bps) >= 1 and abs(pp_bps) >= 1)
    dist = None
    if r.get("coinbase_mid") is not None and r.get("reference_start_price") is not None:
        dist = r["coinbase_mid"] - r["reference_start_price"]
    return {"abs_bps": mag, "signed_bps": signed, "direction": "up" if signed > 0 else "down",
            "source": "both" if both else src, "spot_bps": sp_bps, "perp_bps": pp_bps,
            "avg_bps": _mean([abs(b) for b in (sp_bps, pp_bps) if b is not None]),
            "distance_to_line": dist,
            "near_line": (dist is not None and abs(dist) <= 25.0)}


# --------------------------------------------------------------------------- #
# Part E - Kalshi response measurement
# --------------------------------------------------------------------------- #
def measure_response(series: TickerSeries, t0: int, mkt0, ya0, na0, proxy0) -> dict:
    horizons = {}
    coverage = {}
    for h in PRE_HORIZONS + POST_HORIZONS:
        if h == 0:
            coverage[h] = True
            horizons[h] = {"offset_ms": 0, "mkt": mkt0, "yes_ask": ya0, "no_ask": na0}
            continue
        # POST horizons require a row STRICTLY after the shock (never resolve to t0 itself).
        r = (series.nearest(t0 + h, HORIZON_TOL[h], after_ms=t0) if h > 0
             else series.nearest(t0 + h, HORIZON_TOL[h]))
        if r is None:
            coverage[h] = False
            horizons[h] = None
            continue
        coverage[h] = True
        mkt = market_implied_yes(r)
        horizons[h] = {
            "offset_ms": r["as_of_ms"] - t0, "mkt": mkt,
            "yes_ask": r.get("yes_ask"), "no_ask": r.get("no_ask"),
            "yes_ask_size": r.get("yes_ask_size"), "no_ask_size": r.get("no_ask_size"),
            "mkt_change_c": ((mkt - mkt0) * 100.0) if (mkt is not None and mkt0 is not None) else None,
            "yes_ask_change_c": ((r["yes_ask"] - ya0) * 100.0) if (r.get("yes_ask") is not None and ya0 is not None) else None,
            "no_ask_change_c": ((r["no_ask"] - na0) * 100.0) if (r.get("no_ask") is not None and na0 is not None) else None,
        }
    # time-to-first Kalshi move >= Xc (signed market-implied), in ms
    ttm = {c: None for c in MOVE_CENTS}
    for h in POST_HORIZONS:
        hz = horizons.get(h)
        if hz and hz.get("mkt_change_c") is not None:
            for c in MOVE_CENTS:
                if ttm[c] is None and abs(hz["mkt_change_c"]) >= c:
                    ttm[c] = hz["offset_ms"]
    # lag proxy at first resolved post-horizon: expected (proxy-vs-market) move minus actual market move
    lag = None
    lag_h = None
    for h in POST_HORIZONS:
        hz = horizons.get(h)
        if hz and hz.get("mkt_change_c") is not None and proxy0 is not None and mkt0 is not None:
            expected_move_c = (proxy0 - mkt0) * 100.0
            lag = expected_move_c - hz["mkt_change_c"]
            lag_h = hz["offset_ms"]
            break
    return {"horizons": horizons, "coverage": coverage, "time_to_move_ms": ttm,
            "lag_cents": lag, "lag_horizon_ms": lag_h}


# --------------------------------------------------------------------------- #
# Part G - stale executable quote candidate (t0-only; no look-ahead)
# --------------------------------------------------------------------------- #
def qualify_candidate(r: dict, shock: dict, cfg: V2Config, fee_model: KalshiFeeModel) -> Optional[dict]:
    side = "YES" if shock["direction"] == "up" else "NO"
    stc = r.get("seconds_to_close")
    ask = r.get("yes_ask") if side == "YES" else r.get("no_ask")
    size = r.get("yes_ask_size") if side == "YES" else r.get("no_ask_size")
    p = proxy_p_yes(r, side=side)
    p_side = (p if side == "YES" else (1.0 - p)) if p is not None else None
    reasons = []
    if stc is None or stc <= 0:
        reasons.append("not_in_window")
    if r.get("reference_start_price") is None:
        reasons.append("no_line")
    if p_side is None:
        reasons.append("no_proxy")
    if ask is None or not (0.0 < ask < 1.0):
        reasons.append("no_executable_ask")
    if size is None or size < cfg.min_depth:
        reasons.append("insufficient_depth")
    if r.get("coinbase_stale") or r.get("binance_stale"):
        reasons.append("underlying_stale")
    for a in (r.get("coinbase_age_ms"), r.get("binance_age_ms")):
        if a is None or a > cfg.max_source_age_ms:
            reasons.append("source_age")
            break
    if (r.get("kalshi_book_age_ms") or 0) > cfg.max_book_age_ms:
        reasons.append("book_stale")
    if stc is not None and stc < cfg.min_seconds_to_close:
        reasons.append("settlement_race")
    if cfg.max_seconds_to_close is not None and stc is not None and stc > cfg.max_seconds_to_close:
        reasons.append("outside_ttc")
    if cfg.near_line_only and not shock.get("near_line"):
        reasons.append("not_near_line")
    fee = fee_model.per_contract_fee(ask) if (ask and 0 < ask < 1) else None
    gross_c = ((p_side - ask) * 100.0) if (p_side is not None and ask is not None) else None
    net_c = (gross_c - fee * 100.0 - cfg.conservative_buffer_cents) if (gross_c is not None and fee is not None) else None
    if net_c is None or net_c < cfg.min_net_edge_cents:
        reasons.append("no_fee_buffer_edge")
    if reasons:
        return {"qualified": False, "side": side, "reasons": reasons}
    return {"qualified": True, "side": side, "executable_price": ask, "executable_size": size,
            "proxy_p_side": p_side, "market_implied_yes": market_implied_yes(r),
            "fee_cents": fee * 100.0, "gross_proxy_edge_cents": gross_c,
            "buffer_cents": cfg.conservative_buffer_cents, "net_proxy_edge_cents": net_c}


# --------------------------------------------------------------------------- #
# buckets
# --------------------------------------------------------------------------- #
def _ttc_bucket(stc):
    if stc is None:
        return "unknown"
    if stc >= 600:
        return "early"
    if stc <= 120:
        return "late"
    return "mid"


def _line_bucket(d):
    if d is None:
        return "unknown"
    a = abs(d)
    return "near" if a <= 25 else ("mid" if a <= 100 else "far")


# --------------------------------------------------------------------------- #
# Part H - dedup
# --------------------------------------------------------------------------- #
def dedupe(cands: list[dict], seconds: float) -> list[dict]:
    by = defaultdict(list)
    for c in cands:
        by[(c["market_ticker"], c["side"])].append(c)
    opps = []
    for key, lst in by.items():
        lst.sort(key=lambda c: c["shock_time_ms"])
        cur = None
        for c in lst:
            if (cur and (c["shock_time_ms"] - cur["_last_ms"]) <= seconds * 1000
                    and abs(c["executable_price"] - cur["executable_price"]) <= 0.03):
                cur["n_obs"] += 1
                cur["_last_ms"] = c["shock_time_ms"]
                continue
            cur = dict(c)
            cur["n_obs"] = 1
            cur["_last_ms"] = c["shock_time_ms"]
            opps.append(cur)
    return opps


# --------------------------------------------------------------------------- #
# Part I - outcome scoring
# --------------------------------------------------------------------------- #
def score_outcomes(opps: list[dict], labels: dict, fee_model: KalshiFeeModel) -> None:
    for o in opps:
        lab = labels.get(o["market_ticker"], {})
        y = lab.get("label_yes_resolved")
        if y is None:
            o["status"] = "pending"
            o["win"] = None
            o["pnl_net"] = None
            continue
        o["status"] = "settled"
        win = int((o["side"] == "YES") == (int(y) == 1))
        entry = o["executable_price"]
        fee = fee_model.per_contract_fee(entry)
        gross = (1.0 - entry) if win else (-entry)
        o["win"] = win
        o["pnl_gross"] = gross
        o["pnl_net"] = gross - fee


def _agg(opps: list[dict], keyfn) -> dict:
    g = defaultdict(lambda: {"n": 0, "win": 0, "loss": 0, "pnl": [], "windows": set()})
    for o in opps:
        if o.get("status") != "settled":
            continue
        d = g[keyfn(o)]
        d["n"] += 1
        d["windows"].add(o["market_ticker"])
        d["win" if o["win"] == 1 else "loss"] += 1
        if isinstance(o.get("pnl_net"), (int, float)):
            d["pnl"].append(o["pnl_net"])
    out = {}
    for k, v in g.items():
        wl = v["win"] + v["loss"]
        out[k] = {"opps": v["n"], "windows": len(v["windows"]), "win": v["win"], "loss": v["loss"],
                  "win_rate": (v["win"] / wl) if wl else None, "avg_pnl": _mean(v["pnl"]),
                  "median_pnl": _median(v["pnl"]), "total_pnl": sum(v["pnl"]) if v["pnl"] else 0.0}
    return out


def _profit_factor(pnls) -> Optional[float]:
    pos = sum(p for p in pnls if p > 0)
    neg = -sum(p for p in pnls if p < 0)
    return (pos / neg) if neg > 0 else (None if pos == 0 else float("inf"))


# --------------------------------------------------------------------------- #
# Core engine: load -> detect -> measure -> candidate -> dedup -> outcome
# --------------------------------------------------------------------------- #
def _compute(config, cfg: V2Config, *, date=None, start_date=None, end_date=None) -> dict:
    data = load_joined(config, date=date, start_date=start_date, end_date=end_date)
    if data["n_rows"] < V2_MIN_ROWS or data["n_windows"] < V2_MIN_WINDOWS:
        return {"status": "NOT_READY", "used_v2": True, "live_submission_allowed": False,
                "reason": (f"insufficient high-res joined data: {data['n_rows']} rows / "
                           f"{data['n_windows']} windows (need >= {V2_MIN_ROWS} rows, "
                           f">= {V2_MIN_WINDOWS} windows). Collect more with kalshi-hires-record."),
                "data": {k: data[k] for k in ("n_rows", "n_windows", "days")}}
    fee_model = KalshiFeeModel.from_config(config)
    win = cfg.shock_window
    shocks, candidates = [], []
    cover_counts = Counter()
    cover_total = 0
    lag_by_h = defaultdict(list)
    ttm_all = {c: [] for c in MOVE_CENTS}
    moved_expected = []

    for tk, trows in data["by_ticker"].items():
        series = TickerSeries(trows)
        for r in trows:
            sh = detect_shock(r, win)
            if sh is None or sh["abs_bps"] < 2.0:    # permissive superset (>=2bps); threshold applied later
                continue
            t0 = r["as_of_ms"]
            mkt0 = market_implied_yes(r)
            proxy0 = proxy_p_yes(r, side=("YES" if sh["direction"] == "up" else "NO"))
            resp = measure_response(series, t0, mkt0, r.get("yes_ask"), r.get("no_ask"), proxy0)
            cover_total += 1
            for h, ok in resp["coverage"].items():
                if h > 0 and ok:
                    cover_counts[h] += 1
            if resp["lag_cents"] is not None:
                lag_by_h[resp["lag_horizon_ms"]].append(resp["lag_cents"])
            for c in MOVE_CENTS:
                if resp["time_to_move_ms"][c] is not None:
                    ttm_all[c].append(resp["time_to_move_ms"][c])
            # did Kalshi move in the expected (shock) direction by the first resolved horizon?
            for h in POST_HORIZONS:
                hz = resp["horizons"].get(h)
                if hz and hz.get("mkt_change_c") is not None:
                    moved_expected.append(int((hz["mkt_change_c"] > 0) == (sh["direction"] == "up")))
                    break
            srow = {"market_ticker": tk, "shock_time_ms": t0,
                    "seconds_to_close": r.get("seconds_to_close"),
                    "direction": sh["direction"], "source": sh["source"], "abs_bps": sh["abs_bps"],
                    "spot_bps": sh["spot_bps"], "perp_bps": sh["perp_bps"],
                    "distance_to_line": sh["distance_to_line"], "near_line": sh["near_line"],
                    "coinbase_age_ms": r.get("coinbase_age_ms"), "binance_age_ms": r.get("binance_age_ms"),
                    "kalshi_book_age_ms": r.get("kalshi_book_age_ms"),
                    "yes_ask": r.get("yes_ask"), "no_ask": r.get("no_ask"),
                    "lag_cents": resp["lag_cents"], "time_to_move_1c_ms": resp["time_to_move_ms"][1],
                    "time_to_move_2c_ms": resp["time_to_move_ms"][2],
                    "ttc_bucket": _ttc_bucket(r.get("seconds_to_close")),
                    "line_bucket": _line_bucket(sh["distance_to_line"]),
                    "vol_regime": _vol_regime(r.get("realized_vol_60s"))}
            shocks.append(srow)
            q = qualify_candidate(r, sh, cfg, fee_model)
            if q.get("qualified"):
                candidates.append({**srow, "side": q["side"], "candidate_time_ms": t0,
                                   "executable_price": q["executable_price"],
                                   "executable_size": q["executable_size"],
                                   "proxy_p_side": q["proxy_p_side"],
                                   "market_implied_yes": q["market_implied_yes"],
                                   "fee_cents": q["fee_cents"], "buffer_cents": q["buffer_cents"],
                                   "gross_proxy_edge_cents": q["gross_proxy_edge_cents"],
                                   "net_proxy_edge_cents": q["net_proxy_edge_cents"],
                                   "time_to_reprice_ms": resp["time_to_move_ms"][2],
                                   "horizon_detected_ms": win})

    return {"status": "OK", "used_v2": True, "live_submission_allowed": False,
            "cfg": cfg, "data": data, "fee_model": fee_model,
            "shocks": shocks, "candidates": candidates,
            "coverage": {h: (cover_counts[h] / cover_total if cover_total else 0.0) for h in POST_HORIZONS},
            "coverage_total": cover_total, "lag_by_horizon": lag_by_h, "ttm_all": ttm_all,
            "moved_expected_fraction": _mean(moved_expected)}


def _vol_regime(sigma) -> str:
    if sigma is None:
        return "unknown"
    if sigma >= 1.5e-4:
        return "high-vol"
    if sigma <= 6e-5:
        return "low-vol"
    return "mid-vol"


def _shape_results(comp: dict, cfg: V2Config) -> dict:
    """Apply the shock threshold + dedupe + outcomes to the permissive superset."""
    data = comp["data"]
    thr = cfg.shock_threshold_bps
    shocks = [s for s in comp["shocks"] if s["abs_bps"] >= thr]
    cands = [c for c in comp["candidates"] if c["abs_bps"] >= thr]
    opps = dedupe(cands, cfg.dedupe_seconds)
    score_outcomes(opps, data["labels"], comp["fee_model"])
    settled = [o for o in opps if o.get("status") == "settled"]
    pending = [o for o in opps if o.get("status") == "pending"]
    pnls = [o["pnl_net"] for o in settled if isinstance(o.get("pnl_net"), (int, float))]
    wins = sum(o["win"] for o in settled)
    by_side = _agg(opps, lambda o: o["side"])
    by_day = _agg(opps, lambda o: datetime.fromtimestamp(o["shock_time_ms"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"))
    by_window = _agg(opps, lambda o: o["market_ticker"])
    by_vol = _agg(opps, lambda o: o["vol_regime"])
    by_ttc = _agg(opps, lambda o: o["ttc_bucket"])
    win_pnls = sorted(((v["total_pnl"], k) for k, v in by_window.items()))
    return {
        "raw_shock_rows": len(shocks), "raw_candidates": len(cands),
        "dedup_opportunities": len(opps), "settled_opportunities": len(settled),
        "pending_opportunities": len(pending),
        "distinct_windows_shocks": len({s["market_ticker"] for s in shocks}),
        "distinct_windows_opps": len({o["market_ticker"] for o in opps}),
        "distinct_days": len({datetime.fromtimestamp(s["shock_time_ms"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d") for s in shocks}),
        "up_shocks": sum(1 for s in shocks if s["direction"] == "up"),
        "down_shocks": sum(1 for s in shocks if s["direction"] == "down"),
        "win_rate": (wins / len(settled)) if settled else None, "wins": wins,
        "avg_pnl": _mean(pnls), "median_pnl": _median(pnls), "total_net_pnl": sum(pnls) if pnls else 0.0,
        "profit_factor": _profit_factor(pnls),
        "worst_window": (win_pnls[0] if win_pnls else None), "best_window": (win_pnls[-1] if win_pnls else None),
        "by_side": by_side, "by_day": by_day, "by_window": by_window, "by_vol_regime": by_vol,
        "by_ttc": by_ttc, "opps": opps, "shocks": shocks, "candidates": cands,
    }


# --------------------------------------------------------------------------- #
# Part J - sensitivity
# --------------------------------------------------------------------------- #
def _sensitivity(comp: dict, cfg: V2Config) -> list[dict]:
    grid = []
    for thr in SENS_BPS_GRID:
        c2 = V2Config(**{**cfg.__dict__})
        c2.shock_threshold_bps = thr
        sh = _shape_results(comp, c2)
        for h in SENS_HORIZONS:
            grid.append({
                "shock_threshold_bps": thr, "horizon_ms": h,
                "raw_shocks": sh["raw_shock_rows"], "raw_candidates": sh["raw_candidates"],
                "dedup_opportunities": sh["dedup_opportunities"],
                "distinct_windows": sh["distinct_windows_opps"],
                "win_rate": _f(sh["win_rate"], 3), "avg_pnl": _f(sh["avg_pnl"], 4),
                "median_pnl": _f(sh["median_pnl"], 4), "total_net_pnl": _f(sh["total_net_pnl"], 3),
                "max_drawdown_by_window": _f(sh["worst_window"][0] if sh["worst_window"] else None, 3),
                "coverage_fraction": _f(comp["coverage"].get(h), 3),
                "pending_count": sh["pending_opportunities"],
                "concentration_warning": (sh["distinct_windows_opps"] < 10)})
    return grid


# --------------------------------------------------------------------------- #
# Part K - Deribit regime context (optional)
# --------------------------------------------------------------------------- #
def _deribit_context(config, days: list[str]) -> dict:
    files = glob.glob(str(config.data_path() / "normalized" / "deribit_btc-*.jsonl"))
    present = bool(files)
    fields = []
    if present:
        try:
            for o in _read_rows(files[-1]):
                ev = o.get("event", o)
                fields = [k for k in ("deribit_dvol", "deribit_btc_iv_index", "deribit_historical_vol")
                          if k in ev]
                break
        except Exception:  # noqa: BLE001
            pass
    return {"present": present, "fields": fields,
            "note": ("Deribit is SLOW regime context (separate ~30s collector); joined point-in-time "
                     "later. Not in the sub-second hot path." if present else
                     "Deribit data missing/stale; optional - does not block v2.")}


# --------------------------------------------------------------------------- #
# Reports (Part L)
# --------------------------------------------------------------------------- #
def _reports_dir(config) -> Path:
    d = config.reports_path() / "reprice_lag" / "hires"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _answers(comp: dict, sh: dict, cfg: V2Config) -> dict:
    data = comp["data"]
    cov = comp["coverage"]
    good_h = [h for h in POST_HORIZONS if cov.get(h, 0) >= 0.5]
    sub = [h for h in (250, 500) if cov.get(h, 0) >= 0.2]
    lag1 = comp["lag_by_horizon"]
    all_lags = [v for vs in lag1.values() for v in vs]
    return {
        "q1_sufficient": f"YES - {data['n_rows']} joined rows across {data['n_windows']} windows, {len(data['days'])} day(s).",
        "q2_rows_windows": f"{data['n_rows']} joined rows; {data['n_windows']} distinct windows; days={data['days']}.",
        "q3_coverage": ("Kalshi response is REST-bound (~1.1s cadence): well-covered horizons (>=50%) = "
                        f"{good_h}ms; +250/+500ms coverage = {_pct(cov.get(250))}/{_pct(cov.get(500))} "
                        f"({'observable' if sub else 'too sparse to use - reported, not fabricated'})."),
        "q4_shocks_lead": (f"Median underlying-vs-Kalshi lag proxy = {_f(_median(all_lags), 2)}c at first resolved horizon; "
                           f"Kalshi moved in the expected direction in {_pct(comp['moved_expected_fraction'])} of shocks."),
        "q5_speed": (f"Time-to-first Kalshi move >=2c: median {_f(_median(comp['ttm_all'][2]), 0)}ms "
                     f"(>=1c: {_f(_median(comp['ttm_all'][1]), 0)}ms) - bounded below by the ~1.1s book cadence."),
        "q6_fee_surviving": f"{sh['settled_opportunities']} settled stale-quote opportunities after fees+depth+buffer "
                            f"(+{sh['pending_opportunities']} pending).",
        "q7_positive_negative": (f"win_rate={_pct(sh['win_rate'])} avg_net_pnl={_f(sh['avg_pnl'], 4)}/contract "
                                 f"total={_f(sh['total_net_pnl'], 3)} profit_factor={_f(sh['profit_factor'], 2)} "
                                 f"-> {'POSITIVE' if (sh['avg_pnl'] or 0) > 0 else 'NEGATIVE/none after costs'}."),
        "q8_robust": "see sensitivity CSV: " + "; ".join(
            f"{thr}bps avg_pnl={_f(_shape_thr(comp, cfg, thr)['avg_pnl'], 4)}" for thr in (3, 5, 8, 12)),
        "q9_diversified": (f"opps across {sh['distinct_windows_opps']} windows / {sh['distinct_days']} day(s); "
                           f"sides YES/NO={sh['by_side'].get('YES', {}).get('opps', 0)}/{sh['by_side'].get('NO', {}).get('opps', 0)}; "
                           + ("CONCENTRATED" if sh["distinct_windows_opps"] < 10 else "moderately spread")),
        "q10_worth_shadow": _verdict(sh)[0],
    }


def _shape_thr(comp, cfg, thr):
    c2 = V2Config(**{**cfg.__dict__})
    c2.shock_threshold_bps = thr
    return _shape_results(comp, c2)


def _verdict(sh: dict) -> tuple[str, str]:
    avg = sh["avg_pnl"]
    n = sh["settled_opportunities"]
    w = sh["distinct_windows_opps"]
    if n == 0:
        return ("NO - no fee-surviving stale-quote opportunities exist after costs; dead/negative result. "
                "Continue collecting/research only.", "no_edge")
    if (avg or 0) <= 0 or w < 10:
        return ("NO - opportunities exist but are net-negative after fees/buffer and/or too concentrated; "
                "not worth a shadow strategy. Continue research only.", "no_edge")
    return ("PROMISING but needs more data/regimes before any STAGED shadow study; not paper/live.", "promising")


def _write_reports(config, comp: dict, sh: dict, cfg: V2Config, grid: list[dict],
                   deribit: dict, *, write_all: bool) -> dict:
    d = _reports_dir(config)
    stamp = _ts()
    data = comp["data"]
    reports = {}
    # CSVs
    if write_all:
        _write_csv(d / f"kalshi_hires_reprice_lag_v2_shocks_{stamp}.csv", sh["shocks"],
                   ["market_ticker", "shock_time_ms", "direction", "source", "abs_bps", "spot_bps",
                    "perp_bps", "seconds_to_close", "distance_to_line", "near_line", "coinbase_age_ms",
                    "binance_age_ms", "lag_cents", "time_to_move_1c_ms", "time_to_move_2c_ms",
                    "ttc_bucket", "line_bucket", "vol_regime"])
        _write_csv(d / f"kalshi_hires_reprice_lag_v2_candidates_{stamp}.csv", sh["candidates"],
                   ["market_ticker", "candidate_time_ms", "side", "executable_price", "executable_size",
                    "gross_proxy_edge_cents", "fee_cents", "buffer_cents", "net_proxy_edge_cents",
                    "coinbase_age_ms", "binance_age_ms", "time_to_reprice_ms", "horizon_detected_ms",
                    "seconds_to_close", "distance_to_line", "direction", "abs_bps"])
        _write_csv(d / f"kalshi_hires_reprice_lag_v2_opportunities_{stamp}.csv", sh["opps"],
                   ["market_ticker", "side", "shock_time_ms", "n_obs", "executable_price",
                    "executable_size", "net_proxy_edge_cents", "abs_bps", "direction", "seconds_to_close",
                    "vol_regime", "status", "win", "pnl_net"])
        reports["shocks_csv"] = str(d / f"kalshi_hires_reprice_lag_v2_shocks_{stamp}.csv")
        reports["candidates_csv"] = str(d / f"kalshi_hires_reprice_lag_v2_candidates_{stamp}.csv")
        reports["opportunities_csv"] = str(d / f"kalshi_hires_reprice_lag_v2_opportunities_{stamp}.csv")
        reg_rows = [{"regime": k, **v} for k, v in sh["by_vol_regime"].items()]
        _write_csv(d / f"kalshi_hires_reprice_lag_v2_regime_{stamp}.csv", reg_rows,
                   ["regime", "opps", "windows", "win", "loss", "win_rate", "avg_pnl", "median_pnl", "total_pnl"])
        reports["regime_csv"] = str(d / f"kalshi_hires_reprice_lag_v2_regime_{stamp}.csv")
    _write_csv(d / f"kalshi_hires_reprice_lag_v2_sensitivity_{stamp}.csv", grid,
               ["shock_threshold_bps", "horizon_ms", "raw_shocks", "raw_candidates", "dedup_opportunities",
                "distinct_windows", "win_rate", "avg_pnl", "median_pnl", "total_net_pnl",
                "max_drawdown_by_window", "coverage_fraction", "pending_count", "concentration_warning"])
    reports["sensitivity_csv"] = str(d / f"kalshi_hires_reprice_lag_v2_sensitivity_{stamp}.csv")
    # manifest
    manifest = {"generated_utc": _ts(), "used_v2": True, "live_submission_allowed": False,
                "config": {k: getattr(cfg, k) for k in cfg.__dataclass_fields__},
                "n_files": len(data["files"]), "n_rows": data["n_rows"], "n_windows": data["n_windows"],
                "days": data["days"], "windows_with_label": data["windows_with_label"],
                "line_filled_from_labels": data["line_filled"], "missingness": data["missingness"],
                "coverage_by_horizon": {h: comp["coverage"][h] for h in POST_HORIZONS},
                "proxy": "lognormal_distance_to_line(min/max of coinbase/binance mids; realized_vol_60s; "
                         "line=settlement window-open target); DIAGNOSTIC, not truth",
                "deribit": deribit}
    (d / f"kalshi_hires_reprice_lag_v2_manifest_{stamp}.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    reports["manifest_json"] = str(d / f"kalshi_hires_reprice_lag_v2_manifest_{stamp}.json")
    # markdown
    ans = _answers(comp, sh, cfg)
    verdict, _ = _verdict(sh)
    L = ["# Kalshi KXBTC15M - repricing-lag **v2 (high-res)** study", "",
         f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC. HIGH-RES v2 on "
         "`kalshi_hires_joined_snapshots`. READ-ONLY research; no paper/live/orders/promotion. Settlement "
         "labels used for EVALUATION only; the underlying-implied PROXY is diagnostic, not truth._", "",
         "> **Resolution note:** shock detection is sub-second (underlying returns), but the Kalshi book is "
         "REST-polled (~1.1s cadence), so +250ms/+500ms RESPONSE horizons are sparse and reported honestly.", "",
         "## Findings (10 questions)"]
    for k in ("q1_sufficient", "q2_rows_windows", "q3_coverage", "q4_shocks_lead", "q5_speed",
              "q6_fee_surviving", "q7_positive_negative", "q8_robust", "q9_diversified", "q10_worth_shadow"):
        L.append(f"- **{k}** {ans[k]}")
    L += ["", "## Aggregate (after threshold "
          f"{cfg.shock_threshold_bps}bps, dedupe {cfg.dedupe_seconds}s)",
          f"- raw shock rows: {sh['raw_shock_rows']}  raw candidates: {sh['raw_candidates']}  "
          f"deduped opportunities: **{sh['dedup_opportunities']}** (settled {sh['settled_opportunities']}, pending {sh['pending_opportunities']})",
          f"- distinct windows (opps): {sh['distinct_windows_opps']}  days: {sh['distinct_days']}  "
          f"up/down shocks: {sh['up_shocks']}/{sh['down_shocks']}",
          f"- win_rate: {_pct(sh['win_rate'])}  avg_net_pnl/contract: {_f(sh['avg_pnl'], 4)}  "
          f"total_net_pnl: {_f(sh['total_net_pnl'], 3)}  profit_factor: {_f(sh['profit_factor'], 2)}",
          "", "## Horizon coverage (fraction of shocks with a Kalshi row in tolerance)",
          "| horizon | coverage |", "|---|---:|"]
    for h in POST_HORIZONS:
        L.append(f"| +{h}ms | {_pct(comp['coverage'].get(h))} |")
    L += ["", "## Side breakdown", "| side | opps | windows | win_rate | avg_pnl |", "|---|---:|---:|---:|---:|"]
    for side, v in sh["by_side"].items():
        L.append(f"| {side} | {v['opps']} | {v['windows']} | {_pct(v['win_rate'])} | {_f(v['avg_pnl'], 4)} |")
    L += ["", "## Deribit regime", f"- {deribit['note']} (fields: {deribit['fields']})",
          "", "## Recommendation", f"**{verdict}**",
          "", "## Safety",
          "- No paper, no live, no orders; `live_submission_allowed=false`.",
          "- No promotion/manifest/pointer/gate/buffer change; labels = evaluation only; proxy != truth.",
          "- Reads recorded hires data; writes only under reports/reprice_lag/hires/."]
    md = d / f"kalshi_hires_reprice_lag_v2_study_{stamp}.md"
    md.write_text("\n".join(L) + "\n", encoding="utf-8")
    reports["study_md"] = str(md)
    return reports


# --------------------------------------------------------------------------- #
# Public entry points (study / report / sensitivity share one engine)
# --------------------------------------------------------------------------- #
def _common(config, *, date, start_date, end_date, over) -> tuple:
    cfg = V2Config.from_app(config, **over)
    comp = _compute(config, cfg, date=date, start_date=start_date, end_date=end_date)
    return cfg, comp


def run_hires_v2_study(config, *, series="KXBTC15M", date=None, start_date=None, end_date=None,
                       write_all=True, **over) -> dict:
    cfg, comp = _common(config, date=date, start_date=start_date, end_date=end_date, over=over)
    base = {"series": series, "used_v2": True, "live_submission_allowed": False, "mode": "study"}
    if comp["status"] != "OK":
        return {**base, **comp}
    sh = _shape_results(comp, cfg)
    grid = _sensitivity(comp, cfg)
    deribit = _deribit_context(config, comp["data"]["days"]) if cfg.include_deribit else {"present": False, "fields": [], "note": "skipped"}
    reports = _write_reports(config, comp, sh, cfg, grid, deribit, write_all=write_all)
    return {**base, "status": "OK", "summary": _summary(comp, sh), "answers": _answers(comp, sh, cfg),
            "verdict": _verdict(sh)[1], "reports": reports, "deribit": deribit}


def run_hires_v2_report(config, **kw) -> dict:
    r = run_hires_v2_study(config, write_all=False, **kw)
    r["mode"] = "report"
    return r


def run_hires_v2_sensitivity(config, *, series="KXBTC15M", date=None, start_date=None, end_date=None,
                             **over) -> dict:
    cfg, comp = _common(config, date=date, start_date=start_date, end_date=end_date, over=over)
    base = {"series": series, "used_v2": True, "live_submission_allowed": False, "mode": "sensitivity"}
    if comp["status"] != "OK":
        return {**base, **comp}
    sh = _shape_results(comp, cfg)
    grid = _sensitivity(comp, cfg)
    deribit = {"present": False, "fields": [], "note": "n/a"}
    reports = _write_reports(config, comp, sh, cfg, grid, deribit, write_all=False)
    return {**base, "status": "OK", "grid": grid, "reports": reports}


def _summary(comp: dict, sh: dict) -> dict:
    data = comp["data"]
    return {"n_rows": data["n_rows"], "n_windows": data["n_windows"], "days": data["days"],
            "windows_with_label": data["windows_with_label"], "line_filled_from_labels": data["line_filled"],
            "coverage_by_horizon": {h: comp["coverage"][h] for h in POST_HORIZONS},
            "moved_expected_fraction": comp["moved_expected_fraction"],
            "raw_shock_rows": sh["raw_shock_rows"], "raw_candidates": sh["raw_candidates"],
            "dedup_opportunities": sh["dedup_opportunities"],
            "settled_opportunities": sh["settled_opportunities"],
            "pending_opportunities": sh["pending_opportunities"],
            "distinct_windows_opps": sh["distinct_windows_opps"], "distinct_days": sh["distinct_days"],
            "up_shocks": sh["up_shocks"], "down_shocks": sh["down_shocks"],
            "win_rate": sh["win_rate"], "avg_pnl": sh["avg_pnl"], "median_pnl": sh["median_pnl"],
            "total_net_pnl": sh["total_net_pnl"], "profit_factor": sh["profit_factor"],
            "by_side": sh["by_side"], "by_day": sh["by_day"], "by_vol_regime": sh["by_vol_regime"],
            "worst_window": sh["worst_window"], "best_window": sh["best_window"]}


def v2_ready(config) -> dict:
    """Lightweight readiness check (no full compute) for the CLI gate."""
    data = load_joined(config)
    ready = data["n_rows"] >= V2_MIN_ROWS and data["n_windows"] >= V2_MIN_WINDOWS
    return {"ready": ready, "n_rows": data["n_rows"], "n_windows": data["n_windows"],
            "days": data["days"],
            "reason": (None if ready else
                       f"insufficient: {data['n_rows']} rows / {data['n_windows']} windows "
                       f"(need >= {V2_MIN_ROWS} / {V2_MIN_WINDOWS})")}
