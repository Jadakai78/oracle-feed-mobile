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


    def test_long_boundary_depth_exact(self) -> None:
        self.assert_fixture("long_boundary_depth_exact.json")

    def test_long_boundary_depth_just_over(self) -> None:
        self.assert_fixture("long_boundary_depth_just_over.json")

    def test_short_boundary_depth_exact(self) -> None:
        self.assert_fixture("short_boundary_depth_exact.json")

    def test_short_boundary_depth_just_over(self) -> None:
        self.assert_fixture("short_boundary_depth_just_over.json")

    def test_long_boundary_volume_exact(self) -> None:
        self.assert_fixture("long_boundary_volume_exact.json")

    def test_long_boundary_volume_just_over(self) -> None:
        self.assert_fixture("long_boundary_volume_just_over.json")

    def test_short_boundary_volume_exact(self) -> None:
        self.assert_fixture("short_boundary_volume_exact.json")

    def test_short_boundary_volume_just_over(self) -> None:
        self.assert_fixture("short_boundary_volume_just_over.json")


    def test_long_structural_close_equal_low(self) -> None:
        self.assert_fixture("long_structural_close_equal_low.json")

    def test_short_structural_close_equal_high(self) -> None:
        self.assert_fixture("short_structural_close_equal_high.json")

    def test_long_watch_age_exact(self) -> None:
        self.assert_fixture("long_watch_age_exact.json")

    def test_short_watch_age_exact(self) -> None:
        self.assert_fixture("short_watch_age_exact.json")
