from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent

CONTEXT_PATH = ROOT / "oracle_prop_context_v1.json"
SPEED_PATH = ROOT / "speed_companion_kraken_spot_state_v1.json"
OUTPUT_PATH = ROOT / "oracle_prop_context_kraken_spot_speed_v1.json"

JOIN_NAME = "kraken_spot_speed_companion"
JOIN_SCHEMA_VERSION = "kraken_spot_speed_companion_join_v1"


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


def fallback_unavailable(pair: str) -> Dict[str, Any]:
    return {
        "pair": pair,
        "state": "UNAVAILABLE",
        "reason": "KRAKEN_SPOT_M5_STATE_MISSING_FOR_CONTEXT_PAIR",
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


def project_state(raw: Dict[str, Any], pair: str) -> Dict[str, Any]:
    state = str(raw.get("state") or "").upper()

    if state not in {"AVAILABLE", "UNAVAILABLE"}:
        return fallback_unavailable(pair)

    if canonical_pair(raw.get("pair")) != pair:
        return fallback_unavailable(pair)

    projected = {
        "pair": pair,
        "state": state,
        "reason": raw.get("reason"),
        "input_timeframe": raw.get("input_timeframe") or "5m",
        "last_completed_candle_utc": raw.get("last_completed_candle_utc"),
        "bar_count": raw.get("bar_count") or 0,
        "analysis_window_bars": raw.get("analysis_window_bars") or 0,
        "active_horizon_bars": raw.get("active_horizon_bars") or 12,
        "lifecycle_scope": raw.get("lifecycle_scope") or (
            "UNAVAILABLE" if state == "UNAVAILABLE" else "UNKNOWN"
        ),
        "source": raw.get("source") or "kraken_spot_ohlc",
        "kraken_spot_pair": raw.get("kraken_spot_pair"),
        "kraken_api_pair_key": raw.get("kraken_api_pair_key"),
        "kraken_altname": raw.get("kraken_altname"),
        "kraken_wsname": raw.get("kraken_wsname"),
        "speed_phase": (
            raw.get("speed_phase")
            if state == "AVAILABLE"
            else None
        ),
        "raw_speed_phase": (
            raw.get("raw_speed_phase")
            if state == "AVAILABLE"
            else None
        ),
        "manual_review_only": True,
        "entry_authority": False,
    }

    return projected


def build_payload() -> Dict[str, Any]:
    context = load_object(CONTEXT_PATH)
    speed = load_object(SPEED_PATH)

    pairs = context.get("pairs")
    states = speed.get("states")

    if not isinstance(pairs, list):
        raise ValueError("Context payload must contain a list-valued 'pairs'")

    if not isinstance(states, list):
        raise ValueError("Speed payload must contain a list-valued 'states'")

    state_by_pair: Dict[str, Dict[str, Any]] = {}

    for raw in states:
        if not isinstance(raw, dict):
            continue

        pair = canonical_pair(raw.get("pair"))
        if pair:
            state_by_pair[pair] = raw

    enriched_pairs: List[Dict[str, Any]] = []
    matched_count = 0
    unavailable_count = 0
    missing_count = 0

    for raw_pair in pairs:
        if not isinstance(raw_pair, dict):
            raise ValueError("Context pair records must be JSON objects")

        record = copy.deepcopy(raw_pair)
        pair = canonical_pair(record.get("pair"))

        raw_state = state_by_pair.get(pair)

        if raw_state is None:
            record[JOIN_NAME] = fallback_unavailable(pair)
            missing_count += 1
            unavailable_count += 1
        else:
            projected = project_state(raw_state, pair)
            record[JOIN_NAME] = projected
            matched_count += 1

            if projected["state"] == "UNAVAILABLE":
                unavailable_count += 1

        enriched_pairs.append(record)

    context_pairs = {
        canonical_pair(record.get("pair"))
        for record in enriched_pairs
    }

    extra_state_count = sum(
        1
        for pair in state_by_pair
        if pair not in context_pairs
    )

    result = copy.deepcopy(context)
    result["pairs"] = enriched_pairs
    result["kraken_spot_speed_companion_join"] = {
        "schema_version": JOIN_SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "source_context_file": CONTEXT_PATH.name,
        "source_speed_file": SPEED_PATH.name,
        "manual_review_only": True,
        "entry_authority": False,
        "does_not_authorize_trade": True,
        "does_not_change_queue": True,
        "health": {
            "context_pair_count": len(enriched_pairs),
            "speed_state_source_count": len(states),
            "matched_count": matched_count,
            "unavailable_count": unavailable_count,
            "missing_state_count": missing_count,
            "extra_speed_state_count": extra_state_count,
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
    payload = build_payload()
    write_atomic(payload)

    health = payload["kraken_spot_speed_companion_join"]["health"]

    print(f"Wrote: {OUTPUT_PATH}")
    print(
        f"Context: {health['context_pair_count']} | "
        f"Matched: {health['matched_count']} | "
        f"Unavailable: {health['unavailable_count']} | "
        f"Missing: {health['missing_state_count']} | "
        f"Extra: {health['extra_speed_state_count']}"
    )


if __name__ == "__main__":
    main()
