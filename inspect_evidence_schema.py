from pathlib import Path
import json

files = [
    "shadow_audit_ledger.jsonl",
    "delta_tempo_v4_observations.jsonl",
    "gimba_drive.jsonl",
    "ltf_shadow_5m_v3.jsonl",
]

for name in files:
    matches = list(Path(".").rglob(name))
    print("\n" + "=" * 80)
    print(name)

    if not matches:
        print("NOT FOUND")
        continue

    path = matches[0]
    print(f"Path: {path}")
    print(f"Size MB: {path.stat().st_size / (1024 * 1024):.2f}")

    records = 0
    key_sets = set()

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(row, dict):
                key_sets.add(tuple(sorted(row.keys())))
                records += 1

            if records >= 10:
                break

    print(f"Valid records inspected: {records}")
    for i, keys in enumerate(key_sets, 1):
        print(f"Schema {i}:")
        print(", ".join(keys))