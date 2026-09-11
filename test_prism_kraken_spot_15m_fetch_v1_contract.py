from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prism_kraken_spot_15m_fetch_v1 import (
    fetch_prism_kraken_spot_15m,
)
from test_prism_kraken_spot_15m_adapter_v1_contract import (
    REQUIRED_BARS,
    raw_candles,
)


class PrismKrakenSpot15mFetchV1ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.audit_path = self.root / "symbol_audit.json"

        self.audit = {
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

        self.audit_path.write_text(
            json.dumps(self.audit),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def fetch_success(self, api_pair: str) -> tuple[str, list[list[str]]]:
        self.assertEqual(api_pair, "SOLUSD")
        return "SOLUSD", raw_candles(REQUIRED_BARS)

    def test_resolved_pair_fetches_and_returns_available_parser_payload(self):
        result = fetch_prism_kraken_spot_15m(
            "SOL/USD",
            audit_path=self.audit_path,
            fetch_raw_candles=self.fetch_success,
            fetched_at_utc="2026-08-31T04:12:00Z",
        )

        self.assertEqual(result["state"], "AVAILABLE")
        self.assertEqual(result["reason"], None)
        self.assertEqual(result["data_venue"], "KRAKEN_SPOT")
        self.assertEqual(result["pair"], "SOL/USD")
        self.assertEqual(result["kraken_api_pair"], "SOLUSD")
        self.assertEqual(result["kraken_altname"], "SOLUSD")
        self.assertEqual(result["kraken_wsname"], "SOL/USD")
        self.assertEqual(result["completed_bar_count"], REQUIRED_BARS)
        self.assertEqual(len(result["bars"]), REQUIRED_BARS)
        self.assertEqual(result["fetched_at_utc"], "2026-08-31T04:12:00Z")

    def test_unknown_pair_returns_unavailable_without_fetch(self):
        calls: list[str] = []

        def should_not_fetch(api_pair: str) -> tuple[str, list[list[str]]]:
            calls.append(api_pair)
            raise AssertionError("Unknown pair must not fetch.")

        result = fetch_prism_kraken_spot_15m(
            "ETH/USD",
            audit_path=self.audit_path,
            fetch_raw_candles=should_not_fetch,
            fetched_at_utc="2026-08-31T04:12:00Z",
        )

        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual(result["reason"], "pair_not_found_in_audit")
        self.assertEqual(result["pair"], "ETH/USD")
        self.assertEqual(calls, [])

    def test_unresolved_pair_returns_unavailable_without_fetch(self):
        calls: list[str] = []

        def should_not_fetch(api_pair: str) -> tuple[str, list[list[str]]]:
            calls.append(api_pair)
            raise AssertionError("Unresolved pair must not fetch.")

        result = fetch_prism_kraken_spot_15m(
            "AAVE/USD",
            audit_path=self.audit_path,
            fetch_raw_candles=should_not_fetch,
            fetched_at_utc="2026-08-31T04:12:00Z",
        )

        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual(result["reason"], "pair_not_resolved_in_audit")
        self.assertEqual(result["pair"], "AAVE/USD")
        self.assertEqual(calls, [])

    def test_fetch_exception_is_disclosed_as_unavailable_payload(self):
        def failed_fetch(api_pair: str) -> tuple[str, list[list[str]]]:
            raise TimeoutError("simulated timeout")

        result = fetch_prism_kraken_spot_15m(
            "SOL/USD",
            audit_path=self.audit_path,
            fetch_raw_candles=failed_fetch,
            fetched_at_utc="2026-08-31T04:12:00Z",
        )

        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual(result["reason"], "fetch_error:TimeoutError")
        self.assertEqual(result["pair"], "SOL/USD")
        self.assertEqual(result["kraken_api_pair"], "SOLUSD")
        self.assertEqual(result["bars"], [])

    def test_malformed_fetch_result_is_disclosed_as_unavailable_payload(self):
        def malformed_fetch(api_pair: str) -> object:
            return {"not": "a candle tuple"}

        result = fetch_prism_kraken_spot_15m(
            "SOL/USD",
            audit_path=self.audit_path,
            fetch_raw_candles=malformed_fetch,
            fetched_at_utc="2026-08-31T04:12:00Z",
        )

        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual(result["reason"], "fetch_error:ValueError")
        self.assertEqual(result["pair"], "SOL/USD")
        self.assertEqual(result["bars"], [])

    def test_parser_rejection_is_returned_without_reclassification(self):
        def too_short_fetch(api_pair: str) -> tuple[str, list[list[str]]]:
            return "SOLUSD", raw_candles(REQUIRED_BARS - 1)

        result = fetch_prism_kraken_spot_15m(
            "SOL/USD",
            audit_path=self.audit_path,
            fetch_raw_candles=too_short_fetch,
            fetched_at_utc="2026-08-31T04:12:00Z",
        )

        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual(result["reason"], "insufficient_completed_history")
        self.assertEqual(result["completed_bar_count"], REQUIRED_BARS - 1)
        self.assertEqual(result["bars"], [])

    def test_invalid_pair_or_missing_audit_fails_closed(self):
        calls: list[str] = []

        def should_not_fetch(api_pair: str) -> tuple[str, list[list[str]]]:
            calls.append(api_pair)
            raise AssertionError("Invalid inputs must not fetch.")

        invalid_pair = fetch_prism_kraken_spot_15m(
            "",
            audit_path=self.audit_path,
            fetch_raw_candles=should_not_fetch,
            fetched_at_utc="2026-08-31T04:12:00Z",
        )
        missing_audit = fetch_prism_kraken_spot_15m(
            "SOL/USD",
            audit_path=self.root / "missing.json",
            fetch_raw_candles=should_not_fetch,
            fetched_at_utc="2026-08-31T04:12:00Z",
        )

        self.assertEqual(invalid_pair["state"], "UNAVAILABLE")
        self.assertEqual(invalid_pair["reason"], "invalid_canonical_pair")
        self.assertEqual(missing_audit["state"], "UNAVAILABLE")
        self.assertEqual(missing_audit["reason"], "audit_unavailable")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
