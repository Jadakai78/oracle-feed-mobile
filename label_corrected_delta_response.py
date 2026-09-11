from pathlib import Path
import csv
import json
from datetime import datetime, timezone

CANDIDATES = Path("delta_corrected_tempo_candidates.csv")
LTF_SOURCE = Path("training_logs/ltf_shadow_5m_v3.jsonl")
OUTPUT = Path("corrected_delta_response_ledger.csv")

TARGET_PCT = 0.0025
STOP_PCT = 0.0025
HORIZONS = [3, 6, 12]


def epoch_to_utc(value):
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_candidate_time(value):
    if value is None or value == "":
        return None

    text = str(value).strip().replace("Z", "+00:00")

    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def first_bar_after(bars, event_time):
    for index, bar in enumerate(bars):
        if bar["time"] >= event_time:
            return index
    return None


with CANDIDATES.open("r", newline="", encoding="utf-8") as f:
    candidates = list(csv.DictReader(f))

bars_by_pair = {}

with LTF_SOURCE.open("r", encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.strip()

        if not line:
            continue

        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue

        pair = row.get("pair")
        bar = row.get("bar_5m") or {}

        bar_time = epoch_to_utc(bar.get("bar_end"))
        high = num(bar.get("high"))
        low = num(bar.get("low"))
        close = num(bar.get("close"))

        if not pair or not bar_time or high is None or low is None or close is None:
            continue

        bars_by_pair.setdefault(pair, []).append({
            "time": bar_time,
            "high": high,
            "low": low,
            "close": close,
        })

for pair in bars_by_pair:
    unique = {bar["time"]: bar for bar in bars_by_pair[pair]}
    bars_by_pair[pair] = sorted(unique.values(), key=lambda bar: bar["time"])
    print(f"{pair}: loaded {len(bars_by_pair[pair])} unique 5m bars")

fields = [
    "observed_at",
    "bar_start",
    "bar_end",
    "pair",
    "delta_direction",
    "close",
    "delta_norm",
    "volume_tempo_pct",
    "directional_tempo_pct",
    "trade_count_pct",
    "entry_time",
    "entry_price",
    "horizon_bars",
    "mfe_pct",
    "mae_pct",
    "response_label",
]

results = []
events_with_time = 0
events_with_price_match = 0

for row in candidates:
    event_time = parse_candidate_time(row.get("observed_at"))
    entry_price = num(row.get("close"))
    direction = row.get("delta_direction")
    pair = row.get("pair")
    bars = bars_by_pair.get(pair, [])

    if event_time is None or entry_price is None or direction not in {"UP", "DOWN"}:
        continue

    events_with_time += 1

    start_index = first_bar_after(bars, event_time)

    if start_index is None:
        continue

    events_with_price_match += 1

    for horizon in HORIZONS:
        window = bars[start_index:start_index + horizon]

        if len(window) < horizon:
            continue

        highs = [bar["high"] for bar in window]
        lows = [bar["low"] for bar in window]

        target_hit = False
        stop_hit = False

        if direction == "UP":
            mfe = (max(highs) - entry_price) / entry_price
            mae = (min(lows) - entry_price) / entry_price

            for bar in window:
                if (bar["high"] - entry_price) / entry_price >= TARGET_PCT:
                    target_hit = True
                    break
                if (bar["low"] - entry_price) / entry_price <= -STOP_PCT:
                    stop_hit = True
                    break
        else:
            mfe = (entry_price - min(lows)) / entry_price
            mae = (entry_price - max(highs)) / entry_price

            for bar in window:
                if (entry_price - bar["low"]) / entry_price >= TARGET_PCT:
                    target_hit = True
                    break
                if (entry_price - bar["high"]) / entry_price <= -STOP_PCT:
                    stop_hit = True
                    break

        if target_hit and not stop_hit:
            label = "ACCEPTED"
        elif stop_hit and not target_hit:
            label = "FAILED"
        elif target_hit and stop_hit:
            label = "BOTH"
        else:
            label = "UNRESOLVED"

        results.append({
            "observed_at": row.get("observed_at"),
            "bar_start": row.get("bar_start"),
            "bar_end": row.get("bar_end"),
            "pair": pair,
            "delta_direction": direction,
            "close": row.get("close"),
            "delta_norm": row.get("delta_norm"),
            "volume_tempo_pct": row.get("volume_tempo_pct"),
            "directional_tempo_pct": row.get("directional_tempo_pct"),
            "trade_count_pct": row.get("trade_count_pct"),
            "entry_time": bars[start_index]["time"].isoformat(),
            "entry_price": entry_price,
            "horizon_bars": horizon,
            "mfe_pct": round(mfe, 8),
            "mae_pct": round(mae, 8),
            "response_label": label,
        })

with OUTPUT.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(results)

print(f"\nCandidate events loaded: {len(candidates)}")
print(f"Candidate events with valid timestamps: {events_with_time}")
print(f"Candidate events with matching 5m bars: {events_with_price_match}")
print(f"Response rows created: {len(results)}")
print(f"Created: {OUTPUT.resolve()}")

for horizon in HORIZONS:
    subset = [row for row in results if row["horizon_bars"] == horizon]
    counts = {}

    for row in subset:
        label = row["response_label"]
        counts[label] = counts.get(label, 0) + 1

    print(f"\n{horizon} bars:")
    for label in ["ACCEPTED", "FAILED", "BOTH", "UNRESOLVED"]:
        print(f"  {label}: {counts.get(label, 0)}")
