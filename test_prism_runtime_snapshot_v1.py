import unittest

import prism_runtime_snapshot_v1 as prism


def candle(index: int, close: float, volume: float = 100.0):
    ts = 1_700_000_000 + index * prism.INTERVAL_SECONDS
    return {
        "ts": float(ts),
        "open": close * 0.998,
        "high": close * 1.003,
        "low": close * 0.997,
        "close": close,
        "volume": volume,
    }


def healthy_candles(count=prism.MIN_HISTORY_BARS):
    return [candle(index, 100.0 + index * 0.08, 100.0 + (index % 7)) for index in range(count)]


class PrismRuntimeSnapshotTests(unittest.TestCase):
    def test_completed_history_builds_available_card(self):
        card = prism.build_card("BTC/USD", healthy_candles())
        self.assertEqual(card["source_health"]["state"], "AVAILABLE")
        self.assertEqual(card["pair"], "BTC/USD")
        self.assertEqual(card["construction"]["state"], "AVAILABLE")
        self.assertTrue(card["display"]["manual_review_only"])
        self.assertFalse(card["display"]["entry_authority"])

    def test_insufficient_history_fails_closed(self):
        card = prism.build_card("BTC/USD", healthy_candles(prism.MIN_HISTORY_BARS - 1))
        self.assertEqual(card["source_health"]["state"], "INSUFFICIENT_HISTORY")
        self.assertEqual(card["construction"]["state"], "UNAVAILABLE")
        self.assertIn("PRISM.DATA.INSUFFICIENT_HISTORY", card["source_health"]["reason_codes"])

    def test_missing_bar_remains_visible(self):
        candles = healthy_candles()
        candles[200]["ts"] += prism.INTERVAL_SECONDS
        card = prism.build_card("BTC/USD", candles)
        self.assertEqual(card["source_health"]["state"], "MISSING_BARS")
        self.assertEqual(card["construction"]["state"], "UNAVAILABLE")
        self.assertIn("PRISM.DATA.MISSING_BARS", card["source_health"]["reason_codes"])

    def test_invalid_ohlcv_remains_visible(self):
        candles = healthy_candles()
        candles[20]["low"] = candles[20]["high"] * 1.1
        card = prism.build_card("BTC/USD", candles)
        self.assertEqual(card["source_health"]["state"], "INVALID")
        self.assertEqual(card["construction"]["state"], "UNAVAILABLE")

    def test_snapshot_requires_exact_fixed_universe(self):
        def fetcher(pair):
            return healthy_candles()

        payload = prism.build_snapshot(fetcher)
        self.assertEqual(payload["recordtype"], "PRISMRUNTIMESNAPSHOT")
        self.assertEqual(payload["schema_version"], "prism.runtime-snapshot.v1")
        self.assertEqual(payload["venue"], "KRAKEN_SPOT")
        self.assertEqual(payload["universe"], "APRIL_12_FIXED")
        self.assertFalse(payload["fixture_market_source"])
        self.assertEqual(len(payload["cards"]), 49)
        self.assertEqual(
            [card["pair"] for card in payload["cards"]],
            list(prism.APRIL_12_FIXED_PAIRS),
        )

    def test_safety_contract(self):
        payload = prism.build_snapshot(lambda pair: healthy_candles())
        self.assertTrue(payload["manual_review_only"])
        self.assertFalse(payload["trade_authority"])
        self.assertFalse(payload["entry_authority"])
        self.assertTrue(payload["does_not_send_alerts"])
        self.assertTrue(payload["does_not_change_queue"])
        serialized = str(payload).lower()
        for forbidden in ("trade_instruction", "'entry':", "'stop':", "'target':", "'score':"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main(verbosity=2)