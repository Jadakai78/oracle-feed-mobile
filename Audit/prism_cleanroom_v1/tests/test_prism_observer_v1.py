import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism_common_v1 import scan_forbidden_keys  # noqa: E402
from prism_observer_v1 import build_prism_observation  # noqa: E402
from tests._helpers import load_fixture, make_bars  # noqa: E402


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.fixture = load_fixture("prism_007_valid.json")

    def test_valid_390_bar_fixture_builds_deterministic_observation(self):
        obs = build_prism_observation(self.fixture["pair"], self.fixture["bars"])
        self.assertIsNotNone(obs)
        self.assertEqual(obs["recordtype"], "PRISM_WIDTH_REGIME_OBSERVATION")
        self.assertEqual(obs["status"], "OPEN")
        self.assertEqual(obs["pair"], "SOL/USD")

    def test_repeating_same_inputs_creates_equal_record_and_same_id(self):
        obs1 = build_prism_observation(self.fixture["pair"], self.fixture["bars"])
        obs2 = build_prism_observation(self.fixture["pair"], self.fixture["bars"])
        self.assertEqual(obs1, obs2)
        self.assertEqual(obs1["observation_id"], obs2["observation_id"])

    def test_changing_pair_changes_only_pair_dependent_fields(self):
        obs1 = build_prism_observation("SOL/USD", self.fixture["bars"])
        obs2 = build_prism_observation("BTC/USD", self.fixture["bars"])
        self.assertNotEqual(obs1["pair"], obs2["pair"])
        self.assertNotEqual(obs1["observation_id"], obs2["observation_id"])
        for key in ("terrain", "width", "reference_price", "reference_bar_close_utc", "timeframe", "horizons_bars", "status"):
            self.assertEqual(obs1[key], obs2[key])

    def test_invalid_pair_returns_none(self):
        self.assertIsNone(build_prism_observation("", self.fixture["bars"]))
        self.assertIsNone(build_prism_observation("SOLUSD", self.fixture["bars"]))
        self.assertIsNone(build_prism_observation(None, self.fixture["bars"]))

    def test_whitespace_only_pair_components_rejected(self):
        self.assertIsNone(build_prism_observation("   /USD", self.fixture["bars"]))
        self.assertIsNone(build_prism_observation("SOL/   ", self.fixture["bars"]))
        self.assertIsNone(build_prism_observation("   /   ", self.fixture["bars"]))

    def test_pair_normalized_by_stripping_whitespace(self):
        obs = build_prism_observation("  SOL / USD  ", self.fixture["bars"])
        self.assertIsNotNone(obs)
        self.assertEqual(obs["pair"], "SOL/USD")
        self.assertTrue(obs["observation_id"].startswith("SOL/USD|"))

    def test_wrong_timeframe_returns_none(self):
        self.assertIsNone(build_prism_observation("SOL/USD", self.fixture["bars"], timeframe="1h"))

    def test_insufficient_or_gapped_fixture_returns_none(self):
        insufficient = load_fixture("prism_043_insufficient_history.json")
        gapped = load_fixture("prism_044_missing_bar.json")
        self.assertIsNone(build_prism_observation(insufficient["pair"], insufficient["bars"]))
        self.assertIsNone(build_prism_observation(gapped["pair"], gapped["bars"]))

    def test_inputs_not_mutated(self):
        bars = make_bars(390, amplitude=3.0)
        snapshot = copy.deepcopy(bars)
        build_prism_observation("SOL/USD", bars)
        self.assertEqual(bars, snapshot)

    def test_recursive_forbidden_field_scan_passes(self):
        obs = build_prism_observation(self.fixture["pair"], self.fixture["bars"])
        self.assertEqual(scan_forbidden_keys(obs), [])


if __name__ == "__main__":
    unittest.main()
