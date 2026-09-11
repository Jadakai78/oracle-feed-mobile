import copy
import unittest
from unittest.mock import patch

from oracle_prism_delta_tempo_speed_candidate_feed_v1 import (
    build_payload,
    delta_tempo_timing,
    oracle_context,
)


class CandidateFeedTests(unittest.TestCase):

    def _valid_speed_review(self, pairs=None):
        if pairs is None:
            pairs = ["BTC/USD"] + [f"PAIR{i}/USD" for i in range(1, 49)]

        cards = []
        for pair in pairs:
            cards.append(
                {
                    "pair": pair,
                    "directional_context": "ALIGNED",
                    "market_type": "PERPETUAL",
                    "structure": "ALIGNED",
                    "tempo": "EXPANDING",
                    "flow": "CONFIRMS",
                    "shield": "CLEAR",
                    "location": "ORACLE_LOCATION",
                    "review_state": "ACTIVE",
                    "reason_codes": [],
                    "context_claim": "VALIDATED",
                    "context_score": 100,
                    "tier": 1,
                    "correlation_group": "MAJORS",
                    "correlation_role": "LEADER",
                    "micro_watchlist": True,
                    "micro_state": "ACTIVE",
                    "m5_speed_display": "REACCELERATION",
                    "delta_value": 250.0,
                    "cvd_series": [100.0, 150.0, 300.0],
                    "kraken_spot_speed_companion": {
                        "state": "AVAILABLE",
                        "source": "kraken_spot_ohlc",
                        "input_timeframe": "5m",
                        "last_completed_candle_utc": "2026-09-03T12:00:00Z",
                        "manual_review_only": True,
                        "entry_authority": False,
                        "speed_phase": {
                            "direction": "LONG",
                            "phase": "REACCELERATION",
                            "decay_reason": None,
                            "reclaim_confirmed": True,
                        },
                    },
                }
            )

        return {"recordtype": "SPEEDREVIEW", "cards": cards}

    def _valid_prism_snapshot(self, pairs=None):
        if pairs is None:
            pairs = ["BTC/USD"] + [f"PAIR{i}/USD" for i in range(1, 49)]

        prism_cards = [
            {
                "pair": p,
                "state": "AVAILABLE",
                "source_health": {"state": "AVAILABLE"},
                "context": {"location": "PRISM_LOCATION"},
                "construction": {"state": "AVAILABLE", "current": {"label": "CONSTRUCTED"}},
                "fair_price": {"state": "FAIR"},
                "band_travel": {"state": "INSIDE"},
                "routes_ranked": [],
                "risk": {"state": "CLEAR"},
                "display": {"summary": "PRISM OK"},
            }
            for p in pairs
        ]

        return {
            "recordtype": "PRISMRUNTIMESNAPSHOT",
            "schema_version": "prism.runtime-snapshot.v1",
            "venue": "KRAKEN_SPOT",
            "universe": "APRIL_12_FIXED",
            "fixture_market_source": False,
            "manual_review_only": True,
            "trade_authority": False,
            "entry_authority": False,
            "does_not_send_alerts": True,
            "does_not_change_queue": True,
            "cards": prism_cards,
        }

    def test_runtime_input_remains_pending_review_not_publishable(self):
        payload = build_payload(self._valid_speed_review(), self._valid_prism_snapshot())
        self.assertEqual(payload["operating_mode"], "FIELD_READ_ONLY")
        self.assertFalse(payload["publish_eligible"])

    def test_exactly_49_unique_oracle_pairs_preserved(self):
        payload = build_payload(self._valid_speed_review(), self._valid_prism_snapshot())
        self.assertEqual(len(payload["cards"]), 49)

    def test_speed_is_represented_as_delta_tempo_timing_without_mutation(self):
        payload = build_payload(self._valid_speed_review(), self._valid_prism_snapshot())
        card = payload["cards"][0]
        self.assertEqual(card["delta_tempo_timing"]["lifecycle_state"], "REACCELERATION")

    def test_runtime_prism_exact_match_is_available_and_source_owned(self):
        payload = build_payload(self._valid_speed_review(), self._valid_prism_snapshot())
        self.assertEqual(payload["cards"][0]["prism"]["state"], "AVAILABLE")

    def test_runtime_prism_unavailable_is_visible_and_not_invented(self):
        prism_p = self._valid_prism_snapshot()
        prism_p["cards"] = prism_p["cards"][1:]
        payload = build_payload(self._valid_speed_review(), prism_p)
        self.assertEqual(payload["cards"][0]["prism"]["state"], "UNAVAILABLE")

    def test_runtime_prism_does_not_base_asset_match(self):
        prism_p = self._valid_prism_snapshot(pairs=["BTC/EUR"] + [f"PAIR{i}/USD" for i in range(1, 49)])
        payload = build_payload(self._valid_speed_review(), prism_p)
        self.assertEqual(payload["cards"][0]["prism"]["state"], "UNAVAILABLE")

    def test_runtime_prism_safety_must_be_valid(self):
        prism_p = self._valid_prism_snapshot()
        prism_p["manual_review_only"] = False
        with self.assertRaises(ValueError):
            build_payload(self._valid_speed_review(), prism_p)

    def test_runtime_prism_rejects_fixture_source(self):
        prism_p = self._valid_prism_snapshot()
        prism_p["fixture_market_source"] = True
        with self.assertRaises(ValueError):
            build_payload(self._valid_speed_review(), prism_p)

    def test_field_mode_active_delta_cvd(self):
        payload = build_payload(self._valid_speed_review(), self._valid_prism_snapshot())
        self.assertEqual(payload["deferred_sources"]["delta_cvd"], "ACTIVE_SLOPE_EVALUATION")

    def test_candidate_safety_invariants(self):
        payload = build_payload(self._valid_speed_review(), self._valid_prism_snapshot())
        self.assertTrue(payload["manual_review_only"])
        self.assertFalse(payload["trade_authority"])

    @patch("oracle_prism_delta_tempo_speed_candidate_feed_v1.now_utc")
    def test_candidate_offensive_review_integration(self, mock_now_utc):
        mock_now_utc.return_value = "2026-09-03T12:10:00Z"
        payload = build_payload(self._valid_speed_review(), self._valid_prism_snapshot())

        first_card = payload["cards"][0]
        review = first_card["offensive_review"]

        # Assert 17 contract keys
        self.assertEqual(len(review), 17)
        self.assertEqual(review["offensive_posture"], "PRIORITY_REVIEW")
        self.assertEqual(review["delta_cvd_state"], "AVAILABLE")
        self.assertEqual(review["cvd_slope_state"], "EXPANDING")


if __name__ == "__main__":
    unittest.main()
