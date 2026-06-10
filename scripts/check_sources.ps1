# Read-only collector + source-health (freshness/stale). Never touches collectors.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
& .\.venv\Scripts\python.exe -m btc5m.cli kalshi-collector-status --series KXBTC15M @args
& .\.venv\Scripts\python.exe -m btc5m.cli source-health --series KXBTC15M
