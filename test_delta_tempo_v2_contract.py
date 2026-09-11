import unittest
import delta_tempo_prop_router as router


def episode(
    prior=None,
    side="LONG",
    speed_ok=True,
    lifecycle="SPEED_FLAT",
    direction_reversal=False,
    reclaim_confirmed=False,
    bos=False,
    market_condition="TRENDING",
    radar_state="TARGET_CONTINUATION",
    executioner_state="WAIT",
):
    cache = {}
    if prior is not None:
        cache["v2_episode"] = prior
    return router._v2_episode(
        cache, side, speed_ok, lifecycle, direction_reversal, reclaim_confirmed,
        bos, market_condition, radar_state, executioner_state, "test",
    )


class DeltaTempoV2ContractTests(unittest.TestCase):
    def active(self, direction="LONG"):
        return {
            "state": "WATCH_PERSISTING",
            "direction": direction,
            "watch_active": True,
            "active_feed_visibility": True,
            "promotion_pattern": None,
            "reason_codes": ["watch_persisting_aligned"],
        }

    def test_initial_impulse(self):
        result = episode()
        self.assertEqual(result["state"], "WATCH_INITIAL_IMPULSE")
        self.assertTrue(result["watch_active"])
        self.assertIsNone(result["promotion_pattern"])

    def test_persistence(self):
        result = episode(prior=self.active())
        self.assertEqual(result["state"], "WATCH_PERSISTING")
        self.assertTrue(result["watch_active"])

    def test_controlled_reset(self):
        result = episode(prior=self.active(), market_condition="TREND_PULLBACK")
        self.assertEqual(result["state"], "RESETTING")
        self.assertTrue(result["watch_active"])

    def test_reclaim_promotion(self):
        result = episode(
            prior=self.active(),
            lifecycle="SPEED_INCREASING",
            reclaim_confirmed=True,
        )
        self.assertEqual(result["state"], "RECLAIM_ACCELERATION")
        self.assertEqual(result["promotion_pattern"], "RECLAIM_ACCELERATION")

    def test_breakout_promotion(self):
        result = episode(
            prior=self.active(),
            lifecycle="SPEED_INCREASING",
            bos=True,
        )
        self.assertEqual(result["state"], "BREAKOUT_ACCEPTANCE")
        self.assertEqual(result["promotion_pattern"], "BREAKOUT_ACCEPTANCE")

    def test_pullback_reacceleration(self):
        result = episode(
            prior=self.active(),
            lifecycle="SPEED_INCREASING",
            market_condition="TREND_PULLBACK",
        )
        self.assertEqual(result["state"], "PULLBACK_REACCELERATION")
        self.assertEqual(result["promotion_pattern"], "PULLBACK_REACCELERATION")

    def test_reset_outranks_decay(self):
        result = episode(
            prior=self.active(),
            lifecycle="SPEED_DECAYING",
            market_condition="COMPRESSION",
        )
        self.assertEqual(result["state"], "RESETTING")
        self.assertTrue(result["watch_active"])

    def test_decay(self):
        result = episode(prior=self.active(), lifecycle="SPEED_DECAYING")
        self.assertEqual(result["state"], "DECAYING")
        self.assertFalse(result["watch_active"])

    def test_direction_invalidation(self):
        result = episode(prior=self.active(), direction_reversal=True)
        self.assertEqual(result["state"], "INVALIDATED")
        self.assertFalse(result["watch_active"])

    def test_router_rejection(self):
        result = episode(
            prior=self.active(),
            radar_state="NO_TARGET",
            executioner_state="NO_TRADE",
        )
        self.assertEqual(result["state"], "INVALIDATED")
        self.assertFalse(result["watch_active"])

    def test_contract_invariants(self):
        result = episode()
        self.assertIn(result["direction"], {"LONG", "SHORT", "NONE"})
        self.assertIsInstance(result["reason_codes"], list)
        self.assertTrue(result["reason_codes"])


if __name__ == "__main__":
    unittest.main(verbosity=2)