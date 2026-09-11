"""
EG Trend Recovery v1 — Specialized gate-family candidate.

This module is observation-only. It creates no orders, alerts, routing,
sizing, or live-risk changes. It emits one canonical native lane only when
trend recovery conditions, structural geometry, and all gates pass.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


FAMILY = "EG_TREND_RECOVERY"
VERSION = "1.0"
POLICY = "zone_touch_v1"


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pass(reason: str, **metrics: Any) -> Dict[str, Any]:
    return {"status": "PASS", "reason": reason, "metrics": metrics}


def _fail(reason: str, **metrics: Any) -> Dict[str, Any]:
    return {"status": "FAIL", "reason": reason, "metrics": metrics}


def _ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = value * alpha + result * (1.0 - alpha)
    return result


def build_lane(
    *,
    pair: str,
    candles: List[Dict[str, float]],
    htf_direction: str,
    delta_norm: float,
    rel_vol: float,
    atr: float,
    observed_at: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Creates a zone-touch Trend Recovery lane.

    LONG:
      established UP trend, a pullback below EMA20, then reclaim above EMA20.
    SHORT:
      established DOWN trend, a pullback above EMA20, then reclaim below EMA20.

    The lane waits for a return to the reclaim zone. It does not chase the
    confirmation close.
    """
    if len(candles) < 25 or atr <= 0:
        return None

    direction = str(htf_direction or "").upper()
    if direction not in {"UP", "DOWN"}:
        return None

    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    opens = [float(c["open"]) for c in candles]

    ema20 = _ema(closes, 20)
    if ema20 is None:
        return None

    last = candles[-1]
    price = closes[-1]
    recovery_window = candles[-6:]
    recent_low = min(float(c["low"]) for c in recovery_window)
    recent_high = max(float(c["high"]) for c in recovery_window)

    gates: Dict[str, Any] = {}
    gates["data_integrity"] = _pass("valid_completed_candles", bar_count=len(candles))

    if direction == "UP":
        gates["higher_timeframe_direction"] = _pass("htf_up")
        pullback_seen = any(float(c["low"]) <= ema20 for c in candles[-8:-1])
        reclaim = price > ema20 and float(last["close"]) > float(last["open"])
        pressure_ok = delta_norm >= 0.20
        target = recent_high + max(atr, (recent_high - recent_low) * 0.50)
        invalidation = recent_low - atr
        entry_zone = [ema20 - atr * 0.15, ema20 + atr * 0.15]
        side = "LONG"
    else:
        gates["higher_timeframe_direction"] = _pass("htf_down")
        pullback_seen = any(float(c["high"]) >= ema20 for c in candles[-8:-1])
        reclaim = price < ema20 and float(last["close"]) < float(last["open"])
        pressure_ok = delta_norm <= -0.20
        target = recent_low - max(atr, (recent_high - recent_low) * 0.50)
        invalidation = recent_high + atr
        entry_zone = [ema20 - atr * 0.15, ema20 + atr * 0.15]
        side = "SHORT"

    gates["pullback_location"] = (
        _pass("pullback_into_recovery_area", ema20=round(ema20, 10))
        if pullback_seen else _fail("no_pullback_to_recovery_area", ema20=round(ema20, 10))
    )
    gates["reclaim_confirmation"] = (
        _pass("reclaim_confirmed", price=round(price, 10))
        if reclaim else _fail("reclaim_not_confirmed", price=round(price, 10))
    )
    gates["pressure_confirmation"] = (
        _pass("pressure_realigned", delta_norm=round(delta_norm, 6))
        if pressure_ok else _fail("pressure_not_realigned", delta_norm=round(delta_norm, 6))
    )
    gates["participation"] = (
        _pass("adequate_participation", rel_vol=round(rel_vol, 6))
        if rel_vol >= 0.50 else _fail("thin_participation", rel_vol=round(rel_vol, 6))
    )

    zone_low, zone_high = sorted(float(x) for x in entry_zone)
    midpoint = (zone_low + zone_high) / 2.0
    risk = abs(midpoint - invalidation)
    reward = abs(target - midpoint)
    room_to_risk = reward / risk if risk > 0 else 0.0
    geometry_valid = (
        risk > 0
        and room_to_risk >= 1.50
        and ((side == "LONG" and invalidation < midpoint < target)
             or (side == "SHORT" and target < midpoint < invalidation))
    )
    gates["trigger_risk"] = (
        _pass("recovery_geometry_valid", room_to_risk=round(room_to_risk, 4))
        if geometry_valid else _fail("recovery_geometry_invalid", room_to_risk=round(room_to_risk, 4))
    )

    if not all(gate["status"] == "PASS" for gate in gates.values()):
        return None

    score = min(
        100,
        50
        + 15
        + min(15, int(rel_vol * 10))
        + (10 if abs(delta_norm) >= 0.50 else 5)
        + (5 if room_to_risk >= 2.0 else 0),
    )

    return {
        "record_type": "lane_observed",
        "schema_version": 1,
        "observation_id": str(uuid.uuid4()),
        "family": FAMILY,
        "version": VERSION,
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "pair": pair,
        "side": side,
        "score": score,
        "reason": "htf_trend_pullback_reclaim_zone_touch",
        "gates": gates,
        "features": {
            "htf_direction": direction,
            "ema20": round(ema20, 10),
            "delta_norm": round(delta_norm, 6),
            "rel_vol": round(rel_vol, 6),
            "atr": round(atr, 10),
            "room_to_risk": round(room_to_risk, 6),
        },
        "geometry": {
            "entry_zone": [round(zone_low, 10), round(zone_high, 10)],
            "entry_midpoint": round(midpoint, 10),
            "invalidation": round(invalidation, 10),
            "target_1": round(target, 10),
            "target_2": None,
        },
        "evaluation_policy": POLICY,
        "outcome": {"status": "pending", "label": None},
    }
