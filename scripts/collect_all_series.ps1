# collect_all_series.ps1 — launch one record-only collector per crypto 15m series
# (BTC, ETH, SOL, DOGE, XRP), each in its OWN window and (for non-BTC) its own
# data\series\<SERIES> directory, so processes never share JSONL files.
#
# Rate-limit posture: non-BTC collectors run MaxMarkets=2 (active + next
# upcoming) at Interval=1.5s so five concurrent collectors stay well inside
# Kalshi's public REST limits. BTC keeps its richer defaults.
#
# Usage (from the repo root):
#   .\scripts\collect_all_series.ps1
#   .\scripts\collect_all_series.ps1 -Series KXETH15M,KXSOL15M   # subset
#
# Stop: Ctrl-C (or close) each window; recorded data stays valid. NEVER live.

param(
    [string[]]$Series = @("KXBTC15M", "KXETH15M", "KXSOL15M", "KXDOGE15M", "KXXRP15M")
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot "collect_kalshi_continuous.ps1"

foreach ($s in $Series) {
    if ($s -eq "KXBTC15M") {
        $args = "-NoExit -ExecutionPolicy Bypass -File `"$launcher`" -Series $s"
    } else {
        $args = "-NoExit -ExecutionPolicy Bypass -File `"$launcher`" -Series $s -MaxMarkets 2 -Interval 1.5"
    }
    Write-Host "launching collector: $s" -ForegroundColor Cyan
    Start-Process powershell -ArgumentList $args -WorkingDirectory $repo
    Start-Sleep -Seconds 2   # stagger discovery bursts
}

Write-Host ""
Write-Host "All collectors launched (one window each; record-only; live disabled)." -ForegroundColor Green
Write-Host "Check any series, e.g.:" -ForegroundColor Yellow
Write-Host '  $env:DATA_DIR="' -NoNewline; Write-Host "$repo\data\series\KXETH15M" -NoNewline; Write-Host '"; python -m btc5m.cli kalshi-data-readiness --series KXETH15M'
