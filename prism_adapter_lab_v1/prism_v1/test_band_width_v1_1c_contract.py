from __future__ import annotations

import importlib.util
import math
import statistics
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ANALYZER_PATH = ROOT / "analyzer_v1.py"

spec = importlib.util.spec_from_file_location("analyzer_v1", ANALYZER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load analyzer: {ANALYZER_PATH}")

ANALYZER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ANALYZER)

from band_width_v1_1c import build_band_width_from_bars
from test_band_terrain_v1_1 import load_fixture


WINDOW_SIZE = 365
FULL_HISTORY_COUNT = 25
FORBIDDEN_KEYS = {
    "route",
    "rank",
    "score",
    "signal",
    "direction",
    "execution_eligible",
}


def fixture_bars(fixture_id: str = "PRISM-001") -> tuple[list[dict], str]:
    fixture = load_fixture(fixture_id)
    return fixture["bars"], fixture["timeframe"]


def expected_width(bars: list[dict]) -> float:
    closes = [float(bar["close"]) for bar in bars]

    if len(closes) != WINDOW_SIZE:
        raise ValueError(f"Expected {WINDOW_SIZE} closes, got {len(closes)}")

    return 6.0 * statistics.pstdev(closes)


def expected_prior_widths(bars: list[dict]) -> list[float]:
    if len(bars) < WINDOW_SIZE:
        return []

    current_start = len(bars) - WINDOW_SIZE
    widths: list[float] = []

    for start in range(current_start):
        window = bars[start : start + WINDOW_SIZE]
        widths.append(expected_width(window))

    return widths[-FULL_HISTORY_COUNT:]


class BandWidthV11CContractTests(unittest.TestCase):
    def assert_close(self, actual: float, expected: float) -> None:
        self.assertTrue(
            math.isclose(
                actual,
                expected,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ),
            msg=f"{actual!r} != {expected!r}",
        )

    def assert_safe_metadata(self, result: dict) -> None:
        self.assertTrue(result["manual_review_only"])
        self.assertFalse(result["trade_authority"])
        self.assertFalse(result["entry_authority"])

        for key in FORBIDDEN_KEYS:
            self.assertNotIn(key, result)

    def test_390_bars_produces_current_width_and_25_prior_widths(self):
        bars, timeframe = fixture_bars()
        self.assertGreaterEqual(len(bars), 390)

        sample = bars[-390:]
        result = build_band_width_from_bars(sample, timeframe)

        self.assertEqual(result["state"], "AVAILABLE")
        self.assertEqual(result["history_state"], "AVAILABLE")
        self.assertIsInstance(result["current_width"], float)
        self.assertEqual(result["prior_width_count"], FULL_HISTORY_COUNT)
        self.assertEqual(len(result["prior_widths"]), FULL_HISTORY_COUNT)
        self.assertIn(result["width_slope"], {"UP", "DOWN", "FLAT"})
        self.assert_safe_metadata(result)

    def test_390_bar_widths_match_independent_rolling_pstdev_calculation(self):
        bars, timeframe = fixture_bars()
        sample = bars[-390:]

        result = build_band_width_from_bars(sample, timeframe)

        expected_current = expected_width(sample[-WINDOW_SIZE:])
        expected_prior = expected_prior_widths(sample)

        self.assert_close(result["current_width"], expected_current)
        self.assertEqual(len(result["prior_widths"]), len(expected_prior))

        for actual, expected in zip(result["prior_widths"], expected_prior):
            self.assert_close(actual, expected)

    def test_current_width_is_excluded_from_prior_width_history(self):
        bars, timeframe = fixture_bars()
        sample = bars[-390:]

        result = build_band_width_from_bars(sample, timeframe)
        expected_prior = expected_prior_widths(sample)
        current_window = sample[-WINDOW_SIZE:]
        last_prior_window = sample[-WINDOW_SIZE - 1 : -1]

        self.assertEqual(len(result["prior_widths"]), FULL_HISTORY_COUNT)
        self.assertEqual(len(expected_prior), FULL_HISTORY_COUNT)
        self.assertNotEqual(current_window, last_prior_window)

        for actual, expected in zip(result["prior_widths"], expected_prior):
            self.assert_close(actual, expected)

        self.assert_close(
            result["prior_widths"][-1],
            expected_width(last_prior_window),
        )

    def test_current_width_matches_supplied_available_terrain_bandwidth(self):
        bars, timeframe = fixture_bars()
        sample = bars[-390:]

        terrain = ANALYZER.build_band_terrain(sample, timeframe)
        self.assertEqual(terrain["state"], "AVAILABLE")

        result = build_band_width_from_bars(sample, timeframe, terrain)

        self.assertEqual(result["state"], "AVAILABLE")
        self.assertIs(result["terrain_width_match"], True)
        self.assert_close(result["current_width"], float(terrain["bandwidth"]))

    def test_exactly_365_bars_is_partial_with_current_width_only(self):
        bars, timeframe = fixture_bars()
        sample = bars[-WINDOW_SIZE:]

        result = build_band_width_from_bars(sample, timeframe)

        self.assertEqual(result["state"], "PARTIAL")
        self.assertEqual(result["history_state"], "PARTIAL")
        self.assertIsInstance(result["current_width"], float)
        self.assertEqual(result["prior_widths"], [])
        self.assertEqual(result["prior_width_count"], 0)
        self.assertEqual(result["width_slope"], "UNAVAILABLE")
        self.assert_safe_metadata(result)

    def test_366_to_389_bars_is_partial_with_available_prior_windows(self):
        bars, timeframe = fixture_bars()

        for count in (366, 377, 389):
            with self.subTest(bar_count=count):
                sample = bars[-count:]
                result = build_band_width_from_bars(sample, timeframe)

                self.assertEqual(result["state"], "PARTIAL")
                self.assertEqual(result["history_state"], "PARTIAL")
                self.assertIsInstance(result["current_width"], float)
                self.assertEqual(
                    result["prior_width_count"],
                    count - WINDOW_SIZE,
                )
                self.assertEqual(
                    len(result["prior_widths"]),
                    count - WINDOW_SIZE,
                )
                self.assertEqual(result["width_slope"], "UNAVAILABLE")
                self.assert_safe_metadata(result)

    def test_fewer_than_365_bars_fails_closed(self):
        bars, timeframe = fixture_bars()
        sample = bars[-364:]

        result = build_band_width_from_bars(sample, timeframe)

        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertIsNone(result["current_width"])
        self.assertEqual(result["prior_widths"], [])
        self.assertEqual(result["prior_width_count"], 0)
        self.assertEqual(result["history_state"], "UNAVAILABLE")
        self.assertEqual(result["width_slope"], "UNAVAILABLE")
        self.assert_safe_metadata(result)

    def test_missing_bar_fails_closed(self):
        bars, timeframe = fixture_bars()
        sample = bars[-390:]
        broken = sample[:200] + sample[201:]

        result = build_band_width_from_bars(broken, timeframe)

        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertIsNone(result["current_width"])
        self.assertEqual(result["prior_widths"], [])
        self.assertEqual(result["history_state"], "UNAVAILABLE")
        self.assert_safe_metadata(result)

    def test_invalid_ohlcv_fails_closed(self):
        bars, timeframe = fixture_bars()
        sample = [dict(bar) for bar in bars[-390:]]
        sample[-1]["low"] = float(sample[-1]["high"]) + 1.0

        result = build_band_width_from_bars(sample, timeframe)

        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertIsNone(result["current_width"])
        self.assertEqual(result["prior_widths"], [])
        self.assertEqual(result["history_state"], "UNAVAILABLE")
        self.assert_safe_metadata(result)

    def test_supplied_terrain_bandwidth_mismatch_fails_closed(self):
        bars, timeframe = fixture_bars()
        sample = bars[-390:]
        terrain = dict(ANALYZER.build_band_terrain(sample, timeframe))

        self.assertEqual(terrain["state"], "AVAILABLE")
        terrain["bandwidth"] = float(terrain["bandwidth"]) + 1.0

        result = build_band_width_from_bars(sample, timeframe, terrain)

        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertFalse(result["terrain_width_match"])
        self.assertIn("mismatch", result["reason"].lower())
        self.assertIsNone(result["current_width"])
        self.assertEqual(result["prior_widths"], [])
        self.assert_safe_metadata(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
