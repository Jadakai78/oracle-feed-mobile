from pathlib import Path
import json

ROOT = Path(r"C:\Users\OneDrive\Desktop\jhl_v2\jhl_v2gimba\training_logs\shadow_tournament")

targets = [
    ROOT / "decisions.jsonl",
    ROOT / "rejections.jsonl",
]

packets = ROOT / "oracle_packets"
if packets.exists():
    targets.extend(sorted(packets.glob("*.jsonl"))[:5])

print(f"Arena root: {ROOT}")
print(f"Root exists: {ROOT.exists()}")

for path in targets:
    print("\n" + "=" * 80)
    print(f"FILE: {path}")

    if not path.exists():
        print("NOT FOUND")
        continue

    print(f"Size MB: {path.stat().st_size / (1024 * 1024):.2f}")

    rows = 0
    schemas = set()
    samples = []

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            rows += 1

            if len(samples) < 3:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue

                samples.append(item)

                if isinstance(item, dict):
                    schemas.add(tuple(sorted(item.keys())))

    print(f"Non-empty lines: {rows}")

    for i, schema in enumerate(schemas, 1):
        print(f"Schema {i}:")
        print(", ".join(schema))

    for i, item in enumerate(samples, 1):
        print(f"\nSample {i}:")
        print(json.dumps(item, indent=2, default=str)[:2500])
