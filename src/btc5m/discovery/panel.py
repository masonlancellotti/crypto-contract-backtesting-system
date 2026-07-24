"""Observation panel — one independent, point-in-time observation per 15m window.

For each window we take the decision snapshot nearest a chosen seconds-to-close, and record
the candidate features, the market-implied probability (mid of yes_ask & 1-no_ask), the
executable buy prices (for honest after-cost P&L), and the settled label. One row per window
keeps observations independent for the purged CV / gauntlet."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import feature_factory


def _f(x):
    try:
        if x is None:
            return None
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def market_prob_yes(row) -> float | None:
    ya, na = _f(row.get("yes_ask")), _f(row.get("no_ask"))
    lo = (1.0 - na) if na is not None else None
    hi = ya if ya is not None else None
    vals = [v for v in (lo, hi) if v is not None and 0.0 < v < 1.0]
    return sum(vals) / len(vals) if vals else None


@dataclass
class Observation:
    ticker: str
    asset: str
    close_ms: int
    y: int
    mkt_p: float          # decision-time market-implied prob (for feature screening)
    exec_yes: float       # EXECUTION-time ask (lagged): the price you could really pay
    exec_no: float
    feats: dict = field(default_factory=dict)
    exec_lagged: bool = True
    t0_ms: int | None = None      # decision time (epoch ms) — for maker print-fill joins
    yes_bid: float | None = None  # decision-time best YES bid (maker join level)
    no_bid: float | None = None


def _close_ms(row):
    return row.get("market_close_ts_ms") or row.get("close_ms")


def _exec_prices(row):
    ex_y = _f(row.get("executable_yes_buy_price")) or _f(row.get("yes_ask"))
    ex_n = _f(row.get("executable_no_buy_price")) or _f(row.get("no_ask"))
    return ex_y, ex_n


def build_panel(rows: list[dict], *, asset: str, lead_seconds: float = 180.0,
                tol: float = 45.0, exec_lag_seconds: float = 3.0,
                exec_tol: float = 8.0) -> list[Observation]:
    """One Observation per window: features + market prob read at the decision snapshot
    (~`lead_seconds` to close), but the fill PRICED at a quote sampled `exec_lag_seconds`
    LATER (a realistic post-signal execution lag). Pricing at a same-instant quote lets a
    rule book a fill the market hasn't yet repriced — a stale-quote look-ahead that
    manufactures the reprice-lag artifact (#8/#23). Lagging the execution quote removes it.
    `exec_lag_seconds=0` restores same-instant pricing (for A/B comparison)."""
    by_win: dict[str, list[dict]] = {}
    for r in rows:
        tk = r.get("ticker") or r.get("market_ticker")
        if tk is None or r.get("label_yes_resolved") is None:
            continue
        by_win.setdefault(tk, []).append(r)

    obs: list[Observation] = []
    for tk, wr in by_win.items():
        # decision snapshot: nearest lead_seconds
        dec, decd, dec_s = None, tol + 1, None
        for r in wr:
            s = _f(r.get("seconds_to_close"))
            if s is None:
                continue
            d = abs(s - lead_seconds)
            if d < decd:
                dec, decd, dec_s = r, d, s
        if dec is None or decd > tol:
            continue

        # execution snapshot: a quote at least `exec_lag_seconds` LATER (smaller secs-to-close)
        lagged = True
        if exec_lag_seconds <= 0:
            exec_row = dec
            lagged = False
        else:
            target = dec_s - exec_lag_seconds
            cands = [(abs((_f(r.get("seconds_to_close"))) - target), r) for r in wr
                     if _f(r.get("seconds_to_close")) is not None
                     and _f(r.get("seconds_to_close")) < dec_s - 1e-9]
            if not cands:
                continue                       # no realistic later quote -> can't execute honestly
            d2, exec_row = min(cands, key=lambda t: t[0])
            if d2 > exec_tol:
                continue

        mp = market_prob_yes(dec)
        cm = _close_ms(dec)
        ex_y, ex_n = _exec_prices(exec_row)
        if mp is None or cm is None or ex_y is None or ex_n is None:
            continue
        t0 = int(cm - dec_s * 1000) if dec_s is not None else None   # decision time (epoch ms)
        obs.append(Observation(
            ticker=tk, asset=asset, close_ms=int(cm),
            y=int(dec["label_yes_resolved"]), mkt_p=mp,
            exec_yes=ex_y, exec_no=ex_n, exec_lagged=lagged,
            feats=feature_factory.extract(dec),
            t0_ms=t0, yes_bid=_f(dec.get("yes_bid")), no_bid=_f(dec.get("no_bid")),
        ))
    obs.sort(key=lambda o: o.close_ms)
    return obs


def filter_panel(panel: list[Observation], keys: set) -> list[Observation]:
    """Restrict a panel to a set of window tickers (e.g. vault.search_keys)."""
    keyset = set(keys)
    return [o for o in panel if o.ticker in keyset]


def rank_normalize_per_asset(observations: list[Observation]) -> list[Observation]:
    """Replace each feature value with its within-ASSET percentile rank (0..1).

    Essential for pooling assets: features (vol, returns, depth) live on different scales
    per asset, so a raw threshold mixes apples and oranges. After this, a 'top-quartile'
    rule (feature >= 0.75) means the same thing for every asset, and the after-cost P&L
    (exec prices, label) is untouched. Null features stay null."""
    from collections import defaultdict
    by_asset: dict[str, list[Observation]] = defaultdict(list)
    for o in observations:
        by_asset[o.asset].append(o)
    names: set[str] = set()
    for o in observations:
        names.update(o.feats.keys())

    out: list[Observation] = []
    for asset, obs in by_asset.items():
        pcts: dict[str, dict[int, float]] = {}
        for nm in names:
            present = [(i, o.feats.get(nm)) for i, o in enumerate(obs) if o.feats.get(nm) is not None]
            m = len(present)
            if m < 5:
                continue
            order = sorted(present, key=lambda t: t[1])
            pcts[nm] = {i: (rank + 0.5) / m for rank, (i, _v) in enumerate(order)}
        for i, o in enumerate(obs):
            nf = {nm: pcts[nm][i] for nm in names if nm in pcts and i in pcts[nm]}
            out.append(Observation(ticker=o.ticker, asset=o.asset, close_ms=o.close_ms, y=o.y,
                                   mkt_p=o.mkt_p, exec_yes=o.exec_yes, exec_no=o.exec_no,
                                   feats=nf, exec_lagged=o.exec_lagged))
    out.sort(key=lambda o: o.close_ms)
    return out
