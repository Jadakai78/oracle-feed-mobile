import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism_ledger_validator_v1 import validate_ledger  # noqa: E402

RECORD_A = {
    "recordtype": "PRISM_WIDTH_REGIME_OBSERVATION",
    "schema_version": "prism_width_regime_v1",
    "observation_id": "SOL/USD|15m|2026-01-01T00:00:00Z|PRISM_WIDTH_REGIME_V1",
    "pair": "SOL/USD",
    "timeframe": "15m",
    "reference_bar_close_utc": "2026-01-01T00:00:00Z",
    "reference_price": 100.0,
    "terrain": {"state": "AVAILABLE", "zone": "CENTRAL_ROTATION_ZONE", "middle_slope": "FLAT", "bandwidth": 3.0},
    "width": {
        "state": "AVAILABLE",
        "current_width": 3.0,
        "prior_width_count": 25,
        "width_slope": "FLAT",
        "width_percentile": 0.5,
        "regime": "WIDTH_NEUTRAL",
    },
    "horizons_bars": [1, 4, 16, 64],
    "status": "OPEN",
    "manual_review_only": True,
    "does_not_authorize_trade": True,
    "does_not_simulate_order": True,
}

RECORD_B = copy.deepcopy(RECORD_A)
RECORD_B["reference_bar_close_utc"] = "2026-01-01T00:15:00Z"
RECORD_B["observation_id"] = "SOL/USD|15m|2026-01-01T00:15:00Z|PRISM_WIDTH_REGIME_V1"

RECORD_C_WITH_GAP = copy.deepcopy(RECORD_A)
RECORD_C_WITH_GAP["reference_bar_close_utc"] = "2026-01-01T01:00:00Z"
RECORD_C_WITH_GAP["observation_id"] = "SOL/USD|15m|2026-01-01T01:00:00Z|PRISM_WIDTH_REGIME_V1"


class LedgerValidatorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.obs_path = self.tmp / "observations.jsonl"
        self.state_path = self.tmp / "state.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _write_jsonl(self, records):
        with self.obs_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record))
                handle.write("\n")

    def _write_state(self, observation_ids, outcome_ids=None):
        self.state_path.write_text(
            json.dumps(
                {
                    "schema_version": "prism_width_regime_ledger_v1",
                    "observation_ids": observation_ids,
                    "outcome_ids": outcome_ids or [],
                }
            )
        )

    def test_valid_single_record_and_matching_state_passes(self):
        self._write_jsonl([RECORD_A])
        self._write_state([RECORD_A["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertTrue(ok, issues)

    def test_valid_multiple_chronological_records_and_matching_state_passes(self):
        self._write_jsonl([RECORD_A, RECORD_B])
        self._write_state([RECORD_A["observation_id"], RECORD_B["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertTrue(ok, issues)

    def test_invalid_json_fails(self):
        self.obs_path.write_text("{not valid json\n")
        self._write_state([])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)
        self.assertTrue(any("invalid JSON" in issue for issue in issues))

    def test_duplicate_id_fails(self):
        self._write_jsonl([RECORD_A, RECORD_A])
        self._write_state([RECORD_A["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)
        self.assertTrue(any("duplicate observation_id" in issue for issue in issues))

    def test_noncanonical_id_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["observation_id"] = "WRONG_ID"
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)

    def test_missing_safety_flag_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["manual_review_only"] = False
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)

    def test_nested_forbidden_field_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["width"]["score"] = 99
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)
        self.assertTrue(any("forbidden keys" in issue for issue in issues))

    def test_wrong_state_set_fails(self):
        self._write_jsonl([RECORD_A])
        self._write_state(["SOME/OTHER|15m|2026-01-01T00:00:00Z|PRISM_WIDTH_REGIME_V1"])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)
        self.assertTrue(any("mismatch" in issue for issue in issues))

    def test_bad_timestamp_alignment_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["reference_bar_close_utc"] = "2026-01-01T00:07:00Z"
        bad["observation_id"] = f"SOL/USD|15m|2026-01-01T00:07:00Z|PRISM_WIDTH_REGIME_V1"
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)

    def test_invalid_width_percentile_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["width"]["width_percentile"] = 1.5
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)

    def test_timestamp_gap_yields_pass_with_informational_note(self):
        self._write_jsonl([RECORD_A, RECORD_C_WITH_GAP])
        self._write_state([RECORD_A["observation_id"], RECORD_C_WITH_GAP["observation_id"]])
        ok, issues, summary = validate_ledger(self.obs_path, self.state_path)
        self.assertTrue(ok, issues)
        self.assertIn("informational", summary)

    def test_observation_status_closed_fails_validator(self):
        bad = copy.deepcopy(RECORD_A)
        bad["status"] = "CLOSED"
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)

    def test_nan_reference_price_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["reference_price"] = float("nan")
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)

    def test_infinite_current_width_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["width"]["current_width"] = float("inf")
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)

    def test_infinite_terrain_bandwidth_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["terrain"]["bandwidth"] = float("inf")
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)

    def test_missing_nested_terrain_key_fails(self):
        bad = copy.deepcopy(RECORD_A)
        del bad["terrain"]["zone"]
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)
        self.assertTrue(any("terrain missing keys" in issue for issue in issues))

    def test_missing_nested_width_key_fails(self):
        bad = copy.deepcopy(RECORD_A)
        del bad["width"]["regime"]
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)
        self.assertTrue(any("width missing keys" in issue for issue in issues))

    def test_invalid_zone_label_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["terrain"]["zone"] = "MADE_UP_ZONE"
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)

    def test_invalid_middle_slope_label_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["terrain"]["middle_slope"] = "SIDEWAYS"
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)

    def test_invalid_width_slope_label_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["width"]["width_slope"] = "SIDEWAYS"
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)

    def test_invalid_regime_label_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["width"]["regime"] = "WIDTH_BULLISH"
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)

    def test_width_unavailable_contradiction_fails(self):
        bad = copy.deepcopy(RECORD_A)
        bad["width"]["regime"] = "WIDTH_UNAVAILABLE"
        self._write_jsonl([bad])
        self._write_state([bad["observation_id"]])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)
        self.assertTrue(any("contradiction" in issue for issue in issues))

    def test_missing_state_file_fails(self):
        self._write_jsonl([RECORD_A])
        # Deliberately do not write self.state_path.
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)
        self.assertTrue(any("state file not found" in issue for issue in issues))

    def test_corrupt_state_file_fails(self):
        self._write_jsonl([RECORD_A])
        self.state_path.write_text("{not valid json")
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)
        self.assertTrue(any("corrupt or unreadable" in issue for issue in issues))

    def test_ledger_recovery_scenario_jsonl_row_without_state_entry_fails(self):
        # A JSONL row exists (e.g. from an append whose atomic state replace
        # failed) but state.observation_ids does not yet include it. The
        # validator must surface this as an explicit set-mismatch failure
        # rather than silently passing.
        self._write_jsonl([RECORD_A])
        self._write_state([])
        ok, issues, _summary = validate_ledger(self.obs_path, self.state_path)
        self.assertFalse(ok)
        self.assertTrue(any("mismatch" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
