# Read-only system health check (pass/warn/fail). Add -RunTests to also run pytest.
# Usage: .\scripts\doctor.ps1            (fast)
#        .\scripts\doctor.ps1 --run-tests
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
& .\.venv\Scripts\python.exe -m btc5m.cli kalshi-doctor --series KXBTC15M @args
