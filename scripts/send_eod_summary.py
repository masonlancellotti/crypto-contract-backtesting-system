"""Send the end-of-day summary via Pushover or Noop fallback. Wrapper -> CLI."""

from __future__ import annotations

import sys

from btc5m.cli import main

if __name__ == "__main__":
    sys.exit(main(["eod"]))
