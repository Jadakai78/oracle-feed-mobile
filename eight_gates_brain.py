from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BRAIN_VERSION = "1.0"
UNKNOWN_HISTORY = {
    "context": "UNKNOWN",
    "comparable_resolved_count": 0,
    "win_rate": None,
    "note": "Native Eight Gates learning is locked to context-only until drift-protection thresholds are met.",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(value: Any, name: str) -> None:
    if value is None or value == "" or value == []:
        raise ValueError(f"missing required field: {name}")


def _all_live_gates_pass(gates: dict[str, Any]) -> bool:
    required = (
        "data_integrity",
        "higher_timeframe_direction",
        "local_alignment",
        "pressure_confirmation",
        "participation",
        "noise_no_chase",
        "trigger_risk",
    )
    return all((gates.get(name) or {}).get("status") == "PASS" for name in required)


def validate_lane(lane: dict[str, Any]) -> None:
    for field in ("pair", "side", "entry_zone", "invalidation", "target_1", "target_2", "reason", "gates"):
        _require(lane.get(field), field)
    if lane["side"] not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    if not _all_live_gates_pass(lane["gates"]):
        raise ValueError("native observation requires Gates 1-7 to pass")
    if len(lane["entry_zone"]) != 2:
        raise ValueError("entry_zone must contain exactly two prices")
    for field in ("invalidation", "target_1", "target_2", *lane["entry_zone"]):
        if not isinstance(field, (int, float)) or field <= 0:
            raise ValueError("geometry prices must be positive numbers")


def build_observation(lane: dict[str, Any], observation_id: str, observed_at: str | None = None) -> dict[str, Any]:
    validate_lane(lane)
    _require(observation_id, "observation_id")
    return {
        "record_type": "lane_observed",
        "brain_version": BRAIN_VERSION,
        "observation_id": observation_id,
        "observed_at": observed_at or utc_now(),
        "pair": lane["pair"],
        "side": lane["side"],
        "score": lane.get("score"),
        "gates": lane["gates"],
        "features": lane.get("features") or {},
        "geometry": {
            "entry_zone": lane["entry_zone"],
            "invalidation": lane["invalidation"],
            "target_1": lane["target_1"],
            "target_2": lane["target_2"],
        },
        "history": dict(UNKNOWN_HISTORY),
        "outcome": {"status": "pending", "label": None},
    }


def build_resolution(observation_id: str, label: int | None, reason: str, evaluated_at: str | None = None) -> dict[str, Any]:
    _require(observation_id, "observation_id")
    if label not in {-1, 1, None}:
        raise ValueError("label must be -1, 1, or None")
    _require(reason, "reason")
    return {
        "record_type": "lane_resolved",
        "brain_version": BRAIN_VERSION,
        "observation_id": observation_id,
        "evaluated_at": evaluated_at or utc_now(),
        "outcome": {"status": "resolved", "label": label, "reason": reason},
    }


def append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def history_context() -> dict[str, Any]:
    """Hard lock: native learning is context-only and inactive until separately approved."""
    return dict(UNKNOWN_HISTORY)
