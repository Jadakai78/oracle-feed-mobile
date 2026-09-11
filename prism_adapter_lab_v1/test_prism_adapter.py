from __future__ import annotations

import json
import unittest
from pathlib import Path

from prism_adapter import build_payload

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"

PAIRS = [
    "AAVE", "ADA", "AIXBT", "ALGO", "APT", "ARB", "ASTER", "ATOM", "AVAX",
    "BCH", "BNB", "BTC", "CRV", "DOGE", "DOT", "ETC", "ETH", "FARTCOIN",
    "FIL", "GRASS", "HBAR", "HYPE", "INJ", "JTO", "JUP", "NEAR", "ONDO",
    "OP", "PENGU", "PNUT", "POL", "POPCAT", "PUMP", "RENDER", "S", "SOL",
    "STX", "SUI", "TAO", "TIA", "TRUMP", "TRX", "UNI", "VIRTUAL", "WIF",
    "WLD", "XPL", "XRP", "ZEC",
]

def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class PrismAdapterTests(unittest.TestCase):
    def setUp(self):
        self.oracle = load("oracle_available.json")
        self.eight = load("eight_gates_available.json")
        self.delta = load("delta_v2_available.json")
        self.prism = load("prism_unavailable.json")
        self.payload = build_payload(PAIRS, self.oracle, self.eight, self.delta, self.prism)

    def test_exactly_49_cards(self):
        self.assertEqual(len(self.payload["cards"]), 49)

    def test_all_cards_manual_review_only(self):
        self.assertTrue(self.payload["manual_review_only"])
        self.assertFalse(self.payload["trade_authority"])
        self.assertFalse(self.payload["entry_authority"])
        for card in self.payload["cards"]:
            self.assertTrue(card["display"]["manual_review_only"])
            self.assertFalse(card["display"]["entry_authority"])

    def test_context_is_never_numeric_score(self):
        for card in self.payload["cards"]:
            self.assertIsNone(card["context"]["context_score"])

    def test_scores_are_independent(self):
        for card in self.payload["cards"]:
            confluence = card["confluence"]
            self.assertEqual(confluence["score_relationship"], "INDEPENDENT_NOT_COMBINED")
            self.assertIn("score", confluence["eight_gates"])
            self.assertIn("shadow_score", confluence["delta_tempo_v2"])
            self.assertNotIn("combined_score", confluence)

    def test_delta_raw_v2_fields_preserved(self):
        card = next(card for card in self.payload["cards"] if card["pair"] == "BTC")
        delta = card["confluence"]["delta_tempo_v2"]
        self.assertEqual(delta["state"], "AVAILABLE")
        self.assertEqual(delta["episode_state"], "WATCH_PERSISTING")
        self.assertTrue(delta["manual_review_only"])
        self.assertFalse(delta["entry_authority"])
        self.assertEqual(delta["shadow_score_state"], "NOT_DEFINED")

    def test_prism_missing_is_explicit(self):
        for card in self.payload["cards"]:
            self.assertEqual(card["source_health"]["prism"]["state"], "UNAVAILABLE")
            self.assertEqual(card["prism_map"]["state"], "UNAVAILABLE")
            self.assertIn("prism_source_not_connected", card["risk"]["risk_reasons"])

    def test_missing_delta_does_not_hide_eight_gates(self):
        payload = build_payload(PAIRS, self.oracle, self.eight, [], [])
        card = next(card for card in payload["cards"] if card["pair"] == "BTC")
        self.assertEqual(card["source_health"]["delta_tempo_v2"]["state"], "UNAVAILABLE")
        self.assertEqual(card["confluence"]["eight_gates"]["state"], "AVAILABLE")
        self.assertIsNotNone(card["confluence"]["eight_gates"]["score"])

    def test_bad_delta_version_fails_closed(self):
        invalid = load("source_invalid.json")
        with self.assertRaises(ValueError):
            build_payload(PAIRS, self.oracle, self.eight, invalid, [])

    def test_pair_count_guard(self):
        with self.assertRaises(ValueError):
            build_payload(PAIRS[:-1], self.oracle, self.eight, self.delta, [])

if __name__ == "__main__":
    unittest.main(verbosity=2)