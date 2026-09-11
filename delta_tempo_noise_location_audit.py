from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"
SOURCES = ("gimba_range", "rts_liquidation", "gimba_drive", "gimba_pulse")


def direction(row):
    value = str(row.get("bias") or row.get("side") or "").upper()
    return {"UP": "LONG", "DOWN": "SHORT"}.get(value, value)


def value_for(row):
    outcome = row.get("outcome") or {}
    label = outcome.get("label")
    if label in (1, -1):
        return float(label)
    horizon = (outcome.get("horizons") or {}).get("60m") or {}
    value = horizon.get("net_directional_return")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def main():
    groups = defaultdict(list)
    loaded = 0
    for source in SOURCES:
        path = LOG_DIR / f"{source}.jsonl"
        if not path.exists():
            print(f"{source:17} missing")
            continue
        count = 0
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                outcome = row.get("outcome") or {}
                if str(outcome.get("status") or "").lower() != "resolved":
                    continue
                side = direction(row)
                if side not in {"LONG", "SHORT"}:
                    continue
                noise = row.get("market_noise") or {}
                structure = row.get("structure") or {}
                regime = str(noise.get("regime") or "UNAVAILABLE").upper()
                zone = str(structure.get("zone") or "UNKNOWN").upper()
                groups[(source, regime, zone)].append(value_for(row))
                count += 1
        loaded += count
        print(f"{source:17} resolved directional records={count}")

    print("\nDELTA TEMPO NOISE + LOCATION AUDIT")
    print("Resolved specialist observations only; descriptive screen, not a promotion decision.")
    print("-" * 112)
    print(f"{'SOURCE':17} {'NOISE':16} {'ZONE':12} {'N':>4} {'WIN':>7} {'LOSS':>7} {'NEUTRAL':>8} {'AVG VALUE':>11}")
    for (source, regime, zone), values in sorted(groups.items()):
        n = len(values)
        wins = sum(v is not None and v > 0 for v in values)
        losses = sum(v is not None and v < 0 for v in values)
        neutral = sum(v is None or v == 0 for v in values)
        known = [v for v in values if v is not None]
        average = f"{mean(known):+.4f}" if known else "—"
        print(f"{source:17} {regime[:16]:16} {zone[:12]:12} {n:4} {wins:7} {losses:7} {neutral:8} {average:>11}")
    if not loaded:
        print("No resolved directional records were found. Run the evaluator offline, then rerun this audit.")


if __name__ == "__main__":
    main()
