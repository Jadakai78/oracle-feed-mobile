from pathlib import Path
import json
import math
import statistics

SOURCE = Path("training_logs/delta_tempo_v4_observations.jsonl")
FIELDS = ["volume_per_minute", "delta_per_minute", "trade_count"]

def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

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

        buy = num(r.get("buy_volume"))
        sell = num(r.get("sell_volume"))
        if buy is None or sell is None or buy + sell <= 0:
            continue

        rows.append({
            "delta_norm": abs(buy - sell) / (buy + sell),
            "volume_per_minute": num(r.get("volume_per_minute")),
            "delta_per_minute": num(r.get("delta_per_minute")),
            "trade_count": num(r.get("trade_count")),
        })

def corr(a, b):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 2:
        return None, len(pairs)

    xs, ys = zip(*pairs)
    mx, my = statistics.mean(xs), statistics.mean(ys)
    top = sum((x - mx) * (y - my) for x, y in pairs)
    bottom = math.sqrt(
        sum((x - mx) ** 2 for x in xs) *
        sum((y - my) ** 2 for y in ys)
    )
    return (top / bottom if bottom else None), len(pairs)

delta_norm = [r["delta_norm"] for r in rows]

print(f"Valid observations: {len(rows)}")

for field in FIELDS:
    values = [r[field] for r in rows if r[field] is not None]
    coefficient, n = corr(delta_norm, [r[field] for r in rows])

    print("\n" + field)
    print(f"  Non-null: {len(values)}")
    if values:
        print(f"  Min: {min(values):.8f}")
        print(f"  Median: {statistics.median(values):.8f}")
        print(f"  Max: {max(values):.8f}")
        print(f"  Unique rounded-8: {len(set(round(v, 8) for v in values))}")
    print(
        "  Correlation with delta_norm: "
        + (f"{coefficient:.12f} (n={n})" if coefficient is not None else "unavailable")
    )