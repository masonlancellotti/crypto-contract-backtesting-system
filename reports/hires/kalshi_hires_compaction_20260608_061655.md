# Kalshi high-res compaction (DRY-RUN)

_Generated 2026-06-08 06:16:55 UTC. Compresses CLOSED segments to .jsonl.gz; retention deletes only with --write --retention. Skips files modified within 900s (active-file safety). No orders, live disabled._

## Compression
| kind | files | bytes before | bytes after/est |
|---|---:|---:|---:|
| raw | 3 | 14,043,874 | 1,685,264 |
| normalized | 3 | 29,133,875 | 3,496,064 |
| joined | 1 | 91,961 | 11,035 |

## Retention
| kind | days | over-age files | deleted | bytes freed |
|---|---:|---:|---:|---:|
| raw | 7 | 0 | 0 | 0 |
| normalized | 30 | 0 | 0 | 0 |
| joined | 90 | 0 | 0 | 0 |

- total bytes before: 43,269,710  after/est: 5,192,363  freed: 0
- normalized/joined are deleted only when their retention days > 0 AND `--write --retention` are both passed.
