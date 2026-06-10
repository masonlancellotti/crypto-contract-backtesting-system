<#
.SYNOPSIS
    Launch the fastest comprehensive btc5m data collection: three concurrent
    loops (books, underlying, process) in separate windows.

.DESCRIPTION
    Records Polymarket BTC 5m books+lines and Coinbase/Binance feeds AT THE SAME
    TIME (so features get contemporaneous underlying data), and periodically
    rebuilds labels/features and prints readiness. Record-only/paper - no live
    orders. Each loop runs in its own window so you can watch and stop them.

    NOTE: data rate is gated by Polymarket market availability. The 5-minute
    up/down markets are intermittent (there are gaps). These loops capture every
    window the moment it appears and otherwise keep recording underlying data.

    By default the books loop records LIVE-ONLY windows (live now or starting
    within ~30s) - the windows that actually yield a captured line + settlement
    label. Pre-window markets (listed ~24h ahead) are skipped because they only
    produce unusable 'no_line' rows. Use -AllWindows to record everything.

.PARAMETER MaxMarkets
    Max concurrent markets to record per books cycle (default 0 = all).

.PARAMETER Interval
    Poll interval seconds for the recorders (default 2).

.PARAMETER AllWindows
    Record ALL discovered markets, including pre-window (mostly unusable) ones.

.EXAMPLE
    .\scripts\collect_fast.ps1
    .\scripts\collect_fast.ps1 -AllWindows
#>
param(
    [int]$MaxMarkets = 0,
    [double]$Interval = 2,
    [switch]$AllWindows
)

$worker = Join-Path $PSScriptRoot "collect.ps1"
$base = @("-ExecutionPolicy", "Bypass", "-NoExit", "-File", $worker)

Write-Host "Launching 3 concurrent collectors (books, underlying, process)..." -ForegroundColor Green

$booksArgs = @("-Mode", "books", "-MaxMarkets", "$MaxMarkets", "-Interval", "$Interval", "-Seconds", "300")
if (-not $AllWindows) { $booksArgs += "-LiveOnly" }
Start-Process powershell -ArgumentList ($base + $booksArgs)
Start-Process powershell -ArgumentList ($base + @(
        "-Mode", "underlying", "-Interval", "$Interval", "-Seconds", "300"))
Start-Process powershell -ArgumentList ($base + @(
        "-Mode", "process", "-ProcessPause", "300"))

Write-Host ""
Write-Host "Three windows are now running and will collect continuously." -ForegroundColor Green
Write-Host "STOP: press Ctrl+C in each window, or close the windows."
Write-Host "STOP ALL (nuclear): Get-Process python | Stop-Process -Force"
Write-Host ""
Write-Host "Check progress any time from a 4th terminal (activate venv first):"
Write-Host "  python -m btc5m.cli data-readiness --asset BTC --duration 5m"
