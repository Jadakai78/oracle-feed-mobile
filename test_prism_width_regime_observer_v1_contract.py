from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRISM_LAB = ROOT / "prism_adapter_lab_v1" / "prism_v1"

if str(PRISM_LAB) not in sys.path:
    sys.path.insert(0, str(PRISM_LAB))

from prism_width_regime_observer_v1 import build_prism_width_regime_observation
from test_band_terrain_v1_1 import load_fixture


FORBIDDEN_KEYS = {
    "side",
    "entry",
    "stop",
    "target",
    "tp",
    "sl",
    "score",
    "rank",
    "route",
    "signal",
    "execution_eligible",
    "trade_authority",
    "entry_authority",
    "does_simulate_order",
}


class PrismWidthRegimeObserverV1ContractTests(unittest.TestCase):
    def build(self, fixture_id: str, pair: str = "TEST/USD") -> dict | None:
        fixture = load_fixture(fixture_id)
        return build_prism_width_regime_observation(
            pair=pair,
            bars=fixture["bars"],
            timeframe=fixture["timeframe"],
        )

    def assert_observation_safety(self, record: dict) -> None:
        self.assertTrue(record["manual_review_only"])
        self.assertTrue(record["does_not_authorize_trade"])
        self.assertTrue(record["does_not_simulate_order"])

        for key in FORBIDDEN_KEYS:
            self.assertNotIn(key, record)

    def test_available_390_bar_fixture_creates_frozen_observation(self):
        record = self.build("PRISM-001", pair="SOL/USD")

        self.assertIsInstance(record, dict)
        self.assertEqual(
            record["recordtype"],
            "PRISMWIDTHREGIMEOBSERVATION",
        )
        self.assertEqual(
            record["schema_version"],
            "prismwidthregimev1",
        )
        self.assertEqual(record["pair"], "SOL/USD")
        self.assertEqual(record["timeframe"], "15m")
        self.assertEqual(record["status"], "OPEN")
        self.assertEqual(record["horizons_bars"], [1, 4, 16, 64])

        self.assertEqual(
            record["observation_id"],
            (
                "SOL/USD|15m|2025-01-05T01:15:00Z|"
                "PRISM_WIDTH_REGIME_V1"
            ),
        )
        self.assertEqual(
            record["reference_bar_close_utc"],
            "2025-01-05T01:15:00Z",
        )
        self.assertAlmostEqual(
            record["reference_price"],
            100.29838551,
            places=10,
        )

        terrain = record["terrain"]
        width = record["width"]

        self.assertEqual(terrain["state"], "AVAILABLE")
        self.assertEqual(
            terrain["zone"],
            "EXTREME_UPPER_DISPLACEMENT",
        )
        self.assertEqual(terrain["middle_slope"], "UP")
        self.assertAlmostEqual(
            terrain["bandwidth"],
            0.9246362319871196,
            places=12,
        )

        self.assertEqual(width["state"], "AVAILABLE")
        self.assertEqual(width["prior_width_count"], 25)
        self.assertEqual(width["width_slope"], "DOWN")
        self.assertAlmostEqual(width["width_percentile"], 0.88, places=12)
        self.assertEqual(width["regime"], "WIDTH_ELEVATED")
        self.assert_observation_safety(record)

    def test_same_input_is_deterministic_and_input_bars_are_not_mutated(self):
        fixture = load_fixture("PRISM-007")
        original_bars = copy.deepcopy(fixture["bars"])

        first = build_prism_width_regime_observation(
            pair="ETH/USD",
            bars=fixture["bars"],
            timeframe=fixture["timeframe"],
        )
        second = build_prism_width_regime_observation(
            pair="ETH/USD",
            bars=fixture["bars"],
            timeframe=fixture["timeframe"],
        )

        self.assertEqual(first, second)
        self.assertEqual(fixture["bars"], original_bars)
        self.assertEqual(
            first["observation_id"],
            (
                "ETH/USD|15m|2025-01-05T01:15:00Z|"
                "PRISM_WIDTH_REGIME_V1"
            ),
        )
        self.assertEqual(first["width"]["regime"], "WIDTH_EXPANDING")
        self.assert_observation_safety(first)

    def test_different_pair_changes_only_pair_component_of_id(self):
        fixture = load_fixture("PRISM-001")

        sol = build_prism_width_regime_observation(
            pair="SOL/USD",
            bars=fixture["bars"],
            timeframe=fixture["timeframe"],
        )
        eth = build_prism_width_regime_observation(
            pair="ETH/USD",
            bars=fixture["bars"],
            timeframe=fixture["timeframe"],
        )

        self.assertNotEqual(sol["observation_id"], eth["observation_id"])
        self.assertEqual(sol["observation_id"].split("|")[1:], eth["observation_id"].split("|")[1:])
        self.assertEqual(sol["terrain"], eth["terrain"])
        self.assertEqual(sol["width"], eth["width"])

    def test_unavailable_terrain_returns_none_and_does_not_create_partial_record(self):
        for fixture_id in ("PRISM-043", "PRISM-044"):
            with self.subTest(fixture_id=fixture_id):
                self.assertIsNone(self.build(fixture_id))

    def test_invalid_pair_or_timeframe_returns_none(self):
        fixture = load_fixture("PRISM-001")

        self.assertIsNone(
            build_prism_width_regime_observation(
                pair="",
                bars=fixture["bars"],
                timeframe=fixture["timeframe"],
            )
        )
        self.assertIsNone(
            build_prism_width_regime_observation(
                pair="SOL/USD",
                bars=fixture["bars"],
                timeframe="5m",
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
