import json

with open("execution_normalized_outcomes_v1.json", "r") as f:
    outcomes = json.load(f)

state_stats = {}
for o in outcomes:
    state = o.get("structural_state", "UNKNOWN")
    gross_r = o.get("gross_r")
    
    if isinstance(gross_r, (int, float)) and not isinstance(gross_r, bool):
        if state not in state_stats:
            state_stats[state] = {"wins": 0, "total": 0, "total_r": 0.0}
        
        state_stats[state]["total"] += 1
        state_stats[state]["total_r"] += gross_r
        if gross_r > 0:
            state_stats[state]["wins"] += 1

print(f"{'STRUCTURAL STATE':<30} | {'SAMPLES':<8} | {'WIN RATE':<10} | {'TOTAL R':<8}")
print("-" * 65)
for state, stats in state_stats.items():
    win_rate = (stats["wins"] / stats["total"]) * 100 if stats["total"] > 0 else 0
    print(f"{state:<30} | {stats['total']:<8} | {win_rate:>.1f}%     | {stats['total_r']:>8.2f}")
