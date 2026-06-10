"""Read-only Kalshi market-data WebSocket: feasibility probe + optional book source.

MARKET DATA ONLY. This module subscribes ONLY to read-only market-data channels
(``orderbook_delta``); it NEVER sends order commands, NEVER calls order/portfolio/account
endpoints, and NEVER prints secrets or private-key material. Authentication (RSA-PSS over
``timestamp+GET+path``) is used solely because Kalshi gates even market-data WS behind a key;
the signed headers are used only to open the read-only connection and are never logged.

Kalshi's market-data WS is auth-gated (unlike the public Coinbase/Binance feeds). When
credentials are absent the feasibility probe blocks cleanly (env-var NAMES only) and the
high-res recorder keeps its REST fallback. WebSocket is never the default.
"""

from __future__ import annotations

import json
import inspect
import re
import time
import traceback
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from ....timeutils import now_ms
from ..client import KalshiClient, iso_to_ms, select_collection_targets
from ..orderbook import normalize_orderbook
from .sources import BaseSource, HiResConfig, WINDOW_MS

WS_PATH = "/trade-api/ws/v2"
MARKET_DATA_CHANNELS = ["orderbook_delta"]          # READ-ONLY market data only
READ_ONLY_BANNER = "READ-ONLY MARKET DATA ONLY - NO ORDERS."


def _sanitize_text(text: object, config=None, *, limit: Optional[int] = None) -> str:
    """Redact known auth material from exception text before printing or reporting."""
    s = "" if text is None else str(text)
    for value in _known_secret_values(config):
        if value:
            s = s.replace(value, "<redacted>")
    s = re.sub(r"(KALSHI-ACCESS-KEY['\"]?\s*[:=]\s*['\"]?)[^'\",\s)}]+", r"\1<redacted>", s,
               flags=re.IGNORECASE)
    s = re.sub(r"(KALSHI-ACCESS-SIGNATURE['\"]?\s*[:=]\s*['\"]?)[^'\",\s)}]+", r"\1<redacted>", s,
               flags=re.IGNORECASE)
    s = re.sub(r"(KALSHI-ACCESS-TIMESTAMP['\"]?\s*[:=]\s*['\"]?)[^'\",\s)}]+", r"\1<redacted>", s,
               flags=re.IGNORECASE)
    s = re.sub(r"(Authorization['\"]?\s*[:=]\s*['\"]?)[^'\",\s)}]+", r"\1<redacted>", s,
               flags=re.IGNORECASE)
    s = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
               "<redacted-private-key>", s, flags=re.DOTALL)
    if limit is not None and len(s) > limit:
        return s[: max(0, limit - 3)] + "..."
    return s


def _known_secret_values(config) -> list[str]:
    k = getattr(config, "kalshi", None) if config is not None else None
    values = [
        getattr(k, "key_id", None),
        getattr(k, "private_key_path", None),
        getattr(k, "private_key_passphrase", None),
    ]
    # Avoid redacting tiny/common strings that could make diagnostics unreadable.
    return [str(v) for v in values if v and len(str(v)) >= 4]


def _sanitized_exception(exc: Exception, config=None) -> dict:
    return {
        "type": type(exc).__name__,
        "message": _sanitize_text(exc, config, limit=500),
        "traceback": _sanitize_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                                    config),
    }


def _connect_kwargs(headers: Optional[dict], *, connect_fn=None) -> tuple[dict, str]:
    """Build only kwargs supported by the installed websockets sync connect API."""
    if connect_fn is None:
        from websockets.sync.client import connect as connect_fn
    params = inspect.signature(connect_fn).parameters
    kwargs: dict = {}
    header_arg = "unsupported"
    if headers:
        if "additional_headers" in params:
            kwargs["additional_headers"] = headers
            header_arg = "additional_headers"
        elif "extra_headers" in params:
            kwargs["extra_headers"] = headers
            header_arg = "extra_headers"
        else:
            raise TypeError("websockets.sync.client.connect does not support auth headers")
    for name, value in (("open_timeout", 10), ("close_timeout", 5), ("max_queue", 512)):
        if name in params:
            kwargs[name] = value
    return kwargs, header_arg


def _websockets_connect_info() -> dict:
    try:
        import websockets
        from websockets.sync.client import connect

        sig = inspect.signature(connect)
        params = sig.parameters
        if "additional_headers" in params:
            header_arg = "additional_headers"
        elif "extra_headers" in params:
            header_arg = "extra_headers"
        else:
            header_arg = "unsupported"
        return {
            "version": getattr(websockets, "__version__", "unknown"),
            "connect_signature": str(sig),
            "header_arg": header_arg,
        }
    except Exception as exc:  # noqa: BLE001
        return {"version": "unknown", "connect_signature": None,
                "header_arg": "unknown", "error": type(exc).__name__}


# --------------------------------------------------------------------------- #
# Read-only auth (RSA-PSS). Never prints secrets / key material.
# --------------------------------------------------------------------------- #
def auth_headers(config) -> tuple[Optional[dict], Optional[str]]:
    """Build read-only Kalshi WS auth headers, or (None, reason_code). Secret-safe.

    Returns the signed connection headers (used ONLY to open the read-only socket; never
    logged) or ``(None, reason)`` where reason ∈ {missing_credentials, signing_lib_unavailable,
    private_key_unreadable, signing_error}.
    """
    k = getattr(config, "kalshi", None)
    if not getattr(k, "auth_configured", False):
        return None, "missing_credentials"
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except Exception:  # noqa: BLE001
        return None, "signing_lib_unavailable"
    import base64
    try:
        pw = getattr(k, "private_key_passphrase", None)
        with open(k.private_key_path, "rb") as fh:
            key = serialization.load_pem_private_key(fh.read(), password=(pw.encode() if pw else None))
    except Exception:  # noqa: BLE001 — never surface key contents
        return None, "private_key_unreadable"
    try:
        ts = str(int(time.time() * 1000))
        msg = (ts + "GET" + WS_PATH).encode("utf-8")
        sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                        salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
        return ({"KALSHI-ACCESS-KEY": k.key_id,
                 "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("ascii"),
                 "KALSHI-ACCESS-TIMESTAMP": ts}, None)
    except Exception as exc:  # noqa: BLE001
        return None, f"signing_error:{type(exc).__name__}"


def ws_book_available(config) -> tuple[bool, str]:
    """Whether a read-only WS book source can be used (auth + deps + opt-in). Never raises."""
    k = getattr(config, "kalshi", None)
    if not getattr(k, "auth_configured", False):
        return False, "missing_credentials"
    try:
        import websockets.sync.client  # noqa: F401
    except Exception:  # noqa: BLE001
        return False, "websockets_unavailable"
    try:
        import cryptography  # noqa: F401
    except Exception:  # noqa: BLE001
        return False, "cryptography_unavailable"
    return True, "ok"


def subscribe_message(market_ticker: str, msg_id: int = 1) -> dict:
    """Read-only market-data subscription (orderbook_delta). NOT an order command."""
    return {"id": msg_id, "cmd": "subscribe",
            "params": {"channels": MARKET_DATA_CHANNELS, "market_tickers": [market_ticker]}}


# --------------------------------------------------------------------------- #
# Local book reconstruction from snapshot + deltas (prices in cents)
# --------------------------------------------------------------------------- #
class KalshiBook:
    """Maintains yes/no resting bids from snapshot + delta messages."""

    def __init__(self) -> None:
        self.yes: dict = {}
        self.no: dict = {}
        self.seq: Optional[int] = None

    def apply_snapshot(self, msg: dict) -> None:
        if "yes_dollars_fp" in msg or "no_dollars_fp" in msg:
            self.yes = _levels_to_map(msg.get("yes_dollars_fp") or [], cents=False)
            self.no = _levels_to_map(msg.get("no_dollars_fp") or [], cents=False)
        else:
            self.yes = _levels_to_map(msg.get("yes") or [], cents=True)
            self.no = _levels_to_map(msg.get("no") or [], cents=True)
        self.seq = msg.get("seq")

    def apply_delta(self, msg: dict) -> bool:
        if msg.get("side") == "yes":
            side = self.yes
        elif msg.get("side") == "no":
            side = self.no
        else:
            return False
        price = _delta_price(msg)
        delta = _delta_size(msg)
        if price is None or delta is None:
            return False
        side[price] = side.get(price, Decimal("0")) + delta
        if side[price] <= 0:
            side.pop(price, None)
        self.seq = msg.get("seq", self.seq)
        return True

    def raw_orderbook(self) -> dict:
        """Shape into the fixed-point dollar form normalize_orderbook understands."""
        return {"orderbook_fp": {"yes_dollars": [[str(p), str(s)] for p, s in sorted(self.yes.items())],
                                 "no_dollars": [[str(p), str(s)] for p, s in sorted(self.no.items())]}}


def _levels_to_map(levels, *, cents: bool) -> dict:
    out = {}
    for item in levels or []:
        try:
            price = Decimal(str(item[0]))
            size = Decimal(str(item[1]))
        except (InvalidOperation, IndexError, TypeError, ValueError):
            continue
        if cents:
            price = price / Decimal("100")
        if Decimal("0") <= price <= Decimal("1") and size > 0:
            out[price] = size
    return out


def _delta_price(msg: dict) -> Optional[Decimal]:
    try:
        if msg.get("price_dollars") is not None:
            return Decimal(str(msg.get("price_dollars")))
        if msg.get("price") is not None:
            return Decimal(str(msg.get("price"))) / Decimal("100")
    except (InvalidOperation, TypeError, ValueError):
        return None
    return None


def _delta_size(msg: dict) -> Optional[Decimal]:
    try:
        if msg.get("delta_fp") is not None:
            return Decimal(str(msg.get("delta_fp")))
        if msg.get("delta") is not None:
            return Decimal(str(msg.get("delta")))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return None


def normalize_ws_book(book: KalshiBook, active: dict, recv: int, *, series: str,
                      line_lookup=None) -> dict:
    """Top-of-book normalized hires row from the WS-reconstructed book (recv_ms basis)."""
    tk = active.get("ticker")
    close_ms = iso_to_ms(active.get("close_time"))
    norm = normalize_orderbook(book.raw_orderbook(), market_ticker=tk, series_ticker=series,
                               event_ticker=active.get("event_ticker"), status=active.get("status"),
                               window_start_ms=(close_ms - WINDOW_MS) if close_ms else None,
                               close_ms=close_ms, recv_ms=recv)
    norm["stream"] = "hires_kalshi_active_book"
    norm["as_of_ms"] = recv
    norm["phase"] = active.get("_phase")
    norm["seconds_to_close"] = ((close_ms - recv) / 1000.0) if close_ms else None
    norm["reference_start_price"] = (line_lookup(tk) if line_lookup else None)
    norm["book_age_basis"] = "recv_ms"
    norm["book_age_ms"] = 0
    norm["book_source"] = "websocket"
    norm["live_submission_allowed"] = False
    return norm


def _discover_active(config, series: str, *, client=None) -> Optional[dict]:
    cl = client or KalshiClient(config)
    disc = cl.discover(series_ticker=series, statuses=("open", "unopened"))
    sel = select_collection_targets(disc, max_markets=1)
    return sel["current"][0] if sel["current"] else None


# --------------------------------------------------------------------------- #
# Part C — optional read-only WS book source (behind config; REST stays default)
# --------------------------------------------------------------------------- #
class KalshiWSBookSource(BaseSource):
    """Read-only Kalshi market-data WS book source (orderbook_delta). REST is the fallback."""

    name = "kalshi"
    stream = "hires_kalshi_active_book"

    def __init__(self, config, cfg: HiResConfig, *, client=None, line_lookup=None):
        super().__init__()
        self.config = config
        self.cfg = cfg
        self.series = cfg.series
        self.client = client or KalshiClient(config)
        self.line_lookup = line_lookup or (lambda _t: None)
        self.ws_url = getattr(config.kalshi, "ws_url", "") or ""

    def run(self) -> None:
        headers, reason = auth_headers(self.config)
        if headers is None:
            self._note_error(RuntimeError(f"ws_auth_{reason}"))   # REST fallback handles collection
            return
        from websockets.sync.client import connect
        while not self._stop.is_set():
            try:
                active = _discover_active(self.config, self.series, client=self.client)
                if not active:
                    self._sleep(self.cfg.kalshi_rediscover_ms)
                    continue
                tk = active.get("ticker")
                close_ms = iso_to_ms(active.get("close_time"))
                book = KalshiBook()
                hdrs, _r = auth_headers(self.config)          # fresh signature per (re)connect
                connect_kwargs, _header_arg = _connect_kwargs(hdrs, connect_fn=connect)
                with connect(self.ws_url, **connect_kwargs) as ws:
                    ws.send(json.dumps(subscribe_message(tk)))
                    self._note_connect()
                    while not self._stop.is_set():
                        if close_ms and (close_ms - now_ms()) < 0:    # window handoff -> rediscover
                            break
                        try:
                            raw = ws.recv(timeout=1.0)
                        except TimeoutError:
                            continue
                        try:
                            m = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        mtype = m.get("type")
                        payload = m.get("msg") or {}
                        if mtype == "orderbook_snapshot":
                            book.apply_snapshot(payload)
                        elif mtype == "orderbook_delta":
                            book.apply_delta(payload)
                        else:
                            continue
                        self._emit(m, normalize_ws_book(book, active, now_ms(),
                                                        series=self.series, line_lookup=self.line_lookup))
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                self._note_error(exc)
                self._sleep(self.cfg.kalshi_backoff_on_error_ms)


# --------------------------------------------------------------------------- #
# Part B — feasibility probe (READ-ONLY; ≤30s; never prints secrets)
# --------------------------------------------------------------------------- #
def _have(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


def _reports_dir(config) -> Path:
    d = config.reports_path() / "hires"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_ws_feasibility(config, *, series: str = "KXBTC15M", seconds: float = 30.0) -> dict:
    """READ-ONLY Kalshi market-data WS feasibility probe. No orders. No secrets printed."""
    from ....execution.live_kalshi import kalshi_auth_smoke   # secret-safe inspector

    seconds = min(float(seconds), 30.0)                       # hard cap
    auth = kalshi_auth_smoke(config)                          # booleans/names only, never secrets
    deps = {"websockets": _have("websockets"), "cryptography": _have("cryptography")}
    use_ws = bool(getattr(getattr(config, "low_latency", None), "use_websocket", False))
    result = {
        "banner": READ_ONLY_BANNER, "series": series, "live_submission_allowed": False,
        "no_orders": True, "market_data_only": True, "channels": MARKET_DATA_CHANNELS,
        "ws_url": auth.get("ws_url"), "dependencies": deps,
        "websockets_connect": _websockets_connect_info(),
        "credentials": {"key_id_present": auth["key_id_present"],
                        "private_key_path_present": auth["private_key_path_present"],
                        "private_key_readable": auth["private_key_readable"],
                        "auth_configured": auth["auth_configured"],
                        "rsa_signing_lib_available": auth["rsa_signing_lib_available"],
                        "use_websocket_flag": use_ws},
        "required_env_vars": ["KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY_PATH",
                              "KALSHI_PRIVATE_KEY_PASSPHRASE (optional)", "KALSHI_USE_WEBSOCKET=true"],
    }
    # active ticker via existing active-first selection (public REST; no auth)
    try:
        active = _discover_active(config, series)
        result["active_ticker"] = active.get("ticker") if active else None
    except Exception as exc:  # noqa: BLE001
        active = None
        result["active_ticker"] = None
        result["discovery_error"] = type(exc).__name__

    if not deps["websockets"] or not deps["cryptography"]:
        result["status"] = "BLOCKED_DEPENDENCY"
        result["blocker"] = "missing dependency (install .[data]/.[live]: websockets, cryptography)"
        return _finish(config, result)
    if not auth["auth_configured"]:
        result["status"] = "BLOCKED_MISSING_CREDENTIALS"
        result["blocker"] = ("Kalshi market-data WS is auth-gated; set the read-only env vars below "
                             "(values never printed) and KALSHI_USE_WEBSOCKET=true, then rerun.")
        return _finish(config, result)
    if active is None:
        result["status"] = "BLOCKED_NO_ACTIVE_MARKET"
        result["blocker"] = "no CURRENT_IN_WINDOW KXBTC15M market found to subscribe"
        return _finish(config, result)

    # ---- credentials present: attempt a short READ-ONLY connection ----
    headers, reason = auth_headers(config)
    if headers is None:
        result["status"] = "BLOCKED_SIGNING"
        result["blocker"] = f"could not build read-only auth headers: {reason}"
        return _finish(config, result)
    result.update(_probe(config, active, seconds))
    return _finish(config, result)


def _probe(config, active: dict, seconds: float) -> dict:
    from websockets.sync.client import connect
    tk = active.get("ticker")
    recvs: list[int] = []
    src_ages: list[int] = []
    msg_types: dict = {}
    book = KalshiBook()
    out: dict = {"connected": False, "subscribed": False}
    try:
        hdrs, _r = auth_headers(config)
        connect_kwargs, header_arg = _connect_kwargs(hdrs, connect_fn=connect)
        out["connect_header_arg"] = header_arg
        with connect(getattr(config.kalshi, "ws_url", ""), **connect_kwargs) as ws:
            out["connected"] = True
            ws.send(json.dumps(subscribe_message(tk)))
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                try:
                    raw = ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                recv = now_ms()
                try:
                    m = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                t = m.get("type", "unknown")
                msg_types[t] = msg_types.get(t, 0) + 1
                if t in ("subscribed", "ok"):
                    out["subscribed"] = True
                payload = m.get("msg") or {}
                if t == "orderbook_snapshot":
                    book.apply_snapshot(payload)
                elif t == "orderbook_delta":
                    book.apply_delta(payload)
                else:
                    if t == "error":
                        out["server_error_type"] = payload.get("code") or "error"
                    continue
                recvs.append(recv)
                st = payload.get("ts_ms")
                if isinstance(st, (int, float)):
                    src_ages.append(recv - int(st))
                else:
                    st = payload.get("ts")
                    if isinstance(st, (int, float)):
                        src_ages.append(recv - int(st * 1000 if st < 1e12 else st))
                    elif isinstance(st, str):
                        st_ms = iso_to_ms(st)
                        if st_ms is not None:
                            src_ages.append(recv - st_ms)
    except Exception as exc:  # noqa: BLE001 — categorize, never surface secrets
        sanitized = _sanitized_exception(exc, config)
        out["status"] = "BLOCKED_CONNECT"
        out["blocker"] = _categorize(exc, config)
        out["exception_type"] = sanitized["type"]
        out["exception_message"] = sanitized["message"]
        out["exception_traceback_sanitized"] = sanitized["traceback"]
        return out
    book_msgs = sum(msg_types.get(t, 0) for t in ("orderbook_snapshot", "orderbook_delta"))
    gaps = sorted(recvs[i + 1] - recvs[i] for i in range(len(recvs) - 1)) if len(recvs) > 1 else []
    med_gap = gaps[len(gaps) // 2] if gaps else None
    out.update({
        "status": "OK" if book_msgs > 0 else "NO_BOOK_MESSAGES",
        "message_types": msg_types, "book_messages": book_msgs,
        "book_updates_per_sec": round(book_msgs / seconds, 2) if seconds else None,
        "median_interarrival_ms": med_gap,
        "subsecond_book_updates_available": bool(med_gap is not None and med_gap < 1000),
        "recv_age_ms": ({"median": _med(src_ages), "p95": _p95(src_ages), "max": (max(src_ages) if src_ages else None)}
                        if src_ages else {"note": "no per-message source timestamps"}),
    })
    if book_msgs == 0:
        out["blocker"] = "connected but no orderbook messages (subscription unsupported or wrong channel)"
    return out


def _categorize(exc: Exception, config=None) -> str:
    safe = _sanitize_text(exc, config, limit=120)
    s = f"{type(exc).__name__}: {safe}".lower()
    if "401" in s or "403" in s or "unauthor" in s or "forbidden" in s:
        return "rate/permission error (auth rejected or market-data WS not permitted for this key)"
    if "404" in s or "no such host" in s or "getaddrinfo" in s or "refused" in s:
        return "endpoint unavailable (URL/DNS/connection refused)"
    if "429" in s:
        return "rate limit (429)"
    if "timed out" in s or "timeout" in s:
        return "connection timeout"
    return f"other: {type(exc).__name__}"


def _med(xs):
    v = sorted(x for x in xs if isinstance(x, (int, float)))
    return v[len(v) // 2] if v else None


def _p95(xs):
    v = sorted(x for x in xs if isinstance(x, (int, float)))
    return v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))] if v else None


def _finish(config, result: dict) -> dict:
    d = _reports_dir(config)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    p = d / f"kalshi_ws_feasibility_{stamp}.md"
    cred = result["credentials"]
    ws_api = result.get("websockets_connect") or {}
    L = [f"# Kalshi market-data WebSocket feasibility (READ-ONLY)", "",
         f"_{READ_ONLY_BANNER} Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC. "
         "No orders, no paper/live, no promotion. Secrets are never printed (presence/booleans only)._", "",
         f"- series: {result['series']}  ws_url: {result.get('ws_url')}",
         f"- dependencies: {result['dependencies']}",
         f"- websockets: version={ws_api.get('version')} header_arg={ws_api.get('header_arg')}",
         f"- websockets.sync.client.connect signature: `{ws_api.get('connect_signature')}`",
         f"- credentials (presence only): {cred}",
         f"- active_ticker: {result.get('active_ticker')}",
         f"- **status: {result.get('status')}**",
         f"- blocker: {result.get('blocker', 'none')}"]
    if "connected" in result or "subscribed" in result:
        L += [f"- connected: {result.get('connected')}  subscribed: {result.get('subscribed')}"]
    if result.get("connect_header_arg"):
        L += [f"- connect_header_arg_used: {result.get('connect_header_arg')}"]
    if result.get("exception_type") or result.get("exception_message"):
        L += ["", "## Sanitized exception",
              f"- type: {result.get('exception_type')}",
              f"- message: {result.get('exception_message')}"]
    if result.get("exception_traceback_sanitized"):
        L += ["", "## Sanitized traceback", "```text",
              result["exception_traceback_sanitized"].rstrip(), "```"]
    if "book_messages" in result:
        L += [f"- book messages: {result['book_messages']}  updates/s: {result.get('book_updates_per_sec')}",
              f"- median interarrival ms: {result.get('median_interarrival_ms')}  "
              f"**sub-second book updates available: {result.get('subsecond_book_updates_available')}**",
              f"- message types: {result.get('message_types')}",
              f"- recv age ms: {result.get('recv_age_ms')}"]
    if result.get("status", "").startswith("BLOCKED"):
        L += ["", "## Required (read-only market-data only) — env var NAMES (values never printed)",
              *[f"- {v}" for v in result["required_env_vars"]]]
    L += ["", "## Safety", f"- {READ_ONLY_BANNER}",
          "- Subscribed channels are market-data only (orderbook_delta); no order/portfolio endpoints.",
          "- No live adapter used; live disabled; live_submission_allowed=false; no secrets printed."]
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    result["report_md"] = str(p)
    return result
