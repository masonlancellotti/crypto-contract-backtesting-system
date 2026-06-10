"""Feature store — point-in-time feature rows persisted as JSONL.

Every row is keyed by (slug, as_of_ms) and must contain only information
available at ``as_of_ms`` (the builder enforces no look-ahead). JSONL keeps the
store dependency-free; Parquet/DuckDB can be layered later.

``build-features`` is a FULL rebuild from all recorded data, so it writes a
single canonical ``feature_rows.jsonl`` with ``replace=True`` — this makes
repeated rebuilds (e.g. a continuous collection loop) idempotent and bounded.
``load()`` dedupes by (slug, as_of_ms) so any legacy day-partitioned files or
duplicate appends never inflate counts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config import AppConfig

FEATURE_STREAM = "feature_rows"


class FeatureStore:
    def __init__(self, config: AppConfig):
        self.config = config
        self.dir: Path = config.data_path() / "features"

    @property
    def canonical_file(self) -> Path:
        return self.dir / f"{FEATURE_STREAM}.jsonl"

    def _day_file(self, ref_ms: int | None = None) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        ts = ref_ms if ref_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
        day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y%m%d")
        return self.dir / f"{FEATURE_STREAM}-{day}.jsonl"

    def write_rows(
        self, rows: Iterable[dict], *, replace: bool = False, ref_ms: int | None = None
    ) -> int:
        """Persist rows. ``replace=True`` overwrites the canonical file (full
        rebuild, idempotent); otherwise appends to a day file (incremental)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.canonical_file if replace else self._day_file(ref_ms)
        mode = "w" if replace else "a"
        n = 0
        with path.open(mode, encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
                n += 1
        return n

    def write_row(self, contract_id: str, as_of_ms: int, features: dict[str, Any]) -> None:
        rec = {"slug": features.get("slug", contract_id), "as_of_ms": as_of_ms, **features}
        self.write_rows([rec], ref_ms=as_of_ms)

    def load(self) -> list[dict]:
        """Load all feature rows, deduped by (slug, as_of_ms) — last wins."""
        if not self.dir.exists():
            return []
        deduped: dict[tuple, dict] = {}
        order: list[tuple] = []
        files = []
        if self.canonical_file.exists():
            files.append(self.canonical_file)
        files.extend(sorted(self.dir.glob(f"{FEATURE_STREAM}-*.jsonl")))
        for path in files:
            try:
                with path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        key = (row.get("slug"), row.get("as_of_ms"))
                        if key not in deduped:
                            order.append(key)
                        deduped[key] = row
            except OSError:
                continue
        return [deduped[k] for k in order]
