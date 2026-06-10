<#
.SYNOPSIS
    One continuous collector worker (books | underlying | process).

.DESCRIPTION
    Used by collect_fast.ps1 to run three concurrent loops, but can also be run
    standalone. Record-only/paper - never places live orders. Ctrl+C to stop;
    data captured so far is preserved.

    Modes:
      books      - record Polymarket BTC 5m books + provisional lines for every
                   open market (the scarce data). Captures whenever markets exist.
      underlying - record Coinbase + Binance BTC feeds continuously.
      process    - periodically backfill settlements, rebuild features
                   (idempotent), and print data-readiness.

.EXAMPLE
    .\scripts\collect.ps1 -Mode books -MaxMarkets 8 -Interval 2
    .\scripts\collect.ps1 -Mode underlying
    .\scripts\collect.ps1 -Mode process -ProcessPause 300
#>
param(
    [Parameter(Mandatory)][ValidateSet("books", "underlying", "process")][string]$Mode,
    [double]$Seconds = 300,
    [double]$Interval = 2,
    [int]$MaxMarkets = 8,
    [int]$ProcessPause = 300,
    [switch]$LiveOnly
)

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$py = if (Test-Path $venvPython) { $venvPython } else { "python" }

$host.UI.RawUI.WindowTitle = "btc5m collect [$Mode]"
Write-Host "btc5m collector [$Mode] - Ctrl+C to stop (data is preserved)" -ForegroundColor Green

$cycle = 0
while ($true) {
    $cycle++
    $stamp = Get-Date -Format 'u'
    try {
        if ($Mode -eq "books") {
            Write-Host "=== [books] cycle $cycle @ $stamp ===" -ForegroundColor Cyan
            if ($LiveOnly) {
                & $py -m btc5m.cli record --asset BTC --duration 5m --seconds $Seconds --interval $Interval --max-markets $MaxMarkets --live-only
            }
            else {
                & $py -m btc5m.cli record --asset BTC --duration 5m --seconds $Seconds --interval $Interval --max-markets $MaxMarkets
            }
        }
        elseif ($Mode -eq "underlying") {
            Write-Host "=== [underlying] cycle $cycle @ $stamp ===" -ForegroundColor Magenta
            & $py -m btc5m.cli record-underlying --seconds $Seconds --interval $Interval --sources coinbase,binance
        }
        else {
            Write-Host "=== [process] cycle $cycle @ $stamp ===" -ForegroundColor Yellow
            & $py -m btc5m.cli backfill-settlements --asset BTC --duration 5m
            & $py -m btc5m.cli build-features --asset BTC --duration 5m
            & $py -m btc5m.cli data-readiness --asset BTC --duration 5m
            Start-Sleep -Seconds $ProcessPause
        }
    }
    catch {
        Write-Host "cycle $cycle error: $($_.Exception.Message)" -ForegroundColor Red
        Start-Sleep -Seconds 5
    }
}
