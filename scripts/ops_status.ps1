# Read-only Kalshi ops dashboard. SAFE to run while collectors are active.
# Usage: .\scripts\ops_status.ps1 [-- extra args]
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
& .\.venv\Scripts\python.exe -m btc5m.cli kalshi-ops-status --series KXBTC15M @args
