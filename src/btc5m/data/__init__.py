"""Data ingestion adapters and storage.

All adapters are scaffolds: they import without credentials or third-party libs
(those are imported lazily) and raise a clear error when real connectivity is
requested. Raw AND normalized data are recorded — not only feature snapshots.
"""
