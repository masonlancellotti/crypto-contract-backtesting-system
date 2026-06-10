# Kalshi high-res compaction (WRITE)

_Generated 2026-06-09 03:31:59 UTC. Compresses CLOSED segments to .jsonl.gz; retention deletes only with --write --retention. Skips files modified within 900s (active-file safety). No orders, live disabled._

## Compression
| kind | files | bytes before | bytes after/est |
|---|---:|---:|---:|
| raw | 19 | 257,258,480 | 13,327,456 |
| normalized | 19 | 528,732,993 | 19,643,313 |
| joined | 5 | 2,572,828 | 359,072 |

## Retention
| kind | days | over-age files | deleted | bytes freed |
|---|---:|---:|---:|---:|
| raw | 7 | 0 | 0 | 0 |
| normalized | 30 | 0 | 0 | 0 |
| joined | 90 | 0 | 0 | 0 |

- total bytes before: 788,564,301  after/est: 33,329,841  freed: 0
- normalized/joined are deleted only when their retention days > 0 AND `--write --retention` are both passed.
