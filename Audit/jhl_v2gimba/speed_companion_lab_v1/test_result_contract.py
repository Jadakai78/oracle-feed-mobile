import json
import unittest
from pathlib import Path

from speed_phase import analyze_completed_candles


FIXTURES = Path("fixtures")

REQUIRED_KEYS = {
    "direction",
    "phase",
    "decay_reason",
    "impulse_age_bars",
    "impulse_size_atr",
    "pullback_bars",
    "pullback_depth_fraction",
    "pullback_volume_vs_impulse",
    "reclaim_confirmed",
}

VALID_DIRECTIONS = {"LONG", "SHORT"}
VALID_PHASES = {
    "WATCH",
    "CONTROLLED_PULLBACK",
    "REACCELERATION",
    "DECAY",
}
VALID_DECAY_REASONS = {
    "pullback_depth_breached",
    "pullback_volume_excessive",
    "structure_invalidated",
    "watch_window_expired",
}


class ResultContractTests(unittest.TestCase):
    def test_every_fixture_returns_the_full_contract(self) -> None:
        fixture_paths = sorted(FIXTURES.glob("*.json"))
        self.assertEqual(len(fixture_paths), 31)

        for path in fixture_paths:
            with self.subTest(fixture=path.name):
                fixture = json.loads(path.read_text(encoding="utf-8"))
                actual = analyze_completed_candles(fixture["candles"])

                self.assertEqual(
                    set(actual),
                    REQUIRED_KEYS,
                    f"{path.name} returned an unexpected key set",
                )

    def test_every_fixture_uses_valid_field_types_and_enums(self) -> None:
        for path in sorted(FIXTURES.glob("*.json")):
            with self.subTest(fixture=path.name):
                fixture = json.loads(path.read_text(encoding="utf-8"))
                actual = analyze_completed_candles(fixture["candles"])

                self.assertIn(actual["direction"], VALID_DIRECTIONS)
                self.assertIn(actual["phase"], VALID_PHASES)
                self.assertIsInstance(actual["impulse_age_bars"], int)
                self.assertGreaterEqual(actual["impulse_age_bars"], 0)
                self.assertIsInstance(actual["reclaim_confirmed"], bool)

                for field in (
                    "impulse_size_atr",
                    "pullback_depth_fraction",
                    "pullback_volume_vs_impulse",
                ):
                    value = actual[field]
                    self.assertTrue(
                        value is None or isinstance(value, (int, float)),
                        f"{path.name} has invalid {field}={value!r}",
                    )

                value = actual["pullback_bars"]
                self.assertTrue(
                    value is None or isinstance(value, int),
                    f"{path.name} has invalid pullback_bars={value!r}",
                )
                if value is not None:
                    self.assertGreaterEqual(value, 0)

    def test_phase_and_reason_are_consistent(self) -> None:
        for path in sorted(FIXTURES.glob("*.json")):
            with self.subTest(fixture=path.name):
                fixture = json.loads(path.read_text(encoding="utf-8"))
                actual = analyze_completed_candles(fixture["candles"])

                if actual["phase"] == "DECAY":
                    self.assertIn(
                        actual["decay_reason"],
                        VALID_DECAY_REASONS,
                    )
                    self.assertFalse(actual["reclaim_confirmed"])
                else:
                    self.assertIsNone(actual["decay_reason"])

                if actual["phase"] == "REACCELERATION":
                    self.assertTrue(actual["reclaim_confirmed"])
                else:
                    self.assertFalse(actual["reclaim_confirmed"])


if __name__ == "__main__":
    unittest.main()
