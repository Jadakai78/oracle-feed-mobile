from __future__ import annotations

from typing import Any, Dict


PRESSURE_WEIGHT = 45.0
TEMPO_WEIGHT = 35.0
ACCELERATION_WEIGHT = 25.0
WEIGHT_TOTAL = PRESSURE_WEIGHT + TEMPO_WEIGHT + ACCELERATION_WEIGHT


def clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def weighted_core(
    pressure_strength: Any,
    tempo_strength: Any,
    acceleration_strength: Any,
    threshold: float = 0.60,
) -> Dict[str, Any]:
    pressure = clamp01(pressure_strength)
    tempo = clamp01(tempo_strength)
    acceleration = clamp01(acceleration_strength)

    raw_points = (
        pressure * PRESSURE_WEIGHT
        + tempo * TEMPO_WEIGHT
        + acceleration * ACCELERATION_WEIGHT
    )

    score = raw_points / WEIGHT_TOTAL

    return {
        "pressure_component": round(pressure * PRESSURE_WEIGHT, 4),
        "tempo_component": round(tempo * TEMPO_WEIGHT, 4),
        "acceleration_component": round(acceleration * ACCELERATION_WEIGHT, 4),
        "raw_points": round(raw_points, 4),
        "max_points": WEIGHT_TOTAL,
        "score": round(score, 4),
        "threshold": threshold,
        "qualified": score >= threshold,
        "version": "weighted-core-45-35-25-v1",
    }


def owner_state(
    *,
    core_qualified: bool,
    geometry_valid: bool,
    htf_state: str,
    anti_delta_state: str,
    speed_passes: bool,
) -> str:
    htf_state = str(htf_state or "").upper()
    anti_delta_state = str(anti_delta_state or "").upper()

    if htf_state in {"HTF_CONTEXT_INVALIDATED", "HTF_CONTEXT_CONFLICT"}:
        return "WEIGHTED_CORE_WAIT_HTF"

    if anti_delta_state in {"CONTROL_FLIP", "CONFLICT"}:
        return "WEIGHTED_CORE_BLOCKED_ANTI"

    if not geometry_valid:
        return "WEIGHTED_CORE_NO_GEOMETRY"

    if not core_qualified:
        return "WATCH"

    if not speed_passes:
        return "WEIGHTED_CORE_SPEED_CAUTION"

    return "WEIGHTED_CORE_ACTIVE"
