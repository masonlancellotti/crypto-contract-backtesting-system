"""Cross-horizon implied-vol coherence (⑥) — READ-ONLY, no orders.

Same underlying (BTC), same venue, same CF Benchmarks settlement, two horizons:
  * KXBTC15M  (15-min up/down vs window-open)  -> a single ATM-ish binary
  * KXBTCD    (hourly "Above/below" STRIKE LADDER) -> a full implied terminal CDF

A coherent diffusion implies one instantaneous vol; the two horizons should agree.

Extraction (per live snapshot):
  sigma_15  : invert the GTE fair value of the 15m market.  P_yes = Phi( ln(S/ref) /
              (sigma*sqrt(tau15)) )  ->  sigma_15 = ln(S/ref) / (sqrt(tau15)*Phi^{-1}(P_yes)).
              Only valid when the 15m market is OFF the money (|P-0.5| not tiny) so the
              inversion is well-conditioned.
  sigma_1h  : from the hourly ladder. Near the 50% strike, dP/dK = -phi(0)/(sigma*sqrt(tau1h)*S),
              so sigma_1h*sqrt(tau1h) = phi(0) / (|dP/dK| * S).  Fit |dP/dK| from the
              ladder strikes straddling P=0.5.
Both reported as instantaneous fractional vol (per sqrt-second) so they are directly
comparable; ratio sigma_15/sigma_1h ~ 1 == coherent. Persistent ratio != 1 == a
cross-horizon relative-value signal (buy the cheap-vol horizon, sell the rich one).

Writes one JSONL row per snapshot to data/xhorizon/coherence/<UTCdate>.jsonl, so looping
this script (e.g. every 20s) accumulates the dataset a verdict needs. NO history is
recorded by the existing collectors, so accumulation must start here.

Usage:
  python scripts/research/xhorizon_vol_coherence.py                 # one snapshot
  python scripts/research/xhorizon_vol_coherence.py --loop-seconds 20 --session 900
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from btc5m.config import load_config

UA = "btc5m-research/1.0"
SQRT2 = math.sqrt(2.0)
PHI0 = 1.0 / math.sqrt(2.0 * math.pi)   # phi(0) = 0.3989


def _norm_ppf(p):
    """Inverse standard normal CDF (Acklam approximation; good to ~1e-9)."""
    if not (0.0 < p < 1.0):
        return float("nan")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def _f(x):
    try:
        if x in (None, ""):
            return None
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _get(base, path, params=None, tries=5, timeout=20.0):
    url = f"{base}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                time.sleep(1.5 * (i + 1))
                continue
            raise
    raise last


def _yes_mid(m):
    yb, ya = _f(m.get("yes_bid_dollars")), _f(m.get("yes_ask_dollars"))
    if yb is not None and ya is not None:
        return (yb + ya) / 2.0
    lp = _f(m.get("last_price_dollars"))
    return lp


def _close_s(m):
    ct = m.get("close_time")
    if not ct:
        return None
    try:
        return datetime.strptime(ct, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def snapshot(base, now_s):
    # --- 15m current window ---
    m15 = (_get(base, "/markets", {"series_ticker": "KXBTC15M", "status": "open", "limit": 5})
           .get("markets") or [])
    m15 = [m for m in m15 if (_close_s(m) or 0) > now_s]
    m15.sort(key=lambda m: _close_s(m))
    s15 = m15[0] if m15 else None

    # --- hourly ladder: nearest-close event ---
    allm = []
    cur = None
    for _ in range(6):
        d = _get(base, "/markets", {"series_ticker": "KXBTCD", "status": "open",
                                    "limit": 200, "cursor": cur})
        allm += d.get("markets") or []
        cur = d.get("cursor") or None
        if not cur:
            break
    fut = [m for m in allm if (_close_s(m) or 0) > now_s]
    if not fut:
        return {"ts": now_s, "error": "no_open_ladder"}
    # prefer the soonest ladder with healthy maturity (avoid the about-to-expire one,
    # whose collapsing CDF makes the ATM slope noisy); fall back to the very nearest.
    TAU_FLOOR = 180.0
    closes = sorted({_close_s(m) for m in fut if _close_s(m)})
    healthy = [c for c in closes if (c - now_s) >= TAU_FLOOR]
    nearest_close = healthy[0] if healthy else closes[0]
    ladder = sorted((m for m in fut if abs((_close_s(m) or 0) - nearest_close) < 1),
                    key=lambda m: _f(m.get("floor_strike")) or 0)

    # ladder CDF: P(yes) = P(S >= K)
    pts = [(_f(m.get("floor_strike")), _yes_mid(m)) for m in ladder]
    pts = [(k, p) for k, p in pts if k is not None and p is not None and 0.0 < p < 1.0]
    out = {"ts": now_s, "iso": datetime.fromtimestamp(now_s, tz=timezone.utc).isoformat(),
           "ladder_close_s": nearest_close, "tau_1h_s": nearest_close - now_s,
           "n_strikes": len(pts)}

    # implied ATM level S* (50% crossing) and local slope dP/dK
    sigma_1h_sqrt = None
    s_star = None
    if len(pts) >= 3:
        # find bracket where P crosses 0.5 (P decreasing in K)
        for i in range(len(pts) - 1):
            (k0, p0), (k1, p1) = pts[i], pts[i + 1]
            if p0 >= 0.5 >= p1 and k1 > k0:
                s_star = k0 + (k1 - k0) * (p0 - 0.5) / (p0 - p1)
                # local slope using a small straddle window
                lo = max(0, i - 2)
                hi = min(len(pts) - 1, i + 3)
                kk = [pts[j][0] for j in range(lo, hi + 1)]
                pp = [pts[j][1] for j in range(lo, hi + 1)]
                # OLS slope
                n = len(kk)
                mk = sum(kk) / n
                mp = sum(pp) / n
                den = sum((k - mk) ** 2 for k in kk)
                if den > 0:
                    slope = sum((kk[j] - mk) * (pp[j] - mp) for j in range(n)) / den
                    if slope < 0:
                        sigma_1h_sqrt = PHI0 / (abs(slope) * s_star)  # = sigma*sqrt(tau1h) (fractional)
                break
    tau1h = out["tau_1h_s"]
    out["s_star_ladder"] = s_star
    out["sigma_1h"] = (sigma_1h_sqrt / math.sqrt(tau1h)) if (sigma_1h_sqrt and tau1h and tau1h > 0) else None

    # --- 15m implied sigma via GTE inversion ---
    out["m15_ticker"] = s15.get("ticker") if s15 else None
    if s15:
        ref = _f(s15.get("floor_strike"))         # target = window-open reference
        p15 = _yes_mid(s15)
        c15 = _close_s(s15)
        tau15 = (c15 - now_s) if c15 else None
        spot = s_star if s_star else ref           # best available spot proxy (ladder ATM)
        out.update({"m15_ref": ref, "m15_p_yes": p15, "tau_15_s": tau15, "spot_proxy": spot})
        if (ref and spot and p15 and 0.02 < p15 < 0.98 and tau15 and tau15 > 0
                and abs(p15 - 0.5) > 0.03):
            z = _norm_ppf(p15)
            if z and abs(z) > 1e-6:
                sigma_15_sqrt = math.log(spot / ref) / z      # sigma*sqrt(tau15) (fractional)
                if sigma_15_sqrt > 0:
                    out["sigma_15"] = sigma_15_sqrt / math.sqrt(tau15)
    out.setdefault("sigma_15", None)
    if out["sigma_15"] and out["sigma_1h"]:
        out["vol_ratio_15_over_1h"] = out["sigma_15"] / out["sigma_1h"]
    else:
        out["vol_ratio_15_over_1h"] = None
    return out


def fmt(o):
    if o.get("error"):
        return f"[{o['ts']}] {o['error']}"
    def g(k, nd=6):
        v = o.get(k)
        return f"{v:.{nd}f}" if isinstance(v, (int, float)) else str(v)
    return (f"[{o.get('iso')}] ladder: strikes={o.get('n_strikes')} S*={g('s_star_ladder',1)} "
            f"tau1h={g('tau_1h_s',0)}s sigma_1h={g('sigma_1h')}  |  "
            f"15m: P={g('m15_p_yes',3)} ref={g('m15_ref',1)} tau15={g('tau_15_s',0)}s "
            f"sigma_15={g('sigma_15')}  ||  RATIO 15/1h={g('vol_ratio_15_over_1h',3)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cross-horizon implied-vol coherence probe/recorder (READ-ONLY).")
    ap.add_argument("--loop-seconds", type=float, default=0.0, help="0 = single snapshot")
    ap.add_argument("--session", type=float, default=0.0, help="total seconds to loop")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(mode="paper")
    base = cfg.kalshi.api_base.rstrip("/")

    def run_once():
        now_s = int(time.time())
        o = snapshot(base, now_s)
        print(fmt(o))
        if not args.no_write and not o.get("error"):
            day = datetime.fromtimestamp(now_s, tz=timezone.utc).strftime("%Y%m%d")
            outdir = os.path.join(os.environ.get("DATA_DIR", "data"), "xhorizon", "coherence")
            os.makedirs(outdir, exist_ok=True)
            with open(os.path.join(outdir, f"{day}.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(o) + "\n")
        return o

    if args.loop_seconds <= 0:
        run_once()
        return
    t_end = time.time() + (args.session or args.loop_seconds)
    while time.time() < t_end:
        try:
            run_once()
        except Exception as e:  # noqa: BLE001
            print(f"snapshot error: {e!r}")
        time.sleep(args.loop_seconds)


if __name__ == "__main__":
    main()
