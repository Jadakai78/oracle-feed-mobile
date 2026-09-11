import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism_terrain_v1 import build_terrain  # noqa: E402
from prism_width_v1 import build_width_observation  # noqa: E402
from tests._helpers import flat_bars, make_bars  # noqa: E402


class WidthTests(unittest.TestCase):
    def test_390_bars_available_with_25_priors(self):
        bars = make_bars(390, amplitude=3.0)
        result = build_width_observation(bars)
        self.assertEqual(result["state"], "AVAILABLE")
        self.assertEqual(result["prior_width_count"], 25)
        self.assertEqual(len(result["prior_widths"]), 25)

    def test_current_width_uses_final_365_window(self):
        import statistics

        bars = make_bars(390, amplitude=3.0)
        result = build_width_observation(bars)
        expected = 6 * statistics.pstdev([b["close"] for b in bars][-365:])
        self.assertAlmostEqual(result["current_width"], expected, places=9)

    def test_prior_widths_exclude_current(self):
        import math
        from datetime import timedelta

        from tests._helpers import START

        # Strictly monotonic amplitude means every rolling window has a
        # distinct width, so we can prove the 25 prior widths are exactly
        # the 25 windows preceding (and excluding) the current window.
        ts = START
        bars = []
        for t in range(390):
            amp = 0.5 + (t / 389) * 8.0
            close = 100.0 + amp * math.sin(2 * math.pi * t / 20)
            bars.append(
                {
                    "timestamp": ts.isoformat().replace("+00:00", "Z"),
                    "open": close - 0.01,
                    "high": close + abs(amp) * 0.05 + 0.02,
                    "low": close - abs(amp) * 0.05 - 0.02,
                    "close": close,
                    "volume": 1000.0,
                }
            )
            ts += timedelta(minutes=15)

        result = build_width_observation(bars)
        self.assertEqual(len(result["prior_widths"]), 25)
        self.assertNotIn(result["current_width"], result["prior_widths"])
        # Strictly increasing amplitude -> strictly increasing widths, so the
        # current (final) window's width must exceed every prior width.
        self.assertGreater(result["current_width"], result["prior_widths"][-1])

    def test_current_width_agrees_with_terrain_bandwidth(self):
        bars = make_bars(390, amplitude=3.0)
        terrain = build_terrain(bars)
        result = build_width_observation(bars, terrain=terrain)
        self.assertEqual(result["state"], "AVAILABLE")
        self.assertAlmostEqual(result["current_width"], terrain["bandwidth"], places=9)

    def test_exactly_365_bars_partial_no_slope_no_percentile(self):
        bars = make_bars(365, amplitude=3.0)
        result = build_width_observation(bars)
        self.assertEqual(result["state"], "PARTIAL")
        self.assertEqual(result["prior_widths"], [])
        self.assertEqual(result["width_slope"], "UNAVAILABLE")
        self.assertIsNone(result["width_percentile"])

    def test_366_bars_partial_with_one_prior_width(self):
        bars = make_bars(366, amplitude=3.0)
        result = build_width_observation(bars)
        self.assertEqual(result["state"], "PARTIAL")
        self.assertEqual(result["prior_width_count"], 1)
        self.assertIsNone(result["width_percentile"])

    def test_389_bars_remains_partial(self):
        bars = make_bars(389, amplitude=3.0)
        result = build_width_observation(bars)
        self.assertEqual(result["state"], "PARTIAL")
        self.assertEqual(result["prior_width_count"], 24)

    def test_invalid_ohlcv_fails_closed(self):
        bars = make_bars(390, amplitude=3.0)
        bars[5]["low"] = -5.0
        result = build_width_observation(bars)
        self.assertEqual(result["state"], "UNAVAILABLE")

    def test_missing_bar_fails_closed(self):
        bars = make_bars(390, amplitude=3.0, gap_at=100)
        result = build_width_observation(bars)
        self.assertEqual(result["state"], "UNAVAILABLE")

    def test_available_terrain_bandwidth_mismatch_fails_closed(self):
        bars = make_bars(390, amplitude=3.0)
        terrain = build_terrain(bars)
        bad_terrain = copy.deepcopy(terrain)
        bad_terrain["bandwidth"] = terrain["bandwidth"] + 100.0
        result = build_width_observation(bars, terrain=bad_terrain)
        self.assertEqual(result["state"], "UNAVAILABLE")

    def test_width_slope_up(self):
        # Build a strictly increasing-amplitude series so the final window's
        # dispersion exceeds the immediately preceding window's dispersion.
        bars = []
        import math
        from datetime import timedelta

        from tests._helpers import START

        ts = START
        for t in range(390):
            amp = 0.5 + (t / 389) * 6.0
            close = 100.0 + amp * math.sin(2 * math.pi * t / 20)
            bars.append(
                {
                    "timestamp": ts.isoformat().replace("+00:00", "Z"),
                    "open": close - 0.01,
                    "high": close + abs(amp) * 0.05 + 0.02,
                    "low": close - abs(amp) * 0.05 - 0.02,
                    "close": close,
                    "volume": 1000.0,
                }
            )
            ts += timedelta(minutes=15)
        result = build_width_observation(bars)
        self.assertEqual(result["width_slope"], "UP")

    def test_width_slope_down(self):
        import math
        from datetime import timedelta

        from tests._helpers import START

        ts = START
        bars = []
        for t in range(390):
            amp = 6.5 - (t / 389) * 6.0
            close = 100.0 + amp * math.sin(2 * math.pi * t / 20)
            bars.append(
                {
                    "timestamp": ts.isoformat().replace("+00:00", "Z"),
                    "open": close - 0.01,
                    "high": close + abs(amp) * 0.05 + 0.02,
                    "low": close - abs(amp) * 0.05 - 0.02,
                    "close": close,
                    "volume": 1000.0,
                }
            )
            ts += timedelta(minutes=15)
        result = build_width_observation(bars)
        self.assertEqual(result["width_slope"], "DOWN")

    def test_width_slope_flat(self):
        # period_bars=73 divides the 365-bar window exactly (5 full cycles),
        # so every rolling window has an identical population stddev.
        bars = make_bars(390, amplitude=3.0, period_bars=73)
        result = build_width_observation(bars)
        self.assertEqual(result["width_slope"], "FLAT")
        self.assertAlmostEqual(result["current_width"], result["prior_widths"][-1], places=9)

    def test_inputs_not_mutated(self):
        bars = make_bars(390, amplitude=3.0)
        snapshot = copy.deepcopy(bars)
        build_width_observation(bars)
        self.assertEqual(bars, snapshot)


if __name__ == "__main__":
    unittest.main()
