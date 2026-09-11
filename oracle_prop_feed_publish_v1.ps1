<#
Oracle Prop Feed Publisher v1

Validates local oracle_prop_feed_v1.json, then publishes only that JSON file
into the GitHub Pages repository. No scanner, adapter, alert, queue, trade,
or perpetual-routing behavior is included.

Prerequisite: GitHub CLI (gh) authenticated for the Jadakai78 account.
Run once: gh auth login
#>

[CmdletBinding()]
param(
    [string]$SourcePath = (Join-Path $PSScriptRoot "oracle_prop_feed_v1.json"),
    [string]$Repository = "Jadakai78/oracle-feed-mobile",
    [string]$Branch = "main",
    [string]$RemotePath = "oracle_prop_feed_v1.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    throw "Oracle Prop feed publish blocked: $Message"
}

if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
    Fail "local feed file not found: $SourcePath"
}

try {
    $raw = Get-Content -LiteralPath $SourcePath -Raw -Encoding UTF8
    $feed = $raw | ConvertFrom-Json
}
catch {
    Fail "local file is not valid JSON: $($_.Exception.Message)"
}

if ($feed.recordtype -ne "ORACLEPROPFEED") { Fail "recordtype must be ORACLEPROPFEED" }
if ($feed.venue -ne "PROP") { Fail "venue must be PROP" }
if ($feed.universe -ne "APRIL_12_FIXED") { Fail "universe must be APRIL_12_FIXED" }
if ($feed.manual_review_only -ne $true) { Fail "manual_review_only must be true" }
if ($feed.does_not_authorize_trade -ne $true) { Fail "does_not_authorize_trade must be true" }
if ($feed.does_not_change_queue -ne $true) { Fail "does_not_change_queue must be true" }
if ($feed.does_not_send_alerts -ne $true) { Fail "does_not_send_alerts must be true" }
if ($null -eq $feed.cards -or $feed.cards.Count -ne 49) { Fail "cards must contain exactly 49 records" }
if ($null -eq $feed.health -or $feed.health.pair_count -ne 49) { Fail "health.pair_count must equal 49" }
if ([string]::IsNullOrWhiteSpace([string]$feed.generated_at_utc)) { Fail "generated_at_utc is required" }
if ([string]::IsNullOrWhiteSpace([string]$feed.context_generated_at_utc)) { Fail "context_generated_at_utc is required" }

$requiredCardFields = @(
    "pair", "directional_context", "market_type", "structure", "tempo", "flow",
    "shield", "location", "review_state", "reason_codes", "context_claim",
    "context_score", "tier", "correlation_group", "correlation_role",
    "micro_watchlist", "micro_state"
)

foreach ($card in $feed.cards) {
    foreach ($field in $requiredCardFields) {
        if ($null -eq $card.PSObject.Properties[$field]) {
            Fail "card schema missing '$field'"
        }
    }
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Fail "GitHub CLI 'gh' was not found. Install it, then run: gh auth login"
}

& gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail "GitHub CLI is not authenticated. Run: gh auth login"
}

$repoParts = $Repository.Split("/", 2)
if ($repoParts.Count -ne 2) { Fail "Repository must use OWNER/REPO format" }
$owner = $repoParts[0]
$repo = $repoParts[1]

$encodedContent = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($raw))
$endpoint = "repos/$owner/$repo/contents/$RemotePath"

$existing = $null
try {
    $existing = & gh api "repos/$owner/$repo/contents/$RemotePath?ref=$Branch" 2>$null | ConvertFrom-Json
}
catch {
    $existing = $null
}

$body = @{
    message = "Publish Oracle Prop feed $($feed.generated_at_utc)"
    content = $encodedContent
    branch = $Branch
}
if ($existing -and $existing.sha) {
    $body.sha = $existing.sha
}

$bodyPath = Join-Path ([System.IO.Path]::GetTempPath()) ("oracle_prop_feed_publish_{0}.json" -f [guid]::NewGuid().ToString("N"))
try {
    $bodyJson = $body | ConvertTo-Json -Depth 6 -Compress
[System.IO.File]::WriteAllText(
    $bodyPath,
    $bodyJson,
    [System.Text.UTF8Encoding]::new($false)
)
    & gh api --method PUT $endpoint --input $bodyPath | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "GitHub API update failed" }
}
finally {
    Remove-Item -LiteralPath $bodyPath -Force -ErrorAction SilentlyContinue
}

Write-Host "Published validated Oracle Prop feed to $Repository/$RemotePath" -ForegroundColor Green
Write-Host "Records: $($feed.cards.Count) | Context timestamp: $($feed.context_generated_at_utc)" -ForegroundColor Cyan

