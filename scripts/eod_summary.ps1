# End-of-day Kalshi summary + report. Notification is Noop unless Pushover configured.
# Live trading is never touched. SAFE while collectors run.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
& .\.venv\Scripts\python.exe -m btc5m.cli kalshi-eod-summary --series KXBTC15M --write-report @args
