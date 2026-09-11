from pathlib import Path
import json

SOURCE = Path("training_logs/ltf_shadow_5m_v3.jsonl")

with SOURCE.open("r", encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.strip()

        if not line:
            continue

        row = json.loads(line)

        print("TOP-LEVEL KEYS:")
        print(sorted(row.keys()))

        print("\nbar_5m:")
        print(json.dumps(row.get("bar_5m"), indent=2, default=str))

        print("\nclassified_flow_5m:")
        print(json.dumps(row.get("classified_flow_5m"), indent=2, default=str))

        print("\ncompleted_15m_bar:")
        print(json.dumps(row.get("completed_15m_bar"), indent=2, default=str))

        print("\ncompleted_15m_context:")
        print(json.dumps(row.get("completed_15m_context"), indent=2, default=str))

        break