"""Artifact safety manifest — hash the ACTIVE Kalshi model/calibrator/dataset pointers.

Read-only. Records exactly what the runtime (policy_runtime / lock_runtime /
executable_backtest) would auto-select from ``data/models/`` (NON-recursive glob,
newest by mtime/name), plus the dataset/feature-schema "latest" pointers, with
size + mtime + sha256. Run before and after an ML-upgrade/training pass to prove
no active pointer changed. NEVER writes into data/models; never prints secrets.

Usage:
    python scripts/artifact_manifest.py [--label pre_ml_upgrade] [--data-dir ./data]
        [--reports-dir ./reports] [--out <path>] [--compare <prev_manifest.json>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _entry(path: Path, repo: Path) -> dict:
    st = path.stat()
    try:
        rel = str(path.relative_to(repo))
    except ValueError:
        rel = str(path)
    return {
        "path": rel.replace("\\", "/"),
        "size": st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        "sha256": _sha256(path),
    }


def _runtime_latest_model(models: Path) -> Path | None:
    """Mirror executable_backtest.latest_model_artifact_path (newest by mtime)."""
    if not models.exists():
        return None
    cands = [p for p in models.glob("kalshi_*.pkl")
             if "calibrator" not in p.name and "dataset" not in p.name]
    return sorted(cands, key=lambda p: p.stat().st_mtime)[-1] if cands else None


def _runtime_latest_calibrator(models: Path) -> Path | None:
    """Mirror calibrate.latest_calibrator_path (newest by sorted name)."""
    if not models.exists():
        return None
    files = sorted(models.glob("kalshi_calibrator_*.pkl"))
    return files[-1] if files else None


def build_manifest(repo: Path, data_dir: Path) -> dict:
    models = data_dir / "models"
    # Active pointers the runtime scans: NON-recursive data/models only (staged/ is
    # intentionally invisible to the runtime glob and excluded here).
    pkls = sorted(p for p in models.glob("*.pkl")) if models.exists() else []
    pointers: list[Path] = []
    for name in ("kalshi_model_dataset_latest.jsonl", "kalshi_model_dataset_latest.csv",
                 "kalshi_model_dataset_latest.parquet", "kalshi_feature_schema.json"):
        p = models / name
        if p.exists():
            pointers.append(p)
    rt_model = _runtime_latest_model(models)
    rt_cal = _runtime_latest_calibrator(models)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_models_dir": str(models).replace("\\", "/"),
        "note": "Active runtime-scanned artifacts only; data/models/staged/ is NOT scanned by runtime.",
        "runtime_selected": {
            "latest_model_pkl": _entry(rt_model, repo) if rt_model else None,
            "latest_calibrator_pkl": _entry(rt_cal, repo) if rt_cal else None,
        },
        "model_pkls": [_entry(p, repo) for p in pkls],
        "latest_pointers": [_entry(p, repo) for p in pointers],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="artifact_manifest")
    ap.add_argument("--data-dir", default="./data")
    ap.add_argument("--reports-dir", default="./reports")
    ap.add_argument("--out", default=None)
    ap.add_argument("--compare", default=None, help="prior manifest JSON to diff active pointers against")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[1]
    data_dir = (repo / args.data_dir).resolve() if args.data_dir.startswith(".") else Path(args.data_dir)
    reports_dir = (repo / args.reports_dir).resolve() if args.reports_dir.startswith(".") else Path(args.reports_dir)
    manifest = build_manifest(repo, data_dir)

    out = Path(args.out) if args.out else (
        reports_dir / "models" / f"{args.label}_artifact_manifest_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    rt = manifest["runtime_selected"]
    print(f"manifest: {out}")
    print(f"  model_pkls: {len(manifest['model_pkls'])}  latest_pointers: {len(manifest['latest_pointers'])}")
    m = rt["latest_model_pkl"]; c = rt["latest_calibrator_pkl"]
    print(f"  runtime latest_model    : {m['path'] if m else None}  sha256={m['sha256'][:16]+'...' if m else None}")
    print(f"  runtime latest_calibrator: {c['path'] if c else None}  sha256={c['sha256'][:16]+'...' if c else None}")

    if args.compare:
        prev = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        changed = []
        for key in ("latest_model_pkl", "latest_calibrator_pkl"):
            a = (prev.get("runtime_selected") or {}).get(key)
            b = rt.get(key)
            if (a or {}).get("sha256") != (b or {}).get("sha256") or (a or {}).get("path") != (b or {}).get("path"):
                changed.append(key)
        if changed:
            print(f"  CHANGED runtime pointers: {changed}  <-- INVESTIGATE (active artifact moved!)")
            return 2
        print("  OK: runtime-selected model + calibrator pointers UNCHANGED vs compare manifest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
