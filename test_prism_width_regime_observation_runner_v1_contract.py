from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prism_width_regime_observation_runner_v1 import (
    run_observation_cycle,
)
from test_prism_kraken_spot_15m_adapter_v1_contract import (
    REQUIRED_BARS,
    raw_candles,
)


class PrismWidthRegimeObservationRunnerV1ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

        self.audit_path = self.root / "symbol_audit.json"
        self.observations_path = self.root / "observations.jsonl"
        self.state_path = self.root / "state.json"

        self.audit_path.write_text(
            json.dumps(
                {
                    "recordtype": "KRAKENSPOTCONTEXTSYMBOLAUDIT",
                    "rows": [
                        {
                            "context_pair": "SOL/USD",
                            "resolution_state": "RESOLVED",
                            "api_pair_key": "SOLUSD",
                            "kraken_altname": "SOLUSD",
                            "kraken_wsname": "SOL/USD",
                        },
                        {
                            "context_pair": "AAVE/USD",
                            "resolution_state": "UNRESOLVED",
                            "api_pair_key": None,
                            "kraken_altname": None,
                            "kraken_wsname": None,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def fetch_success(self, api_pair: str) -> tuple[str, list[list[str]]]:
        self.assertEqual(api_pair, "SOLUSD")
        return "SOLUSD", raw_candles(REQUIRED_BARS)

    def test_eligible_pair_builds_and_appends_one_observation(self):
        result = run_observation_cycle(
            "SOL/USD",
            audit_path=self.audit_path,
            observations_path=self.observations_path,
            state_path=self.state_path,
            fetch_raw_candles=self.fetch_success,
            fetched_at_utc="2026-08-31T04:18:00Z",
        )

        self.assertEqual(result["pair"], "SOL/USD")
        self.assertEqual(result["fetch_state"], "AVAILABLE")
        self.assertIsNotNone(result["observation_id"])
        self.assertEqual(result["ledger_status"], "APPENDED")
        self.assertTrue(self.observations_path.exists())
        self.assertTrue(self.state_path.exists())

        rows = [
            json.loads(line)
            for line in self.observations_path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pair"], "SOL/USD")
        self.assertEqual(
            rows[0]["recordtype"],
            "PRISMWIDTHREGIMEOBSERVATION",
        )
        self.assertTrue(rows[0]["manual_review_only"])
        self.assertTrue(rows[0]["does_not_authorize_trade"])
        self.assertTrue(rows[0]["does_not_simulate_order"])

    def test_replay_is_deduplicated_without_second_row(self):
        first = run_observation_cycle(
            "SOL/USD",
            audit_path=self.audit_path,
            observations_path=self.observations_path,
            state_path=self.state_path,
            fetch_raw_candles=self.fetch_success,
            fetched_at_utc="2026-08-31T04:18:00Z",
        )
        second = run_observation_cycle(
            "SOL/USD",
            audit_path=self.audit_path,
            observations_path=self.observations_path,
            state_path=self.state_path,
            fetch_raw_candles=self.fetch_success,
            fetched_at_utc="2026-08-31T04:19:00Z",
        )

        self.assertEqual(first["ledger_status"], "APPENDED")
        self.assertEqual(second["ledger_status"], "DUPLICATE")
        self.assertEqual(
            first["observation_id"],
            second["observation_id"],
        )

        rows = [
            json.loads(line)
            for line in self.observations_path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

        self.assertEqual(len(rows), 1)

    def test_dry_run_builds_observation_but_writes_nothing(self):
        result = run_observation_cycle(
            "SOL/USD",
            audit_path=self.audit_path,
            observations_path=self.observations_path,
            state_path=self.state_path,
            fetch_raw_candles=self.fetch_success,
            fetched_at_utc="2026-08-31T04:18:00Z",
            dry_run=True,
        )

        self.assertEqual(result["fetch_state"], "AVAILABLE")
        self.assertIsNotNone(result["observation_id"])
        self.assertEqual(result["ledger_status"], "DRY_RUN")
        self.assertFalse(self.observations_path.exists())
        self.assertFalse(self.state_path.exists())

    def test_unavailable_fetch_does_not_create_observation_or_write(self):
        def failed_fetch(api_pair: str) -> tuple[str, list[list[str]]]:
            raise TimeoutError("simulated timeout")

        result = run_observation_cycle(
            "SOL/USD",
            audit_path=self.audit_path,
            observations_path=self.observations_path,
            state_path=self.state_path,
            fetch_raw_candles=failed_fetch,
            fetched_at_utc="2026-08-31T04:18:00Z",
        )

        self.assertEqual(result["fetch_state"], "UNAVAILABLE")
        self.assertEqual(result["fetch_reason"], "fetch_error:TimeoutError")
        self.assertIsNone(result["observation_id"])
        self.assertEqual(result["ledger_status"], "NO_OBSERVATION")
        self.assertFalse(self.observations_path.exists())
        self.assertFalse(self.state_path.exists())

    def test_unresolved_pair_does_not_fetch_or_write(self):
        calls: list[str] = []

        def should_not_fetch(api_pair: str) -> tuple[str, list[list[str]]]:
            calls.append(api_pair)
            raise AssertionError("Unresolved pair must not fetch.")

        result = run_observation_cycle(
            "AAVE/USD",
            audit_path=self.audit_path,
            observations_path=self.observations_path,
            state_path=self.state_path,
            fetch_raw_candles=should_not_fetch,
            fetched_at_utc="2026-08-31T04:18:00Z",
        )

        self.assertEqual(result["fetch_state"], "UNAVAILABLE")
        self.assertEqual(
            result["fetch_reason"],
            "pair_not_resolved_in_audit",
        )
        self.assertIsNone(result["observation_id"])
        self.assertEqual(result["ledger_status"], "NO_OBSERVATION")
        self.assertEqual(calls, [])
        self.assertFalse(self.observations_path.exists())
        self.assertFalse(self.state_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
