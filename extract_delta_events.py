from pathlib import Path
import csv
import json

SOURCE = Path("training_logs/delta_tempo_v4_observations.jsonl")
OUTPUT = Path("delta_strong_events.csv")

FIELDS = [
    "observed_at",
    "bar_start",
    "bar_end",
    "bar_timeframe",
    "pair",
    "close",
    "buy_volume",
    "sell_volume",
    "volume",
    "delta",
    "delta_direction",
    "speed_score",
    "prior_speed_score",
    "speed_change_pct",
    "speed_change_ratio",
    "speed_lifecycle",
    "eligible_for_paper_entry",
    "flow_ready",
    "flow_reason",
    "record_type",
    "source_event_key",
]

def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

kept = 0
seen = 0

with SOURCE.open("r", encoding="utf-8", errors="replace") as src, \
     OUTPUT.open("w", newline="", encoding="utf-8") as dst:

    writer = csv.DictWriter(dst, fieldnames=FIELDS + ["delta_norm"])
    writer.writeheader()

    for line in src:
        line = line.strip()
        if not line:
            continue

        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue

        seen += 1

        buy = number(row.get("buy_volume"))
        sell = number(row.get("sell_volume"))
        speed = number(row.get("speed_score"))
        acceleration = number(row.get("speed_change_pct"))

        classified_volume = (
            number(row.get("volume"))
            if number(row.get("volume")) is not None
            else (buy + sell if buy is not None and sell is not None else None)
        )

        if (
            buy is None
            or sell is None
            or classified_volume is None
            or classified_volume <= 0
            or speed is None
            or acceleration is None
        ):
            continue

        delta_norm = abs(buy - sell) / classified_volume

        if (
            delta_norm >= 0.50
            and speed >= 0.50
            and acceleration >= 30.0
        ):
            output = {field: row.get(field) for field in FIELDS}
            output["delta_norm"] = round(delta_norm, 8)
            writer.writerow(output)
            kept += 1

print(f"Rows inspected: {seen}")
print(f"Strong Delta events kept: {kept}")
print(f"Created: {OUTPUT.resolve()}")