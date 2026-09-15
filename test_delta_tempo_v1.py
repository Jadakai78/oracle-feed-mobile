from __future__ import annotations

import copy
import unittest

from delta_tempo_v1 import (
    HEALTH_AVAILABLE,
    HEALTH_INVALID_CANDLES,
    HEALTH_INVALID_PRISM_CONTEXT,
    HEALTH_MISSING_BARS,
    MIN_REQUIRED_BARS,
    build_delta_tempo,
)


def make_candles(
    count: int = MIN_REQUIRED_BARS,
    direction: str = "UP",
    volume: float = 1000.0,
    last_volume: float | None = None,
    body_ratio: float = 0.75,
    range_size: float = 1.0,
    last_range_size: float | None = None,
) -> list[dict]:
    candles = []
    price = 100.0

    for index in range(count):
        is_last = index == count - 1
        active_volume = last_volume if is_last and last_volume is not None else volume
        active_range = (
            last_range_size
            if is_last and last_range_size is not None
            else range_size
        )

        if direction == "UP":
            open_price = price
            close_price = price + (active_range * body_ratio)
            high_price = price + active_range
            low_price = price
            price = close_price
        elif direction == "DOWN":
            open_price = price
            close_price = price - (active_range * body_ratio)
            high_price = price
            low_price = price - active_range
            price = close_price
        else:
            open_price = price
            close_price = price + (active_range * 0.05)
            high_price = price + (active_range * 0.5)
            low_price = price - (active_range * 0.5)
            price = close_price

        candles.append(
            {
                "open": round(open_price, 8),
                "high": round(high_price, 8),
                "low": round(low_price, 8),
                "close": round(close_price, 8),
                "volume": active_volume,
            }
        )

    return candles


def prism_context(
    trend_alignment: str = "LONG",
    route: str = "RECLAIM_REVERSAL",
    terrain_state: str = "PULLBACK_REACCELERATION",
) -> dict:
    return {
        "terrain": {
            "trend_alignment": trend_alignment,
            "route": route,
            "terrain_state": terrain_state,
        },
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
    }


class DeltaTempoV1Tests(unittest.TestCase):
    def test_valid_output_is_manual_review_only(self):
        candles = make_candles(
            direction="UP",
            last_volume=1500.0,
            last_range_size=1.3,
        )
        result = build_delta_tempo(
            pair="SOLUSD",
            candles=candles,
            speed_phase="REACCELERATION",
            prism_context=prism_context(),
        )

        self.assertEqual(result["recordtype"], "DELTATEMPO")
        self.assertEqual(result["schema_version"], "delta.tempo.v1")
        self.assertEqual(result["data_health"]["state"], HEALTH_AVAILABLE)

        self.assertTrue(result["manual_review_only"])
        self.assertFalse(result["trade_authority"])
        self.assertFalse(result["entry_authority"])
        self.assertTrue(result["does_not_send_alerts"])
        self.assertTrue(result["does_not_change_queue"])

        self.assertEqual(result["pressure"]["state"], "BUYER_FAVORING")
        self.assertEqual(result["participation"]["state"], "EXPANDING")
        self.assertEqual(result["tempo"]["state"], "EXPANDING")
        self.assertEqual(result["tempo"]["transition"], "CONFIRMING")
        self.assertEqual(result["prism_alignment"]["state"], "ALIGNED")

    def test_buyer_heavy_candles_produce_buyer_pressure(self):
        candles = make_candles(direction="UP")
        result = build_delta_tempo(
            pair="BTCUSD",
            candles=candles,
            speed_phase="NONE",
            prism_context=prism_context(),
        )

        self.assertEqual(result["pressure"]["state"], "BUYER_FAVORING")
        self.assertGreater(
            result["pressure"]["buyer_pressure"],
            result["pressure"]["seller_pressure"],
        )

    def test_seller_heavy_candles_produce_seller_pressure(self):
        candles = make_candles(direction="DOWN")
        result = build_delta_tempo(
            pair="ETHUSD",
            candles=candles,
            speed_phase="NONE",
            prism_context=prism_context(
                trend_alignment="SHORT",
                route="RECLAIM_REVERSAL",
            ),
        )

        self.assertEqual(result["pressure"]["state"], "SELLER_FAVORING")
        self.assertGreater(
            result["pressure"]["seller_pressure"],
            result["pressure"]["buyer_pressure"],
        )

    def test_low_participation_is_contracting(self):
        candles = make_candles(
            direction="UP",
            volume=1000.0,
            last_volume=500.0,
        )
        result = build_delta_tempo(
            pair="AVAXUSD",
            candles=candles,
            speed_phase="CONTROLLED_PULLBACK",
            prism_context=prism_context(),
        )

        self.assertEqual(result["participation"]["state"], "CONTRACTING")
        self.assertLess(
            result["participation"]["volume_expansion_ratio"],
            0.75,
        )

    def test_long_prism_and_seller_pressure_are_conflict(self):
        candles = make_candles(
            direction="DOWN",
            last_volume=1500.0,
            last_range_size=1.3,
        )
        result = build_delta_tempo(
            pair="SUIUSD",
            candles=candles,
            speed_phase="REACCELERATION",
            prism_context=prism_context(
                trend_alignment="LONG",
                route="RECLAIM_REVERSAL",
            ),
        )

        self.assertEqual(result["pressure"]["state"], "SELLER_FAVORING")
        self.assertEqual(result["prism_alignment"]["state"], "CONFLICT")

    def test_prism_no_route_remains_restricted(self):
        candles = make_candles(
            direction="UP",
            last_volume=1600.0,
            last_range_size=1.4,
        )
        result = build_delta_tempo(
            pair="DOGEUSD",
            candles=candles,
            speed_phase="REACCELERATION",
            prism_context=prism_context(
                trend_alignment="LONG",
                route="NO_ROUTE",
                terrain_state="DECAY",
            ),
        )

        self.assertEqual(result["prism_alignment"]["state"], "RESTRICTED")

    def test_missing_bars_is_explicit(self):
        candles = make_candles(count=MIN_REQUIRED_BARS - 1)
        result = build_delta_tempo(
            pair="XRPUSD",
            candles=candles,
            speed_phase="NONE",
            prism_context=prism_context(),
        )

        self.assertEqual(result["data_health"]["state"], HEALTH_MISSING_BARS)
        self.assertIn(
            "DELTA_TEMPO.DATA.MISSING_BARS",
            result["data_health"]["reason_codes"],
        )
        self.assertEqual(result["pressure"]["state"], "UNAVAILABLE")
        self.assertFalse(result["entry_authority"])

    def test_invalid_candles_fail_closed(self):
        candles = make_candles()
        candles[-1]["low"] = candles[-1]["high"] + 1.0

        result = build_delta_tempo(
            pair="ADAUSD",
            candles=candles,
            speed_phase="NONE",
            prism_context=prism_context(),
        )

        self.assertEqual(result["data_health"]["state"], HEALTH_INVALID_CANDLES)
        self.assertTrue(
            any(
                code.startswith("DELTA_TEMPO.DATA.INVALID_CANDLES:")
                for code in result["data_health"]["reason_codes"]
            )
        )
        self.assertEqual(result["pressure"]["state"], "UNAVAILABLE")
        self.assertFalse(result["trade_authority"])

    def test_invalid_prism_context_fails_closed(self):
        candles = make_candles()

        result = build_delta_tempo(
            pair="NEARUSD",
            candles=candles,
            speed_phase="NONE",
            prism_context=["not", "a", "mapping"],
        )

        self.assertEqual(
            result["data_health"]["state"],
            HEALTH_INVALID_PRISM_CONTEXT,
        )
        self.assertIn(
            "DELTA_TEMPO.PRISM.INVALID_CONTEXT",
            result["data_health"]["reason_codes"],
        )
        self.assertEqual(result["prism_alignment"]["state"], "UNAVAILABLE")

    def test_same_inputs_produce_same_analysis(self):
        candles = make_candles(
            direction="UP",
            last_volume=1400.0,
            last_range_size=1.25,
        )
        context = prism_context()

        first = build_delta_tempo(
            pair="BTCUSD",
            candles=candles,
            speed_phase="REACCELERATION",
            prism_context=context,
        )
        second = build_delta_tempo(
            pair="BTCUSD",
            candles=copy.deepcopy(candles),
            speed_phase="REACCELERATION",
            prism_context=copy.deepcopy(context),
        )

        self.assertEqual(first["data_health"], second["data_health"])
        self.assertEqual(first["pressure"], second["pressure"])
        self.assertEqual(first["participation"], second["participation"])
        self.assertEqual(first["tempo"], second["tempo"])
        self.assertEqual(first["prism_alignment"], second["prism_alignment"])

    def test_pair_and_timeframe_validation(self):
        candles = make_candles()

        with self.assertRaisesRegex(ValueError, "pair_must_be_nonempty_string"):
            build_delta_tempo(
                pair="",
                candles=candles,
                speed_phase="NONE",
            )

        with self.assertRaisesRegex(
            ValueError,
            "timeframe_must_be_nonempty_string",
        ):
            build_delta_tempo(
                pair="BTCUSD",
                candles=candles,
                speed_phase="NONE",
                timeframe="",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
