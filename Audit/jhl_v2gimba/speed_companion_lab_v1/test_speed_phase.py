

import json
import sys
import unittest
from pathlib import Path


LAB_DIR = Path.cwd()
sys.path.insert(0, str(LAB_DIR))

from speed_phase import analyze_completed_candles


class SpeedPhaseFixtureTests(unittest.TestCase):
    def assert_fixture(self, filename: str) -> None:
        fixture_path = LAB_DIR / "fixtures" / filename

        with fixture_path.open(encoding="utf-8") as handle:
            fixture = json.load(handle)

        actual = analyze_completed_candles(fixture["candles"])

        for field, expected_value in fixture["expected"].items():
            self.assertEqual(
                actual[field],
                expected_value,
                msg=(
                    f"{fixture['name']} expected "
                    f"{field}={expected_value!r}, got {actual[field]!r}"
                ),
            )

    def test_long_impulse_watch(self) -> None:
        self.assert_fixture("long_impulse_watch.json")

    def test_long_controlled_pullback(self) -> None:
        self.assert_fixture("long_controlled_pullback.json")

    def test_long_reacceleration_confirmed(self) -> None:
        self.assert_fixture("long_reacceleration_confirmed.json")

    def test_long_reacceleration_rejects_weak_second_reclaim(self) -> None:
        self.assert_fixture(
            "long_reacceleration_rejects_weak_second_reclaim.json"
        )




