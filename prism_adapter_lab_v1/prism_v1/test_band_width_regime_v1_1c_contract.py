from __future__ import annotations

import math
import unittest

from band_width_regime_v1_1c import classify_band_width_regime


TOLERANCE = {
    "rel_tol": 1e-12,
    "abs_tol": 1e-12,
}

FORBIDDEN_KEYS = {
    "route",
    "rank",
    "score",
    "signal",
    "direction",
    "execution_eligible",
    "trade",
    "entry",
}


def observation(
    *,
    current_width: float | None = 10.0,
    prior_widths: list[float] | None = None,
    width_slope: str = "FLAT",
    state: str = "AVAILABLE",
    history_state: str = "AVAILABLE",
) -> dict:
    widths = list(prior_widths) if prior_widths is not None else list(range(1, 26))

    return {
        "state": state,
        "reason": None,
        "current_width": current_width,
        "prior_widths": widths,
        "prior_width_count": len(widths),
        "history_state": history_state,
        "width_slope": width_slope,
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
    }


class BandWidthRegimeV11CContractTests(unittest.TestCase):
    def assert_safe_metadata(self, result: dict) -> None:
        self.assertTrue(result["manual_review_only"])
        self.assertFalse(result["trade_authority"])
        self.assertFalse(result["entry_authority"])

        for key in FORBIDDEN_KEYS:
            self.assertNotIn(key, result)

    def assert_unavailable(self, result: dict) -> None:
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual(result["regime"], "WIDTH_UNAVAILABLE")
        self.assertIsNone(result["current_width"])
        self.assertIsNone(result["width_percentile"])
        self.assertEqual(result["width_slope"], "UNAVAILABLE")
        self.assert_safe_metadata(result)

    def test_midpoint_percentile_uses_strictly_lower_and_equal_counts(self):
        result = classify_band_width_regime(
            observation(
                current_width=10.0,
                prior_widths=[5.0] * 10 + [10.0] * 5 + [15.0] * 10,
                width_slope="FLAT",
            )
        )

        expected_percentile = (10 + 0.5 * 5) / 25

        self.assertEqual(result["state"], "AVAILABLE")
        self.assertTrue(
            math.isclose(
                result["width_percentile"],
                expected_percentile,
                **TOLERANCE,
            )
        )
        self.assertEqual(result["regime"], "WIDTH_NEUTRAL")
        self.assert_safe_metadata(result)

    def test_low_percentile_with_down_slope_is_contracting(self):
        result = classify_band_width_regime(
            observation(
                current_width=5.0,
                prior_widths=list(range(10, 35)),
                width_slope="DOWN",
            )
        )

        self.assertEqual(result["state"], "AVAILABLE")
        self.assertLessEqual(result["width_percentile"], 0.20)
        self.assertEqual(result["regime"], "WIDTH_CONTRACTING")
        self.assert_safe_metadata(result)

    def test_low_percentile_without_down_slope_is_compressed(self):
        for slope in ("UP", "FLAT"):
            with self.subTest(width_slope=slope):
                result = classify_band_width_regime(
                    observation(
                        current_width=5.0,
                        prior_widths=list(range(10, 35)),
                        width_slope=slope,
                    )
                )

                self.assertEqual(result["state"], "AVAILABLE")
                self.assertLessEqual(result["width_percentile"], 0.20)
                self.assertEqual(result["regime"], "WIDTH_COMPRESSED")
                self.assert_safe_metadata(result)

    def test_high_percentile_with_up_slope_is_expanding(self):
        result = classify_band_width_regime(
            observation(
                current_width=40.0,
                prior_widths=list(range(1, 26)),
                width_slope="UP",
            )
        )

        self.assertEqual(result["state"], "AVAILABLE")
        self.assertGreaterEqual(result["width_percentile"], 0.80)
        self.assertEqual(result["regime"], "WIDTH_EXPANDING")
        self.assert_safe_metadata(result)

    def test_high_percentile_without_up_slope_is_elevated(self):
        for slope in ("DOWN", "FLAT"):
            with self.subTest(width_slope=slope):
                result = classify_band_width_regime(
                    observation(
                        current_width=40.0,
                        prior_widths=list(range(1, 26)),
                        width_slope=slope,
                    )
                )

                self.assertEqual(result["state"], "AVAILABLE")
                self.assertGreaterEqual(result["width_percentile"], 0.80)
                self.assertEqual(result["regime"], "WIDTH_ELEVATED")
                self.assert_safe_metadata(result)

    def test_middle_percentile_is_neutral(self):
        result = classify_band_width_regime(
            observation(
                current_width=13.0,
                prior_widths=list(range(1, 26)),
                width_slope="UP",
            )
        )

        self.assertEqual(result["state"], "AVAILABLE")
        self.assertGreater(result["width_percentile"], 0.20)
        self.assertLess(result["width_percentile"], 0.80)
        self.assertEqual(result["regime"], "WIDTH_NEUTRAL")
        self.assert_safe_metadata(result)

    def test_current_width_is_not_implicitly_added_to_prior_distribution(self):
        prior_widths = list(range(1, 26))
        result = classify_band_width_regime(
            observation(
                current_width=40.0,
                prior_widths=prior_widths,
                width_slope="UP",
            )
        )

        self.assertEqual(result["prior_width_count"], 25)
        self.assertEqual(result["width_percentile"], 1.0)
        self.assertEqual(result["regime"], "WIDTH_EXPANDING")
        self.assert_safe_metadata(result)

    def test_partial_or_unavailable_width_observation_fails_closed(self):
        cases = (
            observation(
                current_width=10.0,
                prior_widths=[],
                width_slope="UNAVAILABLE",
                state="PARTIAL",
                history_state="PARTIAL",
            ),
            observation(
                current_width=None,
                prior_widths=[],
                width_slope="UNAVAILABLE",
                state="UNAVAILABLE",
                history_state="UNAVAILABLE",
            ),
        )

        for width_observation in cases:
            with self.subTest(state=width_observation["state"]):
                result = classify_band_width_regime(width_observation)
                self.assert_unavailable(result)

    def test_wrong_prior_width_count_fails_closed(self):
        result = classify_band_width_regime(
            observation(
                current_width=10.0,
                prior_widths=list(range(1, 25)),
                width_slope="FLAT",
            )
        )

        self.assert_unavailable(result)

    def test_invalid_width_values_fail_closed(self):
        cases = (
            observation(
                current_width=math.nan,
                prior_widths=list(range(1, 26)),
                width_slope="UP",
            ),
            observation(
                current_width=10.0,
                prior_widths=[1.0] * 24 + [math.inf],
                width_slope="UP",
            ),
            observation(
                current_width=-1.0,
                prior_widths=list(range(1, 26)),
                width_slope="UP",
            ),
        )

        for width_observation in cases:
            with self.subTest(current_width=width_observation["current_width"]):
                result = classify_band_width_regime(width_observation)
                self.assert_unavailable(result)

    def test_invalid_slope_fails_closed(self):
        result = classify_band_width_regime(
            observation(
                current_width=10.0,
                prior_widths=list(range(1, 26)),
                width_slope="SIDEWAYS",
            )
        )

        self.assert_unavailable(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
