"""Chainlink Data Streams client — the OFFICIAL BTC/USD numeric source (gated).

Polymarket BTC 5-minute markets resolve from the Chainlink BTC/USD **Data
Stream** (`data.chain.link/streams/btc-usd`). The Data Streams (Data Engine) API
is authenticated (HMAC-signed) and is NOT public, so by default this client is
**not configured** and the system keeps Coinbase/Binance values as
PROVISIONAL_REFERENCE. If — and only if — the user provides credentials locally
(env-only), this client can fetch OFFICIAL settlement-grade reference prices.

Credentials (env-only; never hardcoded, never logged):
    CHAINLINK_STREAMS_API_KEY
    CHAINLINK_STREAMS_API_SECRET
    CHAINLINK_STREAMS_API_URL   (default https://api.dataengine.chain.link)
    CHAINLINK_BTC_FEED_ID       (the BTC/USD stream feed id / report id)

Limitations / honesty:
- This client is implemented to the documented Data Streams HMAC scheme but is
  UNVERIFIED end-to-end without live credentials. The pure signing + report
  parsing are unit-tested with fixtures. Treat a successful fetch as OFFICIAL
  ONLY when it actually comes from this Chainlink source.
- Timestamp alignment: Data Streams reports are keyed by observation time. We
  request the report at/around the window boundary (`window_start` / `expiry`)
  in seconds; sub-second alignment to the exact resolution instant is a known
  limitation and is recorded in the line/label detail.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.request
from typing import Optional

_log = logging.getLogger("btc5m.chainlink")

DEFAULT_API_URL = "https://api.dataengine.chain.link"
_REPORT_PATH = "/api/v1/reports"
# Data Streams report prices are fixed-point with 18 decimals.
_PRICE_SCALE = 10**18


class ChainlinkStreamsClient:
    """Authenticated Chainlink Data Streams client (OFFICIAL source, gated)."""

    source = "chainlink_streams"

    def __init__(self, config=None):
        self.config = config
        self.api_url = os.environ.get("CHAINLINK_STREAMS_API_URL") or DEFAULT_API_URL
        self.feed_id = os.environ.get("CHAINLINK_BTC_FEED_ID") or None
        self._api_key = os.environ.get("CHAINLINK_STREAMS_API_KEY") or None
        self._api_secret = os.environ.get("CHAINLINK_STREAMS_API_SECRET") or None

    @property
    def is_configured(self) -> bool:
        """True only when key + secret + feed id are all present (env-only)."""
        return bool(self._api_key and self._api_secret and self.feed_id)

    def not_configured_reason(self) -> str:
        missing = [
            name
            for name, val in (
                ("CHAINLINK_STREAMS_API_KEY", self._api_key),
                ("CHAINLINK_STREAMS_API_SECRET", self._api_secret),
                ("CHAINLINK_BTC_FEED_ID", self.feed_id),
            )
            if not val
        ]
        return f"Chainlink Data Streams not configured (missing: {', '.join(missing)})"

    # ----- pure helpers (unit-tested) --------------------------------------
    @staticmethod
    def build_signature(
        method: str,
        path: str,
        body: bytes,
        api_key: str,
        api_secret: str,
        timestamp_ms: int,
    ) -> str:
        """Compute the Data Streams HMAC-SHA256 signature (hex).

        Per the documented scheme the signing string is:
            method + space + path + space + sha256(body) + space + apiKey +
            space + timestampMs
        and the signature is HMAC-SHA256(secret, signing_string).
        """
        body_hash = hashlib.sha256(body).hexdigest()
        signing_string = f"{method} {path} {body_hash} {api_key} {timestamp_ms}"
        return hmac.new(
            api_secret.encode("utf-8"), signing_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def report_to_price(report: dict, *, scale: int = _PRICE_SCALE) -> Optional[float]:
        """Extract a USD benchmark price from a Data Streams report dict.

        Looks for a benchmark/price field (decimal or 0x-hex big integer) and
        rescales by ``scale`` (1e18). Returns None if no usable field exists.
        """
        node = report.get("report", report) if isinstance(report, dict) else {}
        for key in ("benchmarkPrice", "price", "median", "benchmark"):
            if key in node and node[key] is not None:
                raw = node[key]
                try:
                    if isinstance(raw, str) and raw.startswith("0x"):
                        val = int(raw, 16)
                    else:
                        val = int(raw)
                except (TypeError, ValueError):
                    try:
                        return float(raw)  # already a decimal price
                    except (TypeError, ValueError):
                        return None
                return val / scale
        return None

    # ----- network (gated) --------------------------------------------------
    def _signed_request(self, path: str) -> dict:
        method = "GET"
        body = b""
        ts = int(time.time() * 1000)
        sig = self.build_signature(method, path, body, self._api_key, self._api_secret, ts)
        url = f"{self.api_url}{path}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": self._api_key,
                "X-Authorization-Timestamp": str(ts),
                "X-Authorization-Signature-SHA256": sig,
                "User-Agent": "btc5m/0.1",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def price_at(self, ts_ms: int) -> tuple[Optional[float], dict]:
        """OFFICIAL BTC/USD price near ``ts_ms`` from Chainlink Data Streams.

        Returns (price, detail). If not configured or on failure, returns
        (None, {"reason": ...}) — callers must NOT treat None as official.
        """
        if not self.is_configured:
            return None, {"reason": self.not_configured_reason()}
        ts_seconds = ts_ms // 1000
        path = f"{_REPORT_PATH}?feedID={self.feed_id}&timestamp={ts_seconds}"
        try:
            payload = self._signed_request(path)
        except Exception as exc:  # noqa: BLE001 - never raise; report the blocker
            _log.warning("Chainlink fetch failed: %s", type(exc).__name__)
            return None, {"reason": f"fetch_failed: {type(exc).__name__}"}
        price = self.report_to_price(payload)
        if price is None:
            return None, {"reason": "no_price_in_report", "ts_seconds": ts_seconds}
        return price, {
            "ts_seconds": ts_seconds,
            "feed_id": self.feed_id,
            "source": "chainlink_data_streams",
        }
