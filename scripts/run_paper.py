"""Run paper-trading mode. Safe: no real orders. Wrapper -> CLI."""

from __future__ import annotations

import sys

from btc5m.cli import main

if __name__ == "__main__":
    sys.exit(main(["paper"]))
