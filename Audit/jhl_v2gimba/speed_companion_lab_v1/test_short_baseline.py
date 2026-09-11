import json
import unittest
from pathlib import Path

from speed_phase import analyze_completed_candles


class ShortBaselineFixtureTests(unittest.TestCase):
    def assert_fixture(self, filename: str) -> None:
        fixture_path = Path.cwd() / "fixtures" / filename

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

    def test_short_impulse_watch(self) -> None:
        self.assert_fixture("short_impulse_watch.json")

    def test_short_controlled_pullback(self) -> None:
        self.assert_fixture("short_controlled_pullback.json")
