from __future__ import annotations

from typing import Any, Dict, Optional
import math


MIN_ROOM_TO_RISK = 3.0
ATR_BUFFER = 0.25


def _n(value: Any) -> Optional[float]:
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def build(
    side: str,
    entry: Any,
    local_geometry: Dict[str, Any],
    structure: Dict[str, Any],
    reclaim_confirmed: bool,
) -> Dict[str, Any]:
    result = {
        "geometry_version": "structural_v1_3r",
        "geometry_status": "GEOMETRY_REJECTED",
        "geometry_reason": "structure_geometry_unavailable",
        "entry": None,
        "sl": None,
        "tp": None,
        "tp1": None,
        "tp2": None,
        "tp3": None,
        "risk_pct": None,
        "reward_pct": None,
        "room_to_risk": None,
        "invalidation_type": None,
        "target_type": None,
    }

    entry = _n(entry)
    atr = _n(local_geometry.get("atr"))
    swing_high = _n(structure.get("swing_high"))
    swing_low = _n(structure.get("swing_low"))

    if side not in {"LONG", "SHORT"} or entry is None or atr is None:
        result["geometry_reason"] = "side_entry_or_atr_unavailable"
        return result

    buffer = atr * ATR_BUFFER

    if side == "LONG":
        invalidation_base = swing_low
        target = swing_high
        if invalidation_base is None or target is None:
            result["geometry_reason"] = "long_structure_levels_unavailable"
            return result
        sl = invalidation_base - buffer
        risk = entry - sl
        reward = target - entry
        invalidation_type = "d1_swing_low_plus_atr_buffer"
        target_type = "d1_swing_high"

    else:
        invalidation_base = swing_high
        target = swing_low
        if invalidation_base is None or target is None:
            result["geometry_reason"] = "short_structure_levels_unavailable"
            return result
        sl = invalidation_base + buffer
        risk = sl - entry
        reward = entry - target
        invalidation_type = "d1_swing_high_plus_atr_buffer"
        target_type = "d1_swing_low"

    if risk <= 0:
        result["geometry_reason"] = "entry_on_wrong_side_of_invalidation"
        return result

    if reward <= 0:
        result["geometry_reason"] = "no_room_to_structural_target"
        return result

    room_to_risk = reward / risk
    if room_to_risk < MIN_ROOM_TO_RISK:
        result.update({
            "entry": round(entry, 8),
            "sl": round(sl, 8),
            "tp": round(target, 8),
            "risk_pct": round(risk / entry * 100.0, 4),
            "reward_pct": round(reward / entry * 100.0, 4),
            "room_to_risk": round(room_to_risk, 3),
            "invalidation_type": invalidation_type,
            "target_type": target_type,
            "geometry_reason": f"structural_room_below_{MIN_ROOM_TO_RISK:.1f}R",
        })
        return result

    result.update({
        "geometry_status": "STRUCTURAL_VALID",
        "geometry_reason": "d1_swing_invalidation_to_opposing_d1_swing",
        "entry": round(entry, 8),
        "sl": round(sl, 8),
        "tp": round(target, 8),
        "tp1": round(target, 8),
        "risk_pct": round(risk / entry * 100.0, 4),
        "reward_pct": round(reward / entry * 100.0, 4),
        "room_to_risk": round(room_to_risk, 3),
        "invalidation_type": invalidation_type,
        "target_type": target_type,
        "reclaim_confirmed": bool(reclaim_confirmed),
    })
    return result
