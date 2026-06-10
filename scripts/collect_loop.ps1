<#
.SYNOPSIS
    Run the btc5m record-only/paper pipeline continuously until you stop it.

.DESCRIPTION
    Repeatedly runs `run-paper-pipeline`, which records BTC 5-minute Polymarket
    books + Coinbase/Binance feeds, labels finished windows, builds features,
    makes gated (paper-only) decisions, and writes the paper ledger + session
    summary. No live orders are ever placed.

    Stop any time with Ctrl+C - the current cycle ends and data captured so far
    is preserved (the recorder flushes on exit).

    Self-contained: it uses the project's .venv automatically, so you do NOT
    need to activate the venv first.

.PARAMETER Seconds
    Recording budget per cycle (default 600 = ~10 min).

.PARAMETER Sources
    Underlying feeds to record (default "coinbase,binance").

.PARAMETER MaxMarkets
    Max markets to record per cycle (default 3).

.PARAMETER PauseSeconds
    Pause between cycles (default 5).

.EXAMPLE
    .\scripts\collect_loop.ps1
    .\scripts\collect_loop.ps1 -Seconds 600 -MaxMarkets 5
#>
param(
    [double]$Seconds = 600,
    [string]$Sources = "coinbase,binance",
    [int]$MaxMarkets = 3,
    [int]$PauseSeconds = 5
)

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot

# Prefer the project venv python; fall back to whatever `python` is on PATH.
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$py = if (Test-Path $venvPython) { $venvPython } else { "python" }

Write-Host "btc5m continuous collection (record-only/paper). Ctrl+C to stop." -ForegroundColor Green
Write-Host "python : $py"
Write-Host "seconds=$Seconds sources=$Sources max-markets=$MaxMarkets pause=$PauseSeconds`n"

$cycle = 0
while ($true) {
    $cycle++
    Write-Host "=== cycle $cycle @ $(Get-Date -Format 'u') ===" -ForegroundColor Cyan
    & $py -m btc5m.cli run-paper-pipeline --seconds $Seconds --sources $Sources --max-markets $MaxMarkets
    Write-Host "--- cycle $cycle done; readiness snapshot ---" -ForegroundColor DarkGray
    & $py -m btc5m.cli data-readiness --asset BTC --duration 5m
    Start-Sleep -Seconds $PauseSeconds
}
