"""Settlement labeling for 5-minute BTC binaries.

Labels are derived from the EXACT contract line, expiry timestamp, and the
agreed resolution source — never from contract titles or approximate times.
Overlapping 5-minute windows must use purge/embargo to avoid leakage.
"""
