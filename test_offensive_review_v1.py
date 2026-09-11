import unittest
from offensive_review_v1 import (
    EXPECTED_CONTRACT_KEYS,
    PROHIBITED_KEYS,
    build_offensive_review,
    evaluate_delta_cvd,
)


class TestOffensiveReviewV1(unittest.TestCase):

    def setUp(self):
        self.sample_card = {
            "pair": "BTC/USD",
            "oracle_context": {
                "location": "ORACLE_LOCATION",
                "structure": "ALIGNED",
                "flow": "CONFIRMS",
                "tempo": "EXPANDING",
            },
            "prism": {"state": "AVAILABLE"},
            "delta_tempo_timing": {
                "direction": "LONG",
                "lifecycle_state": "REACCELERATION",
                "reclaim_confirmed": True,
            },
            "delta_cvd": {
                "delta_value": 150.5,
                "cvd_series": [100.0, 120.0, 160.0],
            },
        }

    def test_evaluate_delta_cvd_expanding(self):
        res = evaluate_delta_cvd(100.0, [10.0, 20.0, 50.0], "LONG")
        self.assertEqual(res["state"], "AVAILABLE")
        self.assertTrue(res["delta_aligned"])
        self.assertEqual(res["cvd_slope_state"], "EXPANDING")
        self.assertTrue(res["confirmed"])

    def test_evaluate_delta_cvd_insufficient_data(self):
        res = evaluate_delta_cvd(100.0, [10.0], "LONG")
        self.assertEqual(res["state"], "UNAVAILABLE")
        self.assertFalse(res["confirmed"])

    def test_contract_keys_and_posture(self):
        review = build_offensive_review(self.sample_card, "2026-09-03T12:10:00Z")

        # 17-key contract check
        self.assertEqual(len(review), 17)
        self.assertEqual(set(review.keys()), EXPECTED_CONTRACT_KEYS)
        self.assertEqual(review["offensive_posture"], "PRIORITY_REVIEW")
        self.assertEqual(review["delta_cvd_state"], "AVAILABLE")
        self.assertEqual(review["cvd_slope_state"], "EXPANDING")

    def test_posture_downgrade_when_cvd_flat(self):
        self.sample_card["delta_cvd"]["cvd_series"] = [50.0, 50.0, 50.0]
        review = build_offensive_review(self.sample_card, "2026-09-03T12:10:00Z")
        self.assertEqual(review["offensive_posture"], "OBSERVE")

    def test_prohibited_keys_absent(self):
        review = build_offensive_review(self.sample_card, "2026-09-03T12:10:00Z")
        for key in review:
            self.assertNotIn(key.lower(), PROHIBITED_KEYS)


if __name__ == "__main__":
    unittest.main()
