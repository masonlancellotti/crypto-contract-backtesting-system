"""Paper-trading: non-midpoint fill simulation, persistent ledger, session
summaries, data-readiness gating, and the record-only/paper pipeline.

Everything here is record-only / paper. No real orders are ever placed. Fills use
EXECUTABLE ask/bid prices with depth walking and fees — never the midpoint.
"""
