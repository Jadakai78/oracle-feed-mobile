from __future__ import annotations

import json
from datetime import datetime, timezone
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

STAMP = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def write(name, payload):
    (FIXTURES / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")

oracle = []
eight = []
delta = []

for index, pair in enumerate(PAIRS):
    directional = "LONG" if index % 2 == 0 else "SHORT"
    oracle.append({
        "pair": pair,
        "generated_at_utc": STAMP,
        "age_seconds": 0,
        "directional_context": directional,
        "market_type": "TREND_UP" if directional == "LONG" else "TREND_DOWN",
        "structure": "STRUCTURE_CONTEXT",
        "tempo": "CONTROLLED",
        "flow": "NORMAL",
        "shield": "CLEAR",
        "location": "SUPPORT" if directional == "LONG" else "RESISTANCE",
        "review_state": "WATCH",
        "reason_codes": ["fixture_oracle_context"],
        "context_score": 70 + (index % 20),
        "constraint_state": "DESCRIPTIVE",
        "constraint_reasons": [],
    })
    eight.append({
        "pair": pair,
        "generated_at_utc": STAMP,
        "age_seconds": 0,
        "score": 55 + (index % 40),
        "eligibility": "ELIGIBLE_WATCH",
        "reason_codes": ["fixture_eight_gates"],
    })
    delta.append({
        "pair": pair,
        "generated_at_utc": STAMP,
        "age_seconds": 0,
        "delta_tempo_version": 2,
        "v2_episode_state": "WATCH_PERSISTING",
        "v2_episode_direction": directional,
        "v2_watch_active": True,
        "v2_active_feed_visibility": True,
        "v2_promotion_pattern": None,
        "v2_reason_codes": ["fixture_delta_watch_persisting"],
        "v2_manual_review_only": True,
        "v2_entry_authority": False,
        "shadow_score": None,
    })

write("oracle_available.json", oracle)
write("eight_gates_available.json", eight)
write("delta_v2_available.json", delta)
write("prism_unavailable.json", [])
write("source_stale.json", [{"pair": "BTC", "generated_at_utc": "2000-01-01T00:00:00Z", "age_seconds": 999999}])
write("source_invalid.json", [{"pair": "BTC", "delta_tempo_version": 1}])

payload = build_payload(PAIRS, oracle, eight, delta, [])
(ROOT / "sample_prism_adapter_feed.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(f"Fixture universe: {len(PAIRS)} pairs")
print(f"Output written: {ROOT / 'sample_prism_adapter_feed.json'}")