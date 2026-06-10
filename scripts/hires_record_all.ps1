# hires_record_all.ps1 — launch one sub-second hi-res recorder per crypto 15m
# series, each in its own window with per-series underlying WS symbols and (for
# non-BTC) per-series data isolation. Requires Kalshi API creds in .env for the
# WS book source (KALSHI_HIRES_BOOK_SOURCE=auto falls back to REST without them).
#
# Usage:  .\scripts\hires_record_all.ps1
#         .\scripts\hires_record_all.ps1 -Series KXBTC15M,KXETH15M
# Stop:   Ctrl-C / close each window. READ-ONLY; no orders; live disabled.

param(
    [string[]]$Series = @("KXBTC15M", "KXETH15M", "KXSOL15M", "KXDOGE15M", "KXXRP15M"),
    [int]$SessionSeconds = 900
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$symbols = @{
    "KXBTC15M"  = @{ cb = "BTC-USD";  bn = "BTCUSDT"  }
    "KXETH15M"  = @{ cb = "ETH-USD";  bn = "ETHUSDT"  }
    "KXSOL15M"  = @{ cb = "SOL-USD";  bn = "SOLUSDT"  }
    "KXDOGE15M" = @{ cb = "DOGE-USD"; bn = "DOGEUSDT" }
    "KXXRP15M"  = @{ cb = "XRP-USD";  bn = "XRPUSDT"  }
}

foreach ($s in $Series) {
    if (-not $symbols.ContainsKey($s)) { Write-Host "skip unknown series $s"; continue }
    $cb = $symbols[$s].cb
    $bn = $symbols[$s].bn
    $cmd = "`$env:COINBASE_HIRES_SYMBOL='$cb'; `$env:BINANCE_HIRES_SYMBOL='$bn'; "
    if ($s -ne "KXBTC15M") {
        $cmd += "`$env:DATA_DIR='$repo\data\series\$s'; `$env:REPORTS_DIR='$repo\reports\series\$s'; "
    }
    $cmd += "& '$py' -m btc5m.cli kalshi-hires-record-loop --series $s --session-seconds $SessionSeconds"
    Write-Host "launching hi-res recorder: $s ($cb / $bn)" -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $cmd -WorkingDirectory $repo
    Start-Sleep -Seconds 2
}

Write-Host "All hi-res recorders launched (READ-ONLY; sub-second WS where creds allow)." -ForegroundColor Green
