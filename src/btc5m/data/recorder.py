"""Event recorder — persists RAW and NORMALIZED events as JSONL.

We store raw payloads (as received) AND normalized events, not only feature
snapshots, so the dataset can be re-derived later. Functional with stdlib only.
Files are line-delimited JSON under DATA_DIR/raw and DATA_DIR/normalized.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from ..config import AppConfig


def _default(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


class Recorder:
    """Append-only JSONL recorder for raw and normalized streams."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.raw_dir = config.data_path() / "raw"
        self.norm_dir = config.data_path() / "normalized"
        self._handles: dict[Path, Any] = {}

    def _day_file(self, base: Path, stream: str) -> Path:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{stream}-{day}.jsonl"

    def _write(self, path: Path, record: dict[str, Any]) -> None:
        fh = self._handles.get(path)
        if fh is None:
            fh = path.open("a", encoding="utf-8")
            self._handles[path] = fh
        fh.write(json.dumps(record, default=_default) + "\n")

    def record_raw(self, stream: str, payload: Any) -> None:
        if not self.config.raw.get("data", {}).get("record_raw", True):
            return
        self._write(self._day_file(self.raw_dir, stream), {"stream": stream, "payload": payload})

    def record_normalized(self, stream: str, event: Any) -> None:
        if not self.config.raw.get("data", {}).get("record_normalized", True):
            return
        self._write(self._day_file(self.norm_dir, stream), {"stream": stream, "event": event})

    def flush(self) -> None:
        """Flush buffered writes so readers (in-process feature/label builds in a
        long-running collector) see the latest recorded data."""
        for fh in self._handles.values():
            try:
                fh.flush()
            except Exception:
                pass

    def close(self) -> None:
        for fh in self._handles.values():
            try:
                fh.close()
            except Exception:
                pass
        self._handles.clear()

    def __enter__(self) -> "Recorder":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
