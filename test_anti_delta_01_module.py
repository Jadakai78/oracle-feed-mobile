from __future__ import annotations

import copy
import unittest

from anti_delta_01_module import (
    HEALTH_AVAILABLE,
    HEALTH_INVALID_CANDLES,
    HEALTH_INVALID_DELTA_CONTEXT,
    HEALTH_MISSING_BARS,
    MIN_REQUIRED_BARS,
    STATE_ABSORPTION,
    STATE_CONTROL_FLIP,
    STATE_QUIET,
    STATE_UNAVAILABLE,
    build_anti_delta,
)


def make_candle(
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> dict:
    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def long_progress_candles(
    count: int = MIN_REQUIRED_BARS,
) -> list[dict]:
    candles = []
    price = 100.0

    for _ in range(count):
        open_price = price
        high = price + 1.00
        low = price - 0.20
        close = price + 0.75

        candles.append(
            make_candle(
                open_price,
                high,
                low,
                close,
                1000.0,
            )
        )

        price = close

    return candles


def short_progress_candles(
    count: int = MIN_REQUIRED_BARS,
) -> list[dict]:
    candles = []
    price = 100.0

    for _ in range(count):
        open_price = price
        high = price + 0.20
        low = price - 1.00
        close = price - 0.75

        candles.append(
            make_candle(
                open_price,
                high,
                low,
                close,
                1000.0,
            )
        )

        price = close

    return candles


def high_volume_absorption_candles() -> list[dict]:
    candles = long_progress_candles()
    prior_close = candles[-2]["close"]

    candles[-1] = make_candle(
        prior_close,
        prior_close + 1.00,
        prior_close - 0.20,
        prior_close - 0.05,
        1800.0,
    )

    return candles


def control_flip_candles() -> list[dict]:
    candles = long_progress_candles()
    price = candles[-7]["close"]

    for index in range(6):
        open_price = price
        high = price + 0.15
        low = price - 1.50
        close = price - 1.20
        price = close

        candles[-6 + index] = make_candle(
            open_price,
            high,
            low,
            close,
            1600.0,
        )

    return candles


def delta_context(
    pressure_state: str,
    participation: str = "NORMAL",
    tempo: str = "BALANCED",
) -> dict:
    return {
        "pressure": {
            "state": pressure_state,
            "balance": (
                0.40
                if pressure_state == "BUYER_FAVORING"
                else -0.40
                if pressure_state == "SELLER_FAVORING"
                else 0.0
            ),
        },
        "participation": {
            "state": participation,
        },
        "tempo": {
            "state": tempo,
        },
    }


class AntiDelta01Tests(unittest.TestCase):
    def test_quiet_when_long_delta_produces_progress(self):
        result = build_anti_delta(
            pair="BTCUSD",
            candles=long_progress_candles(),
            delta_context=delta_context("BUYER_FAVORING"),
        )

        self.assertEqual(
            result["data_health"]["state"],
            HEALTH_AVAILABLE,
        )

        self.assertEqual(
            result["anti_delta"]["state"],
            STATE_QUIET,
        )

        self.assertEqual(
            result["anti_delta"]["direction"],
            "LONG",
        )

    def test_quiet_when_short_delta_produces_progress(self):
        result = build_anti_delta(
            pair="ETHUSD",
            candles=short_progress_candles(),
            delta_context=delta_context("SELLER_FAVORING"),
        )

        self.assertEqual(
            result["anti_delta"]["state"],
            STATE_QUIET,
        )

        self.assertEqual(
            result["anti_delta"]["direction"],
            "SHORT",
        )

    def test_absorption_on_high_volume_bad_close(self):
        result = build_anti_delta(
            pair="SOLUSD",
            candles=high_volume_absorption_candles(),
            delta_context=delta_context(
                "BUYER_FAVORING",
                participation="EXPANDING",
            ),
        )

        self.assertEqual(
            result["anti_delta"]["state"],
            STATE_ABSORPTION,
        )

        self.assertEqual(
            result["anti_delta"]["direction"],
            "NONE",
        )

    def test_control_flip_when_recent_bars_reverse_long_delta(self):
        result = build_anti_delta(
            pair="XRPUSD",
            candles=control_flip_candles(),
            delta_context=delta_context(
                "BUYER_FAVORING",
                participation="EXPANDING",
                tempo="EXPANDING",
            ),
        )

        self.assertEqual(
            result["anti_delta"]["state"],
            STATE_CONTROL_FLIP,
        )

        self.assertEqual(
            result["anti_delta"]["direction"],
            "SHORT",
        )

    def test_balanced_delta_is_unresolved(self):
        result = build_anti_delta(
            pair="ADAUSD",
            candles=long_progress_candles(),
            delta_context=delta_context("BALANCED"),
        )

        self.assertEqual(
            result["anti_delta"]["state"],
            "UNRESOLVED",
        )

    def test_missing_bars_fails_closed(self):
        result = build_anti_delta(
            pair="NEARUSD",
            candles=long_progress_candles(
                count=MIN_REQUIRED_BARS - 1
            ),
            delta_context=delta_context("BUYER_FAVORING"),
        )

        self.assertEqual(
            result["data_health"]["state"],
            HEALTH_MISSING_BARS,
        )

        self.assertEqual(
            result["anti_delta"]["state"],
            STATE_UNAVAILABLE,
        )

    def test_invalid_candle_fails_closed(self):
        candles = long_progress_candles()
        candles[-1]["low"] = candles[-1]["high"] + 1.0

        result = build_anti_delta(
            pair="SUIUSD",
            candles=candles,
            delta_context=delta_context("BUYER_FAVORING"),
        )

        self.assertEqual(
            result["data_health"]["state"],
            HEALTH_INVALID_CANDLES,
        )

        self.assertEqual(
            result["anti_delta"]["state"],
            STATE_UNAVAILABLE,
        )

    def test_invalid_delta_context_fails_closed(self):
        result = build_anti_delta(
            pair="AVAXUSD",
            candles=long_progress_candles(),
            delta_context={
                "pressure": {
                    "state": "NOT_VALID"
                }
            },
        )

        self.assertEqual(
            result["data_health"]["state"],
            HEALTH_INVALID_DELTA_CONTEXT,
        )

        self.assertEqual(
            result["anti_delta"]["state"],
            STATE_UNAVAILABLE,
        )

    def test_same_inputs_are_deterministic(self):
        candles = short_progress_candles()
        context = delta_context("SELLER_FAVORING")

        first = build_anti_delta(
            pair="LINKUSD",
            candles=candles,
            delta_context=context,
        )

        second = build_anti_delta(
            pair="LINKUSD",
            candles=copy.deepcopy(candles),
            delta_context=copy.deepcopy(context),
        )

        self.assertEqual(
            first["anti_delta"],
            second["anti_delta"],
        )

        self.assertEqual(
            first["response"],
            second["response"],
        )

    def test_module_remains_descriptive_only(self):
        result = build_anti_delta(
            pair="BCHUSD",
            candles=long_progress_candles(),
            delta_context=delta_context("BUYER_FAVORING"),
        )

        self.assertTrue(result["manual_review_only"])
        self.assertFalse(result["trade_authority"])
        self.assertFalse(result["entry_authority"])
        self.assertTrue(result["does_not_send_alerts"])
        self.assertTrue(result["does_not_change_queue"])


if __name__ == "__main__":
    unittest.main(verbosity=2)