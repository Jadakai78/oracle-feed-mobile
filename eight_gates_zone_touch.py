from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


EVALUATION_POLICY = "zone_touch_v1"


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _result(
    *,
    status: str,
    label: Optional[int],
    reason: str,
    fill_status: str,
    exit_status: str,
    evaluated_at: str,
    **extra: Any,
) -> Dict[str, Any]:
    return {
        "status": status,
        "label": label,
        "reason": reason,
        "evaluation_policy": EVALUATION_POLICY,
        "fill_status": fill_status,
        "exit_status": exit_status,
        "evaluated_at": evaluated_at,
        **extra,
    }


def resolve_zone_touch_lane(
    record: Dict[str, Any],
    candles: List[List[Any]],
    horizon_bars: int,
) -> Optional[Dict[str, Any]]:
    """
    Native resolver for eight_gates_brain lane_observed records.

    Rule:
      1. Observe completed candles after observed_at.
      2. A trade exists only after a candle overlaps entry_zone.
      3. Fill price is entry-zone midpoint for v1 research.
      4. TP/SL are evaluated only after the fill.
      5. TP and SL in one candle is ambiguous.
      6. No zone touch by horizon is UNFILLED.
    """
    current = record.get("outcome") or {}
    if str(current.get("status") or "").lower() in {"resolved", "invalid"}:
        return None

    now = datetime.now(timezone.utc).isoformat()
    geometry = record.get("geometry") or {}
    side = str(record.get("side") or "").upper()
    zone = geometry.get("entry_zone") or []
    invalidation = _number(geometry.get("invalidation"))
    target = _number(geometry.get("target_1"))

    if side not in {"LONG", "SHORT"} or len(zone) != 2:
        return _result(
            status="invalid",
            label=None,
            reason="invalid_lane_side_or_entry_zone",
            fill_status="UNFILLED",
            exit_status="INVALID",
            evaluated_at=now,
        )

    zone_values = [_number(zone[0]), _number(zone[1])]
    if any(value is None or value <= 0 for value in zone_values):
        return _result(
            status="invalid",
            label=None,
            reason="invalid_lane_entry_zone_prices",
            fill_status="UNFILLED",
            exit_status="INVALID",
            evaluated_at=now,
        )

    zone_low, zone_high = sorted(zone_values)
    midpoint = (zone_low + zone_high) / 2.0

    if invalidation is None or target is None or invalidation <= 0 or target <= 0:
        return _result(
            status="invalid",
            label=None,
            reason="invalid_lane_target_or_invalidation",
            fill_status="UNFILLED",
            exit_status="INVALID",
            evaluated_at=now,
        )

    if side == "LONG" and not (invalidation < midpoint < target):
        return _result(
            status="invalid",
            label=None,
            reason="invalid_long_geometry",
            fill_status="UNFILLED",
            exit_status="INVALID",
            evaluated_at=now,
        )

    if side == "SHORT" and not (target < midpoint < invalidation):
        return _result(
            status="invalid",
            label=None,
            reason="invalid_short_geometry",
            fill_status="UNFILLED",
            exit_status="INVALID",
            evaluated_at=now,
        )

    rows = [row for row in candles if len(row) >= 5][:horizon_bars]
    if len(rows) < horizon_bars:
        return None

    risk = abs(midpoint - invalidation)
    if risk <= 0:
        return _result(
            status="invalid",
            label=None,
            reason="zero_risk_distance",
            fill_status="UNFILLED",
            exit_status="INVALID",
            evaluated_at=now,
        )

    fill_bar = None
    fill_timestamp = None
    mfe_r = 0.0
    mae_r = 0.0

    for bar_number, row in enumerate(rows, start=1):
        timestamp = int(float(row[0]))
        high = float(row[2])
        low = float(row[3])

        if fill_bar is None:
            zone_touched = low <= zone_high and high >= zone_low
            if not zone_touched:
                continue

            fill_bar = bar_number
            fill_timestamp = _iso(timestamp)

        if side == "LONG":
            target_hit = high >= target
            stop_hit = low <= invalidation
            mfe_r = max(mfe_r, (high - midpoint) / risk)
            mae_r = min(mae_r, (low - midpoint) / risk)
        else:
            target_hit = low <= target
            stop_hit = high >= invalidation
            mfe_r = max(mfe_r, (midpoint - low) / risk)
            mae_r = min(mae_r, (midpoint - high) / risk)

        shared = {
            "fill_bar": fill_bar,
            "fill_timestamp": fill_timestamp,
            "fill_price": round(midpoint, 10),
            "entry_zone": [round(zone_low, 10), round(zone_high, 10)],
            "target_1": round(target, 10),
            "invalidation": round(invalidation, 10),
            "exit_bar": bar_number,
            "exit_timestamp": _iso(timestamp),
            "mfe_r": round(mfe_r, 6),
            "mae_r": round(mae_r, 6),
            "horizon_bars": horizon_bars,
        }

        if target_hit and stop_hit:
            return _result(
                status="resolved",
                label=None,
                reason="ambiguous_target_and_invalidation_same_candle",
                fill_status="FILLED",
                exit_status="AMBIGUOUS",
                evaluated_at=now,
                gross_r=None,
                **shared,
            )

        if target_hit:
            return _result(
                status="resolved",
                label=1,
                reason="target_after_zone_touch",
                fill_status="FILLED",
                exit_status="TARGET",
                evaluated_at=now,
                gross_r=round(abs(target - midpoint) / risk, 6),
                **shared,
            )

        if stop_hit:
            return _result(
                status="resolved",
                label=-1,
                reason="invalidation_after_zone_touch",
                fill_status="FILLED",
                exit_status="INVALIDATION",
                evaluated_at=now,
                gross_r=-1.0,
                **shared,
            )

    if fill_bar is None:
        return _result(
            status="resolved",
            label=None,
            reason="unfilled_horizon_expired",
            fill_status="UNFILLED",
            exit_status="UNFILLED",
            evaluated_at=now,
            horizon_bars=horizon_bars,
            entry_zone=[round(zone_low, 10), round(zone_high, 10)],
        )

    return _result(
        status="resolved",
        label=None,
        reason="filled_horizon_expired",
        fill_status="FILLED",
        exit_status="TIMEOUT",
        evaluated_at=now,
        fill_bar=fill_bar,
        fill_timestamp=fill_timestamp,
        fill_price=round(midpoint, 10),
        entry_zone=[round(zone_low, 10), round(zone_high, 10)],
        target_1=round(target, 10),
        invalidation=round(invalidation, 10),
        horizon_bars=horizon_bars,
        mfe_r=round(mfe_r, 6),
        mae_r=round(mae_r, 6),
        gross_r=0.0,
    )
