$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$logDirectory = Join-Path $PSScriptRoot "training_logs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

$lockPath = Join-Path $logDirectory "kraken_spot_speed_review_refresh.lock"

if (Test-Path -LiteralPath $lockPath) {
    $lockAgeSeconds = (
        (Get-Date) - (Get-Item -LiteralPath $lockPath).LastWriteTime
    ).TotalSeconds

    if ($lockAgeSeconds -lt 240) {
        Write-Host "Refresh already running; skipping overlapping invocation."
        exit 0
    }

    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
}

New-Item `
    -ItemType File `
    -Path $lockPath `
    -Force |
    Out-Null

try {
    $steps = @(
        ".\kraken_spot_5m_bar_collector_v1.py",
        ".\speed_companion_kraken_spot_state_v1.py",
        ".\oracle_prop_context_kraken_spot_speed_join_v1.py",
        ".\oracle_prop_feed_kraken_spot_speed_review_v1.py"
    )

    foreach ($step in $steps) {
        Write-Host ""
        Write-Host "Running $step" -ForegroundColor Cyan

        & python $step

        if ($LASTEXITCODE -ne 0) {
            throw "Failed: $step (exit code $LASTEXITCODE)"
        }
    }

    $reviewPath = Join-Path `
        $PSScriptRoot `
        "oracle_prop_feed_kraken_spot_speed_review_v1.json"

    if (-not (Test-Path -LiteralPath $reviewPath)) {
        throw "Review feed was not created: $reviewPath"
    }

    $review = Get-Content -LiteralPath $reviewPath -Raw |
        ConvertFrom-Json

    $health = $review.kraken_spot_speed_review_health

    if ($null -eq $health) {
        throw "Review feed does not contain kraken_spot_speed_review_health."
    }

    if ($health.feed_card_count -ne 49) {
        throw "Expected 49 feed cards; got $($health.feed_card_count)."
    }

    if ($health.m5_available_count -ne 47) {
        throw "Expected 47 M5 available cards; got $($health.m5_available_count)."
    }

    if ($health.m5_unavailable_count -ne 2) {
        throw "Expected 2 M5 unavailable cards; got $($health.m5_unavailable_count)."
    }

    Write-Host ""
    Write-Host "Review feed refresh succeeded." -ForegroundColor Green
    Write-Host "Cards: $($health.feed_card_count)"
    Write-Host "M5 available: $($health.m5_available_count)"
    Write-Host "M5 unavailable: $($health.m5_unavailable_count)"
    Write-Host "Labels: $($health.label_counts | ConvertTo-Json -Compress)"

    exit 0
}
catch {
    Write-Host ""
    Write-Host "Review feed refresh FAILED." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
finally {
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
}