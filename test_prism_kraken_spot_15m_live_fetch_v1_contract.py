from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from prism_kraken_spot_15m_live_fetch_v1 import (
    fetch_kraken_spot_15m_raw,
)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return False


class PrismKrakenSpot15mLiveFetchV1ContractTests(unittest.TestCase):
    def test_request_uses_audit_resolved_pair_and_native_15m_interval(self):
        payload = {
            "error": [],
            "result": {
                "SOLUSD": [
                    [1735689600, "100", "101", "99", "100.5", "100.2", "12", 10],
                ],
                "last": 1735690500,
            },
        }

        with patch(
            "prism_kraken_spot_15m_live_fetch_v1.urllib.request.urlopen",
            return_value=FakeResponse(payload),
        ) as mocked:
            candle_key, candles = fetch_kraken_spot_15m_raw("SOLUSD")

        self.assertEqual(candle_key, "SOLUSD")
        self.assertEqual(candles, payload["result"]["SOLUSD"])

        request = mocked.call_args.args[0]
        self.assertEqual(mocked.call_args.kwargs["timeout"], 20)
        self.assertIn("/0/public/OHLC?", request.full_url)
        self.assertIn("pair=SOLUSD", request.full_url)
        self.assertIn("interval=15", request.full_url)
        self.assertEqual(
            request.headers.get("User-agent"),
            "JHL-PRISM-Kraken15m/1.0",
        )

    def test_api_error_raises_runtime_error(self):
        payload = {
            "error": ["EQuery:Unknown asset pair"],
            "result": {},
        }

        with patch(
            "prism_kraken_spot_15m_live_fetch_v1.urllib.request.urlopen",
            return_value=FakeResponse(payload),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "EQuery:Unknown asset pair",
            ):
                fetch_kraken_spot_15m_raw("BADPAIR")

    def test_missing_result_object_raises_runtime_error(self):
        payload = {"error": []}

        with patch(
            "prism_kraken_spot_15m_live_fetch_v1.urllib.request.urlopen",
            return_value=FakeResponse(payload),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "no result object",
            ):
                fetch_kraken_spot_15m_raw("SOLUSD")

    def test_missing_candle_series_raises_runtime_error(self):
        payload = {
            "error": [],
            "result": {"last": 1735690500},
        }

        with patch(
            "prism_kraken_spot_15m_live_fetch_v1.urllib.request.urlopen",
            return_value=FakeResponse(payload),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "no OHLC series",
            ):
                fetch_kraken_spot_15m_raw("SOLUSD")

    def test_non_list_candle_series_raises_runtime_error(self):
        payload = {
            "error": [],
            "result": {
                "SOLUSD": {"not": "a list"},
                "last": 1735690500,
            },
        }

        with patch(
            "prism_kraken_spot_15m_live_fetch_v1.urllib.request.urlopen",
            return_value=FakeResponse(payload),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "OHLC series is not a list",
            ):
                fetch_kraken_spot_15m_raw("SOLUSD")

    def test_invalid_pair_input_raises_value_error_before_network(self):
        with patch(
            "prism_kraken_spot_15m_live_fetch_v1.urllib.request.urlopen",
        ) as mocked:
            with self.assertRaises(ValueError):
                fetch_kraken_spot_15m_raw("")

        mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
