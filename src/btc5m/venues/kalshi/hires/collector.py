"""High-res collector orchestration: threaded writer, joiner, metrics, runners.

Drains the background sources and hands records to a threaded, bounded, priority-aware
:class:`HiResWriter` (so writer lag never blocks/contaminates the recv_ms-stamped sources),
maintains point-in-time ring buffers, and emits throttled joined snapshots. Bounded runtime,
safe Ctrl+C shutdown. MEASUREMENT ONLY — no orders, no paper, no live, no promotion.
"""

from __future__ import annotations

import collections
import glob
import gzip
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ....timeutils import now_ms
from .sources import HiResConfig, build_sources
from .writer import JOINED_STREAM, HiResWriter

_FRESH_2S = 2000
RETURN_HORIZONS = {"250ms": 250, "500ms": 500, "1s": 1000, "2s": 2000, "5s": 5000, "15s": 15000}
V2_MIN_JOINED = 2000
V2_MIN_WINDOWS = 20


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _day() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _median(xs):
    v = sorted(x for x in xs if isinstance(x, (int, float)))
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _pctile(xs, q):
    v = sorted(x for x in xs if isinstance(x, (int, float)))
    if not v:
        return None
    return v[min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))]


def _lat(xs) -> dict:
    return {"p50": _median(xs), "p95": _pctile(xs, 0.95),
            "max": max(xs) if xs else None}


# --------------------------------------------------------------------------- #
# Point-in-time joiner helpers (no look-ahead: only samples with recv <= as_of)
# --------------------------------------------------------------------------- #
def _last_at(buf, t_ms: int):
    found = None
    for recv, mid in buf:
        if recv <= t_ms:
            found = (recv, mid)
        else:
            break
    return found


def _mid_at(buf, t_ms: int) -> Optional[float]:
    pt = _last_at(buf, t_ms)
    return pt[1] if pt else None


def _ret(buf, as_of: int, w_ms: int) -> Optional[float]:
    now_mid = _mid_at(buf, as_of)
    past_mid = _mid_at(buf, as_of - w_ms)
    if now_mid and past_mid and now_mid > 0 and past_mid > 0:
        return math.log(now_mid / past_mid)
    return None


# --------------------------------------------------------------------------- #
# Collector
# --------------------------------------------------------------------------- #
class HiResCollector:
    def __init__(self, config, cfg: HiResConfig, sources, writer: HiResWriter, *, joined: bool = True):
        self.config = config
        self.cfg = cfg
        self.sources = sources
        self.writer = writer
        self.joined = joined
        self.buffers = {"coinbase": collections.deque(maxlen=8000),
                        "binance": collections.deque(maxlen=8000)}
        self.counts: collections.Counter = collections.Counter()
        self.joined_count = 0
        self.joined_ages = {"coinbase": [], "binance": []}
        self.kalshi_intervals: list = []
        self._last_kalshi_recv: Optional[int] = None
        self._last_joined_ms: Optional[int] = None
        self.active_ticker: Optional[str] = None
        self.elapsed_s = 0.0

    def _joined_due(self, as_of: int) -> bool:
        if not self.cfg.joined_on_kalshi_update:
            return False
        min_gap = 1000.0 / max(1, int(self.cfg.joined_max_hz))
        if self._last_joined_ms is not None and (as_of - self._last_joined_ms) < min_gap:
            return False
        self._last_joined_ms = as_of
        return True

    def _build_joined(self, kb: dict) -> dict:
        as_of = kb["recv_ms"]
        cb_pt = _last_at(self.buffers["coinbase"], as_of)
        bn_pt = _last_at(self.buffers["binance"], as_of)
        cb_mid = cb_pt[1] if cb_pt else None
        bn_mid = bn_pt[1] if bn_pt else None
        cb_age = (as_of - cb_pt[0]) if cb_pt else None
        bn_age = (as_of - bn_pt[0]) if bn_pt else None
        basis = (bn_mid - cb_mid) if (bn_mid is not None and cb_mid is not None) else None

        def _basis_at(t):
            c, b = _mid_at(self.buffers["coinbase"], t), _mid_at(self.buffers["binance"], t)
            return (b - c) if (c is not None and b is not None) else None

        out = {
            "stream": JOINED_STREAM, "as_of_ms": as_of, "market_ticker": kb.get("market_ticker"),
            "seconds_to_close": kb.get("seconds_to_close"),
            "reference_start_price": kb.get("reference_start_price"),
            "yes_ask": kb.get("yes_ask"), "no_ask": kb.get("no_ask"),
            "yes_ask_size": kb.get("yes_ask_size"), "no_ask_size": kb.get("no_ask_size"),
            "coinbase_mid": cb_mid, "binance_mid": bn_mid,
            "coinbase_age_ms": cb_age, "binance_age_ms": bn_age,
            "kalshi_book_age_ms": kb.get("book_age_ms", 0), "basis": basis,
            "basis_change_1s": (basis - _basis_at(as_of - 1000)) if (basis is not None and _basis_at(as_of - 1000) is not None) else None,
            "basis_change_5s": (basis - _basis_at(as_of - 5000)) if (basis is not None and _basis_at(as_of - 5000) is not None) else None,
            "coinbase_stale": bool(cb_age is None or cb_age > _FRESH_2S),
            "binance_stale": bool(bn_age is None or bn_age > _FRESH_2S),
            "has_spot_feed": cb_mid is not None, "has_perp_feed": bn_mid is not None,
            "no_live_orders": True, "live_submission_allowed": False,
        }
        for label, ms in RETURN_HORIZONS.items():
            out[f"spot_return_{label}"] = _ret(self.buffers["coinbase"], as_of, ms)
            out[f"perp_return_{label}"] = _ret(self.buffers["binance"], as_of, ms)
        return out

    def _drain_once(self) -> None:
        for s in self.sources:
            for raw, norm in s.drain():
                stream = norm.get("stream", "hires")
                self.counts[stream] += 1
                src, mid = norm.get("source"), norm.get("mid")
                if src == "coinbase" and mid:
                    self.buffers["coinbase"].append((norm["recv_ms"], mid))
                elif stream == "hires_binance_book_ticker" and mid:
                    self.buffers["binance"].append((norm["recv_ms"], mid))
                recv = norm.get("recv_ms")
                self.writer.submit("raw", stream, {"stream": stream, "payload": raw}, recv)
                self.writer.submit("normalized", stream, {"stream": stream, "event": norm}, recv)
                if stream == "hires_kalshi_active_book":
                    self.active_ticker = norm.get("market_ticker")
                    if self._last_kalshi_recv is not None:
                        self.kalshi_intervals.append(norm["recv_ms"] - self._last_kalshi_recv)
                    self._last_kalshi_recv = norm["recv_ms"]
                    if self.joined and self._joined_due(norm["recv_ms"]):
                        j = self._build_joined(norm)
                        self.writer.submit("joined", JOINED_STREAM, j, j["as_of_ms"])
                        self.joined_count += 1
                        if j["coinbase_age_ms"] is not None:
                            self.joined_ages["coinbase"].append(j["coinbase_age_ms"])
                        if j["binance_age_ms"] is not None:
                            self.joined_ages["binance"].append(j["binance_age_ms"])

    def run(self, seconds: float, *, heartbeat=None) -> dict:
        self.writer.start()
        for s in self.sources:
            try:
                s.start()
            except RuntimeError:
                pass
        start = time.monotonic()
        end = start + max(0.0, float(seconds))
        last_hb = 0.0
        try:
            while time.monotonic() < end:
                self._drain_once()
                if heartbeat and (time.monotonic() - last_hb) >= 5.0:
                    last_hb = time.monotonic()
                    heartbeat(self.snapshot())
                time.sleep(0.02)
        except KeyboardInterrupt:
            pass
        finally:
            for s in self.sources:
                s.request_stop()
            self._drain_once()
            for s in self.sources:
                if hasattr(s, "join"):
                    try:
                        s.join(timeout=2.0)
                    except Exception:  # noqa: BLE001
                        pass
            self._drain_once()
            self.elapsed_s = time.monotonic() - start
            self.writer.stop(drain_timeout=5.0)
        return self.summary()

    def snapshot(self) -> dict:
        return {"counts": dict(self.counts), "joined": self.joined_count,
                "active_ticker": self.active_ticker, "queue_depth": self.writer.q.depth()}

    def _binance_streams(self) -> dict:
        secs = max(1e-9, self.elapsed_s)
        bn = next((s for s in self.sources if getattr(s, "name", "") == "binance"), None)
        st = bn.stats() if bn else {}
        return {
            "aggtrade_enabled": bool(self.cfg.binance_aggtrade_enabled),
            "binance_book_ticker_msgs_per_sec": round(st.get("book_msgs", 0) / secs, 1),
            "binance_agg_trade_msgs_per_sec": round(st.get("trade_msgs", 0) / secs, 1),
            "binance_agg_trade_dropped_or_sampled": st.get("trade_sampled_dropped", 0),
            "binance_rate_capped": st.get("rate_capped", 0),
        }

    def summary(self) -> dict:
        per_source = {s.name: s.stats() for s in self.sources}
        wm = self.writer.metrics()
        return {
            "counts": dict(self.counts), "joined_snapshots": self.joined_count,
            "active_ticker": self.active_ticker, "elapsed_s": round(self.elapsed_s, 2),
            "per_source": per_source, "binance_streams": self._binance_streams(),
            "queue": {"depth_current": wm["queue_depth_current"], "depth_max": wm["queue_depth_max"],
                      "warn_size": wm["queue_warn_size"], "warned": wm["queue_warned"],
                      "dropped_by_stream": wm["rows_dropped_by_stream"],
                      "high_priority_overflow": wm["high_priority_overflow"]},
            "writer": {"mode": wm["writer_mode"], "rows_written_by_stream": wm["rows_written_by_stream"],
                       "flush_count": wm["flush_count"], "rotate_count": wm["rotate_count"],
                       "compression_count": wm["compression_count"], "writer_errors": wm["writer_errors"],
                       "writer_lag_ms": _lat(self.writer.writer_lag_ms),
                       "recv_to_write_ms": _lat(self.writer.recv_to_write_ms),
                       "write_latency_ms": {"median": _median(self.writer.write_latency_ms),
                                            "p95": _pctile(self.writer.write_latency_ms, 0.95)}},
            "kalshi_poll_ms": {"target": max(self.cfg.kalshi_rest_poll_ms, self.cfg.kalshi_rest_min_poll_ms),
                               "actual_median": _median(self.kalshi_intervals)},
            "joined_age_ms": {
                "coinbase_median": _median(self.joined_ages["coinbase"]),
                "coinbase_max": max(self.joined_ages["coinbase"]) if self.joined_ages["coinbase"] else None,
                "binance_median": _median(self.joined_ages["binance"]),
                "binance_max": max(self.joined_ages["binance"]) if self.joined_ages["binance"] else None},
            "live_submission_allowed": False, "no_orders": True,
        }


# --------------------------------------------------------------------------- #
# Reference-line lookup (best-effort, from already-computed feature rows)
# --------------------------------------------------------------------------- #
def build_line_lookup(config):
    table: dict[str, float] = {}
    try:
        files = sorted(glob.glob(str(config.data_path() / "features" / "kalshi_feature_rows-*.jsonl")))
        if files:
            path = files[-1]
            sz = os.path.getsize(path)
            with open(path, "rb") as fh:
                if sz > 3_000_000:
                    fh.seek(sz - 3_000_000)
                text = fh.read().decode("utf-8", "ignore")
            for line in text.splitlines()[1:]:
                try:
                    o = json.loads(line)
                except (ValueError, TypeError):
                    continue
                tk, ref = o.get("market_ticker"), o.get("reference_start_price")
                if tk and ref is not None:
                    table[tk] = ref
    except Exception:  # noqa: BLE001
        pass
    return lambda tk: table.get(tk)


# --------------------------------------------------------------------------- #
# Reports + session metrics
# --------------------------------------------------------------------------- #
def _reports_dir(config) -> Path:
    d = config.reports_path() / "hires"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_session(config, out: dict) -> str:
    d = _reports_dir(config)
    sid = out.get("summary", {}).get("writer", {}).get("session_id") or _ts()
    p = d / f"kalshi_hires_session_{_ts()}.json"
    p.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return str(p)


def _write_reports(config, summary: dict, cfg: HiResConfig, *, mode: str, seconds: float,
                   blockers: list) -> dict:
    d = _reports_dir(config)
    stamp = _ts()
    md = d / f"kalshi_hires_health_{stamp}.md"
    q = summary["queue"]
    w = summary["writer"]
    bs = summary["binance_streams"]
    L = [
        f"# Kalshi KXBTC15M high-res measurement — {mode} ({seconds:.0f}s)", "",
        "_READ-ONLY measurement; no orders, no paper/live, no promotion. "
        "`live_submission_allowed=false`, `no_orders=true`._", "",
        f"- active ticker: {summary.get('active_ticker')}  joined snapshots: {summary.get('joined_snapshots')}",
        f"- writer mode: {w['mode']}  queue depth max/warn: {q['depth_max']}/{q['warn_size']}  "
        f"warned: {q['warned']}  high-priority overflow: {q['high_priority_overflow']}",
        f"- dropped by stream: {q['dropped_by_stream'] or 'none'}",
        f"- writer lag ms p50/p95/max: {w['writer_lag_ms']['p50']}/{w['writer_lag_ms']['p95']}/{w['writer_lag_ms']['max']}",
        f"- recv->write ms p50/p95/max: {w['recv_to_write_ms']['p50']}/{w['recv_to_write_ms']['p95']}/{w['recv_to_write_ms']['max']}",
        f"- rotate_count: {w['rotate_count']}  compression_count: {w['compression_count']}  "
        f"flush_count: {w['flush_count']}  writer_errors: {w['writer_errors']}",
        f"- binance bookTicker/s: {bs['binance_book_ticker_msgs_per_sec']}  "
        f"aggTrade/s: {bs['binance_agg_trade_msgs_per_sec']}  aggTrade_enabled: {bs['aggtrade_enabled']}  "
        f"sampled/dropped: {bs['binance_agg_trade_dropped_or_sampled']}  rate_capped: {bs['binance_rate_capped']}",
        f"- Kalshi poll target/actual ms: {summary['kalshi_poll_ms']['target']}/{summary['kalshi_poll_ms']['actual_median']}",
        "",
        "| source | messages | reconnects | errors | last_age_ms |",
        "|---|---:|---:|---:|---:|",
    ]
    now = now_ms()
    for name, st in summary["per_source"].items():
        last_age = (now - st["last_recv_ms"]) if st.get("last_recv_ms") else None
        L.append(f"| {name} | {st['messages']} | {st['reconnects']} | {st['errors']} | {last_age} |")
    if blockers:
        L += ["", "## Notes / fallbacks", *[f"- {b}" for b in blockers]]
    L += ["", "## Safety",
          "- No orders, no paper/live; `live_submission_allowed=false` on every row.",
          "- Public WS (Coinbase/Binance) + public REST (Kalshi); no auth, no secrets.",
          "- Writes confined to hires/ paths; production files untouched."]
    md.write_text("\n".join(L) + "\n", encoding="utf-8")
    return {"health_md": str(md)}


# --------------------------------------------------------------------------- #
# Runners
# --------------------------------------------------------------------------- #
def _make_cfg(overrides: dict) -> HiResConfig:
    return HiResConfig.from_env().with_overrides(**overrides)


def _run_collection(config, cfg: HiResConfig, *, seconds: float, joined: bool, mode: str,
                    sources_factory=None, write_reports: bool = True, heartbeat=None) -> dict:
    line_lookup = build_line_lookup(config)
    if sources_factory is not None:
        sources, blockers = sources_factory(config, cfg, line_lookup=line_lookup)
    else:
        sources, blockers = build_sources(config, cfg, line_lookup=line_lookup)
    writer = HiResWriter(config, cfg)
    collector = HiResCollector(config, cfg, sources, writer, joined=joined)
    summary = collector.run(seconds, heartbeat=heartbeat)
    out = {"status": "OK", "mode": mode, "series": cfg.series, "seconds": seconds,
           "live_submission_allowed": False, "no_orders": True, "blockers": blockers,
           "summary": summary, "output_paths": {k: str(v) for k, v in writer.dirs.items()}}
    if write_reports:
        out["reports"] = _write_reports(config, summary, cfg, mode=mode, seconds=seconds,
                                        blockers=blockers)
        out["reports"]["session_json"] = _write_session(config, out)
    return out


def run_hires_record(config, *, series="KXBTC15M", seconds=60.0, kalshi_source=None,
                     kalshi_poll_ms=None, coinbase_source=None, binance_source=None,
                     joined=True, raw=None, normalized=None, max_markets=None, output_dir=None,
                     writer_mode=None, aggtrade=None, verbose=False, dry_run=False,
                     sources_factory=None) -> dict:
    cfg = _make_cfg({
        "series": series, "kalshi_book_source": kalshi_source, "kalshi_rest_poll_ms": kalshi_poll_ms,
        "coinbase_source": coinbase_source, "binance_source": binance_source, "joined": joined,
        "record_raw": raw, "record_normalized": normalized, "kalshi_max_markets": max_markets,
        "output_dir": output_dir, "writer_mode": writer_mode,
        "binance_aggtrade_enabled": aggtrade})
    seconds = min(float(seconds), float(cfg.max_runtime_seconds))
    if dry_run:
        sources, blockers = build_sources(config, cfg, line_lookup=lambda _t: None)
        return {"status": "DRY_RUN", "mode": "record", "series": series, "seconds": seconds,
                "planned_sources": [s.name for s in sources], "blockers": blockers,
                "writer_mode": cfg.writer_mode, "aggtrade_enabled": cfg.binance_aggtrade_enabled,
                "live_submission_allowed": False, "no_orders": True,
                "note": "dry-run: no network, no files written."}
    return _run_collection(config, cfg, seconds=seconds, joined=cfg.joined, mode="record",
                           sources_factory=sources_factory)


def run_hires_record_loop(config, *, series="KXBTC15M", session_seconds=900.0, max_sessions=0,
                          kalshi_source=None, kalshi_poll_ms=None, aggtrade=None,
                          sources_factory=None) -> dict:
    """Bounded, repeated record sessions (graceful Ctrl+C). Each session rotates/flushes."""
    sessions = []
    i = 0
    try:
        while max_sessions <= 0 or i < max_sessions:
            i += 1
            res = run_hires_record(config, series=series, seconds=session_seconds,
                                   kalshi_source=kalshi_source, kalshi_poll_ms=kalshi_poll_ms,
                                   aggtrade=aggtrade, sources_factory=sources_factory)
            s = res.get("summary", {})
            sessions.append({"session": i, "active_ticker": s.get("active_ticker"),
                             "joined": s.get("joined_snapshots"),
                             "queue_depth_max": s.get("queue", {}).get("depth_max"),
                             "dropped": s.get("queue", {}).get("dropped_by_stream"),
                             "reports": res.get("reports")})
    except KeyboardInterrupt:
        pass
    return {"status": "OK", "mode": "record_loop", "series": series, "sessions_run": len(sessions),
            "sessions": sessions, "live_submission_allowed": False, "no_orders": True}


def run_hires_smoke(config, *, series="KXBTC15M", seconds=30.0, sources_factory=None) -> dict:
    cfg = _make_cfg({"series": series})
    seconds = min(float(seconds), float(cfg.max_runtime_seconds))
    res = _run_collection(config, cfg, seconds=seconds, joined=True, mode="smoke",
                          sources_factory=sources_factory)
    s = res["summary"]
    q = s["queue"]
    bs = s["binance_streams"]
    kalshi_n = s["counts"].get("hires_kalshi_active_book", 0)
    high_dropped = any(k.startswith(("hires_kalshi_active_book", "hires_joined_snapshot"))
                       for k in q["dropped_by_stream"]) or q["high_priority_overflow"] > 0
    res["smoke"] = {
        "rows_per_source": dict(s["counts"]), "joined_snapshots": s["joined_snapshots"],
        "source_age": {"coinbase": s["joined_age_ms"]["coinbase_median"],
                       "binance": s["joined_age_ms"]["binance_median"]},
        "binance_book_ticker_msgs_per_sec": bs["binance_book_ticker_msgs_per_sec"],
        "binance_agg_trade_msgs_per_sec": bs["binance_agg_trade_msgs_per_sec"],
        "aggtrade_enabled": bs["aggtrade_enabled"],
        "aggtrade_load_manageable": (q["depth_max"] < q["warn_size"] and not high_dropped),
        "queue_below_warning": q["depth_max"] < q["warn_size"],
        "high_priority_rows_dropped": high_dropped,
        "joined_one_to_one_with_kalshi": (s["joined_snapshots"] == kalshi_n) if kalshi_n else False,
        "joined_usable_for_reprice_lag_v2": bool(s["joined_snapshots"] > 0),
        "active_ticker": s["active_ticker"], "no_orders": True}
    return res


# --------------------------------------------------------------------------- #
# Status (READ-ONLY; file-derived) + reprice-lag v2 readiness
# --------------------------------------------------------------------------- #
def _hires_dirs(config):
    base = config.data_path()
    return {"raw": base / "raw" / "hires", "normalized": base / "normalized" / "hires",
            "joined": base / "features" / "hires"}


def _find_stream_files(d: Path, base: str) -> list[Path]:
    """Find all segment files for a stream base across date-subdirs + flat layout (+ .gz)."""
    if not d.exists():
        return []
    out = list(d.rglob(f"{base}-*.jsonl")) + list(d.rglob(f"{base}-*.jsonl.gz"))
    return sorted(out, key=lambda p: p.stat().st_mtime if p.exists() else 0)


def _tail_rows(path: Path, max_bytes=1_500_000) -> list[dict]:
    rows = []
    try:
        if str(path).endswith(".gz"):
            with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()[-4000:]
        else:
            sz = path.stat().st_size
            with open(path, "rb") as fh:
                if sz > max_bytes:
                    fh.seek(sz - max_bytes)
                lines = fh.read().decode("utf-8", "ignore").splitlines()
        for ln in lines:
            if not ln.strip():
                continue
            try:
                rows.append(json.loads(ln))
            except (ValueError, TypeError):
                continue
    except OSError:
        pass
    return rows


def _stream_info(d: Path, base: str) -> dict:
    files = _find_stream_files(d, base)
    if not files:
        return {"present": False}
    total_bytes = sum(p.stat().st_size for p in files if p.exists())
    latest = files[-1]
    rows = _tail_rows(latest)
    now = now_ms()
    last, recvs, ticker = None, [], None
    for o in rows:
        ev = o.get("event", o)
        r = ev.get("recv_ms") or ev.get("as_of_ms")
        if r:
            last = r
            recvs.append(r)
        if isinstance(ev, dict) and ev.get("market_ticker"):
            ticker = ev["market_ticker"]
    msgs_per_sec = None
    if len(recvs) >= 2:
        span = (max(recvs) - min(recvs)) / 1000.0
        recent = [r for r in recvs if r >= max(recvs) - 10_000]
        msgs_per_sec = round(len(recent) / 10.0, 1) if span > 0 else None
    return {"present": True, "segments": len(files), "latest_file": os.path.basename(str(latest)),
            "total_bytes": total_bytes, "last_recv_ms": last,
            "age_ms": (now - last) if last else None, "rows_in_tail": len(rows),
            "msgs_per_sec": msgs_per_sec, "active_ticker": ticker}


def reprice_lag_v2_readiness(config) -> dict:
    d = _hires_dirs(config)["joined"]
    files = _find_stream_files(d, "kalshi_hires_joined_snapshots")
    rows = 0
    windows = set()
    subsec = 0
    sampled = 0
    for p in files:
        for o in _tail_rows(p, max_bytes=3_000_000):
            rows += 1
            if o.get("market_ticker"):
                windows.add(o["market_ticker"])
            if sampled < 5000:
                sampled += 1
                if o.get("spot_return_250ms") is not None or o.get("perp_return_250ms") is not None:
                    subsec += 1
    subsec_frac = (subsec / sampled) if sampled else 0.0
    ready = (rows >= V2_MIN_JOINED and len(windows) >= V2_MIN_WINDOWS and subsec_frac >= 0.2)
    reason = None
    if not ready:
        bits = []
        if rows < V2_MIN_JOINED:
            bits.append(f"joined rows {rows} < {V2_MIN_JOINED}")
        if len(windows) < V2_MIN_WINDOWS:
            bits.append(f"distinct windows {len(windows)} < {V2_MIN_WINDOWS}")
        if subsec_frac < 0.2:
            bits.append(f"sub-second returns present in {subsec_frac:.0%} of sampled rows (<20%)")
        reason = "; ".join(bits) + " - run more kalshi-hires-record sessions across windows/days"
    return {"ready": bool(ready), "joined_rows": rows, "distinct_windows": len(windows),
            "subsecond_return_fraction": round(subsec_frac, 3), "reason": reason}


def run_hires_status(config, *, series="KXBTC15M") -> dict:
    d = _hires_dirs(config)
    info = {
        "kalshi_active_book": _stream_info(d["normalized"], "kalshi_active_book"),
        "coinbase": _stream_info(d["normalized"], "hires_coinbase_ticker"),
        "binance_book_ticker": _stream_info(d["normalized"], "hires_binance_book_ticker"),
        "binance_agg_trade": _stream_info(d["normalized"], "hires_binance_trade"),
        "joined": _stream_info(d["joined"], "kalshi_hires_joined_snapshots"),
    }
    # latest session runtime metrics (queue/drops/writer), if any
    sess = sorted(glob.glob(str(_reports_dir(config) / "kalshi_hires_session_*.json")))
    session = {}
    if sess:
        try:
            j = json.loads(Path(sess[-1]).read_text(encoding="utf-8"))
            s = j.get("summary", {})
            session = {"session_file": os.path.basename(sess[-1]),
                       "queue_depth_current": s.get("queue", {}).get("depth_current"),
                       "queue_depth_max": s.get("queue", {}).get("depth_max"),
                       "dropped_by_stream": s.get("queue", {}).get("dropped_by_stream"),
                       "writer_lag_ms": s.get("writer", {}).get("writer_lag_ms"),
                       "writer_errors": s.get("writer", {}).get("writer_errors"),
                       "compression_count": s.get("writer", {}).get("compression_count"),
                       "binance_streams": s.get("binance_streams")}
        except (ValueError, OSError):
            session = {}
    v2 = reprice_lag_v2_readiness(config)
    return {"series": series, "status": "OK", "live_submission_allowed": False, "no_orders": True,
            "files": info, "session": session,
            "reprice_lag_v2_ready": v2["ready"], "reprice_lag_v2": v2}


def hires_inputs_available(config) -> dict:
    """Back-compat shim used by the reprice-lag --hires gate; now backed by v2 readiness."""
    v2 = reprice_lag_v2_readiness(config)
    return {"available": v2["joined_rows"] > 0, "joined_rows": v2["joined_rows"],
            "distinct_windows": v2["distinct_windows"], "sufficient_for_v2": v2["ready"],
            "reason": v2["reason"]}
