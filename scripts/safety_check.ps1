# Read-only safety verification. Confirms LIVE TRADING DISABLED + adapters refuse.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
& .\.venv\Scripts\python.exe -m btc5m.cli kalshi-safety-status --series KXBTC15M
& .\.venv\Scripts\python.exe -m btc5m.cli check-live-disabled
