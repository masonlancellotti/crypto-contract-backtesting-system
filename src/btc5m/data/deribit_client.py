"""Deribit volatility / options client — OPTIONAL auxiliary regime source.

Deribit is NOT a trading venue here and NOT required for the Kalshi MVP. It is an
optional volatility/options/regime signal: when the Kalshi line is close, time is
short, and realized + implied vol are elevated, widen uncertainty / demand more
edge. It must NEVER be used as a directional signal (e.g. "OI is bullish → buy
YES").

Disabled by default (``DERIBIT_ENABLED=false``). Public REST reads (DVOL, index,
historical vol, option book summary) need NO credentials. The parse helpers are
pure functions so they can be unit-tested offline against fixtures.

Public endpoints (all GET, no auth):
    /public/get_index_price?index_name=btc_usd
    /public/get_volatility_index_data?currency=BTC&start_timestamp&end_timestamp&resolution
    /public/get_historical_volatility?currency=BTC
    /public/get_book_summary_by_currency?currency=BTC&kind=option
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from statistics import median
from typing import Any, Optional

from ..config import AppConfig
from ..timeutils import now_ms

_USER_AGENT = "btc5m-deribit/0.1 (+research; read-only public endpoints)"


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Pure parsers (offline-testable)
# --------------------------------------------------------------------------- #
def parse_index_price(raw: dict) -> Optional[float]:
    return _f((raw or {}).get("result", {}).get("index_price"))


def parse_dvol(raw: dict) -> Optional[float]:
    """Last close of the DVOL volatility-index series. Data rows: [ts,o,h,l,c]."""
    data = (raw or {}).get("result", {}).get("data") or []
    if not data:
        return None
    last = data[-1]
    if isinstance(last, list) and len(last) >= 5:
        return _f(last[4])
    return None


def parse_historical_vol(raw: dict) -> Optional[float]:
    """Last value of Deribit's annualized historical-vol series. Rows: [ts,vol]."""
    data = (raw or {}).get("result") or []
    if isinstance(data, list) and data:
        last = data[-1]
        if isinstance(last, list) and len(last) >= 2:
            return _f(last[1])
    return None


def _expiry_token(instrument_name: str) -> Optional[str]:
    # BTC-27JUN25-60000-C -> "27JUN25"
    parts = (instrument_name or "").split("-")
    return parts[1] if len(parts) >= 4 else None


def _strike_token(instrument_name: str) -> Optional[float]:
    # BTC-27JUN25-60000-C -> 60000.0
    parts = (instrument_name or "").split("-")
    if len(parts) >= 4:
        return _f(parts[2])
    return None


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """numerator/denominator, guarding None and division by zero -> None."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    try:
        return numerator / denominator
    except ZeroDivisionError:
        return None


def summarize_options(raw: dict, *, index_price: Optional[float] = None) -> dict:
    """Aggregate the option book summary into OI/volume/IV/skew proxies.

    ``skew_proxy`` = mean put mark_iv − mean call mark_iv (put-call IV skew).
    ``near_expiry_iv`` = median mark_iv of the soonest-listed (front) expiry.
    ``atm_iv`` = mean mark_iv of the option(s) whose strike is closest to
    ``index_price`` within the front expiry (an honest at-the-money proxy; only
    computed when an index price and strikes are available). All values are None
    when the underlying data is absent — never invented.
    """
    empty = {"open_interest_total": None, "volume_total": None,
             "call_open_interest_total": None, "put_open_interest_total": None,
             "call_volume_total": None, "put_volume_total": None,
             "near_expiry_iv": None, "atm_iv": None, "skew_proxy": None,
             "n_instruments": 0}
    rows = (raw or {}).get("result") or []
    if not isinstance(rows, list) or not rows:
        return empty
    oi_total = vol_total = 0.0
    call_oi = put_oi = call_vol = put_vol = 0.0
    call_iv: list[float] = []
    put_iv: list[float] = []
    by_expiry: dict[str, list[float]] = {}
    # (expiry, strike, iv) per instrument for the ATM proxy.
    strikes_by_expiry: dict[str, list[tuple[float, float]]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        oi = _f(r.get("open_interest"))
        vol = _f(r.get("volume"))
        iv = _f(r.get("mark_iv"))
        name = r.get("instrument_name") or ""
        is_call = name.endswith("-C")
        is_put = name.endswith("-P")
        if oi:
            oi_total += oi
            if is_call:
                call_oi += oi
            elif is_put:
                put_oi += oi
        if vol:
            vol_total += vol
            if is_call:
                call_vol += vol
            elif is_put:
                put_vol += vol
        if iv is not None:
            if is_call:
                call_iv.append(iv)
            elif is_put:
                put_iv.append(iv)
            exp = _expiry_token(name)
            if exp:
                by_expiry.setdefault(exp, []).append(iv)
                strike = _strike_token(name)
                if strike is not None:
                    strikes_by_expiry.setdefault(exp, []).append((strike, iv))
    skew = (sum(put_iv) / len(put_iv) - sum(call_iv) / len(call_iv)) if (put_iv and call_iv) else None
    near_iv = atm_iv = None
    if by_expiry:
        # soonest expiry by count is unreliable; pick the expiry with the most
        # instruments listed as a stable "front" proxy when dates aren't parsed.
        front_exp = max(by_expiry.items(), key=lambda kv: len(kv[1]))[0]
        front = by_expiry[front_exp]
        near_iv = median(front) if front else None
        if index_price is not None:
            strikes = strikes_by_expiry.get(front_exp) or []
            if strikes:
                nearest = min(abs(s - index_price) for s, _iv in strikes)
                at = [iv for s, iv in strikes if abs(s - index_price) == nearest]
                atm_iv = (sum(at) / len(at)) if at else None
    return {
        "open_interest_total": oi_total or None,
        "volume_total": vol_total or None,
        "call_open_interest_total": call_oi or None,
        "put_open_interest_total": put_oi or None,
        "call_volume_total": call_vol or None,
        "put_volume_total": put_vol or None,
        "near_expiry_iv": near_iv,
        "atm_iv": atm_iv,
        "skew_proxy": skew,
        "n_instruments": len(rows),
    }


# Public REST endpoints used to assemble a snapshot (no auth, all GET).
ENDPOINTS = {
    "index": "/public/get_index_price",
    "dvol": "/public/get_volatility_index_data",
    "historical_vol": "/public/get_historical_volatility",
    "book_summary": "/public/get_book_summary_by_currency",
}


def normalize(raw: dict, *, recv_ms: Optional[int] = None) -> dict:
    """Combine raw sub-payloads into the normalized Deribit snapshot row.

    Every field is None (with a ``deribit_missing_reason``) when its source
    sub-payload is absent or errored — values are never invented. ``recv_ms`` is
    the local receive time; ``source_ts_ms`` is Deribit's own send time when
    present. ``deribit_dvol`` and ``deribit_btc_iv_index`` are the same DVOL
    value (the latter kept for back-compat).
    """
    recv = recv_ms if recv_ms is not None else now_ms()
    index_price = parse_index_price(raw.get("index") or {})
    dvol = parse_dvol(raw.get("dvol") or {})
    hist = parse_historical_vol(raw.get("historical_vol") or {})
    opts = summarize_options(raw.get("book_summary") or {}, index_price=index_price)

    src_ts = (raw.get("index") or {}).get("usIn")  # Deribit usIn is microseconds
    source_ts_ms = freshness = None
    if src_ts:
        try:
            source_ts_ms = int(int(src_ts) / 1000)
            freshness = recv - source_ts_ms
        except (TypeError, ValueError):
            source_ts_ms = freshness = None

    # Per-endpoint error capture (one failing endpoint is non-fatal upstream).
    errored = [k for k in ENDPOINTS
               if isinstance(raw.get(k), dict) and raw[k].get("_error")]
    core = (index_price, dvol, hist, opts["open_interest_total"])
    missing_reason = None
    if all(c is None for c in core):
        missing_reason = "no_public_data_parsed"
        if errored:
            missing_reason += f" (endpoint_errors: {','.join(sorted(errored))})"

    return {
        "source": "deribit",
        "recv_ms": recv,
        "source_ts_ms": source_ts_ms,
        "currency": raw.get("currency", "BTC"),
        "deribit_index_price": index_price,
        "deribit_dvol": dvol,
        "deribit_btc_iv_index": dvol,  # back-compat alias
        "deribit_historical_vol": hist,
        "deribit_options_open_interest_total": opts["open_interest_total"],
        "deribit_call_open_interest_total": opts["call_open_interest_total"],
        "deribit_put_open_interest_total": opts["put_open_interest_total"],
        "deribit_options_volume_total": opts["volume_total"],
        "deribit_option_volume_total": opts["volume_total"],  # back-compat alias
        "deribit_call_volume_total": opts["call_volume_total"],
        "deribit_put_volume_total": opts["put_volume_total"],
        "deribit_near_expiry_iv": opts["near_expiry_iv"],
        "deribit_atm_iv": opts["atm_iv"],
        "deribit_skew_proxy": opts["skew_proxy"],
        "deribit_put_call_oi_ratio": _ratio(opts["put_open_interest_total"],
                                            opts["call_open_interest_total"]),
        "deribit_put_call_volume_ratio": _ratio(opts["put_volume_total"],
                                               opts["call_volume_total"]),
        "deribit_n_option_instruments": opts["n_instruments"],
        "deribit_data_freshness_ms": freshness,
        "deribit_endpoints": dict(ENDPOINTS),
        "deribit_missing_reason": missing_reason,
    }


def fetch_deribit_snapshot(config: AppConfig | None = None, *, currency: str = "BTC") -> dict:
    """Fetch all public sub-payloads and return one normalized snapshot dict.

    Uses only public endpoints (no credentials). Per-endpoint failures are
    tolerated and surface as None values + ``deribit_missing_reason``.
    """
    client = DeribitClient(config, currency=currency)
    return normalize(client.fetch_all())


# --------------------------------------------------------------------------- #
# Public client
# --------------------------------------------------------------------------- #
class DeribitClient:
    """Public Deribit volatility/options client (REST polling, stdlib only)."""

    source = "deribit"

    def __init__(self, config: AppConfig | None = None, *, currency: str = "BTC"):
        self.config = config
        self.currency = currency.upper()
        de = getattr(config, "deribit", None)
        self.base = (de.api_url if de else "https://www.deribit.com/api/v2").rstrip("/")
        self.enabled = bool(de.enabled) if de else False

    def _get(self, path: str, params: Optional[dict] = None, *, timeout: float = 15.0) -> Any:
        url = f"{self.base}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            url = f"{url}?{urllib.parse.urlencode(clean)}"
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_index_price(self) -> dict:
        return self._get("/public/get_index_price",
                         {"index_name": f"{self.currency.lower()}_usd"})

    def get_dvol(self, *, lookback_ms: int = 7_200_000, resolution: int = 3600) -> dict:
        end = now_ms()
        return self._get("/public/get_volatility_index_data", {
            "currency": self.currency, "start_timestamp": end - lookback_ms,
            "end_timestamp": end, "resolution": resolution,
        })

    def get_historical_volatility(self) -> dict:
        return self._get("/public/get_historical_volatility", {"currency": self.currency})

    def get_book_summary(self) -> dict:
        return self._get("/public/get_book_summary_by_currency",
                         {"currency": self.currency, "kind": "option"})

    def fetch_all(self) -> dict:
        """Fetch all public sub-payloads, tolerating per-endpoint failure."""
        raw: dict = {"currency": self.currency}
        for key, fn in (("index", self.get_index_price), ("dvol", self.get_dvol),
                        ("historical_vol", self.get_historical_volatility),
                        ("book_summary", self.get_book_summary)):
            try:
                raw[key] = fn()
            except Exception as exc:  # noqa: BLE001 - one endpoint failing is non-fatal
                raw[key] = {"_error": f"{type(exc).__name__}: {exc}"}
        return raw

    def poll(self) -> list[tuple[dict, dict]]:
        """One polling cycle: [(raw_combined, normalized)]."""
        raw = self.fetch_all()
        return [(raw, normalize(raw))]
