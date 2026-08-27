import json
import unittest
from pathlib import Path

from speed_phase import analyze_completed_candles


class ShortReaccelerationFixtureTests(unittest.TestCase):
    def test_short_reacceleration_confirmed(self) -> None:
        fixture_path = (
            Path.cwd()
            / "fixtures"
            / "short_reacceleration_confirmed.json"
        )

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

    def test_short_reacceleration_rejects_weak_second_reclaim(self) -> None:
        fixture_path = (
            Path.cwd()
            / "fixtures"
            / "short_reacceleration_rejects_weak_second_reclaim.json"
        )

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
