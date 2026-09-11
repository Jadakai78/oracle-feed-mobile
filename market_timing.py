"""Observation-only timing/confluence layer for Gimba.

This module is analytics-only. It does not alter execution eligibility,
OFFENSE/PERMISSION, routing, orders, sizing, risk, conviction, or KNN.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _text(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip()


def _upper(value: Any, default: str = "") -> str:
    return _text(value, default).upper()


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def unavailable(reason: str) -> Dict[str, Any]:
    return {
        "available": False,
        "base_status": "no_base",
        "delta_state": "unavailable",
        "cvd_state": "unavailable",
        "noise_relation": "unavailable",
        "gap": "no_actionable_base",
        "timing_state": "OBSERVE",
        "reasons": [reason],
        "rationale": reason,
    }


def _base_status(market_state: Dict[str, Any], rts_signal: Dict[str, Any], range_signal: Dict[str, Any]) -> str:
    indicators = (rts_signal or {}).get("indicators") or {}
    swept_high = bool(indicators.get("swept_high"))
    swept_low = bool(indicators.get("swept_low"))
    reclaim_high = bool(indicators.get("reclaim_high"))
    reclaim_low = bool(indicators.get("reclaim_low"))
    setup = _upper((rts_signal or {}).get("setup_type"))
    state = _upper((market_state or {}).get("state"))
    range_watch = _text((range_signal or {}).get("action_state")).lower() == "watch"

    if not indicators and not state and not range_watch:
        return "no_base"
    if reclaim_high or reclaim_low:
        return "swept_reclaimed"
    if swept_high or swept_low:
        return "accepting_through_base"
    if setup in {"LIQUIDATION_TO_CONTINUATION_LONG", "LIQUIDATION_TO_CONTINUATION_SHORT"}:
        return "holding_base"
    if state in {"FAILED_DOWN_AUCTION_RECLAIM", "FAILED_UP_AUCTION_RECLAIM"}:
        return "holding_base"
    if range_watch:
        return "at_base"
    return "away_from_base"


def _delta_state(volume_flow: Dict[str, Any]) -> str:
    if not bool((volume_flow or {}).get("ready")):
        return "unavailable"
    state = _text((volume_flow or {}).get("delta_state")).lower()
    if state in {"buy", "sell", "balanced"}:
        return state
    delta_norm = _number((volume_flow or {}).get("delta_norm"))
    if delta_norm is None:
        return "unavailable"
    if delta_norm >= 0.20:
        return "buy"
    if delta_norm <= -0.20:
        return "sell"
    return "balanced"


def _cvd_state(volume_flow: Dict[str, Any]) -> str:
    if not bool((volume_flow or {}).get("ready")):
        return "unavailable"
    slope = _number((volume_flow or {}).get("cvd_slope"))
    if slope is None:
        return "unavailable"
    if slope > 0:
        return "rising"
    if slope < 0:
        return "falling"
    return "flat"


def observe(
    *,
    structure: Dict[str, Any],
    volume_flow: Dict[str, Any],
    market_noise: Dict[str, Any],
    market_state: Dict[str, Any],
    rts_signal: Dict[str, Any],
    range_signal: Dict[str, Any],
) -> Dict[str, Any]:
    _ = structure  # accepted for compatibility with scanner shared context inputs
    base_status = _base_status(market_state or {}, rts_signal or {}, range_signal or {})
    delta_state = _delta_state(volume_flow or {})
    cvd_state = _cvd_state(volume_flow or {})

    noise_available = bool((market_noise or {}).get("available"))
    regime = _upper((market_noise or {}).get("regime"))
    pressure_aligned = (delta_state == "buy" and cvd_state == "rising") or (
        delta_state == "sell" and cvd_state == "falling"
    )

    reasons: List[str] = [
        f"base={base_status}",
        f"delta={delta_state}",
        f"cvd={cvd_state}",
    ]

    if not noise_available:
        noise_relation = "unavailable"
        reasons.append("noise=unavailable")
    elif base_status == "swept_reclaimed":
        noise_relation = "post_sweep"
        reasons.append(f"noise={regime or 'UNKNOWN'}")
    elif base_status == "accepting_through_base":
        noise_relation = "destructive_at_base"
        reasons.append(f"noise={regime or 'UNKNOWN'}")
    elif base_status in {"at_base", "holding_base"}:
        if base_status == "holding_base" and regime in {"CLEAN", "MIXED"} and pressure_aligned:
            noise_relation = "constructive_at_base"
        else:
            noise_relation = "contested_at_base"
        reasons.append(f"noise={regime or 'UNKNOWN'}")
    else:
        noise_relation = "neutral_away_from_base"
        reasons.append(f"noise={regime or 'UNKNOWN'}")

    if base_status in {"no_base", "away_from_base"}:
        gap = "no_actionable_base"
    elif base_status == "accepting_through_base":
        gap = "base_failing"
    elif not pressure_aligned:
        gap = "awaiting_pressure_alignment"
    elif noise_relation == "contested_at_base" and base_status == "at_base":
        gap = "awaiting_reclaim_close_and_hold"
    elif noise_relation == "contested_at_base":
        gap = "awaiting_noise_resolution"
    else:
        gap = "none"

    if (
        base_status in {"holding_base", "swept_reclaimed"}
        and pressure_aligned
        and noise_relation in {"constructive_at_base", "post_sweep"}
    ):
        timing_state = "CONFIRMED"
    elif base_status in {"at_base", "holding_base", "swept_reclaimed"} and gap != "base_failing":
        timing_state = "STALK"
    else:
        timing_state = "OBSERVE"

    if gap != "none":
        reasons.append(f"gap={gap}")
    reasons.append(f"timing={timing_state}")

    return {
        "available": True,
        "base_status": base_status,
        "delta_state": delta_state,
        "cvd_state": cvd_state,
        "noise_relation": noise_relation,
        "gap": gap,
        "timing_state": timing_state,
        "reasons": reasons,
        "rationale": " | ".join(reasons),
    }
