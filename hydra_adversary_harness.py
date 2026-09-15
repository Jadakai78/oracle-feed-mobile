"""
Hydra Adversary Harness v1 (Corrected Fixture Generator)
"""
from liquidity_acceptance_rejection_v1 import analyze_liquidity_acceptance_rejection

def generate_ranging_candles(count=45, base_price=100.0):
    candles = []
    for i in range(count):
        p = base_price + (1.5 * ((i % 10) - 5) * 0.2)
        candles.append({
            "timestamp": f"2026-09-14T{str(i // 6).zfill(2)}:{str((i % 6) * 10).zfill(2)}:00Z",
            "open": p - 0.05,
            "high": p + 0.40,
            "low": p - 0.40,
            "close": p,
            "volume": 1000.0
        })
    return candles

def run_hydra_audit():
    print("=" * 75)
    print("HYDRA ADVERSARY HARNESS V1: CORRECTED FIXTURE STRESS TEST")
    print("=" * 75)
    scenarios = [
        ("UPPER_SWEEP_RECLAIM", "SHORT_RECLAIM_ONLY", "REJECTION_RECLAIM"),
        ("LOWER_SWEEP_RECLAIM", "LONG_RECLAIM_ONLY", "REJECTION_RECLAIM"),
        ("UPPER_BREAK_ACCEPTED", "LONG_CONTINUATION_ONLY", "BREAKOUT_ACCEPTED"),
        ("LOWER_BREAK_ACCEPTED", "SHORT_CONTINUATION_ONLY", "BREAKOUT_ACCEPTED"),
        ("DOUBLE_SWEEP_CHOP", "BLOCK", "UNRESOLVED_SWEEP"),
    ]
    results = []
    for attack_name, expected_permission, expected_state in scenarios:
        correct_count = 0
        total_runs = 100
        for _ in range(total_runs):
            candles = generate_ranging_candles(45, base_price=100.0)
            last = candles[-1]
            if attack_name == "UPPER_SWEEP_RECLAIM":
                candles[-5]["high"] = 102.50
                candles[-10]["high"] = 102.50
                last["high"] = 103.10
                last["close"] = 102.10
                candles[-2]["close"] = 101.90
            elif attack_name == "LOWER_SWEEP_RECLAIM":
                candles[-5]["low"] = 97.50
                candles[-10]["low"] = 97.50
                last["low"] = 96.80
                last["close"] = 97.90
                candles[-2]["close"] = 98.10
            elif attack_name == "UPPER_BREAK_ACCEPTED":
                candles[-5]["high"] = 102.50
                last["high"] = 103.20
                last["close"] = 102.95
                candles[-2]["close"] = 102.80
            elif attack_name == "LOWER_BREAK_ACCEPTED":
                candles[-5]["low"] = 97.50
                last["low"] = 96.70
                last["close"] = 97.05
                candles[-2]["close"] = 97.20
            elif attack_name == "DOUBLE_SWEEP_CHOP":
                last["high"] = 103.50
                last["low"] = 96.50
                last["close"] = 100.00
            res = analyze_liquidity_acceptance_rejection(candles, pair="BTCUSD", atr_multiplier=0.15)
            gate = res["liquidity_gate"]
            if gate["entry_permission"] == expected_permission and gate["state"] == expected_state:
                correct_count += 1
        results.append({
            "attack": attack_name,
            "expected_state": expected_state,
            "expected_perm": expected_permission,
            "accuracy": f"{(correct_count / total_runs) * 100:.1f}%",
            "passed": correct_count,
            "total": total_runs
        })
    print(f"{'ATTACK SCENARIO':25} | {'EXPECTED PERMISSION':22} | {'ACCURACY':10} | {'STATUS'}")
    print("-" * 75)
    for r in results:
        status = "PASSED" if r["passed"] == r["total"] else "REVIEW REQUIRED"
        print(f"{r['attack']:25} | {r['expected_perm']:22} | {r['accuracy']:10} | {status}")
    print("=" * 75)

if __name__ == '__main__':
    run_hydra_audit()
