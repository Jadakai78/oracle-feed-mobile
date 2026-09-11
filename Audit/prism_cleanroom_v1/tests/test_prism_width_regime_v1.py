import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism_width_regime_v1 import classify_width_regime  # noqa: E402


def _available_width(percentile, slope, current=5.0):
    return {
        "state": "AVAILABLE",
        "recordtype": "PRISM_WIDTH_OBSERVATION",
        "schema_version": "prism_width_v1",
        "current_width": current,
        "prior_width_count": 25,
        "width_slope": slope,
        "width_percentile": percentile,
    }


class WidthRegimeTests(unittest.TestCase):
    def test_contracting_threshold(self):
        result = classify_width_regime(_available_width(0.20, "DOWN"))
        self.assertEqual(result["regime"], "WIDTH_CONTRACTING")
        self.assertEqual(result["state"], "AVAILABLE")

    def test_compressed_threshold(self):
        result = classify_width_regime(_available_width(0.20, "UP"))
        self.assertEqual(result["regime"], "WIDTH_COMPRESSED")
        result_flat = classify_width_regime(_available_width(0.10, "FLAT"))
        self.assertEqual(result_flat["regime"], "WIDTH_COMPRESSED")

    def test_expanding_threshold(self):
        result = classify_width_regime(_available_width(0.80, "UP"))
        self.assertEqual(result["regime"], "WIDTH_EXPANDING")

    def test_elevated_threshold(self):
        result = classify_width_regime(_available_width(0.80, "DOWN"))
        self.assertEqual(result["regime"], "WIDTH_ELEVATED")
        result_flat = classify_width_regime(_available_width(0.95, "FLAT"))
        self.assertEqual(result_flat["regime"], "WIDTH_ELEVATED")

    def test_neutral_case(self):
        result = classify_width_regime(_available_width(0.50, "UP"))
        self.assertEqual(result["regime"], "WIDTH_NEUTRAL")

    def test_invalid_percentile_fails_unavailable(self):
        result = classify_width_regime(_available_width(1.5, "UP"))
        self.assertEqual(result["regime"], "WIDTH_UNAVAILABLE")
        self.assertEqual(result["state"], "UNAVAILABLE")

    def test_wrong_prior_count_fails_unavailable(self):
        width = _available_width(0.80, "UP")
        width["prior_width_count"] = 24
        result = classify_width_regime(width)
        self.assertEqual(result["regime"], "WIDTH_UNAVAILABLE")

    def test_partial_unavailable_width_input_fails_unavailable(self):
        result = classify_width_regime({"state": "PARTIAL", "prior_width_count": 3})
        self.assertEqual(result["regime"], "WIDTH_UNAVAILABLE")
        result_none = classify_width_regime(None)
        self.assertEqual(result_none["regime"], "WIDTH_UNAVAILABLE")

    def test_input_not_mutated(self):
        width = _available_width(0.80, "UP")
        snapshot = copy.deepcopy(width)
        classify_width_regime(width)
        self.assertEqual(width, snapshot)


if __name__ == "__main__":
    unittest.main()
