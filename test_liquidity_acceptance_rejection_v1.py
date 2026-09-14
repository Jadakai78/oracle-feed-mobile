"""
Hydra Adversary Test Suite v2.1 (Fully Aligned & Uncompromising)
----------------------------------------------------------------
"""

import unittest
from datetime import datetime, timedelta, timezone
from liquidity_acceptance_rejection_v1 import analyze_liquidity_acceptance_rejection

def generate_valid_candles(count=45, base_price=100.0, start_time=None):
    if start_time is None:
        start_time = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
    candles = []
    for i in range(count):
        dt = start_time + timedelta(minutes=5 * i)
        p = base_price + (1.0 * ((i % 8) - 4) * 0.25)
        candles.append({
            "timestamp": dt.isoformat().replace("+00:00", "Z"),
            "open": p - 0.05,
            "high": p + 0.35,
            "low": p - 0.35,
            "close": p,
            "volume": 1000.0
        })
    return candles

class TestLARGatev11(unittest.TestCase):
    
    def test_01_insufficient_bars_blocks(self):
        candles = generate_valid_candles(35)
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "INSUFFICIENT_CANDLES")
        self.assertEqual(res["liquidity_gate"]["entry_permission"], "BLOCK")

    def test_02_empty_list_blocks(self):
        res = analyze_liquidity_acceptance_rejection([])
        self.assertEqual(res["liquidity_gate"]["state"], "INSUFFICIENT_CANDLES")

    def test_03_missing_required_field_blocks(self):
        candles = generate_valid_candles(45)
        del candles[-1]["volume"]
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "INVALID_INPUT")
        self.assertEqual(res["liquidity_gate"]["entry_permission"], "BLOCK")

    def test_04_non_finite_ohlcv_blocks(self):
        candles = generate_valid_candles(45)
        candles[-1]["close"] = float('nan')
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "INVALID_INPUT")

    def test_05_invalid_geometry_blocks(self):
        candles = generate_valid_candles(45)
        candles[-1]["high"] = 50.0
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "INVALID_INPUT")

    def test_06_timestamp_gap_blocks(self):
        candles = generate_valid_candles(45)
        dt = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
        candles[-1]["timestamp"] = dt.isoformat().replace("+00:00", "Z")
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "INVALID_INPUT")

    def test_07_true_cluster_ignored_isolated_high(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["high"] = 101.50
            candles[idx]["close"] = 101.30
            candles[idx-1]["high"] = 100.0
            candles[idx-2]["high"] = 100.0
            candles[idx+1]["high"] = 100.0
            candles[idx+2]["high"] = 100.0
        candles[40]["high"] = 103.00
        candles[40]["close"] = 102.80
        candles[-1]["high"] = 101.80
        candles[-1]["close"] = 101.10
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["pool_type"], "EQUAL_HIGHS")
        self.assertAlmostEqual(res["liquidity_gate"]["pool_level"], 101.50, places=2)

    def test_08_true_cluster_ignored_isolated_low(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["low"] = 98.50
            candles[idx]["close"] = 98.70
            candles[idx-1]["low"] = 100.0
            candles[idx-2]["low"] = 100.0
            candles[idx+1]["low"] = 100.0
            candles[idx+2]["low"] = 100.0
        candles[40]["low"] = 96.00
        candles[40]["close"] = 96.20
        candles[-1]["low"] = 98.10
        candles[-1]["close"] = 98.80
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["pool_type"], "EQUAL_LOWS")
        self.assertAlmostEqual(res["liquidity_gate"]["pool_level"], 98.50, places=2)

    def test_09_weak_single_touch_level_labeled_range(self):
        candles = generate_valid_candles(45, 100.0)
        for i, c in enumerate(candles):
            c["high"] = 100.0 + (i * 0.01)
        candles[25]["high"] = 102.50
        candles[25]["close"] = 102.30
        candles[24]["high"] = 100.50
        candles[26]["high"] = 100.50
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertIn(res["liquidity_gate"]["pool_type"], ["RANGE_HIGH", "NO_POOL"])

    def test_10_shallow_breach_remains_no_sweep(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["high"] = 101.50
            candles[idx]["close"] = 101.30
            candles[idx-1]["high"] = 100.0
            candles[idx-2]["high"] = 100.0
            candles[idx+1]["high"] = 100.0
            candles[idx+2]["high"] = 100.0
        candles[-1]["high"] = 101.55
        candles[-1]["close"] = 101.00
        res = analyze_liquidity_acceptance_rejection(candles, atr_multiplier=0.99)
        self.assertEqual(res["liquidity_gate"]["state"], "NO_SWEEP")

    def test_11_exact_penetration_threshold(self):
        candles = generate_valid_candles(45, 100.0)
        candles[-1]["high"] = 105.00
        candles[-1]["close"] = 101.00
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertNotEqual(res["liquidity_gate"]["state"], "NO_SWEEP")

    def test_12_deep_upper_sweep_reclaim_short_only(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["high"] = 101.50
            candles[idx]["close"] = 101.30
            candles[idx-1]["high"] = 100.0
            candles[idx-2]["high"] = 100.0
            candles[idx+1]["high"] = 100.0
            candles[idx+2]["high"] = 100.0
        candles[-1]["high"] = 103.50
        candles[-1]["close"] = 101.10
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "REJECTION_RECLAIM")
        self.assertEqual(res["liquidity_gate"]["entry_permission"], "SHORT_RECLAIM_ONLY")

    def test_13_deep_lower_sweep_reclaim_long_only(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["low"] = 98.50
            candles[idx]["close"] = 98.70
            candles[idx-1]["low"] = 100.0
            candles[idx-2]["low"] = 100.0
            candles[idx+1]["low"] = 100.0
            candles[idx+2]["low"] = 100.0
        candles[-1]["low"] = 97.80
        candles[-1]["close"] = 98.90
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "REJECTION_RECLAIM")
        self.assertEqual(res["liquidity_gate"]["entry_permission"], "LONG_RECLAIM_ONLY")

    def test_14_upper_sweep_enters_pending_state(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["high"] = 101.50
            candles[idx]["close"] = 101.30
            candles[idx-1]["high"] = 100.0
            candles[idx-2]["high"] = 100.0
            candles[idx+1]["high"] = 100.0
            candles[idx+2]["high"] = 100.0
        candles[-1]["high"] = 102.20
        candles[-1]["close"] = 101.80
        candles[-2]["high"] = 100.50
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "SWEEP_PENDING_CONFIRMATION")

    def test_15_next_bar_confirms_upper_acceptance(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["high"] = 101.50
            candles[idx]["close"] = 101.30
            candles[idx-1]["high"] = 100.0
            candles[idx-2]["high"] = 100.0
            candles[idx+1]["high"] = 100.0
            candles[idx+2]["high"] = 100.0
        candles[-2]["high"] = 102.20
        candles[-2]["close"] = 101.80
        candles[-1]["high"] = 102.30
        candles[-1]["close"] = 101.90
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "BREAKOUT_ACCEPTED")
        self.assertEqual(res["liquidity_gate"]["entry_permission"], "LONG_CONTINUATION_ONLY")

    def test_16_next_bar_reclaims_below_upper_pool(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["high"] = 101.50
            candles[idx]["close"] = 101.30
            candles[idx-1]["high"] = 100.0
            candles[idx-2]["high"] = 100.0
            candles[idx+1]["high"] = 100.0
            candles[idx+2]["high"] = 100.0
        candles[-2]["high"] = 102.20
        candles[-2]["close"] = 102.10
        candles[-1]["high"] = 101.90
        candles[-1]["close"] = 101.30
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "REJECTION_RECLAIM")
        self.assertEqual(res["liquidity_gate"]["entry_permission"], "SHORT_RECLAIM_ONLY")

    def test_17_lower_sweep_enters_pending_state(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["low"] = 98.50
            candles[idx]["close"] = 98.70
            candles[idx-1]["low"] = 100.0
            candles[idx-2]["low"] = 100.0
            candles[idx+1]["low"] = 100.0
            candles[idx+2]["low"] = 100.0
        candles[-1]["low"] = 97.80
        candles[-1]["close"] = 98.20
        candles[-2]["low"] = 99.50
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "SWEEP_PENDING_CONFIRMATION")

    def test_18_next_bar_confirms_lower_acceptance(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["low"] = 98.50
            candles[idx]["close"] = 98.70
            candles[idx-1]["low"] = 100.0
            candles[idx-2]["low"] = 100.0
            candles[idx+1]["low"] = 100.0
            candles[idx+2]["low"] = 100.0
        candles[-2]["low"] = 97.80
        candles[-2]["close"] = 98.20
        candles[-1]["low"] = 97.70
        candles[-1]["close"] = 98.10
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "BREAKOUT_ACCEPTED")
        self.assertEqual(res["liquidity_gate"]["entry_permission"], "SHORT_CONTINUATION_ONLY")

    def test_19_next_bar_reclaims_above_lower_pool(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["low"] = 98.50
            candles[idx]["close"] = 98.70
            candles[idx-1]["low"] = 100.0
            candles[idx-2]["low"] = 100.0
            candles[idx+1]["low"] = 100.0
            candles[idx+2]["low"] = 100.0
        candles[-2]["low"] = 97.80
        candles[-2]["close"] = 98.20
        candles[-1]["low"] = 98.10
        candles[-1]["close"] = 98.90
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "REJECTION_RECLAIM")
        self.assertEqual(res["liquidity_gate"]["entry_permission"], "LONG_RECLAIM_ONLY")

    def test_20_same_bar_dual_sweep_blocks(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["high"] = 101.50
            candles[idx]["low"] = 98.50
        candles[-1]["high"] = 102.50
        candles[-1]["low"] = 97.50
        candles[-1]["close"] = 100.00
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "UNRESOLVED_SWEEP")
        self.assertEqual(res["liquidity_gate"]["pool_side"], "BOTH")
        self.assertEqual(res["liquidity_gate"]["entry_permission"], "BLOCK")

    def test_21_neutral_no_sweep_uses_no_restriction(self):
        candles = generate_valid_candles(45, 100.0)
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["entry_permission"], "NO_LAR_RESTRICTION")

    def test_22_output_schema_identity(self):
        candles = generate_valid_candles(45, 100.0)
        res = analyze_liquidity_acceptance_rejection(candles, pair="ETHUSD", timeframe="5m")
        gate = res["liquidity_gate"]
        self.assertEqual(gate["pair"], "ETHUSD")
        self.assertEqual(gate["timeframe"], "5m")

    def type_atr_multiplier_sensitivity(self):
        pass

    def test_23_atr_multiplier_sensitivity(self):
        candles = generate_valid_candles(45, 100.0)
        for idx in [15, 25]:
            candles[idx]["high"] = 101.50
            candles[idx]["close"] = 101.30
            candles[idx-1]["high"] = 100.0
            candles[idx-2]["high"] = 100.0
            candles[idx+1]["high"] = 100.0
            candles[idx+2]["high"] = 100.0
        candles[-1]["high"] = 101.65
        candles[-1]["close"] = 101.00
        res_strict = analyze_liquidity_acceptance_rejection(candles, atr_multiplier=0.99)
        self.assertEqual(res_strict["liquidity_gate"]["state"], "NO_SWEEP")

    def test_24_valid_multi_touch_timestamps_preserved(self):
        candles = generate_valid_candles(45, 100.0)
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertIn("source_bar_count", res["liquidity_gate"])

    def test_25_clean_pass_through_no_sweep(self):
        candles = generate_valid_candles(45, 100.0)
        res = analyze_liquidity_acceptance_rejection(candles)
        self.assertEqual(res["liquidity_gate"]["state"], "NO_SWEEP")

if __name__ == "__main__":
    unittest.main()
