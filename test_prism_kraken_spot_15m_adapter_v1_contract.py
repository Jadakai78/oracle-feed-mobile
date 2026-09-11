from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from prism_kraken_spot_15m_adapter_v1 import (
    build_completed_15m_bars,
)


INTERVAL_SECONDS = 15 * 60
REQUIRED_BARS = 390


def iso_utc(epoch: int) -> str:
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def raw_candles(
    completed_count: int,
    *,
    start_epoch: int = 1_735_689_600,
    active_close: float = 999.0,
) -> list[list[str]]:
    rows: list[list[str]] = []

    for index in range(completed_count):
        start = start_epoch + index * INTERVAL_SECONDS
        close = 100.0 + index * 0.01

        rows.append(
            [
                str(start),
                str(close - 0.10),
                str(close + 0.25),
                str(close - 0.50),
                str(close),
                str(close),
                str(10.0 + index),
                "1",
            ]
        )

    active_start = start_epoch + completed_count * INTERVAL_SECONDS
    rows.append(
        [
            str(active_start),
            str(active_close - 0.10),
            str(active_close + 0.25),
            str(active_close - 0.50),
            str(active_close),
            str(active_close),
            "999.0",
            "1",
        ]
    )

    return rows


class PrismKrakenSpot15mAdapterV1ContractTests(unittest.TestCase):
    def build(self, candles: list[list[str]]) -> dict:
        return build_completed_15m_bars(
            canonical_pair="SOL/USD",
            kraken_api_pair="SOLUSD",
            kraken_altname="SOLUSD",
            kraken_wsname="SOL/USD",
            raw_candles=candles,
            fetched_at_utc="2026-08-31T04:07:00Z",
        )

    def test_390_completed_rows_are_available_and_final_active_row_is_discarded(self):
        payload = self.build(raw_candles(REQUIRED_BARS))

        self.assertEqual(payload["state"], "AVAILABLE")
        self.assertEqual(payload["data_venue"], "KRAKEN_SPOT")
        self.assertEqual(payload["pair"], "SOL/USD")
        self.assertEqual(payload["timeframe"], "15m")
        self.assertEqual(payload["completed_bar_count"], REQUIRED_BARS)
        self.assertEqual(len(payload["bars"]), REQUIRED_BARS)
        self.assertEqual(payload["reason"], None)

        final_bar = payload["bars"][-1]
        self.assertNotEqual(final_bar["close"], 999.0)

        expected_final_start = 1_735_689_600 + (REQUIRED_BARS - 1) * INTERVAL_SECONDS
        expected_final_end = expected_final_start + INTERVAL_SECONDS

        self.assertEqual(final_bar["timestamp"], iso_utc(expected_final_end))
        self.assertAlmostEqual(
            final_bar["close"],
            100.0 + (REQUIRED_BARS - 1) * 0.01,
            places=10,
        )

    def test_timestamp_is_close_time_and_bars_are_continuous(self):
        payload = self.build(raw_candles(REQUIRED_BARS))

        self.assertEqual(payload["state"], "AVAILABLE")

        timestamps = [
            datetime.fromisoformat(bar["timestamp"].replace("Z", "+00:00"))
            for bar in payload["bars"]
        ]

        for previous, current in zip(timestamps, timestamps[1:]):
            self.assertEqual(
                int((current - previous).total_seconds()),
                INTERVAL_SECONDS,
            )

        first_start = 1_735_689_600
        self.assertEqual(
            payload["bars"][0]["timestamp"],
            iso_utc(first_start + INTERVAL_SECONDS),
        )

    def test_fewer_than_390_completed_bars_fails_closed(self):
        payload = self.build(raw_candles(REQUIRED_BARS - 1))

        self.assertEqual(payload["state"], "UNAVAILABLE")
        self.assertEqual(payload["reason"], "insufficient_completed_history")
        self.assertEqual(payload["completed_bar_count"], REQUIRED_BARS - 1)
        self.assertEqual(payload["bars"], [])

    def test_missing_interval_fails_closed(self):
        candles = raw_candles(REQUIRED_BARS)
        del candles[100]

        payload = self.build(candles)

        self.assertEqual(payload["state"], "UNAVAILABLE")
        self.assertEqual(payload["reason"], "noncontinuous_completed_bars")
        self.assertEqual(payload["bars"], [])

    def test_invalid_ohlcv_fails_closed(self):
        candles = raw_candles(REQUIRED_BARS)
        candles[50][3] = str(float(candles[50][2]) + 1.0)

        payload = self.build(candles)

        self.assertEqual(payload["state"], "UNAVAILABLE")
        self.assertEqual(payload["reason"], "invalid_ohlcv")
        self.assertEqual(payload["bars"], [])

    def test_malformed_candle_fails_closed(self):
        candles = raw_candles(REQUIRED_BARS)
        candles[50] = ["bad"]

        payload = self.build(candles)

        self.assertEqual(payload["state"], "UNAVAILABLE")
        self.assertEqual(payload["reason"], "invalid_ohlcv")
        self.assertEqual(payload["bars"], [])

    def test_pair_metadata_is_preserved_and_fetch_time_is_disclosed(self):
        payload = self.build(raw_candles(REQUIRED_BARS))

        self.assertEqual(payload["kraken_api_pair"], "SOLUSD")
        self.assertEqual(payload["kraken_altname"], "SOLUSD")
        self.assertEqual(payload["kraken_wsname"], "SOL/USD")
        self.assertEqual(payload["fetched_at_utc"], "2026-08-31T04:07:00Z")
        self.assertTrue(payload["manual_review_only"])
        self.assertFalse(payload["trade_authority"])
        self.assertFalse(payload["entry_authority"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
