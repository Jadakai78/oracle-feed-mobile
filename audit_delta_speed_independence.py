from pathlib import Path
import csv
import math
import statistics

SOURCE = Path("delta_strong_events.csv")

pairs = []
diffs = []

with SOURCE.open("r", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        try:
            delta_norm = float(row["delta_norm"])
            speed_score = float(row["speed_score"])
        except (KeyError, TypeError, ValueError):
            continue

        pairs.append((delta_norm, speed_score))
        diffs.append(abs(delta_norm - speed_score))

n = len(pairs)
xs = [x for x, _ in pairs]
ys = [y for _, y in pairs]

mean_x = statistics.mean(xs)
mean_y = statistics.mean(ys)

numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
correlation = numerator / (denom_x * denom_y) if denom_x and denom_y else float("nan")

print(f"Events checked: {n}")
print(f"Correlation(delta_norm, speed_score): {correlation:.12f}")
print(f"Maximum absolute difference: {max(diffs):.12f}")
print(f"Mean absolute difference: {statistics.mean(diffs):.12f}")
print(f"Exact matches within 1e-12: {sum(d <= 1e-12 for d in diffs)} / {n}")