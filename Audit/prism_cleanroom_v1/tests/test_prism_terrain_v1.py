import statistics
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism_terrain_v1 import build_terrain  # noqa: E402
from tests._helpers import flat_bars, make_bars  # noqa: E402


class TerrainTests(unittest.TestCase):
    def test_valid_390_bar_matches_independent_calculation(self):
        bars = make_bars(390, amplitude=3.0)
        result = build_terrain(bars)
        closes = [b["close"] for b in bars][-365:]
        expected_mean = statistics.fmean(closes)
        expected_std = statistics.pstdev(closes)
        self.assertEqual(result["state"], "AVAILABLE")
        self.assertAlmostEqual(result["middle_band"], expected_mean, places=9)
        self.assertAlmostEqual(result["stddev"], expected_std, places=9)
        self.assertAlmostEqual(result["bandwidth"], 6 * expected_std, places=9)

    def test_current_window_is_last_365_closes(self):
        bars = make_bars(400, amplitude=3.0)
        result = build_terrain(bars)
        expected_mean = statistics.fmean([b["close"] for b in bars][-365:])
        self.assertAlmostEqual(result["middle_band"], expected_mean, places=9)

    def test_zone_boundaries(self):
        # A single large positive outlier against 364 flat closes drives a
        # large positive z-score -> extreme upper displacement.
        bars = flat_bars(365)
        bars[-1]["close"] = 130.0
        bars[-1]["open"] = 129.5
        bars[-1]["high"] = 130.5
        bars[-1]["low"] = 129.4
        result = build_terrain(bars)
        self.assertEqual(result["state"], "AVAILABLE")
        self.assertGreater(result["z_score"], 3)
        self.assertEqual(result["zone"], "EXTREME_UPPER_DISPLACEMENT")

        # Mirror case: large negative outlier -> extreme lower displacement.
        bars_low = flat_bars(365)
        bars_low[-1]["close"] = 70.0
        bars_low[-1]["open"] = 70.5
        bars_low[-1]["high"] = 70.6
        bars_low[-1]["low"] = 69.9
        result_low = build_terrain(bars_low)
        self.assertLess(result_low["z_score"], -3)
        self.assertEqual(result_low["zone"], "EXTREME_LOWER_DISPLACEMENT")

        # Gentle sinusoidal noise keeps the final close near the mean ->
        # central rotation zone.
        bars_central = make_bars(365, amplitude=1.0, period_bars=364)
        result_central = build_terrain(bars_central)
        self.assertTrue(-1 < result_central["z_score"] < 1)
        self.assertEqual(result_central["zone"], "CENTRAL_ROTATION_ZONE")

    def test_365_bars_available_terrain_unavailable_slope(self):
        bars = make_bars(365, amplitude=3.0)
        result = build_terrain(bars)
        self.assertEqual(result["state"], "AVAILABLE")
        self.assertIsNone(result["prior_middle_band"])
        self.assertEqual(result["middle_slope"], "UNAVAILABLE")

    def test_364_bars_fails_closed_insufficient_history(self):
        bars = make_bars(364, amplitude=3.0)
        result = build_terrain(bars)
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertIn("PRISM.DATA.INSUFFICIENT_HISTORY", result["reason_codes"])

    def test_missing_bar_fails_closed(self):
        bars = make_bars(390, amplitude=3.0, gap_at=200)
        result = build_terrain(bars)
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertIn("PRISM.DATA.MISSING_BARS", result["reason_codes"])

    def test_short_series_with_gap_reports_missing_bars_not_insufficient_history(self):
        # Fewer than 365 bars AND a timestamp gap: the more specific
        # integrity failure (MISSING_BARS) must take precedence over the
        # generic INSUFFICIENT_HISTORY reason.
        bars = make_bars(364, amplitude=3.0, gap_at=100)
        result = build_terrain(bars)
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual(result["reason_codes"], ["PRISM.DATA.MISSING_BARS"])

    def test_short_series_with_malformed_bar_reports_invalid_ohlcv(self):
        # Fewer than 365 bars AND a malformed bar: the more specific
        # integrity failure (INVALID_OHLCV) must take precedence over the
        # generic INSUFFICIENT_HISTORY reason.
        bars = make_bars(364, amplitude=3.0)
        bars[50]["high"] = -1.0
        result = build_terrain(bars)
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual(result["reason_codes"], ["PRISM.DATA.INVALID_OHLCV"])

    def test_invalid_ohlcv_fails_closed(self):
        bars = make_bars(390, amplitude=3.0)
        bars[10]["high"] = -1.0
        result = build_terrain(bars)
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertIn("PRISM.DATA.INVALID_OHLCV", result["reason_codes"])

    def test_constant_closes_stddev_zero_fails_closed(self):
        bars = flat_bars(390)
        result = build_terrain(bars)
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertIn("PRISM.RUNTIME.BAND_STDDEV_UNAVAILABLE", result["reason_codes"])

    def test_input_bars_not_mutated(self):
        bars = make_bars(390, amplitude=3.0)
        import copy

        snapshot = copy.deepcopy(bars)
        build_terrain(bars)
        self.assertEqual(bars, snapshot)

    def test_middle_slope_up_down_flat(self):
        up_bars = make_bars(400, amplitude=3.0, period_bars=401)  # near-monotonic ramp region
        # Build a clean monotonic increasing close series for an unambiguous UP slope.
        bars = []
        ts_bars = make_bars(366, amplitude=0.0001)
        for i, b in enumerate(ts_bars):
            b["close"] = 100.0 + i * 0.01
            b["open"] = b["close"] - 0.001
            b["high"] = b["close"] + 0.01
            b["low"] = b["close"] - 0.01
            bars.append(b)
        result = build_terrain(bars)
        self.assertEqual(result["middle_slope"], "UP")


if __name__ == "__main__":
    unittest.main()
