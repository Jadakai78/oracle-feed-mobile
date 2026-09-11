import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism_ledger_v1 import append_closed_outcome, append_observation, load_state  # noqa: E402

VALID_OBSERVATION = {
    "recordtype": "PRISM_WIDTH_REGIME_OBSERVATION",
    "schema_version": "prism_width_regime_v1",
    "observation_id": "SOL/USD|15m|2026-01-01T00:00:00Z|PRISM_WIDTH_REGIME_V1",
    "pair": "SOL/USD",
    "status": "OPEN",
}

VALID_OUTCOME = {
    "recordtype": "PRISM_WIDTH_REGIME_OUTCOME",
    "schema_version": "prism_width_regime_v1",
    "observation_id": VALID_OBSERVATION["observation_id"],
    "status": "CLOSED",
}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.obs_path = self.tmp / "observations.jsonl"
        self.outcomes_path = self.tmp / "outcomes.jsonl"
        self.state_path = self.tmp / "state.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_state_load_does_not_create_file(self):
        state = load_state(self.state_path)
        self.assertEqual(state["observation_ids"], [])
        self.assertFalse(self.state_path.exists())

    def test_valid_observation_appends_once(self):
        result = append_observation(VALID_OBSERVATION, self.obs_path, self.state_path)
        self.assertEqual(result["status"], "APPENDED")
        lines = self.obs_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)

    def test_observation_replay_is_duplicate_no_second_line(self):
        append_observation(VALID_OBSERVATION, self.obs_path, self.state_path)
        result = append_observation(VALID_OBSERVATION, self.obs_path, self.state_path)
        self.assertEqual(result["status"], "DUPLICATE")
        lines = self.obs_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)

    def test_observation_dry_run_creates_no_files(self):
        result = append_observation(VALID_OBSERVATION, self.obs_path, self.state_path, dry_run=True)
        self.assertEqual(result["status"], "DRY_RUN")
        self.assertFalse(self.obs_path.exists())
        self.assertFalse(self.state_path.exists())

    def test_invalid_observation_creates_no_files(self):
        bad = {"recordtype": "WRONG", "status": "OPEN"}
        result = append_observation(bad, self.obs_path, self.state_path)
        self.assertEqual(result["status"], "INVALID_RECORD")
        self.assertFalse(self.obs_path.exists())
        self.assertFalse(self.state_path.exists())

    def test_unknown_observation_outcome_rejected_no_files_changed(self):
        result = append_closed_outcome(VALID_OUTCOME, self.outcomes_path, self.state_path)
        self.assertEqual(result["status"], "UNKNOWN_OBSERVATION")
        self.assertFalse(self.outcomes_path.exists())
        self.assertFalse(self.state_path.exists())

    def test_valid_known_closed_outcome_appends_once(self):
        append_observation(VALID_OBSERVATION, self.obs_path, self.state_path)
        result = append_closed_outcome(VALID_OUTCOME, self.outcomes_path, self.state_path)
        self.assertEqual(result["status"], "APPENDED")
        lines = self.outcomes_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)

    def test_outcome_replay_is_duplicate(self):
        append_observation(VALID_OBSERVATION, self.obs_path, self.state_path)
        append_closed_outcome(VALID_OUTCOME, self.outcomes_path, self.state_path)
        result = append_closed_outcome(VALID_OUTCOME, self.outcomes_path, self.state_path)
        self.assertEqual(result["status"], "DUPLICATE")
        lines = self.outcomes_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)

    def test_outcome_dry_run_creates_no_files_or_changes(self):
        append_observation(VALID_OBSERVATION, self.obs_path, self.state_path)
        state_before = self.state_path.read_text()
        result = append_closed_outcome(VALID_OUTCOME, self.outcomes_path, self.state_path, dry_run=True)
        self.assertEqual(result["status"], "DRY_RUN")
        self.assertFalse(self.outcomes_path.exists())
        self.assertEqual(self.state_path.read_text(), state_before)

    def test_atomic_state_reflects_ids_after_each_accepted_append(self):
        append_observation(VALID_OBSERVATION, self.obs_path, self.state_path)
        state = load_state(self.state_path)
        self.assertIn(VALID_OBSERVATION["observation_id"], state["observation_ids"])
        append_closed_outcome(VALID_OUTCOME, self.outcomes_path, self.state_path)
        state2 = load_state(self.state_path)
        self.assertIn(VALID_OUTCOME["observation_id"], state2["outcome_ids"])

    def test_invalid_corrupt_state_file_fails_safely_to_empty_state(self):
        self.state_path.write_text("{not valid json")
        state = load_state(self.state_path)
        self.assertEqual(state["observation_ids"], [])
        self.assertEqual(state["outcome_ids"], [])

    def test_observation_retry_after_simulated_state_write_failure_leaves_one_row(self):
        # Simulate a crash between the JSONL append and the atomic state
        # replace: the JSONL row exists, but state was never updated.
        with self.obs_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(VALID_OBSERVATION))
            handle.write("\n")
        self.assertFalse(self.state_path.exists())

        # Retry with the same record must be detected via the JSONL scan
        # (not just state) and must not create a second row.
        result = append_observation(VALID_OBSERVATION, self.obs_path, self.state_path)
        self.assertEqual(result["status"], "DUPLICATE")
        lines = self.obs_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)

    def test_outcome_retry_after_simulated_state_write_failure_leaves_one_row(self):
        append_observation(VALID_OBSERVATION, self.obs_path, self.state_path)
        # Simulate a crash between the outcome JSONL append and the atomic
        # state replace: the outcome row exists, but state.outcome_ids was
        # never updated to include it.
        with self.outcomes_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(VALID_OUTCOME))
            handle.write("\n")
        state = load_state(self.state_path)
        self.assertNotIn(VALID_OUTCOME["observation_id"], state["outcome_ids"])

        result = append_closed_outcome(VALID_OUTCOME, self.outcomes_path, self.state_path)
        self.assertEqual(result["status"], "DUPLICATE")
        lines = self.outcomes_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)

    def test_missing_state_file_returns_empty_state(self):
        state = load_state(self.tmp / "does_not_exist.json")
        self.assertEqual(state, {"schema_version": "prism_width_regime_ledger_v1", "observation_ids": [], "outcome_ids": []})


if __name__ == "__main__":
    unittest.main()
