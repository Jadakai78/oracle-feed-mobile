from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
SCHEMA_PATH = ROOT / "manifest_schema.json"
MANIFEST_DIR = ROOT / "manifests"
FIXTURE_DIR = ROOT / "fixtures"
REPORT_DIR = ROOT / "reports"

EXPECTED_IDS = ["PRISM-001", "PRISM-007", "PRISM-008", "PRISM-009", "PRISM-043", "PRISM-044"]
FORBIDDEN_OUTPUT_FIELDS = {
    "score",
    "trade_instruction",
    "entry",
    "stop",
    "target",
    "position_size",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot_load_module:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


GENERATOR = load_module("prism_fixture_generator_v1", ROOT / "fixture_generator_v1.py")
ANALYZER = load_module("prism_analyzer_v1", ROOT / "analyzer_v1.py")


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def contains_forbidden_key(value) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_OUTPUT_FIELDS:
                return True
            if contains_forbidden_key(child):
                return True
    elif isinstance(value, list):
        return any(contains_forbidden_key(child) for child in value)
    return False


class PrismV1RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with SCHEMA_PATH.open(encoding="utf-8") as handle:
            cls.schema = json.load(handle)

        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )

        cls.manifest_paths = sorted(MANIFEST_DIR.glob("PRISM-*.yaml"))
        cls.fixture_paths = sorted(FIXTURE_DIR.glob("PRISM-*.ohlcv.json"))
        cls.report_paths = sorted(REPORT_DIR.glob("PRISM-*.analysis.json"))

    def test_expected_file_sets_exist(self):
        self.assertEqual(
            [path.stem for path in self.manifest_paths],
            EXPECTED_IDS,
        )
        self.assertEqual(
            [path.name.removesuffix(".ohlcv.json") for path in self.fixture_paths],
            EXPECTED_IDS,
        )
        self.assertEqual(
            [path.name.removesuffix(".analysis.json") for path in self.report_paths],
            EXPECTED_IDS,
        )

    def test_all_manifests_validate_against_schema(self):
        for path in self.manifest_paths:
            with self.subTest(manifest=path.name):
                manifest = load_yaml(path)
                errors = sorted(
                    self.validator.iter_errors(manifest),
                    key=lambda error: list(error.path),
                )
                self.assertEqual(
                    errors,
                    [],
                    "\n".join(
                        f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}"
                        for error in errors
                    ),
                )

    def test_locked_fingerprints_match_fixture_bytes(self):
        for path in self.manifest_paths:
            with self.subTest(manifest=path.name):
                manifest = load_yaml(path)
                fixture_path = FIXTURE_DIR / f"{manifest['id']}.ohlcv.json"
                actual_digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()

                self.assertEqual(
                    manifest["audit"]["expected_input_fingerprint"],
                    actual_digest,
                )
                self.assertRegex(actual_digest, r"^[a-f0-9]{64}$")

    def test_fixture_integrity_and_expected_bar_counts(self):
        for path in self.manifest_paths:
            with self.subTest(manifest=path.name):
                manifest = load_yaml(path)
                fixture = load_json(FIXTURE_DIR / f"{manifest['id']}.ohlcv.json")

                self.assertEqual(fixture["recordtype"], "PRISMOHLCVFIXTURE")
                self.assertEqual(fixture["schema_version"], "prism.ohlcv.fixture.v1")
                self.assertEqual(
                    fixture["canonicalization"],
                    "prism.ohlcv.canonical.v1",
                )
                if manifest["kind"] == "missing_bar":
                    self.assertEqual(
                        len(fixture["bars"]),
                        manifest["timing"]["completed_bars"] - 1,
                    )
                    self.assertEqual(
                        fixture["as_of_bar_index"],
                        manifest["timing"]["as_of_bar_index"],
                    )

                    timestamps = [
                        ANALYZER.parse_utc(bar["timestamp"])
                        for bar in fixture["bars"]
                    ]
                    interval = manifest["timing"]["bar_interval_seconds"]
                    gaps = [
                        int((right - left).total_seconds())
                        for left, right in zip(timestamps, timestamps[1:])
                        if int((right - left).total_seconds()) != interval
                    ]

                    self.assertEqual(gaps, [interval * 2])
                else:
                    self.assertEqual(
                        len(fixture["bars"]),
                        manifest["timing"]["completed_bars"],
                    )
                    self.assertEqual(
                        fixture["as_of_bar_index"],
                        len(fixture["bars"]) - 1,
                    )

                for index, bar in enumerate(fixture["bars"]):
                    with self.subTest(index=index):
                        open_price = float(bar["open"])
                        high_price = float(bar["high"])
                        low_price = float(bar["low"])
                        close_price = float(bar["close"])
                        volume = float(bar["volume"])

                        self.assertLessEqual(low_price, min(open_price, close_price))
                        self.assertGreaterEqual(high_price, max(open_price, close_price))
                        self.assertGreaterEqual(volume, 0.0)

    def test_generator_is_byte_deterministic_in_temporary_output(self):
        for path in self.manifest_paths:
            with self.subTest(manifest=path.name):
                manifest = load_yaml(path)
                expected_fixture_path = FIXTURE_DIR / f"{manifest['id']}.ohlcv.json"
                expected_bytes = expected_fixture_path.read_bytes()

                bars_first = GENERATOR.generate_bars(manifest)
                payload_first = GENERATOR.fixture_payload(manifest, bars_first)
                bytes_first = GENERATOR.canonical_bytes(payload_first)

                bars_second = GENERATOR.generate_bars(manifest)
                payload_second = GENERATOR.fixture_payload(manifest, bars_second)
                bytes_second = GENERATOR.canonical_bytes(payload_second)

                self.assertEqual(bytes_first, bytes_second)
                self.assertEqual(bytes_first, expected_bytes)

    def test_reports_match_declared_expected_outcomes(self):
        for path in self.manifest_paths:
            with self.subTest(manifest=path.name):
                manifest = load_yaml(path)
                report = load_json(REPORT_DIR / f"{manifest['id']}.analysis.json")
                expected = manifest["expected"]
                comparison = report["expected_comparison"]

                self.assertEqual(report["fixture_id"], manifest["id"])
                self.assertEqual(report["map_status"], expected["map_status"])
                self.assertEqual(
                    report["data_health"]["state"],
                    expected["data_health"]["state"],
                )
                self.assertTrue(comparison["map_status"]["match"])
                self.assertTrue(comparison["data_health_state"]["match"])

                if manifest["kind"] == "missing_bar":
                    self.assertEqual(report["map_status"], "unavailable")
                    self.assertIn(
                        "PRISM.DATA.MISSING_BARS",
                        report["data_health"]["reason_codes"],
                    )
                    self.assertEqual(
                        report["construction"]["current"]["label"],
                        "unavailable",
                    )
                    self.assertEqual(
                        report["construction"]["transition"]["status"],
                        "unavailable",
                    )
                    self.assertEqual(
                        report["evidence"]["PRISM.EVIDENCE.CLASSIFICATION_SKIPPED"],
                        "info",
                    )
                elif manifest["kind"] == "insufficient_history":
                    self.assertEqual(report["map_status"], "degraded")
                    self.assertIn(
                        "PRISM.DATA.INSUFFICIENT_HISTORY",
                        report["data_health"]["reason_codes"],
                    )
                    self.assertEqual(
                        report["construction"]["current"]["label"],
                        "unavailable",
                    )
                    self.assertEqual(
                        report["construction"]["transition"]["status"],
                        "unavailable",
                    )
                    self.assertEqual(
                        report["evidence"]["PRISM.EVIDENCE.CLASSIFICATION_SKIPPED"],
                        "info",
                    )
                else:
                    self.assertEqual(
                        report["construction"]["previous"]["label"],
                        expected["construction"]["previous"]["label"],
                    )
                    self.assertEqual(
                        report["construction"]["current"]["label"],
                        expected["construction"]["current"]["label"],
                    )
                    self.assertEqual(
                        report["construction"]["transition"]["status"],
                        expected["construction"]["transition"]["status"],
                    )
                    self.assertTrue(
                        comparison["construction"]["previous_label"]["match"]
                    )
                    self.assertTrue(
                        comparison["construction"]["current_label"]["match"]
                    )
                    self.assertTrue(
                        comparison["construction"]["transition_status"]["match"]
                    )
                    self.assertEqual(
                        report["evidence"]["PRISM.EVIDENCE.EXPECTED_COMPARISON"],
                        "pass",
                    )

    def test_analyzer_reports_are_read_only_and_execution_free(self):
        for path in self.report_paths:
            with self.subTest(report=path.name):
                report = load_json(path)

                self.assertTrue(report["manual_review_only"])
                self.assertFalse(report["trade_authority"])
                self.assertFalse(report["entry_authority"])
                self.assertFalse(
                    contains_forbidden_key(report),
                    f"forbidden field found in {path.name}",
                )

    def test_analyzer_recomputes_the_persisted_reports(self):
        for path in self.manifest_paths:
            with self.subTest(manifest=path.name):
                manifest = load_yaml(path)
                fixture_path = FIXTURE_DIR / f"{manifest['id']}.ohlcv.json"
                fixture = load_json(fixture_path)
                recomputed = ANALYZER.analyze(manifest, fixture, fixture_path)
                persisted = load_json(REPORT_DIR / f"{manifest['id']}.analysis.json")

                self.assertEqual(recomputed, persisted)


if __name__ == "__main__":
    unittest.main(verbosity=2)
