"""
Hydra Adversary Test Suite v2
-----------------------------
Comprehensive test harness validating the hardened LAR-Gate against flat-ranging
structural fixtures, multi-bar confirmation sequences, and edge cases.
"""

from liquidity_acceptance_rejection_v1 import analyze_liquidity_acceptance_rejection

def generate_flat_range_candles(count=45, base_price=100.0):
    candles = []
    for i in range(count):
        # Bounded horizontal range generator
        p = base_price + (1.0 * ((i % 8) - 4) * 0.25)
        candles.append({
            "timestamp": f"2026-09-14T{str(i // 6).zfill(2)}:{str((i % 6) * 10).zfill(2)}:00Z",
            "open": p - 0.05,
            "high": p + 0.35,
            "low": p - 0.35,
            "close": p,
            "volume": 1000.0
        })
    return candles

def run_comprehensive_audit():
    print("=" * 80)
    print("HYDRA ADVERSARY TEST SUITE V2: COMPREHENSIVE STRUCTURAL AUDIT")
    print("=" * 80)
    
    test_cases = [
        ("UPPER_SWEEP_RECLAIM", "SHORT_RECLAIM_ONLY", "REJECTION_RECLAIM"),
        ("LOWER_SWEEP_RECLAIM", "LONG_RECLAIM_ONLY", "REJECTION_RECLAIM"),
        ("UPPER_BREAK_ACCEPTED", "LONG_CONTINUATION_ONLY", "BREAKOUT_ACCEPTED"),
        ("LOWER_BREAK_ACCEPTED", "SHORT_CONTINUATION_ONLY", "BREAKOUT_ACCEPTED"),
        ("DOUBLE_SWEEP_CHOP", "BLOCK", "UNRESOLVED_SWEEP"),
    ]
    
    results = []
    
    for case_name, expected_perm, expected_state in test_cases:
        passed = 0
        total = 50
        
        for _ in range(total):
            candles = generate_flat_range_candles(45, 100.0)
            last = candles[-1]
            prev = candles[-2]
            
            if case_name == "UPPER_SWEEP_RECLAIM":
                candles[-5]["high"] = 101.50
                candles[-10]["high"] = 101.50
                last["high"] = 102.10
                last["close"] = 101.20
            elif case_name == "LOWER_SWEEP_RECLAIM":
                candles[-5]["low"] = 98.50
                candles[-10]["low"] = 98.50
                last["low"] = 97.90
                last["close"] = 98.80
            elif case_name == "UPPER_BREAK_ACCEPTED":
                candles[-5]["high"] = 101.50
                last["high"] = 102.20
                last["close"] = 101.80
                prev["close"] = 101.70  # Consecutive close confirmation
            elif case_name == "LOWER_BREAK_ACCEPTED":
                candles[-5]["low"] = 98.50
                last["low"] = 97.80
                last["close"] = 98.20
                prev["close"] = 98.30  # Consecutive close confirmation
            elif case_name == "DOUBLE_SWEEP_CHOP":
                last["high"] = 102.50
                last["low"] = 97.50
                last["close"] = 100.00
                
            res = analyze_liquidity_acceptance_rejection(candles, pair="BTCUSD", atr_multiplier=0.15)
            gate = res["liquidity_gate"]
            
            if gate["entry_permission"] == expected_perm and gate["state"] == expected_state:
                passed += 1
                
        results.append({
            "scenario": case_name,
            "expected_perm": expected_perm,
            "expected_state": expected_state,
            "accuracy": f"{(passed / total) * 100:.1f}%",
            "status": "PASSED" if passed == total else "FAILED"
        })
        
    print(f"{'TEST SCENARIO':25} | {'EXPECTED PERMISSION':22} | {'ACCURACY':10} | {'STATUS'}")
    print("-" * 80)
    for r in results:
        print(f"{r['scenario']:25} | {r['expected_perm']:22} | {r['accuracy']:10} | {r['status']}")
    print("=" * 80)

if __name__ == "__main__":
    run_comprehensive_audit()
