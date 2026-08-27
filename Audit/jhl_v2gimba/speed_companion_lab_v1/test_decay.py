import json
import unittest
from pathlib import Path

from speed_phase import analyze_completed_candles


class DecayFixtureTests(unittest.TestCase):
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

    def test_long_impulse_decay_watch_expired(self) -> None:
        self.assert_fixture("long_impulse_decay_watch_expired.json")

    def test_short_impulse_decay_watch_expired(self) -> None:
        self.assert_fixture("short_impulse_decay_watch_expired.json")
    def test_long_impulse_decay_structure_invalidated(self) -> None:
        self.assert_fixture(
            "long_impulse_decay_structure_invalidated.json"
        )
    def test_short_impulse_decay_structure_invalidated(self) -> None:
        self.assert_fixture(
            "short_impulse_decay_structure_invalidated.json"
        )

    def test_long_impulse_decay_pullback_depth_breached(self) -> None:
        self.assert_fixture(
            "long_impulse_decay_pullback_depth_breached.json"
        )

    def test_short_impulse_decay_pullback_depth_breached(self) -> None:
        self.assert_fixture(
            "short_impulse_decay_pullback_depth_breached.json"
        )

    def test_long_impulse_decay_pullback_volume_excessive(self) -> None:
        self.assert_fixture(
            "long_impulse_decay_pullback_volume_excessive.json"
        )

    def test_short_impulse_decay_pullback_volume_excessive(self) -> None:
        self.assert_fixture(
            "short_impulse_decay_pullback_volume_excessive.json"
        )


    def test_long_decay_precedence_structure_over_expiry(self) -> None:
        self.assert_fixture(
            "long_decay_precedence_structure_over_expiry.json"
        )

    def test_long_decay_precedence_depth_over_expiry(self) -> None:
        self.assert_fixture(
            "long_decay_precedence_depth_over_expiry.json"
        )

    def test_long_decay_precedence_volume_over_expiry(self) -> None:
        self.assert_fixture(
            "long_decay_precedence_volume_over_expiry.json"
        )
