from __future__ import annotations

import copy
import importlib.util
import math
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
ANALYZER_PATH = ROOT / "analyzer_v1.py"
MANIFEST_DIR = ROOT / "manifests"

spec = importlib.util.spec_from_file_location("analyzer_v1", ANALYZER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load analyzer: {ANALYZER_PATH}")

ANALYZER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ANALYZER)

from test_band_terrain_v1_1 import load_fixture


NESTED_KEY = "band_width_v1_1c"
FORBIDDEN_ROOT_KEYS = {
    "route",
    "rank",
    "score",
    "signal",
    "direction",
    "execution_eligible",
}


def build_terrain(fixture_id: str) -> tuple[dict, list[dict], str]:
    fixture = load_fixture(fixture_id)
    bars = fixture["bars"]
    timeframe = fixture["timeframe"]
    terrain = ANALYZER._build_band_terrain_core(bars, timeframe)
    return terrain, bars, timeframe


def load_construction(fixture_id: str) -> dict:
    manifest_path = MANIFEST_DIR / f"{fixture_id}.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return manifest["expected"]["construction"]


class BandTerrainV11CIntegrationContractTests(unittest.TestCase):
    def assert_no_forbidden_root_keys(self, terrain: dict) -> None:
        for key in FORBIDDEN_ROOT_KEYS:
            self.assertNotIn(key, terrain)

    def assert_terrain_widths_agree(self, terrain: dict) -> None:
        nested = terrain[NESTED_KEY]

        self.assertEqual(terrain["state"], "AVAILABLE")
        self.assertEqual(nested["state"], "AVAILABLE")
        self.assertTrue(nested["terrain_width_match"])
        self.assertTrue(
            math.isclose(
                float(terrain["bandwidth"]),
                float(nested["current_width"]),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        )

    def test_prism_001_adds_only_namespaced_width_observation(self):
        baseline, bars, timeframe = build_terrain("PRISM-001")
        baseline = copy.deepcopy(baseline)

        integrated = ANALYZER.build_band_terrain(bars, timeframe)

        self.assertIn(NESTED_KEY, integrated)

        observed_root = dict(integrated)
        nested = observed_root.pop(NESTED_KEY)

        self.assertEqual(observed_root, baseline)
        self.assertIsInstance(nested, dict)
        self.assert_terrain_widths_agree(integrated)
        self.assert_no_forbidden_root_keys(integrated)

    def test_prism_007_adds_width_without_changing_terrain_fields(self):
        baseline, bars, timeframe = build_terrain("PRISM-007")
        baseline = copy.deepcopy(baseline)

        integrated = ANALYZER.build_band_terrain(bars, timeframe)

        self.assertIn(NESTED_KEY, integrated)

        observed_root = dict(integrated)
        observed_root.pop(NESTED_KEY)

        self.assertEqual(observed_root, baseline)
        self.assert_terrain_widths_agree(integrated)
        self.assert_no_forbidden_root_keys(integrated)

    def test_unavailable_terrain_preserves_existing_root_result(self):
        baseline, bars, timeframe = build_terrain("PRISM-043")
        baseline = copy.deepcopy(baseline)

        integrated = ANALYZER.build_band_terrain(bars, timeframe)

        self.assertIn(NESTED_KEY, integrated)

        observed_root = dict(integrated)
        nested = observed_root.pop(NESTED_KEY)

        self.assertEqual(observed_root, baseline)
        self.assertEqual(baseline["state"], "UNAVAILABLE")
        self.assertEqual(nested["state"], "UNAVAILABLE")
        self.assert_no_forbidden_root_keys(integrated)

    def test_missing_bar_terrain_preserves_existing_root_result(self):
        baseline, bars, timeframe = build_terrain("PRISM-044")
        baseline = copy.deepcopy(baseline)

        integrated = ANALYZER.build_band_terrain(bars, timeframe)

        self.assertIn(NESTED_KEY, integrated)

        observed_root = dict(integrated)
        nested = observed_root.pop(NESTED_KEY)

        self.assertEqual(observed_root, baseline)
        self.assertEqual(baseline["state"], "UNAVAILABLE")
        self.assertEqual(nested["state"], "UNAVAILABLE")
        self.assert_no_forbidden_root_keys(integrated)

    def test_arrival_and_middle_role_remain_unchanged_for_available_fixtures(self):
        for fixture_id in ("PRISM-001", "PRISM-007", "PRISM-008", "PRISM-009"):
            with self.subTest(fixture_id=fixture_id):
                fixture = load_fixture(fixture_id)
                bars = fixture["bars"]
                timeframe = fixture["timeframe"]
                construction = load_construction(fixture_id)

                baseline_terrain = ANALYZER.build_band_terrain(bars, timeframe)
                baseline_arrival = ANALYZER.classify_arrival_mode(
                    baseline_terrain,
                    construction,
                )
                baseline_middle = ANALYZER.classify_middle_role(
                    baseline_terrain,
                    baseline_arrival,
                    construction,
                )

                integrated_terrain = ANALYZER.build_band_terrain(bars, timeframe)
                integrated_arrival = ANALYZER.classify_arrival_mode(
                    integrated_terrain,
                    construction,
                )
                integrated_middle = ANALYZER.classify_middle_role(
                    integrated_terrain,
                    integrated_arrival,
                    construction,
                )

                self.assertIn(NESTED_KEY, integrated_terrain)
                self.assertEqual(integrated_arrival, baseline_arrival)
                self.assertEqual(integrated_middle, baseline_middle)
                self.assert_terrain_widths_agree(integrated_terrain)
                self.assert_no_forbidden_root_keys(integrated_terrain)


if __name__ == "__main__":
    unittest.main(verbosity=2)
