from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _zone_touched(high: float, low: float, zone_low: float, zone_high: float) -> bool:
    return low <= zone_high and high >= zone_low


def resolve_zone_touch_lane(
    record: Dict[str, Any],
    candles: List[List[Any]],
    horizon_bars: int = 16,
) -> Optional[Dict[str, Any]]:
    """Resolve a canonical lane_observed record using zone-touch-fill policy.

    Candles must contain completed OHLC rows after observed_at in Kraken form:
    [timestamp, open, high, low, close, ...].
    """
    if record.get("record_type") != "lane_observed":
        return None
    current = record.get("outcome") or {}
    if str(current.get("status") or "").lower() == "resolved":
        return None

    geometry = record.get("geometry") or {}
    side = str(record.get("side") or "").upper()
    zone = geometry.get("entry_zone") or []
    invalidation = _num(geometry.get("invalidation"))
    target = _num(geometry.get("target_1"))

    if side not in {"LONG", "SHORT"} or len(zone) != 2 or invalidation is None or target is None:
        return {
            "status": "invalid",
            "label": None,
            "reason": "invalid_lane_geometry",
            "evaluation_policy": "zone_touch_v1",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

    zone_low, zone_high = sorted((_num(zone[0]), _num(zone[1])))
    if zone_low is None or zone_high is None or zone_low <= 0 or zone_high <= 0:
        return {
            "status": "invalid",
            "label": None,
            "reason": "invalid_entry_zone",
            "evaluation_policy": "zone_touch_v1",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

    midpoint = (zone_low + zone_high) / 2.0
    if side == "LONG" and not (invalidation < midpoint < target):
        return {
            "status": "invalid",
            "label": None,
            "reason": "invalid_long_geometry",
            "evaluation_policy": "zone_touch_v1",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
    if side == "SHORT" and not (target < midpoint < invalidation):
        return {
            "status": "invalid",
            "label": None,
            "reason": "invalid_short_geometry",
            "evaluation_policy": "zone_touch_v1",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

    completed = [row for row in candles if len(row) >= 5][:horizon_bars]
    if len(completed) < horizon_bars:
        return None

    fill_index: Optional[int] = None
    mfe_r = 0.0
    mae_r = 0.0
    risk = abs(midpoint - invalidation)

    for index, row in enumerate(completed, start=1):
        timestamp = int(float(row[0]))
        high = float(row[2])
        low = float(row[3])

        if fill_index is None:
            if not _zone_touched(high, low, zone_low, zone_high):
                continue
            fill_index = index

            if side == "LONG":
                target_hit = high >= target
                stop_hit = low <= invalidation
            else:
                target_hit = low <= target
                stop_hit = high >= invalidation

            if target_hit and stop_hit:
                return {
                    "status": "resolved",
                    "label": None,
                    "reason": "ambiguous_fill_target_and_invalidation_same_candle",
                    "evaluation_policy": "zone_touch_v1",
                    "fill_status": "FILLED",
                    "fill_bar": fill_index,
                    "fill_timestamp": _iso(timestamp),
                    "fill_price": round(midpoint, 10),
                    "exit_status": "AMBIGUOUS",
                    "exit_bar": index,
                    "exit_timestamp": _iso(timestamp),
                    "gross_r": None,
                    "evaluated_at": datetime.now(timezone.utc).isoformat(),
                }
            if target_hit:
                return {
                    "status": "resolved",
                    "label": 1,
                    "reason": "target_after_zone_touch",
                    "evaluation_policy": "zone_touch_v1",
                    "fill_status": "FILLED",
                    "fill_bar": fill_index,
                    "fill_timestamp": _iso(timestamp),
                    "fill_price": round(midpoint, 10),
                    "exit_status": "TARGET",
                    "exit_bar": index,
                    "exit_timestamp": _iso(timestamp),
                    "gross_r": round(abs(target - midpoint) / risk, 6),
                    "mfe_r": round(abs(target - midpoint) / risk, 6),
                    "mae_r": 0.0,
                    "evaluated_at": datetime.now(timezone.utc).isoformat(),
                }
            if stop_hit:
                return {
                    "status": "resolved",
                    "label": -1,
                    "reason": "invalidation_after_zone_touch",
                    "evaluation_policy": "zone_touch_v1",
                    "fill_status": "FILLED",
                    "fill_bar": fill_index,
                    "fill_timestamp": _iso(timestamp),
                    "fill_price": round(midpoint, 10),
                    "exit_status": "INVALIDATION",
                    "exit_bar": index,
                    "exit_timestamp": _iso(timestamp),
                    "gross_r": -1.0,
                    "mfe_r": 0.0,
                    "mae_r": -1.0,
                    "evaluated_at": datetime.now(timezone.utc).isoformat(),
                }
            continue

        if side == "LONG":
            mfe_r = max(mfe_r, (high - midpoint) / risk)
            mae_r = min(mae_r, (low - midpoint) / risk)
            target_hit = high >= target
            stop_hit = low <= invalidation
        else:
            mfe_r = max(mfe_r, (midpoint - low) / risk)
            mae_r = min(mae_r, (midpoint - high) / risk)
            target_hit = low <= target
            stop_hit = high >= invalidation

        if target_hit and stop_hit:
            return {
                "status": "resolved",
                "label": None,
                "reason": "ambiguous_target_and_invalidation_same_candle",
                "evaluation_policy": "zone_touch_v1",
                "fill_status": "FILLED",
                "fill_bar": fill_index,
                "fill_timestamp": _iso(int(float(completed[fill_index - 1][0]))),
                "fill_price": round(midpoint, 10),
                "exit_status": "AMBIGUOUS",
                "exit_bar": index,
                "exit_timestamp": _iso(timestamp),
                "mfe_r": round(mfe_r, 6),
                "mae_r": round(mae_r, 6),
                "gross_r": None,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
        if target_hit:
            return {
                "status": "resolved",
                "label": 1,
                "reason": "target_after_zone_touch",
                "evaluation_policy": "zone_touch_v1",
                "fill_status": "FILLED",
                "fill_bar": fill_index,
                "fill_timestamp": _iso(int(float(completed[fill_index - 1][0]))),
                "fill_price": round(midpoint, 10),
                "exit_status": "TARGET",
                "exit_bar": index,
                "exit_timestamp": _iso(timestamp),
                "gross_r": round(abs(target - midpoint) / risk, 6),
                "mfe_r": round(mfe_r, 6),
                "mae_r": round(mae_r, 6),
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
        if stop_hit:
            return {
                "status": "resolved",
                "label": -1,
                "reason": "invalidation_after_zone_touch",
                "evaluation_policy": "zone_touch_v1",
                "fill_status": "FILLED",
                "fill_bar": fill_index,
                "fill_timestamp": _iso(int(float(completed[fill_index - 1][0]))),
                "fill_price": round(midpoint, 10),
                "exit_status": "INVALIDATION",
                "exit_bar": index,
                "exit_timestamp": _iso(timestamp),
                "gross_r": -1.0,
                "mfe_r": round(mfe_r, 6),
                "mae_r": round(mae_r, 6),
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }

    if fill_index is None:
        return {
            "status": "resolved",
            "label": None,
            "reason": "unfilled_horizon_expired",
            "evaluation_policy": "zone_touch_v1",
            "fill_status": "UNFILLED",
            "exit_status": "UNFILLED",
            "horizon_bars": horizon_bars,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

    return {
        "status": "resolved",
        "label": None,
        "reason": "filled_horizon_expired",
        "evaluation_policy": "zone_touch_v1",
        "fill_status": "FILLED",
        "fill_bar": fill_index,
        "fill_timestamp": _iso(int(float(completed[fill_index - 1][0]))),
        "fill_price": round(midpoint, 10),
        "exit_status": "TIMEOUT",
        "horizon_bars": horizon_bars,
        "mfe_r": round(mfe_r, 6),
        "mae_r": round(mae_r, 6),
        "gross_r": round((mfe_r + mae_r) * 0.0, 6),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
