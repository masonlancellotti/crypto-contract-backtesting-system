"""Threaded, bounded, priority-aware JSONL writer for the high-res recorder.

Source threads enqueue records onto a bounded :class:`PriorityDropQueue`; a single writer
thread owns the file handles and writes JSONL, rotating segment files on a wall-clock
interval and handing closed files to a compression worker. Under overload, LOW-priority
streams (raw verbose / aggTrade) are dropped first; HIGH-priority rows (Kalshi active book
and joined snapshots) are NEVER dropped and any pressure on them is reported loudly.

Tracks queue depth, per-stream written/dropped counts, write + recv->write + writer-lag
latency, flush/rotate/compression counts, and writer errors. MEASUREMENT ONLY — no orders.
"""

from __future__ import annotations

import collections
import gzip
import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ....timeutils import now_ms

# Stream filename bases (others use the stream name verbatim).
_FILE_BASE = {"hires_kalshi_active_book": "kalshi_active_book",
              "hires_joined_snapshot": "kalshi_hires_joined_snapshots"}
JOINED_STREAM = "hires_joined_snapshot"

# Normalized-row priorities (0 = highest, never dropped). raw rows are one lower.
_STREAM_PRIORITY = {
    "hires_kalshi_active_book": 0, "hires_joined_snapshot": 0,
    "hires_coinbase_ticker": 1, "hires_binance_book_ticker": 1,
    "hires_coinbase_trade": 2, "hires_binance_trade": 2,
}
NEVER_DROP = {"hires_kalshi_active_book", "hires_joined_snapshot"}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _day() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def stream_priority(dest: str, stream: str) -> int:
    """Priority of a (dest, stream) row. Normalized high-priority streams stay 0 even as raw."""
    if stream in NEVER_DROP and dest != "raw":
        return 0
    p = _STREAM_PRIORITY.get(stream, 2)
    if dest == "raw":
        p = min(3, p + 1)            # raw verbose is one step lower than its normalized row
    return p


# --------------------------------------------------------------------------- #
# Bounded, priority-aware drop queue (thread-safe; unit-testable without threads)
# --------------------------------------------------------------------------- #
class PriorityDropQueue:
    """Single FIFO deque with priority-aware admission. Items: (priority, dest, stream,
    record, recv_ms, enq_ms). Priority 0 is admitted unconditionally; droppable items
    (priority >= 1) honour the configured policy when the queue is full."""

    def __init__(self, maxsize: int = 100_000, warn_size: int = 50_000,
                 drop_policy: str = "drop_low_priority"):
        self.maxsize = max(1, int(maxsize))
        self.warn_size = int(warn_size)
        self.policy = drop_policy
        self._dq: collections.deque = collections.deque()
        self._cv = threading.Condition()
        self.depth_max = 0
        self.dropped_by_stream: collections.Counter = collections.Counter()
        self.high_overflow = 0
        self.warned = False

    def put(self, item) -> str:
        priority = item[0]
        stream = item[2]
        with self._cv:
            n = len(self._dq)
            if priority == 0:
                if n >= self.maxsize:
                    self.high_overflow += 1          # admitted anyway; loud signal
                self._dq.append(item)
                self._after_append()
                return "queued_high_overflow" if n >= self.maxsize else "queued"
            if n < self.maxsize:
                self._dq.append(item)
                self._after_append()
                return "queued"
            # ----- full + droppable -----
            if self.policy == "block":
                end = time.monotonic() + 0.2          # best-effort bounded backpressure
                while len(self._dq) >= self.maxsize and (time.monotonic() < end):
                    self._cv.wait(timeout=0.05)
                if len(self._dq) < self.maxsize:
                    self._dq.append(item)
                    self._after_append()
                    return "queued"
                self.dropped_by_stream[f"{stream}:dropped_full"] += 1
                return "dropped"
            if self.policy == "drop_oldest_low_priority":
                victim_idx = next((i for i, it in enumerate(self._dq)
                                   if it[0] >= 1 and it[0] >= priority), None)
                if victim_idx is not None:
                    victim = self._dq[victim_idx]
                    del self._dq[victim_idx]
                    self.dropped_by_stream[f"{victim[2]}:evicted_oldest"] += 1
                    self._dq.append(item)
                    self._after_append()
                    return "queued_evicted"
                self.dropped_by_stream[f"{stream}:dropped_full"] += 1
                return "dropped"
            # default: drop_low_priority -> drop the incoming low-priority item
            self.dropped_by_stream[f"{stream}:dropped_full"] += 1
            return "dropped"

    def _after_append(self) -> None:
        n = len(self._dq)
        if n > self.depth_max:
            self.depth_max = n
        if not self.warned and n >= self.warn_size:
            self.warned = True
        self._cv.notify()

    def get_batch(self, max_items: int, timeout: float) -> list:
        with self._cv:
            if not self._dq:
                self._cv.wait(timeout=timeout)
            out = []
            while self._dq and len(out) < max_items:
                out.append(self._dq.popleft())
            return out

    def depth(self) -> int:
        with self._cv:
            return len(self._dq)

    def total_dropped(self) -> int:
        return int(sum(self.dropped_by_stream.values()))


# --------------------------------------------------------------------------- #
# Writer
# --------------------------------------------------------------------------- #
class HiResWriter:
    """Owns file handles; writes JSONL with rotation + (worker-thread) compression."""

    def __init__(self, config, cfg):
        base = Path(cfg.output_dir) if cfg.output_dir else config.data_path()
        self.dirs = {"raw": base / "raw" / "hires", "normalized": base / "normalized" / "hires",
                     "joined": base / "features" / "hires"}
        self.cfg = cfg
        self.mode = getattr(cfg, "writer_mode", "threaded")
        self.session_id = _ts()
        self.q = PriorityDropQueue(getattr(cfg, "queue_maxsize", 100_000),
                                   getattr(cfg, "queue_warn_size", 50_000),
                                   getattr(cfg, "drop_policy", "drop_low_priority"))
        self._handles: dict = {}                  # (dest, stream) -> {fh, path, open_ms}
        self._seg_seq = 0                          # monotonic -> unique segment filenames
        self._lock = threading.Lock()
        self.written_by_stream: collections.Counter = collections.Counter()
        self.write_latency_ms: list = []
        self.recv_to_write_ms: list = []
        self.writer_lag_ms: list = []
        self.flush_count = 0
        self.rotate_count = 0
        self.compression_count = 0
        self.writer_errors = 0
        self._last_flush = now_ms()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._comp_q: collections.deque = collections.deque()
        self._comp_cv = threading.Condition()
        self._comp_thread: Optional[threading.Thread] = None

    # ----- lifecycle ----- #
    def start(self) -> None:
        if self.mode == "threaded":
            self._thread = threading.Thread(target=self._run, daemon=True, name="hires-writer")
            self._thread.start()
            if self.cfg.compress_closed_files:
                self._comp_thread = threading.Thread(target=self._compress_worker, daemon=True,
                                                     name="hires-compress")
                self._comp_thread.start()

    def submit(self, dest: str, stream: str, record: dict, recv_ms: Optional[int] = None) -> None:
        if dest == "raw" and not self.cfg.record_raw:
            return
        if dest == "normalized" and not self.cfg.record_normalized:
            return
        item = (stream_priority(dest, stream), dest, stream, record, recv_ms, now_ms())
        if self.mode == "sync":
            self._write_item(item)
        else:
            self.q.put(item)

    def stop(self, drain_timeout: float = 5.0) -> None:
        if self.mode == "threaded" and self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=drain_timeout)
        # close (and queue-compress) all open segments
        with self._lock:
            for key in list(self._handles):
                self._close_segment(key)
        # finish compression backlog
        if self._comp_thread is not None:
            with self._comp_cv:
                self._comp_cv.notify_all()
            self._comp_thread.join(timeout=drain_timeout)
        else:
            self._drain_compression_inline()

    # ----- writer thread ----- #
    def _run(self) -> None:
        while not self._stop.is_set():
            batch = self.q.get_batch(2000, timeout=0.1)
            for item in batch:
                self._write_item(item)
            self._maybe_flush()
        # final drain
        while True:
            batch = self.q.get_batch(5000, timeout=0.0)
            if not batch:
                break
            for item in batch:
                self._write_item(item)
        self.flush()

    def _segment(self, dest: str, stream: str):
        key = (dest, stream)
        now = now_ms()
        h = self._handles.get(key)
        if h is not None and (now - h["open_ms"]) >= self.cfg.rotate_every_seconds * 1000:
            self._close_segment(key)
            h = None
        if h is None:
            d = self.dirs[dest] / _day()
            d.mkdir(parents=True, exist_ok=True)
            base = _FILE_BASE.get(stream, stream)
            self._seg_seq += 1
            path = d / f"{base}-{_ts()}_{self._seg_seq:04d}.jsonl"   # seq -> unique within a second
            fh = open(path, "a", encoding="utf-8")
            h = {"fh": fh, "path": path, "open_ms": now}
            self._handles[key] = h
        return h

    def _close_segment(self, key) -> None:
        h = self._handles.pop(key, None)
        if not h:
            return
        try:
            h["fh"].flush()
            h["fh"].close()
        except Exception:  # noqa: BLE001
            self.writer_errors += 1
        self.rotate_count += 1
        if self.cfg.compress_closed_files:
            with self._comp_cv:
                self._comp_q.append(h["path"])
                self._comp_cv.notify()

    def _write_item(self, item) -> None:
        _pri, dest, stream, record, recv_ms, enq_ms = item
        try:
            h = self._segment(dest, stream)
            t0 = time.perf_counter()
            h["fh"].write(json.dumps(record, default=str) + "\n")
            self.write_latency_ms.append((time.perf_counter() - t0) * 1000.0)
            self.written_by_stream[stream] += 1
            w = now_ms()
            self.writer_lag_ms.append(w - enq_ms)
            if recv_ms is not None:
                self.recv_to_write_ms.append(w - recv_ms)
        except Exception:  # noqa: BLE001
            self.writer_errors += 1

    def _maybe_flush(self) -> None:
        if now_ms() - self._last_flush >= self.cfg.flush_every_ms:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            for h in self._handles.values():
                try:
                    h["fh"].flush()
                except Exception:  # noqa: BLE001
                    self.writer_errors += 1
        self.flush_count += 1
        self._last_flush = now_ms()

    # ----- compression worker ----- #
    def _compress_worker(self) -> None:
        while not self._stop.is_set() or self._comp_q:
            with self._comp_cv:
                if not self._comp_q:
                    self._comp_cv.wait(timeout=0.25)
                path = self._comp_q.popleft() if self._comp_q else None
            if path is not None:
                self._gzip_file(path)

    def _drain_compression_inline(self) -> None:
        while self._comp_q:
            self._gzip_file(self._comp_q.popleft())

    def _gzip_file(self, path: Path) -> None:
        try:
            if not Path(path).exists() or str(path).endswith(".gz"):
                return
            gz = Path(str(path) + ".gz")
            with open(path, "rb") as src, gzip.open(gz, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            os.replace(str(gz), str(gz))   # ensure flushed
            os.remove(path)
            self.compression_count += 1
        except Exception:  # noqa: BLE001
            self.writer_errors += 1

    # ----- metrics ----- #
    def metrics(self) -> dict:
        return {
            "writer_mode": self.mode, "session_id": self.session_id,
            "queue_depth_current": self.q.depth(), "queue_depth_max": self.q.depth_max,
            "queue_warn_size": self.q.warn_size, "queue_warned": self.q.warned,
            "rows_written_by_stream": dict(self.written_by_stream),
            "rows_dropped_by_stream": dict(self.q.dropped_by_stream),
            "high_priority_overflow": self.q.high_overflow,
            "flush_count": self.flush_count, "rotate_count": self.rotate_count,
            "compression_count": self.compression_count, "writer_errors": self.writer_errors,
            "open_segments": len(self._handles),
        }
