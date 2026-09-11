import copy
import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism_common_v1 import parse_utc, scan_forbidden_keys  # noqa: E402
from prism_observer_v1 import build_prism_observation  # noqa: E402
from prism_outcome_resolver_v1 import resolve_prism_outcome  # noqa: E402
from tests._helpers import load_fixture, make_bars  # noqa: E402


def _future_bars(reference_ts_str, count=64, amplitude=1.0):
    start = parse_utc(reference_ts_str) + timedelta(minutes=15)
    return make_bars(count, amplitude=amplitude, start=start)


class OutcomeResolverTests(unittest.TestCase):
    def setUp(self):
        fixture = load_fixture("prism_007_valid.json")
        self.observation = build_prism_observation(fixture["pair"], fixture["bars"])
        self.assertIsNotNone(self.observation)

    def test_valid_64_future_bars_resolves_all_horizons(self):
        future = _future_bars(self.observation["reference_bar_close_utc"])
        outcome = resolve_prism_outcome(self.observation, future)
        self.assertIsNotNone(outcome)
        self.assertEqual(set(outcome["samples"].keys()), {"1bar", "4bar", "16bar", "64bar"})
        self.assertEqual(outcome["status"], "CLOSED")

    def test_first_future_bar_begins_exactly_one_interval_after_reference(self):
        future = _future_bars(self.observation["reference_bar_close_utc"])
        expected_first = parse_utc(self.observation["reference_bar_close_utc"]) + timedelta(minutes=15)
        self.assertEqual(parse_utc(future[0]["timestamp"]), expected_first)
        self.assertIsNotNone(resolve_prism_outcome(self.observation, future))

    def test_fewer_than_64_bars_returns_none(self):
        future = _future_bars(self.observation["reference_bar_close_utc"], count=63)
        self.assertIsNone(resolve_prism_outcome(self.observation, future))

    def test_gap_returns_none(self):
        future = _future_bars(self.observation["reference_bar_close_utc"])
        # Introduce a gap by pushing every bar after index 10 forward.
        for i in range(11, len(future)):
            ts = parse_utc(future[i]["timestamp"]) + timedelta(minutes=15)
            future[i]["timestamp"] = ts.isoformat().replace("+00:00", "Z")
        self.assertIsNone(resolve_prism_outcome(self.observation, future))

    def test_invalid_future_ohlcv_returns_none(self):
        future = _future_bars(self.observation["reference_bar_close_utc"])
        future[3]["high"] = -1.0
        self.assertIsNone(resolve_prism_outcome(self.observation, future))

    def test_wrong_start_time_returns_none(self):
        future = _future_bars(self.observation["reference_bar_close_utc"])
        future = make_bars(64, amplitude=1.0, start=parse_utc(future[0]["timestamp"]) + timedelta(minutes=15))
        self.assertIsNone(resolve_prism_outcome(self.observation, future))

    def test_malformed_observation_returns_none(self):
        bad = copy.deepcopy(self.observation)
        bad["status"] = "CLOSED"
        future = _future_bars(self.observation["reference_bar_close_utc"])
        self.assertIsNone(resolve_prism_outcome(bad, future))

    def test_zero_reference_price_returns_none(self):
        bad = copy.deepcopy(self.observation)
        bad["reference_price"] = 0.0
        future = _future_bars(self.observation["reference_bar_close_utc"])
        self.assertIsNone(resolve_prism_outcome(bad, future))

    def test_negative_reference_price_returns_none(self):
        bad = copy.deepcopy(self.observation)
        bad["reference_price"] = -100.0
        future = _future_bars(self.observation["reference_bar_close_utc"])
        self.assertIsNone(resolve_prism_outcome(bad, future))

    def test_nan_reference_price_returns_none(self):
        bad = copy.deepcopy(self.observation)
        bad["reference_price"] = float("nan")
        future = _future_bars(self.observation["reference_bar_close_utc"])
        self.assertIsNone(resolve_prism_outcome(bad, future))

    def test_infinite_reference_price_returns_none(self):
        bad = copy.deepcopy(self.observation)
        bad["reference_price"] = float("inf")
        future = _future_bars(self.observation["reference_bar_close_utc"])
        self.assertIsNone(resolve_prism_outcome(bad, future))
        bad["reference_price"] = float("-inf")
        self.assertIsNone(resolve_prism_outcome(bad, future))

    def test_reference_anchor_included_in_extrema(self):
        # A future series entirely below the reference price must still show
        # the reference price as the ceiling of the 1-bar extrema.
        future = _future_bars(self.observation["reference_bar_close_utc"], amplitude=0.001)
        for bar in future:
            for key in ("open", "high", "low", "close"):
                bar[key] = self.observation["reference_price"] - 5.0
            bar["low"] -= 0.01
            bar["high"] += 0.01
        outcome = resolve_prism_outcome(self.observation, future)
        self.assertIsNotNone(outcome)
        one_bar = outcome["samples"]["1bar"]
        self.assertAlmostEqual(one_bar["upside_excursion_pct"], 0.0, places=6)
        self.assertLess(one_bar["downside_excursion_pct"], 0.0)

    def test_computed_metrics_match_independent_calculation(self):
        future = _future_bars(self.observation["reference_bar_close_utc"])
        outcome = resolve_prism_outcome(self.observation, future)
        p0 = self.observation["reference_price"]
        for horizon, key in ((1, "1bar"), (4, "4bar"), (16, "16bar"), (64, "64bar")):
            window = future[:horizon]
            close_h = window[-1]["close"]
            highs = [p0] + [b["high"] for b in window]
            lows = [p0] + [b["low"] for b in window]
            high_h, low_h = max(highs), min(lows)
            expected_close_return = 100.0 * ((close_h / p0) - 1.0)
            expected_range = 100.0 * ((high_h - low_h) / p0)
            expected_upside = 100.0 * ((high_h - p0) / p0)
            expected_downside = 100.0 * ((low_h - p0) / p0)
            sample = outcome["samples"][key]
            self.assertAlmostEqual(sample["close_return_pct"], expected_close_return, places=9)
            self.assertAlmostEqual(sample["realized_range_pct"], expected_range, places=9)
            self.assertAlmostEqual(sample["upside_excursion_pct"], expected_upside, places=9)
            self.assertAlmostEqual(sample["downside_excursion_pct"], expected_downside, places=9)

    def test_observation_not_mutated(self):
        snapshot = copy.deepcopy(self.observation)
        future = _future_bars(self.observation["reference_bar_close_utc"])
        resolve_prism_outcome(self.observation, future)
        self.assertEqual(self.observation, snapshot)

    def test_frozen_terrain_and_width_snapshots_copied_unchanged(self):
        future = _future_bars(self.observation["reference_bar_close_utc"])
        outcome = resolve_prism_outcome(self.observation, future)
        self.assertEqual(outcome["terrain"], self.observation["terrain"])
        self.assertEqual(outcome["width"], self.observation["width"])
        self.assertIsNot(outcome["terrain"], self.observation["terrain"])

    def test_recursive_forbidden_field_scan_passes(self):
        future = _future_bars(self.observation["reference_bar_close_utc"])
        outcome = resolve_prism_outcome(self.observation, future)
        self.assertEqual(scan_forbidden_keys(outcome), [])


if __name__ == "__main__":
    unittest.main()
