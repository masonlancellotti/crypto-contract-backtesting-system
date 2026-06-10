"""Rich, point-in-time Kalshi underlying microstructure features.

The thin v1 Kalshi feature row carried only a single spot ``reference_price`` and
a ``spot_sigma_per_sqrt_s``. This module adds the richer external-crypto
microstructure the older Polymarket path had — returns, realized vol, spot-perp
basis, microprice, queue imbalance, OFI, CVD, trade intensity — computed
**point-in-time** from rolling buffers of recorded :class:`UnderlyingEvent`s.

HARD RULE (no invented features): every value is derived only from data already
observed at/before ``as_of_ms``. If a feature cannot be computed from the
currently recorded raw/normalized data, it is emitted as ``None`` and a
missingness flag + reason code is recorded instead of being faked. Coinbase's
public *ticker* carries no bid/ask SIZES, so spot microprice/queue-imbalance/OFI
are reported missing (reason ``COINBASE_TICKER_HAS_NO_SIZES``); Binance USDT-M
``bookTicker`` carries sizes, so perp microprice/imbalance/OFI are available.

Source labels (matching ``data/underlying.py``):
- spot  = ``coinbase`` (BTC-USD ticker + trades)
- perp  = ``binance_futures`` (BTCUSDT bookTicker + trades)
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Optional

# Bump when the feature schema changes so downstream code can gate on it.
# v2: rich Coinbase/Binance microstructure. v3: + optional point-in-time Deribit
# vol/options/regime fields (deribit_*; None/flagged when disabled/stale/missing).
FEATURE_SET_VERSION = 3

# Rolling buffer horizon: keep ~15 min of underlying so a full 15m window fits.
_MAX_AGE_MS = 16 * 60 * 1000

# Return / realized-vol horizons (seconds).
RETURN_HORIZONS_S = (5, 15, 30, 60, 180)
VOL_HORIZONS_S = (30, 60, 180)

# A feed older than this (ms) at as_of is considered stale.
_STALE_MS = 5_000

_SPOT_SOURCES = {"coinbase", "coinbase_spot", "cb"}
_PERP_SOURCES = {"binance_futures", "binance", "binance_perp"}


def _f(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _ev_get(ev: Any, key: str) -> Any:
    """Read a field from either an UnderlyingEvent dataclass or a plain dict."""
    if isinstance(ev, dict):
        return ev.get(key)
    return getattr(ev, key, None)


def _mid_of(ev: Any) -> Optional[float]:
    bid = _f(_ev_get(ev, "best_bid"))
    ask = _f(_ev_get(ev, "best_ask"))
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0
    return _f(_ev_get(ev, "price"))


class UnderlyingMicrostructureState:
    """Rolling buffers of underlying events for point-in-time feature reads.

    Feed it every recorded ``UnderlyingEvent`` (dict or dataclass) via
    :meth:`ingest`; ask for a flat feature dict at any ``as_of_ms`` via
    :meth:`features`. Buffers are time-trimmed so memory stays bounded across a
    long continuous run. No look-ahead: ``features(as_of_ms)`` only reads samples
    whose timestamp is ``<= as_of_ms``.
    """

    def __init__(self, max_age_ms: int = _MAX_AGE_MS) -> None:
        self.max_age_ms = max_age_ms
        # (ts_ms, mid)
        self.spot_mid: deque[tuple[int, float]] = deque()
        self.perp_mid: deque[tuple[int, float]] = deque()
        # latest perp quote (binance has sizes): (ts, bid, ask, bid_size, ask_size)
        self.perp_quotes: deque[tuple[int, float, float, Optional[float], Optional[float]]] = deque()
        self.spot_quotes: deque[tuple[int, Optional[float], Optional[float]]] = deque()
        # trades: (ts_ms, price, size, side)  side in {"buy","sell",None}
        self.spot_trades: deque[tuple[int, Optional[float], Optional[float], Optional[str]]] = deque()
        self.perp_trades: deque[tuple[int, Optional[float], Optional[float], Optional[str]]] = deque()
        self.last_spot_ms: Optional[int] = None
        self.last_perp_ms: Optional[int] = None

    # ----- ingest --------------------------------------------------------- #
    def ingest(self, ev: Any) -> None:
        source = (_ev_get(ev, "source") or "").lower()
        etype = (_ev_get(ev, "event_type") or "").lower()
        ts = _ev_get(ev, "recv_ms") or _ev_get(ev, "exchange_ts_ms")
        ts = int(ts) if ts is not None else None
        if ts is None:
            return
        if source in _SPOT_SOURCES:
            self.last_spot_ms = max(self.last_spot_ms or 0, ts)
            if etype == "trade":
                self.spot_trades.append((ts, _f(_ev_get(ev, "price")), _f(_ev_get(ev, "size")),
                                         _ev_get(ev, "side")))
            else:
                m = _mid_of(ev)
                if m is not None:
                    self.spot_mid.append((ts, m))
                self.spot_quotes.append((ts, _f(_ev_get(ev, "best_bid")), _f(_ev_get(ev, "best_ask"))))
        elif source in _PERP_SOURCES:
            self.last_perp_ms = max(self.last_perp_ms or 0, ts)
            if etype == "trade":
                self.perp_trades.append((ts, _f(_ev_get(ev, "price")), _f(_ev_get(ev, "size")),
                                         _ev_get(ev, "side")))
            else:
                m = _mid_of(ev)
                if m is not None:
                    self.perp_mid.append((ts, m))
                self.perp_quotes.append((ts, _f(_ev_get(ev, "best_bid")), _f(_ev_get(ev, "best_ask")),
                                         _f(_ev_get(ev, "bid_size")), _f(_ev_get(ev, "ask_size"))))
        self._trim(ts)

    def _trim(self, now_ms: int) -> None:
        cutoff = now_ms - self.max_age_ms
        for buf in (self.spot_mid, self.perp_mid, self.spot_quotes, self.perp_quotes,
                    self.spot_trades, self.perp_trades):
            while buf and buf[0][0] < cutoff:
                buf.popleft()

    # ----- helpers -------------------------------------------------------- #
    @staticmethod
    def _at_or_before(buf, t_ms: int):
        """Latest (ts, *) tuple with ts <= t_ms, or None."""
        found = None
        for item in buf:
            if item[0] <= t_ms:
                found = item
            else:
                break
        return found

    @staticmethod
    def _window(buf, lo_ms: int, hi_ms: int) -> list:
        return [it for it in buf if lo_ms <= it[0] <= hi_ms]

    @staticmethod
    def _sigma_per_sqrt_s(samples: list[tuple[int, float]]) -> Optional[float]:
        rets = []
        for (t0, p0), (t1, p1) in zip(samples, samples[1:]):
            if p0 and p1 and p0 > 0 and p1 > 0 and t1 > t0:
                dt = (t1 - t0) / 1000.0
                if dt > 0:
                    rets.append(math.log(p1 / p0) / math.sqrt(dt))
        if len(rets) < 3:
            return None
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        return math.sqrt(var) if var > 0 else None

    # ----- the feature read ----------------------------------------------- #
    def features(self, *, as_of_ms: int, window_start_ms: Optional[int] = None) -> dict:
        """Return a flat dict of point-in-time underlying features + flags."""
        spot_hist = [it for it in self.spot_mid if it[0] <= as_of_ms]
        perp_hist = [it for it in self.perp_mid if it[0] <= as_of_ms]
        spot_now = spot_hist[-1][1] if spot_hist else None
        perp_now = perp_hist[-1][1] if perp_hist else None

        out: dict[str, Any] = {}
        missing: list[str] = []
        has_spot = spot_now is not None
        has_perp = perp_now is not None

        # ---- returns (spot) -------------------------------------------------
        for h in RETURN_HORIZONS_S:
            key = f"spot_return_{h}s"
            val = None
            if has_spot:
                past = self._at_or_before(self.spot_mid, as_of_ms - h * 1000)
                if past and past[1] and past[1] > 0 and spot_now > 0:
                    val = math.log(spot_now / past[1])
            out[key] = val
            if val is None:
                missing.append(key)
        # return since window start
        rsw = None
        if has_spot and window_start_ms:
            start = self._at_or_before(self.spot_mid, window_start_ms) or (
                spot_hist[0] if spot_hist else None)
            if start and start[1] and start[1] > 0 and spot_now > 0:
                rsw = math.log(spot_now / start[1])
        out["spot_return_since_window_start"] = rsw

        # ---- realized vol (spot) -------------------------------------------
        for w in VOL_HORIZONS_S:
            key = f"realized_vol_{w}s"
            samples = self._window(self.spot_mid, as_of_ms - w * 1000, as_of_ms)
            val = self._sigma_per_sqrt_s(samples)
            out[key] = val
            if val is None:
                missing.append(key)
        if window_start_ms:
            wtd = self._sigma_per_sqrt_s(self._window(self.spot_mid, window_start_ms, as_of_ms))
        else:
            wtd = None
        out["realized_vol_window_to_date"] = wtd

        # ---- spot-perp basis ------------------------------------------------
        basis = (perp_now - spot_now) if (has_spot and has_perp) else None
        out["spot_perp_basis"] = basis
        basis_change = None
        if basis is not None:
            sp_past = self._at_or_before(self.spot_mid, as_of_ms - 60_000)
            pp_past = self._at_or_before(self.perp_mid, as_of_ms - 60_000)
            if sp_past and pp_past:
                basis_change = (perp_now - spot_now) - (pp_past[1] - sp_past[1])
        out["spot_perp_basis_change_60s"] = basis_change
        if basis is None:
            missing.append("spot_perp_basis")

        # ---- quotes / spreads ----------------------------------------------
        sq = self._at_or_before(self.spot_quotes, as_of_ms)
        out["coinbase_best_bid"] = sq[1] if sq else None
        out["coinbase_best_ask"] = sq[2] if sq else None
        out["coinbase_spread"] = (sq[2] - sq[1]) if (sq and sq[1] is not None and sq[2] is not None) else None
        pq = self._at_or_before(self.perp_quotes, as_of_ms)
        out["binance_best_bid"] = pq[1] if pq else None
        out["binance_best_ask"] = pq[2] if pq else None
        out["binance_spread"] = (pq[2] - pq[1]) if (pq and pq[1] is not None and pq[2] is not None) else None

        # ---- perp microprice / queue imbalance (binance has sizes) ----------
        micro = qimb = None
        has_perp_sizes = bool(pq and pq[3] is not None and pq[4] is not None)
        if has_perp_sizes and pq[1] is not None and pq[2] is not None:
            sb, sa = pq[3], pq[4]
            denom = sb + sa
            if denom > 0:
                micro = (pq[1] * sa + pq[2] * sb) / denom  # Stoikov microprice
                qimb = (sb - sa) / denom
        out["binance_microprice"] = micro
        out["binance_queue_imbalance"] = qimb
        # spot microprice cannot be computed (no sizes on the public ticker)
        out["coinbase_microprice"] = None
        out["coinbase_queue_imbalance"] = None

        # ---- OFI (binance best-level, between last two quotes) ---------------
        ofi = None
        perp_q_hist = [q for q in self.perp_quotes if q[0] <= as_of_ms]
        if has_perp_sizes and len(perp_q_hist) >= 2:
            prev, cur = perp_q_hist[-2], perp_q_hist[-1]
            if all(v is not None for v in (prev[1], prev[2], prev[3], prev[4],
                                           cur[1], cur[2], cur[3], cur[4])):
                ofi = _best_level_ofi((prev[1], prev[3]), (prev[2], prev[4]),
                                      (cur[1], cur[3]), (cur[2], cur[4]))
        out["binance_ofi_best"] = ofi
        if ofi is None:
            missing.append("binance_ofi_best")
        # multi-level OFI is not derivable from the recorded top-of-book feed.
        out["binance_ofi_multilevel"] = None

        # ---- CVD / signed trade imbalance / trade intensity (60s) -----------
        for label, trades in (("spot", self.spot_trades), ("perp", self.perp_trades)):
            win = self._window(trades, as_of_ms - 60_000, as_of_ms)
            buy = sum((s or 0.0) for (_t, _p, s, side) in win if side == "buy")
            sell = sum((s or 0.0) for (_t, _p, s, side) in win if side == "sell")
            signed = (buy - sell)
            denom = buy + sell
            out[f"{label}_cvd_60s"] = signed if win else None
            out[f"{label}_signed_trade_imbalance_60s"] = (signed / denom) if denom > 0 else None
            out[f"{label}_trade_intensity_60s"] = (len(win) / 60.0) if win else None
            if not win:
                missing.append(f"{label}_trades_60s")

        # ---- feed freshness / staleness / source health --------------------
        spot_age = (as_of_ms - self.last_spot_ms) if self.last_spot_ms else None
        perp_age = (as_of_ms - self.last_perp_ms) if self.last_perp_ms else None
        out["coinbase_feed_age_ms"] = spot_age
        out["binance_feed_age_ms"] = perp_age
        out["coinbase_stale"] = bool(spot_age is not None and spot_age > _STALE_MS)
        out["binance_stale"] = bool(perp_age is not None and perp_age > _STALE_MS)

        out["underlying_feature_flags"] = {
            "has_spot": has_spot,
            "has_perp": has_perp,
            "has_perp_sizes": has_perp_sizes,
            "has_spot_trades": bool(self._window(self.spot_trades, as_of_ms - 60_000, as_of_ms)),
            "has_perp_trades": bool(self._window(self.perp_trades, as_of_ms - 60_000, as_of_ms)),
            "coinbase_stale": out["coinbase_stale"],
            "binance_stale": out["binance_stale"],
        }
        reasons: list[str] = []
        if not has_spot:
            reasons.append("NO_SPOT_FEED")
        if not has_perp:
            reasons.append("NO_PERP_FEED")
        if has_perp and not has_perp_sizes:
            reasons.append("PERP_QUOTE_HAS_NO_SIZES")
        if not has_spot or True:  # spot ticker never carries sizes
            reasons.append("COINBASE_TICKER_HAS_NO_SIZES")
        out["underlying_missing_features"] = missing
        out["underlying_missing_reason_codes"] = reasons
        return out


def _best_level_ofi(prev_bid, prev_ask, bid, ask) -> float:
    """Cont/Kukanov/Stoikov best-level OFI between two snapshots (price, size)."""
    pb_p, pb_s = prev_bid
    pa_p, pa_s = prev_ask
    b_p, b_s = bid
    a_p, a_s = ask
    if b_p > pb_p:
        d_bid = b_s
    elif b_p == pb_p:
        d_bid = b_s - pb_s
    else:
        d_bid = -pb_s
    if a_p < pa_p:
        d_ask = a_s
    elif a_p == pa_p:
        d_ask = a_s - pa_s
    else:
        d_ask = -pa_s
    return d_bid - d_ask
