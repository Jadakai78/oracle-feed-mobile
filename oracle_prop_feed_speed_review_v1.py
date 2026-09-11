from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent

FEED_PATH = ROOT / "oracle_prop_feed_v1.json"
ENRICHED_CONTEXT_PATH = ROOT / "oracle_prop_context_speed_v1.json"
OUTPUT_PATH = ROOT / "oracle_prop_feed_speed_review_v1.json"

RECORDTYPE = "ORACLEPROPFEEDSPEEDREVIEW"
SCHEMA_VERSION = "oracle_prop_feed_speed_review_v1"


def now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_object(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")

    return payload


def pair_key(value: Any) -> str:
    return str(value or "").upper().strip()


def compact_m5_label(speed: Any) -> str:
    if not isinstance(speed, dict):
        return "UNAVAIL"

    if str(speed.get("state") or "").upper() != "AVAILABLE":
        return "UNAVAIL"

    phase_data = speed.get("speed_phase")
    if not isinstance(phase_data, dict):
        return "UNAVAIL"

    direction = str(phase_data.get("direction") or "NONE").upper()
    phase = str(phase_data.get("phase") or "NONE").upper()

    if direction == "NONE" or phase == "NONE":
        return "NONE"

    prefixes = {
        "WATCH": "WATCH",
        "CONTROLLED_PULLBACK": "PULLBACK",
        "REACCELERATION": "REACCEL",
        "DECAY": "DECAY",
    }

    prefix = prefixes.get(phase)
    if prefix is None:
        return "UNAVAIL"

    if direction not in {"LONG", "SHORT"}:
        return prefix

    return f"{prefix}-{direction}"


def build_speed_index(context: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    records = context.get("pairs")
    if not isinstance(records, list):
        raise ValueError("Enriched context must contain a list-valued 'pairs'")

    indexed: Dict[str, Dict[str, Any]] = {}

    for record in records:
        if not isinstance(record, dict):
            continue

        key = pair_key(record.get("pair"))
        speed = record.get("speed_companion")

        if key and isinstance(speed, dict):
            indexed[key] = copy.deepcopy(speed)

    return indexed


def find_cards_container(feed: Dict[str, Any]) -> Optional[str]:
    for key in ("cards", "candidates", "pairs", "items"):
        if isinstance(feed.get(key), list):
            return key
    return None


def build_payload() -> Dict[str, Any]:
    feed = load_object(FEED_PATH)
    context = load_object(ENRICHED_CONTEXT_PATH)

    cards_key = find_cards_container(feed)
    if cards_key is None:
        raise ValueError(
            "Feed has no recognized list container: cards, candidates, pairs, or items"
        )

    source_cards = feed.get(cards_key)
    if not isinstance(source_cards, list):
        raise ValueError(f"Feed field '{cards_key}' must be a list")

    speed_by_pair = build_speed_index(context)

    enriched_cards: List[Dict[str, Any]] = []
    available_count = 0
    unavailable_count = 0

    for raw_card in source_cards:
        if not isinstance(raw_card, dict):
            raise ValueError("Feed card entries must be JSON objects")

        card = copy.deepcopy(raw_card)
        pair = pair_key(card.get("pair"))

        speed = speed_by_pair.get(pair)
        label = compact_m5_label(speed)

        if label == "UNAVAIL":
            unavailable_count += 1
        else:
            available_count += 1

        card["m5_speed_display"] = label
        card["speed_companion"] = speed if speed is not None else {
            "state": "UNAVAILABLE",
            "reason": "M5_STATE_MISSING_FOR_CONTEXT_PAIR",
            "input_timeframe": "5m",
            "last_completed_candle_utc": None,
            "speed_phase": None,
            "manual_review_only": True,
            "entry_authority": False,
        }

        enriched_cards.append(card)

    result = copy.deepcopy(feed)

    # Keep the original feed payload intact except for the separate review wrapper.
    result["recordtype"] = RECORDTYPE
    result["schema_version"] = SCHEMA_VERSION
    result["generated_at_utc"] = now_utc()
    result["manual_review_only"] = True
    result["entry_authority"] = False
    result["does_not_authorize_trade"] = True
    result["does_not_change_queue"] = True
    result["source_feed"] = FEED_PATH.name
    result["source_enriched_context"] = ENRICHED_CONTEXT_PATH.name
    result[cards_key] = enriched_cards
    result["speed_companion_review_health"] = {
        "feed_card_container": cards_key,
        "feed_card_count": len(enriched_cards),
        "m5_available_display_count": available_count,
        "m5_unavailable_display_count": unavailable_count,
    }

    return result


def write_atomic(payload: Dict[str, Any]) -> None:
    temporary = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(OUTPUT_PATH)


def main() -> None:
    payload = build_payload()
    write_atomic(payload)

    health = payload["speed_companion_review_health"]
    print(f"Wrote: {OUTPUT_PATH}")
    print(
        f"Cards: {health['feed_card_count']} | "
        f"M5 displayed: {health['m5_available_display_count']} | "
        f"M5 unavailable: {health['m5_unavailable_display_count']}"
    )


if __name__ == "__main__":
    main()
