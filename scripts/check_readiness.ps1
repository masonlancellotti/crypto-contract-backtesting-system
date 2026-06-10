# Read-only gate progress + data readiness. SAFE while collectors run.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
& .\.venv\Scripts\python.exe -m btc5m.cli kalshi-gate-progress --series KXBTC15M
& .\.venv\Scripts\python.exe -m btc5m.cli kalshi-data-readiness --series KXBTC15M
