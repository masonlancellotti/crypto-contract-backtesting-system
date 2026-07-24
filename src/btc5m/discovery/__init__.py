"""Alpha Discovery Engine (ADE) — competition-grade, leakage-safe, multiple-testing-aware
search for a proprietary edge in the Kalshi 15m binary markets.

Design principle (non-negotiable): this market has survived many rigorous hypothesis-driven
attacks with NO edge after cost. An automated search WILL surface false positives unless
every discovery is forced through an overfitting/multiple-testing gauntlet. The engine is
built to find edge IF it exists and to PROVE it is real — not to produce a comforting
backtest. Read `docs/ADE_DESIGN.md`.

Milestone 1 (this package): the rigor spine —
  metrics.py   per-observation scoring (Sharpe/PSR inputs, after-cost EV, Brier-skill, IC)
  gauntlet.py  Deflated Sharpe Ratio + PBO (CSCV) + parameter-plateau  [the heart]
  cpcv.py      combinatorial purged cross-validation (purge+embargo on windows) + CSCV split
  holdout.py   hash-pinned, sealed holdout vault (no search ever touches it)
  registry.py  append-only trial registry → cumulative multiple-testing budget across runs

Nothing here trades; `live_submission_allowed` is never touched.
"""
from __future__ import annotations

__all__ = ["metrics", "gauntlet", "cpcv", "holdout", "registry"]
