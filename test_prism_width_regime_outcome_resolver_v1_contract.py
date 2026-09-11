from __future__ import annotations

from datetime import timedelta
import copy
import unittest

from prism_width_regime_outcome_resolver_v1 import (
    resolve_prism_width_regime_outcome,
)
from prism_width_regime_observer_v1 import (
    build_prism_width_regime_observation,
)
from test_prism_width_regime_observer_v1_contract import PRISM_LAB
from test_band_terrain_v1_1 import load_fixture


HORIZONS = (1, 4, 16, 64)
FORBIDDEN_KEYS = {
    "side",
    "entry",
    "stop",
    "target",
    "tp",
    "sl",
    "score",
    "rank",
    "route",
    "signal",
    "execution_eligible",
    "trade_authority",
    "entry_authority",
    "does_simulate_order",
}


def observation() -> dict:
    fixture = load_fixture("PRISM-001")
    record = build_prism_width_regime_observation(
        pair="SOL/USD",
        bars=fixture["bars"],
        timeframe=fixture["timeframe"],
    )
    if record is None:
        raise RuntimeError("Expected valid PRISM-001 observation.")
    return record


def future_bars(
    count: int = 64,
    *,
    reference_timestamp: str = "2025-01-05T01:15:00Z",
    reference_price: float = 100.0,
) -> list[dict]:
    from datetime import datetime, timezone

    reference = datetime.fromisoformat(
        reference_timestamp.replace("Z", "+00:00")
    ).astimezone(timezone.utc)

    bars: list[dict] = []

    for index in range(1, count + 1):
        timestamp = reference + timedelta(minutes=15 * index)
        close = reference_price + float(index)
        high = close + 0.25
        low = close - 0.50

        bars.append(
            {
                "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                "open": close - 0.10,
                "high": high,
                "low": low,
                "close": close,
                "volume": 10.0 + index,
            }
        )

    return bars


class PrismWidthRegimeOutcomeResolverV1ContractTests(unittest.TestCase):
    def assert_safe(self, result: dict) -> None:
        self.assertTrue(result["manual_review_only"])
        self.assertTrue(result["does_not_authorize_trade"])
        self.assertTrue(result["does_not_simulate_order"])

        for key in FORBIDDEN_KEYS:
            self.assertNotIn(key, result)

    def test_complete_64_bar_future_series_resolves_all_horizons(self):
        record = observation()
        reference = float(record["reference_price"])
        bars = future_bars(
            64,
            reference_timestamp=record["reference_bar_close_utc"],
            reference_price=reference,
        )

        result = resolve_prism_width_regime_outcome(record, bars)

        self.assertIsInstance(result, dict)
        self.assertEqual(
            result["recordtype"],
            "PRISMWIDTHREGIMEOUTCOME",
        )
        self.assertEqual(
            result["schema_version"],
            "prismwidthregimev1",
        )
        self.assertEqual(result["observation_id"], record["observation_id"])
        self.assertEqual(result["pair"], "SOL/USD")
        self.assertEqual(result["timeframe"], "15m")
        self.assertEqual(
            result["reference_bar_close_utc"],
            record["reference_bar_close_utc"],
        )
        self.assertEqual(result["reference_price"], reference)
        self.assertEqual(result["horizons_bars"], [1, 4, 16, 64])
        self.assertEqual(result["status"], "CLOSED")
        self.assertEqual(set(result["samples"]), {"1bar", "4bar", "16bar", "64bar"})
        self.assert_safe(result)

    def test_metrics_are_direction_neutral_and_include_reference_anchor(self):
        record = observation()
        reference = float(record["reference_price"])
        bars = future_bars(
            64,
            reference_timestamp=record["reference_bar_close_utc"],
            reference_price=reference,
        )

        result = resolve_prism_width_regime_outcome(record, bars)

        first = result["samples"]["1bar"]
        expected_close = reference + 1.0
        expected_high = expected_close + 0.25
        expected_low = expected_close - 0.50

        self.assertAlmostEqual(
            first["close_return_pct"],
            ((expected_close / reference) - 1.0) * 100.0,
            places=10,
        )
        self.assertAlmostEqual(
            first["realized_range_pct"],
            ((expected_high - min(reference, expected_low)) / reference) * 100.0,
            places=10,
        )
        self.assertAlmostEqual(
            first["upside_excursion_pct"],
            ((expected_high - reference) / reference) * 100.0,
            places=10,
        )
        self.assertAlmostEqual(
            first["downside_excursion_pct"],
            ((min(reference, expected_low) - reference) / reference) * 100.0,
            places=10,
        )

        for sample in result["samples"].values():
            self.assertGreaterEqual(sample["realized_range_pct"], 0.0)
            self.assertGreaterEqual(sample["upside_excursion_pct"], 0.0)
            self.assertLessEqual(sample["downside_excursion_pct"], 0.0)

    def test_future_bars_must_start_one_interval_after_reference(self):
        record = observation()
        reference = float(record["reference_price"])
        bars = future_bars(
            64,
            reference_timestamp=record["reference_bar_close_utc"],
            reference_price=reference,
        )

        bars[0]["timestamp"] = record["reference_bar_close_utc"]

        self.assertIsNone(
            resolve_prism_width_regime_outcome(record, bars)
        )

    def test_noncontinuous_future_bars_fail_closed(self):
        record = observation()
        reference = float(record["reference_price"])
        bars = future_bars(
            64,
            reference_timestamp=record["reference_bar_close_utc"],
            reference_price=reference,
        )

        del bars[20]

        self.assertIsNone(
            resolve_prism_width_regime_outcome(record, bars)
        )

    def test_invalid_future_ohlcv_fails_closed(self):
        record = observation()
        reference = float(record["reference_price"])
        bars = future_bars(
            64,
            reference_timestamp=record["reference_bar_close_utc"],
            reference_price=reference,
        )
        bars[10]["low"] = bars[10]["high"] + 1.0

        self.assertIsNone(
            resolve_prism_width_regime_outcome(record, bars)
        )

    def test_less_than_64_completed_future_bars_stays_pending(self):
        record = observation()
        reference = float(record["reference_price"])
        bars = future_bars(
            63,
            reference_timestamp=record["reference_bar_close_utc"],
            reference_price=reference,
        )

        self.assertIsNone(
            resolve_prism_width_regime_outcome(record, bars)
        )

    def test_observation_is_not_mutated(self):
        record = observation()
        original = copy.deepcopy(record)
        reference = float(record["reference_price"])
        bars = future_bars(
            64,
            reference_timestamp=record["reference_bar_close_utc"],
            reference_price=reference,
        )

        result = resolve_prism_width_regime_outcome(record, bars)

        self.assertIsInstance(result, dict)
        self.assertEqual(record, original)

    def test_outcome_carries_frozen_feature_snapshot_for_later_grouping(self):
        record = observation()
        reference = float(record["reference_price"])
        bars = future_bars(
            64,
            reference_timestamp=record["reference_bar_close_utc"],
            reference_price=reference,
        )

        result = resolve_prism_width_regime_outcome(record, bars)

        self.assertEqual(result["terrain"], record["terrain"])
        self.assertEqual(result["width"], record["width"])
        self.assert_safe(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
