from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent

FEED_PATH = ROOT / "oracle_prop_feed_v1.json"
ENRICHED_CONTEXT_PATH = ROOT / "oracle_prop_context_kraken_spot_speed_v1.json"
OUTPUT_PATH = ROOT / "oracle_prop_feed_kraken_spot_speed_review_v1.json"

RECORDTYPE = "ORACLEPROPFEEDKRAKENSPOTSPEEDREVIEW"
SCHEMA_VERSION = "oracle_prop_feed_kraken_spot_speed_review_v1"
SPEED_KEY = "kraken_spot_speed_companion"


def utc_now() -> str:
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


def unavailable_projection(pair: str) -> Dict[str, Any]:
    return {
        "pair": pair,
        "state": "UNAVAILABLE",
        "reason": "KRAKEN_SPOT_M5_STATE_MISSING_FOR_FEED_PAIR",
        "input_timeframe": "5m",
        "last_completed_candle_utc": None,
        "bar_count": 0,
        "analysis_window_bars": 0,
        "active_horizon_bars": 12,
        "lifecycle_scope": "UNAVAILABLE",
        "source": "kraken_spot_ohlc",
        "kraken_spot_pair": None,
        "kraken_api_pair_key": None,
        "kraken_altname": None,
        "kraken_wsname": None,
        "speed_phase": None,
        "raw_speed_phase": None,
        "manual_review_only": True,
        "entry_authority": False,
    }


def compact_label(speed: Any) -> str:
    if not isinstance(speed, dict):
        return "UNAVAIL"

    if str(speed.get("state") or "").upper() != "AVAILABLE":
        return "UNAVAIL"

    scope = str(speed.get("lifecycle_scope") or "").upper()

    if scope != "CURRENT_IMPULSE":
        return "NONE"

    phase_data = speed.get("speed_phase")
    if not isinstance(phase_data, dict):
        return "NONE"

    direction = str(phase_data.get("direction") or "NONE").upper()
    phase = str(phase_data.get("phase") or "NONE").upper()

    if direction not in {"LONG", "SHORT"}:
        return "NONE"

    labels = {
        "WATCH": "WATCH",
        "CONTROLLED_PULLBACK": "PULLBACK",
        "REACCELERATION": "REACCEL",
        "DECAY": "DECAY",
    }

    prefix = labels.get(phase)
    if prefix is None:
        return "NONE"

    return f"{prefix}-{direction}"


def build_speed_index(context: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    pairs = context.get("pairs")

    if not isinstance(pairs, list):
        raise ValueError("Enriched context must contain a list-valued 'pairs'")

    indexed: Dict[str, Dict[str, Any]] = {}

    for record in pairs:
        if not isinstance(record, dict):
            continue

        pair = pair_key(record.get("pair"))
        speed = record.get(SPEED_KEY)

        if pair and isinstance(speed, dict):
            indexed[pair] = copy.deepcopy(speed)

    return indexed


def find_cards_key(feed: Dict[str, Any]) -> Optional[str]:
    for candidate in ("cards", "candidates", "pairs", "items"):
        if isinstance(feed.get(candidate), list):
            return candidate
    return None


def build_payload() -> Dict[str, Any]:
    feed = load_object(FEED_PATH)
    context = load_object(ENRICHED_CONTEXT_PATH)

    cards_key = find_cards_key(feed)
    if cards_key is None:
        raise ValueError(
            "Feed has no recognized list container: cards, candidates, pairs, items"
        )

    source_cards = feed.get(cards_key)
    if not isinstance(source_cards, list):
        raise ValueError(f"Feed field '{cards_key}' must be a list")

    speed_by_pair = build_speed_index(context)

    cards: List[Dict[str, Any]] = []
    label_counts: Dict[str, int] = {}

    for raw_card in source_cards:
        if not isinstance(raw_card, dict):
            raise ValueError("Feed card entries must be JSON objects")

        card = copy.deepcopy(raw_card)
        pair = pair_key(card.get("pair"))

        speed = speed_by_pair.get(pair)
        if speed is None:
            speed = unavailable_projection(pair)

        label = compact_label(speed)
        label_counts[label] = label_counts.get(label, 0) + 1

        card["m5_speed_display"] = label
        card[SPEED_KEY] = speed

        cards.append(card)

    result = copy.deepcopy(feed)

    result["recordtype"] = RECORDTYPE
    result["schema_version"] = SCHEMA_VERSION
    result["generated_at_utc"] = utc_now()
    result["manual_review_only"] = True
    result["entry_authority"] = False
    result["does_not_authorize_trade"] = True
    result["does_not_change_queue"] = True
    result["source_feed_file"] = FEED_PATH.name
    result["source_enriched_context_file"] = ENRICHED_CONTEXT_PATH.name
    result["m5_source"] = "kraken_spot_ohlc"
    result[cards_key] = cards
    result["kraken_spot_speed_review_health"] = {
        "feed_card_container": cards_key,
        "feed_card_count": len(cards),
        "label_counts": dict(sorted(label_counts.items())),
        "m5_available_count": sum(
            card[SPEED_KEY].get("state") == "AVAILABLE"
            for card in cards
        ),
        "m5_unavailable_count": sum(
            card[SPEED_KEY].get("state") == "UNAVAILABLE"
            for card in cards
        ),
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

    health = payload["kraken_spot_speed_review_health"]

    print(f"Wrote: {OUTPUT_PATH}")
    print(
        f"Cards: {health['feed_card_count']} | "
        f"M5 available: {health['m5_available_count']} | "
        f"M5 unavailable: {health['m5_unavailable_count']} | "
        f"Labels: {health['label_counts']}"
    )


if __name__ == "__main__":
    main()
