$root = "C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba"

$cases = @(
    @{ Pair = "BONK/USD"; Time = "2026-08-21T10:24:03Z" },
    @{ Pair = "FET/USD";  Time = "2026-08-21T12:52:18Z" },
    @{ Pair = "WLD/USD";  Time = "2026-08-21T13:20:53Z" },
    @{ Pair = "BCH/USD";  Time = "2026-08-21T22:12:28Z" },
    @{ Pair = "BTC/USD";  Time = "2026-08-21T22:53:08Z" },
    @{ Pair = "ETH/USD";  Time = "2026-08-22T00:50:58Z" },
    @{ Pair = "ETH/USD";  Time = "2026-08-22T01:04:10Z" },
    @{ Pair = "BCH/USD";  Time = "2026-08-22T03:36:55Z" }
)

$files = @(
    "$root\training_logs\delta_tempo.jsonl",
    "$root\training_logs\delta_tempo_v4_observations.jsonl",
    "$root\training_logs\delta_tempo_outcomes.jsonl"
)

function Get-FirstValue {
    param($Object, [string[]]$Names)

    foreach ($name in $Names) {
        $prop = $Object.PSObject.Properties[$name]
        if ($prop -and $null -ne $prop.Value -and "$($prop.Value)" -ne "") {
            return $prop.Value
        }
    }

    return $null
}

$all = @()

foreach ($file in $files) {
    if (-not (Test-Path $file)) { continue }

    Get-Content $file | Where-Object { $_.Trim() } | ForEach-Object {
        try {
            $row = $_ | ConvertFrom-Json
        }
        catch {
            return
        }

        $pair = Get-FirstValue $row @("pair", "symbol", "kraken_pair", "market")
        $stamp = Get-FirstValue $row @(
            "generated_at_utc", "observed_at_utc", "recorded_at_utc",
            "timestamp_utc", "timestamp", "ts", "created_at_utc"
        )

        if ($pair -and $stamp) {
            try {
                $all += [PSCustomObject]@{
                    File      = Split-Path $file -Leaf
                    Pair      = "$pair"
                    StampText = "$stamp"
                    StampUtc  = [datetime]::Parse("$stamp").ToUniversalTime()
                    RecordType = Get-FirstValue $row @("recordtype", "record_type", "type")
                    Side      = Get-FirstValue $row @("side", "delta_side", "direction")
                    Event     = Get-FirstValue $row @("event", "event_name", "event_type")
                    Lifecycle = Get-FirstValue $row @("lifecycle", "tempo_lifecycle")
                    Action    = Get-FirstValue $row @("action", "action_state", "execution_state")
                    Verdict   = Get-FirstValue $row @("verdict", "status", "outcome")
                    Score     = Get-FirstValue $row @("score", "delta_score")
                }
            }
            catch {
            }
        }
    }
}

$results = foreach ($case in $cases) {
    $readyUtc = [datetime]::Parse($case.Time).ToUniversalTime()

    $eligible = $all | Where-Object {
        $_.Pair -eq $case.Pair -and
        $_.StampUtc -le $readyUtc -and
        ($readyUtc - $_.StampUtc).TotalMinutes -le 10
    }

    if ($eligible) {
        $nearest = $eligible |
            Sort-Object StampUtc -Descending |
            Select-Object -First 1

        [PSCustomObject]@{
            Pair         = $case.Pair
            ReadyUTC     = $case.Time
            SourceFile   = $nearest.File
            DeltaUTC     = $nearest.StampText
            LagSeconds   = [math]::Round(($readyUtc - $nearest.StampUtc).TotalSeconds, 0)
            RecordType   = $nearest.RecordType
            Side         = $nearest.Side
            Event        = $nearest.Event
            Lifecycle    = $nearest.Lifecycle
            Action       = $nearest.Action
            Verdict      = $nearest.Verdict
            Score        = $nearest.Score
        }
    }
    else {
        [PSCustomObject]@{
            Pair         = $case.Pair
            ReadyUTC     = $case.Time
            SourceFile   = "NO MATCH <= 10 MIN"
            DeltaUTC     = $null
            LagSeconds   = $null
            RecordType   = $null
            Side         = $null
            Event        = $null
            Lifecycle    = $null
            Action       = $null
            Verdict      = $null
            Score        = $null
        }
    }
}

$results |
    Format-Table Pair, ReadyUTC, SourceFile, DeltaUTC, LagSeconds,
        RecordType, Side, Event, Lifecycle, Action, Verdict, Score -Wrap