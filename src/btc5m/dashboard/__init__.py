"""Keyless, hermetic research dashboard for the Kalshi Microstructure Lab.

Serves the committed zero-key sample (`sample_data/`) and the committed research
reports (`docs/`, `sample_data/expected/`) as an interactive quant-desk. No API
keys, no network, no live compute beyond reading committed artifacts. Every number
on screen traces to a committed file. See `btc5m dashboard` (CLI) and app.create_app().
"""
from .app import create_app  # noqa: F401

__all__ = ["create_app"]
