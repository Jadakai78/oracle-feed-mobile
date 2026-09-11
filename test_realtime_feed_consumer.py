"""
Unit Tests for Real-Time Feed Consumer Module
---------------------------------------------
Verifies L2 orderbook depth maintenance, CVD series accumulation,
and integration with offensive_review_v1.
"""

import unittest
from realtime_feed_consumer import OrderbookState, RealTimeFeedConsumer


class TestRealTimeFeedConsumer(unittest.TestCase):

    def setUp(self):
        self.expectancy_report = {
            "PRISM:AVAILABLE|SPEED:REACCELERATION|RECLAIM:True|CVD_SLOPE:EXPANDING": {
                "sample_size": 40,
                "win_rate_pct": 70.0,
                "profit_factor": 3.5,
                "expected_value_r": 0.90,
                "confidence_status": "STATISTICALLY_VALIDATED",
                "recommended_posture": "PRIORITY_REVIEW",
            }
        }
        self.consumer = RealTimeFeedConsumer(
            expectancy_report=self.expectancy_report
        )

    def test_orderbook_state_and_cvd_accumulation(self):
        ob = OrderbookState("ETH/USD", max_cvd_bars=5)

        # Ingest ticks
        ob.update_orderbook(
            bids=[[3000.0, 10.0]], asks=[[3001.0, 5.0]], trade_delta=5.0
        )
        ob.update_orderbook(
            bids=[[3000.5, 8.0]], asks=[[3001.5, 4.0]], trade_delta=10.0
        )

        payload = ob.get_delta_cvd_payload()
        self.assertEqual(payload["delta_value"], 10.0)
        self.assertEqual(payload["cvd_series"], [0.0, 5.0, 15.0])
        self.assertEqual(ob.bids[3000.5], 8.0)

    def test_process_candidate_card_integration(self):
        pair = "BTC/USD"

        # Stream orderbook ticks
        self.consumer.ingest_orderbook_tick(
            pair, bids=[[65000.0, 1.0]], asks=[[65010.0, 1.0]], trade_delta=10.0
        )
        self.consumer.ingest_orderbook_tick(
            pair, bids=[[65005.0, 2.0]], asks=[[65015.0, 1.0]], trade_delta=15.0
        )

        raw_card = {
            "pair": pair,
            "oracle_context": {
                "location": "HIGH_CONFLUENCE_SUPPORT",
                "structure": "BULLISH_CONTINUATION",
                "flow": "CONFIRMS",
                "tempo": "EXPANDING",
            },
            "prism": {"state": "AVAILABLE"},
            "delta_tempo_timing": {
                "lifecycle_state": "REACCELERATION",
                "reclaim_confirmed": True,
                "direction": "LONG",
            },
        }

        review = self.consumer.process_candidate_card(raw_card)

        self.assertEqual(review["pair"], "BTC/USD")
        self.assertEqual(review["offensive_posture"], "PRIORITY_REVIEW")
        self.assertEqual(review["cvd_slope_state"], "EXPANDING")
        self.assertTrue(review["manual_review_only"])
        self.assertTrue(review["does_not_authorize_trade"])


if __name__ == "__main__":
    unittest.main()
