from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent

CONTEXT_PATH = ROOT / "oracle_prop_context_v1.json"
SPEED_PATH = ROOT / "speed_companion_state_v1.json"
OUTPUT_PATH = ROOT / "oracle_prop_context_speed_v1.json"

JOIN_NAME = "speed_companion"
JOIN_SCHEMA_VERSION = "speed_companion_join_v1"


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


def canonical_pair(value: Any) -> str:
    return str(value or "").upper().strip()


def missing_speed_state(pair: str) -> Dict[str, Any]:
    return {
        "state": "UNAVAILABLE",
        "reason": "M5_STATE_MISSING_FOR_CONTEXT_PAIR",
        "input_timeframe": "5m",
        "last_completed_candle_utc": None,
        "speed_phase": None,
        "manual_review_only": True,
        "entry_authority": False,
    }


def state_projection(raw: Dict[str, Any], pair: str) -> Dict[str, Any]:
    state = raw.get("state")
    if state not in {"AVAILABLE", "UNAVAILABLE"}:
        return {
            "state": "UNAVAILABLE",
            "reason": "INVALID_M5_STATE_RECORD",
            "input_timeframe": "5m",
            "last_completed_candle_utc": None,
            "speed_phase": None,
            "manual_review_only": True,
            "entry_authority": False,
        }

    return {
        "state": state,
        "reason": raw.get("reason"),
        "input_timeframe": raw.get("input_timeframe") or "5m",
        "last_completed_candle_utc": raw.get("last_completed_candle_utc"),
        "speed_phase": raw.get("speed_phase") if state == "AVAILABLE" else None,
        "manual_review_only": True,
        "entry_authority": False,
    }


def build_enriched_context() -> Dict[str, Any]:
    context = load_object(CONTEXT_PATH)
    speed = load_object(SPEED_PATH)

    pairs = context.get("pairs")
    states = speed.get("states")

    if not isinstance(pairs, list):
        raise ValueError("Context payload has no list-valued 'pairs'")
    if not isinstance(states, list):
        raise ValueError("Speed payload has no list-valued 'states'")

    speed_by_pair: Dict[str, Dict[str, Any]] = {}
    for raw in states:
        if not isinstance(raw, dict):
            continue
        pair = canonical_pair(raw.get("pair"))
        if pair:
            speed_by_pair[pair] = raw

    enriched_pairs: List[Dict[str, Any]] = []
    matched = 0
    missing = 0

    for raw_pair in pairs:
        if not isinstance(raw_pair, dict):
            raise ValueError("Context 'pairs' entries must be JSON objects")

        pair_record = copy.deepcopy(raw_pair)
        pair = canonical_pair(pair_record.get("pair"))

        raw_speed_state = speed_by_pair.get(pair)
        if raw_speed_state is None:
            pair_record[JOIN_NAME] = missing_speed_state(pair)
            missing += 1
        else:
            pair_record[JOIN_NAME] = state_projection(raw_speed_state, pair)
            matched += 1

        enriched_pairs.append(pair_record)

    result = copy.deepcopy(context)
    result["pairs"] = enriched_pairs
    result["speed_companion_join"] = {
        "schema_version": JOIN_SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "source_context_file": CONTEXT_PATH.name,
        "source_speed_file": SPEED_PATH.name,
        "manual_review_only": True,
        "entry_authority": False,
        "health": {
            "context_pair_count": len(enriched_pairs),
            "speed_state_source_count": len(states),
            "matched_count": matched,
            "missing_count": missing,
            "extra_speed_state_count": len(
                [
                    pair
                    for pair in speed_by_pair
                    if pair not in {
                        canonical_pair(record.get("pair"))
                        for record in enriched_pairs
                    }
                ]
            ),
        },
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
    payload = build_enriched_context()
    write_atomic(payload)

    health = payload["speed_companion_join"]["health"]
    print(f"Wrote: {OUTPUT_PATH}")
    print(
        f"Context: {health['context_pair_count']} | "
        f"Matched M5: {health['matched_count']} | "
        f"Missing M5: {health['missing_count']} | "
        f"Extra M5: {health['extra_speed_state_count']}"
    )


if __name__ == "__main__":
    main()
