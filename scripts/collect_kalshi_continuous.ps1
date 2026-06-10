# collect_kalshi_continuous.ps1 — continuous, single-process Kalshi KXBTC15M
# collection (record-only / paper). Safe to stop with Ctrl-C; all recorded data
# is append-only JSONL and stays valid. NEVER submits live orders.
#
# Usage (from the repo root):
#   .\scripts\collect_kalshi_continuous.ps1
#   .\scripts\collect_kalshi_continuous.ps1 -Sources "coinbase" -MaxMarkets 6
#
# Overnight: just leave it running. Watch readiness in another terminal with
#   python -m btc5m.cli kalshi-data-readiness --series KXBTC15M

param(
    [string]$Series       = "KXBTC15M",
    [string]$Sources      = "coinbase,binance",
    [int]   $SecondsPerCycle = 900,
    [double]$Interval     = 1,
    [int]   $MaxMarkets   = 4,
    [int]   $ReadinessEvery = 1,
    [int]   $BackfillEvery  = 1,
    [int]   $MaxCycles    = 0
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# Prefer the venv python if present.
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "=== Kalshi continuous collection (record-only; live disabled) ===" -ForegroundColor Cyan
Write-Host "series=$Series sources=$Sources cycle=${SecondsPerCycle}s interval=${Interval}s max_markets=$MaxMarkets"
Write-Host "Stop any time with Ctrl-C; recorded data stays valid." -ForegroundColor Yellow

& $py -m btc5m.cli kalshi-collect-continuous `
    --series $Series `
    --sources $Sources `
    --seconds-per-cycle $SecondsPerCycle `
    --interval $Interval `
    --max-markets $MaxMarkets `
    --readiness-every $ReadinessEvery `
    --backfill-every $BackfillEvery `
    --max-cycles $MaxCycles
