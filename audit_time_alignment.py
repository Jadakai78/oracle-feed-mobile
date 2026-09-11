from pathlib import Path
import csv
from datetime import datetime, timezone

CANDIDATES = Path("delta_corrected_tempo_candidates.csv")
PRICE_FILE = next(Path("finance_5m").glob("BTCUSD_price_history_external_*_5min.csv"))

def parse_time(value):
    if not value:
        return None

    text = value.strip().replace("Z", "+00:00")

    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)

candidate_times = []
with CANDIDATES.open("r", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        raw = row.get("bar_end") or row.get("observed_at")
        dt = parse_time(raw)
        if dt:
            candidate_times.append((raw, dt))

price_times = []
with PRICE_FILE.open("r", newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    print("Price CSV columns:", reader.fieldnames)

    for row in reader:
        raw = (
            row.get("timestamp") or row.get("time") or row.get("datetime")
            or row.get("date") or row.get("Timestamp") or row.get("Date")
        )
        dt = parse_time(raw)
        if dt:
            price_times.append((raw, dt))

print("\nCandidate timestamps:")
print("Count:", len(candidate_times))
if candidate_times:
    print("First raw:", candidate_times[0][0])
    print("First UTC:", candidate_times[0][1].isoformat())
    print("Last raw:", candidate_times[-1][0])
    print("Last UTC:", candidate_times[-1][1].isoformat())

print("\nBTC price timestamps:")
print("Count:", len(price_times))
if price_times:
    print("First raw:", price_times[0][0])
    print("First UTC:", price_times[0][1].isoformat())
    print("Last raw:", price_times[-1][0])
    print("Last UTC:", price_times[-1][1].isoformat())