from pathlib import Path
import csv
import json
import math
from collections import defaultdict

SOURCE = Path("training_logs/delta_tempo_v4_observations.jsonl")
OUTPUT = Path("delta_corrected_tempo_candidates.csv")

def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def percentile_rank(values, value):
    if not values:
        return None
    count = sum(1 for x in values if x <= value)
    return count / len(values)

rows = []

with SOURCE.open("r", encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue

        pair = r.get("pair")
        buy = num(r.get("buy_volume"))
        sell = num(r.get("sell_volume"))
        volume_pm = num(r.get("volume_per_minute"))
        delta_pm = num(r.get("delta_per_minute"))
        trades = num(r.get("trade_count"))

        if (
            not pair
            or buy is None
            or sell is None
            or buy + sell <= 0
            or volume_pm is None
            or delta_pm is None
        ):
            continue

        rows.append({
            "observed_at": r.get("observed_at"),
            "bar_start": r.get("bar_start"),
            "bar_end": r.get("bar_end"),
            "bar_timeframe": r.get("bar_timeframe"),
            "pair": pair,
            "close": r.get("close"),
            "buy_volume": buy,
            "sell_volume": sell,
            "delta": num(r.get("delta")),
            "delta_direction": r.get("delta_direction"),
            "delta_norm": abs(buy - sell) / (buy + sell),
            "volume_per_minute": volume_pm,
            "delta_per_minute": delta_pm,
            "abs_delta_per_minute": abs(delta_pm),
            "trade_count": trades,
            "eligible_for_paper_entry": r.get("eligible_for_paper_entry"),
            "flow_ready": r.get("flow_ready"),
            "flow_reason": r.get("flow_reason"),
        })

by_pair = defaultdict(list)
for row in rows:
    by_pair[row["pair"]].append(row)

for pair_rows in by_pair.values():
    volume_values = sorted(r["volume_per_minute"] for r in pair_rows)
    directional_values = sorted(r["abs_delta_per_minute"] for r in pair_rows)
    trade_values = sorted(r["trade_count"] for r in pair_rows if r["trade_count"] is not None)

    for r in pair_rows:
        r["volume_tempo_pct"] = percentile_rank(volume_values, r["volume_per_minute"])
        r["directional_tempo_pct"] = percentile_rank(
            directional_values, r["abs_delta_per_minute"]
        )
        r["trade_count_pct"] = (
            percentile_rank(trade_values, r["trade_count"])
            if r["trade_count"] is not None else None
        )

candidate_rows = [
    r for r in rows
    if r["delta_norm"] >= 0.50
    and r["volume_tempo_pct"] >= 0.70
    and r["directional_tempo_pct"] >= 0.70
]

fields = [
    "observed_at",
    "bar_start",
    "bar_end",
    "bar_timeframe",
    "pair",
    "close",
    "buy_volume",
    "sell_volume",
    "delta",
    "delta_direction",
    "delta_norm",
    "volume_per_minute",
    "delta_per_minute",
    "abs_delta_per_minute",
    "trade_count",
    "volume_tempo_pct",
    "directional_tempo_pct",
    "trade_count_pct",
    "eligible_for_paper_entry",
    "flow_ready",
    "flow_reason",
]
with OUTPUT.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(candidate_rows)

print(f"Valid observations: {len(rows)}")
print(f"Pairs represented: {len(by_pair)}")
print(f"Corrected candidates: {len(candidate_rows)}")
print(f"Created: {OUTPUT.resolve()}")

print("\nCandidates by pair:")
for pair in sorted(by_pair):
    count = sum(1 for r in candidate_rows if r["pair"] == pair)
    if count:
        print(f"{pair}: {count}")