"""High-res file compaction: gzip CLOSED segment files + optional retention (READ-ONLY-ish).

Compresses closed ``.jsonl`` segments to ``.jsonl.gz`` and, only when explicitly asked,
enforces age-based retention. NEVER touches currently-active files (skips anything modified
within a safety grace window) and NEVER deletes normalized/joined files unless the per-kind
retention is configured (>0 days) AND the caller passes both ``--write`` and ``--retention``.
No orders, no paper/live, no promotion.
"""

from __future__ import annotations

import gzip
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from .sources import HiResConfig

_KINDS = {"raw": ("raw", "hires"), "normalized": ("normalized", "hires"),
          "joined": ("features", "hires")}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _kind_dir(config, kind: str) -> Path:
    sub = _KINDS[kind]
    return config.data_path() / sub[0] / sub[1]


def _all_files(d: Path, suffix: str) -> list[Path]:
    if not d.exists():
        return []
    return sorted(d.rglob(f"*{suffix}"))


def _gzip_file(path: Path) -> tuple[int, int]:
    before = path.stat().st_size
    gz = Path(str(path) + ".gz")
    with open(path, "rb") as src, gzip.open(gz, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    after = gz.stat().st_size
    os.remove(path)
    return before, after


def run_hires_compact(config, *, write: bool = False, enforce_retention: bool = False,
                      active_grace_seconds: int | None = None) -> dict:
    cfg = HiResConfig.from_env()
    grace = int(active_grace_seconds if active_grace_seconds is not None
                else max(120, cfg.rotate_every_seconds))
    now = time.time()
    retention_days = {"raw": cfg.retention_raw_days, "normalized": cfg.retention_normalized_days,
                      "joined": cfg.retention_joined_days}

    out = {"status": "OK", "write": bool(write), "enforce_retention": bool(enforce_retention),
           "active_grace_seconds": grace, "live_submission_allowed": False, "no_orders": True,
           "compress": {}, "retention": {}, "bytes_before": 0, "bytes_after": 0, "bytes_freed": 0}

    # ----- compression of CLOSED .jsonl segments -----
    for kind in _KINDS:
        d = _kind_dir(config, kind)
        planned, done, b_before, b_after = 0, 0, 0, 0
        for p in _all_files(d, ".jsonl"):
            try:
                if (now - p.stat().st_mtime) < grace:      # likely active/just-written -> skip
                    continue
                sz = p.stat().st_size
                planned += 1
                b_before += sz
                if write:
                    bf, af = _gzip_file(p)
                    b_after += af
                    done += 1
                else:
                    b_after += int(sz * 0.12)              # rough gzip estimate for the report
            except OSError:
                continue
        out["compress"][kind] = {"files_planned": planned, "files_compressed": done,
                                 "bytes_before": b_before, "bytes_after_or_estimate": b_after}
        out["bytes_before"] += b_before
        out["bytes_after"] += b_after

    # ----- retention (delete files older than the per-kind window) -----
    for kind in _KINDS:
        d = _kind_dir(config, kind)
        days = retention_days[kind]
        cutoff = now - days * 86400
        candidates, freed, deleted = 0, 0, 0
        if days and days > 0:
            for p in _all_files(d, ".jsonl") + _all_files(d, ".jsonl.gz"):
                try:
                    if (now - p.stat().st_mtime) < grace:
                        continue
                    if p.stat().st_mtime < cutoff:
                        candidates += 1
                        sz = p.stat().st_size
                        if write and enforce_retention:
                            os.remove(p)
                            freed += sz
                            deleted += 1
                except OSError:
                    continue
        out["retention"][kind] = {"retention_days": days, "files_over_age": candidates,
                                  "files_deleted": deleted, "bytes_freed": freed}
        out["bytes_freed"] += freed

    # ----- report -----
    rd = config.reports_path() / "hires"
    rd.mkdir(parents=True, exist_ok=True)
    rep = rd / f"kalshi_hires_compaction_{_ts()}.md"
    lines = [
        f"# Kalshi high-res compaction ({'WRITE' if write else 'DRY-RUN'})",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC. "
        "Compresses CLOSED segments to .jsonl.gz; retention deletes only with --write --retention. "
        f"Skips files modified within {grace}s (active-file safety). No orders, live disabled._",
        "",
        "## Compression",
        "| kind | files | bytes before | bytes after/est |",
        "|---|---:|---:|---:|",
    ]
    for kind, c in out["compress"].items():
        lines.append(f"| {kind} | {c['files_planned']} | {c['bytes_before']:,} | "
                     f"{c['bytes_after_or_estimate']:,} |")
    lines += ["", "## Retention", "| kind | days | over-age files | deleted | bytes freed |",
              "|---|---:|---:|---:|---:|"]
    for kind, r in out["retention"].items():
        lines.append(f"| {kind} | {r['retention_days']} | {r['files_over_age']} | "
                     f"{r['files_deleted']} | {r['bytes_freed']:,} |")
    lines += ["", f"- total bytes before: {out['bytes_before']:,}  after/est: {out['bytes_after']:,}  "
              f"freed: {out['bytes_freed']:,}",
              "- normalized/joined are deleted only when their retention days > 0 AND "
              "`--write --retention` are both passed."]
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out["report_md"] = str(rep)
    return out
