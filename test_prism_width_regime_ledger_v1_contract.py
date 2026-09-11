from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from prism_width_regime_ledger_v1 import (
    append_closed_outcome,
    append_observation,
    load_state,
)
from prism_width_regime_observer_v1 import (
    build_prism_width_regime_observation,
)
from prism_width_regime_outcome_resolver_v1 import (
    resolve_prism_width_regime_outcome,
)
from test_prism_width_regime_observer_v1_contract import PRISM_LAB
from test_band_terrain_v1_1 import load_fixture
from test_prism_width_regime_outcome_resolver_v1_contract import future_bars


def observation(pair: str = "SOL/USD") -> dict:
    fixture = load_fixture("PRISM-001")
    record = build_prism_width_regime_observation(
        pair=pair,
        bars=fixture["bars"],
        timeframe=fixture["timeframe"],
    )
    if record is None:
        raise RuntimeError("Expected valid PRISM observation.")
    return record


def outcome(record: dict) -> dict:
    resolved = resolve_prism_width_regime_outcome(
        record,
        future_bars(
            64,
            reference_timestamp=record["reference_bar_close_utc"],
            reference_price=float(record["reference_price"]),
        ),
    )
    if resolved is None:
        raise RuntimeError("Expected complete PRISM outcome.")
    return resolved


def jsonl_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class PrismWidthRegimeLedgerV1ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.observations_path = self.root / "observations.jsonl"
        self.outcomes_path = self.root / "outcomes.jsonl"
        self.state_path = self.root / "state.json"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_initial_state_is_empty_and_read_only(self):
        state = load_state(self.state_path)

        self.assertEqual(
            state,
            {
                "schema_version": "prismwidthregimeledgerv1",
                "observation_ids": [],
                "outcome_ids": [],
            },
        )
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.observations_path.exists())
        self.assertFalse(self.outcomes_path.exists())

    def test_append_observation_writes_once_and_tracks_id_in_state(self):
        record = observation()

        result = append_observation(
            record,
            observations_path=self.observations_path,
            state_path=self.state_path,
        )

        self.assertEqual(result["status"], "APPENDED")
        self.assertEqual(result["observation_id"], record["observation_id"])
        self.assertEqual(jsonl_records(self.observations_path), [record])

        state = load_state(self.state_path)
        self.assertEqual(state["observation_ids"], [record["observation_id"]])
        self.assertEqual(state["outcome_ids"], [])

    def test_observation_replay_is_idempotent(self):
        record = observation()

        first = append_observation(
            record,
            observations_path=self.observations_path,
            state_path=self.state_path,
        )
        second = append_observation(
            copy.deepcopy(record),
            observations_path=self.observations_path,
            state_path=self.state_path,
        )

        self.assertEqual(first["status"], "APPENDED")
        self.assertEqual(second["status"], "DUPLICATE")
        self.assertEqual(jsonl_records(self.observations_path), [record])

        state = load_state(self.state_path)
        self.assertEqual(state["observation_ids"], [record["observation_id"]])

    def test_observation_dry_run_writes_nothing(self):
        record = observation()

        result = append_observation(
            record,
            observations_path=self.observations_path,
            state_path=self.state_path,
            dry_run=True,
        )

        self.assertEqual(result["status"], "DRY_RUN")
        self.assertEqual(result["observation_id"], record["observation_id"])
        self.assertFalse(self.observations_path.exists())
        self.assertFalse(self.state_path.exists())

    def test_append_outcome_requires_known_observation(self):
        record = observation()
        resolved = outcome(record)

        result = append_closed_outcome(
            resolved,
            outcomes_path=self.outcomes_path,
            state_path=self.state_path,
        )

        self.assertEqual(result["status"], "UNKNOWN_OBSERVATION")
        self.assertFalse(self.outcomes_path.exists())
        self.assertFalse(self.state_path.exists())

    def test_append_closed_outcome_writes_once_after_observation(self):
        record = observation()
        resolved = outcome(record)

        append_observation(
            record,
            observations_path=self.observations_path,
            state_path=self.state_path,
        )
        result = append_closed_outcome(
            resolved,
            outcomes_path=self.outcomes_path,
            state_path=self.state_path,
        )

        self.assertEqual(result["status"], "APPENDED")
        self.assertEqual(result["observation_id"], record["observation_id"])
        self.assertEqual(jsonl_records(self.outcomes_path), [resolved])

        state = load_state(self.state_path)
        self.assertEqual(state["observation_ids"], [record["observation_id"]])
        self.assertEqual(state["outcome_ids"], [record["observation_id"]])

    def test_outcome_replay_is_idempotent(self):
        record = observation()
        resolved = outcome(record)

        append_observation(
            record,
            observations_path=self.observations_path,
            state_path=self.state_path,
        )
        first = append_closed_outcome(
            resolved,
            outcomes_path=self.outcomes_path,
            state_path=self.state_path,
        )
        second = append_closed_outcome(
            copy.deepcopy(resolved),
            outcomes_path=self.outcomes_path,
            state_path=self.state_path,
        )

        self.assertEqual(first["status"], "APPENDED")
        self.assertEqual(second["status"], "DUPLICATE")
        self.assertEqual(jsonl_records(self.outcomes_path), [resolved])

        state = load_state(self.state_path)
        self.assertEqual(state["outcome_ids"], [record["observation_id"]])

    def test_outcome_dry_run_writes_nothing(self):
        record = observation()
        resolved = outcome(record)

        append_observation(
            record,
            observations_path=self.observations_path,
            state_path=self.state_path,
        )

        before_state = copy.deepcopy(load_state(self.state_path))
        result = append_closed_outcome(
            resolved,
            outcomes_path=self.outcomes_path,
            state_path=self.state_path,
            dry_run=True,
        )

        self.assertEqual(result["status"], "DRY_RUN")
        self.assertEqual(result["observation_id"], record["observation_id"])
        self.assertFalse(self.outcomes_path.exists())
        self.assertEqual(load_state(self.state_path), before_state)

    def test_invalid_record_is_rejected_without_writing(self):
        record = observation()
        invalid = copy.deepcopy(record)
        invalid["recordtype"] = "WRONG"

        result = append_observation(
            invalid,
            observations_path=self.observations_path,
            state_path=self.state_path,
        )

        self.assertEqual(result["status"], "INVALID_RECORD")
        self.assertFalse(self.observations_path.exists())
        self.assertFalse(self.state_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
