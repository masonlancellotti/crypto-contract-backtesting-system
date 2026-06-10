"""Run live mode (GATED).

This wrapper does NOT enable live trading. The live adapter refuses orders unless
every safety gate, credential, and risk check passes. With shipped defaults this
prints the blockers and exits without trading.
"""

from __future__ import annotations

import sys

from btc5m.cli import main

if __name__ == "__main__":
    print("run_live: live trading is gated. Verifying the live adapter refuses by default...")
    sys.exit(main(["check-live-disabled"]))
