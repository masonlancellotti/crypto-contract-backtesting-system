"""Regime identification — tag each window by the market 'state' it sits in.

The market is efficient ON AVERAGE; efficiency can still break in specific regimes (vol
spikes, thin liquidity, low volume, strong trend, certain hours). We tag each observation
along several dimensions (terciles of the relevant feature, computed on the search set), so
the conditional mine can ask: is there a regime where an indicator beats the price after
cost? Tags are pure observable state (no look-ahead). Returns {ticker: {dim: bucket}}."""
from __future__ import annotations

from datetime import datetime, timezone

# regime dimension -> the feature whose terciles define lo/mid/hi
NUMERIC_DIMS = {
    "vol": "realized_vol_60s",          # realized volatility
    "spread": "yes_spread",             # quote tightness (liquidity)
    "depth": "top_depth",               # book depth (liquidity)
    "volume": "spot_trade_intensity_60s",  # CEX trade volume/intensity
    "ksize": "kalshi_top_size",         # Kalshi top-of-book resting size
    "trend": "spot_return_180s",        # directional move (down/flat/up)
    "iv": "deribit_atm_iv",             # options-implied vol regime (if collected)
}
T3 = ["lo", "mid", "hi"]


def _tercile_thresholds(observations, col):
    vals = sorted(o.feats.get(col) for o in observations if o.feats.get(col) is not None)
    if len(vals) < 30:
        return None
    return vals[len(vals) // 3], vals[2 * len(vals) // 3]


def assign_regimes(observations, *, terciles_from=None) -> dict:
    src = terciles_from or observations
    thr = {}
    for dim, col in NUMERIC_DIMS.items():
        t = _tercile_thresholds(src, col)
        if t is not None:
            thr[dim] = (col, t[0], t[1])
    tags: dict[str, dict] = {}
    for o in observations:
        d = {}
        for dim, (col, q1, q2) in thr.items():
            v = o.feats.get(col)
            if v is None:
                continue
            d[dim] = T3[0] if v < q1 else (T3[2] if v >= q2 else T3[1])
        # time-of-day (UTC, 4 six-hour buckets)
        h = datetime.fromtimestamp(o.close_ms / 1000, tz=timezone.utc).hour
        d["tod"] = f"h{(h // 6) * 6:02d}"
        tags[o.ticker] = d
    return tags


def regime_cells(tags: dict) -> list[tuple[str, str]]:
    """All (dimension, bucket) cells present in the tagged panel."""
    cells = set()
    for d in tags.values():
        for dim, bucket in d.items():
            cells.add((dim, bucket))
    return sorted(cells)
