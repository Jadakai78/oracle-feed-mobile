from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"
SOURCES = ("gimba_range", "rts_liquidation", "gimba_drive", "gimba_pulse")


def side(row):
    value = str(row.get("bias") or row.get("side") or "").upper()
    return {"UP": "LONG", "DOWN": "SHORT"}.get(value, value)


def location(direction, zone):
    zone = str(zone or "UNKNOWN").upper()
    if direction == "LONG":
        return {"DISCOUNT": "FAVORABLE", "PREMIUM": "EXTENDED", "NEUTRAL": "NEUTRAL"}.get(zone, "UNKNOWN")
    if direction == "SHORT":
        return {"PREMIUM": "FAVORABLE", "DISCOUNT": "EXTENDED", "NEUTRAL": "NEUTRAL"}.get(zone, "UNKNOWN")
    return "UNKNOWN"


def value(row):
    outcome = row.get("outcome") or {}
    if outcome.get("label") in (1, -1):
        return float(outcome["label"])
    horizon = (outcome.get("horizons") or {}).get("60m") or {}
    try:
        return float(horizon["net_directional_return"])
    except (KeyError, TypeError, ValueError):
        return None


def main():
    groups = defaultdict(list)
    for source in SOURCES:
        path = LOG_DIR / f"{source}.jsonl"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str((row.get("outcome") or {}).get("status") or "").lower() != "resolved":
                    continue
                direction = side(row)
                if direction not in {"LONG", "SHORT"}:
                    continue
                noise = str((row.get("market_noise") or {}).get("regime") or "UNAVAILABLE").upper()
                loc = location(direction, (row.get("structure") or {}).get("zone"))
                groups[(source, noise, loc)].append(value(row))

    print("DIRECTIONAL LOCATION AUDIT")
    print("FAVORABLE = long/discount or short/premium; EXTENDED = long/premium or short/discount.")
    print("Descriptive only; do not promote a filter from this screen alone.")
    print("-" * 100)
    print(f"{'SOURCE':17} {'NOISE':16} {'LOCATION':12} {'N':>4} {'WIN':>6} {'LOSS':>6} {'NEUTRAL':>8} {'AVG':>9}")
    for (source, noise, loc), rows in sorted(groups.items()):
        known = [x for x in rows if x is not None]
        wins = sum(x is not None and x > 0 for x in rows)
        losses = sum(x is not None and x < 0 for x in rows)
        neutral = len(rows) - wins - losses
        average = f"{mean(known):+.4f}" if known else "—"
        print(f"{source:17} {noise[:16]:16} {loc:12} {len(rows):4} {wins:6} {losses:6} {neutral:8} {average:>9}")


if __name__ == "__main__":
    main()
