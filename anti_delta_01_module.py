"""
Anti-Delta 01.2 Module

Completed-candle response analysis for Delta pressure.

This module determines whether Delta pressure is:
- producing normal progress,
- being absorbed at a level,
- facing growing counterpressure,
- or losing control to the opposite side.

It is descriptive only. It performs no market reads, alerts,
execution, sizing, position management, or authority changes.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


RECORD_TYPE = "ANTI_DELTA"
SCHEMA_VERSION = "anti.delta.01.2"

MIN_REQUIRED_BARS = 40
RESPONSE_WINDOW = 12
RECENT_WINDOW = 4
PROGRESS_WINDOW = 6
VOLUME_WINDOW = 20

HEALTH_AVAILABLE = "AVAILABLE"
HEALTH_MISSING_BARS = "MISSING_BARS"
HEALTH_INVALID_CANDLES = "INVALID_CANDLES"
HEALTH_INVALID_DELTA_CONTEXT = "INVALID_DELTA_CONTEXT"

STATE_QUIET = "QUIET"
STATE_ABSORPTION = "ABSORPTION"
STATE_OPPOSITION_BUILDING = "OPPOSITION_BUILDING"
STATE_CONTROL_FLIP = "CONTROL_FLIP"
STATE_UNRESOLVED = "UNRESOLVED"
STATE_UNAVAILABLE = "UNAVAILABLE"

MANUAL_REVIEW_ONLY = True
TRADE_AUTHORITY = False
ENTRY_AUTHORITY = False


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid_{name}")

    numeric = float(value)

    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"invalid_{name}")

    return numeric


def _validate_candle(
    candle: Mapping[str, Any],
    index: int,
) -> dict[str, float]:
    if not isinstance(candle, Mapping):
        raise ValueError(f"candle_{index}_must_be_object")

    required = ("open", "high", "low", "close", "volume")
    missing = [field for field in required if field not in candle]

    if missing:
        raise ValueError(
            f"candle_{index}_missing_{'_'.join(missing)}"
        )

    open_price = _number(candle["open"], f"open_{index}")
    high = _number(candle["high"], f"high_{index}")
    low = _number(candle["low"], f"low_{index}")
    close = _number(candle["close"], f"close_{index}")
    volume = _number(candle["volume"], f"volume_{index}")

    if high < low:
        raise ValueError(f"candle_{index}_high_below_low")

    if high < max(open_price, close):
        raise ValueError(
            f"candle_{index}_high_below_open_or_close"
        )

    if low > min(open_price, close):
        raise ValueError(
            f"candle_{index}_low_above_open_or_close"
        )

    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _validate_candles(
    candles: Sequence[Mapping[str, Any]],
) -> list[dict[str, float]]:
    if (
        not isinstance(candles, Sequence)
        or isinstance(candles, (str, bytes))
    ):
        raise ValueError("candles_must_be_sequence")

    return [
        _validate_candle(candle, index)
        for index, candle in enumerate(candles)
    ]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _range(candle: Mapping[str, float]) -> float:
    return candle["high"] - candle["low"]


def _close_location(candle: Mapping[str, float]) -> float:
    candle_range = _range(candle)

    if candle_range <= 0:
        return 0.5

    location = (
        (candle["close"] - candle["low"])
        / candle_range
    )

    return max(0.0, min(1.0, location))


def _directional_location(
    candle: Mapping[str, float],
    direction: str,
) -> float:
    raw_location = _close_location(candle)

    if direction == "LONG":
        return raw_location

    return 1.0 - raw_location


def _direction_from_delta(
    delta_context: Mapping[str, Any],
) -> str:
    pressure = delta_context.get("pressure", {})

    if not isinstance(pressure, Mapping):
        raise ValueError("delta_pressure_must_be_object")

    state = str(pressure.get("state", "")).upper()

    if state == "BUYER_FAVORING":
        return "LONG"

    if state == "SELLER_FAVORING":
        return "SHORT"

    if state == "BALANCED":
        return "NONE"

    raise ValueError("delta_pressure_state_invalid")


def _validate_delta_context(
    delta_context: Mapping[str, Any],
) -> tuple[str, dict[str, str]]:
    if not isinstance(delta_context, Mapping):
        raise ValueError("delta_context_must_be_object")

    direction = _direction_from_delta(delta_context)

    participation = delta_context.get("participation", {})
    tempo = delta_context.get("tempo", {})

    if not isinstance(participation, Mapping):
        participation = {}

    if not isinstance(tempo, Mapping):
        tempo = {}

    return direction, {
        "participation_state": str(
            participation.get("state", "UNKNOWN")
        ).upper(),
        "tempo_state": str(
            tempo.get("state", "UNKNOWN")
        ).upper(),
    }


def calculate_response(
    candles: Sequence[Mapping[str, float]],
    delta_direction: str,
) -> dict[str, Any]:
    response_bars = candles[-RESPONSE_WINDOW:]
    recent_bars = candles[-RECENT_WINDOW:]
    progress_bars = candles[-PROGRESS_WINDOW:]
    latest = candles[-1]

    baseline_bars = candles[-VOLUME_WINDOW:-1]

    average_volume = (
        _mean([bar["volume"] for bar in baseline_bars])
        if baseline_bars
        else latest["volume"]
    )

    volume_ratio = latest["volume"] / max(average_volume, 1.0)

    directional_locations = [
        _directional_location(bar, delta_direction)
        for bar in response_bars
    ]

    recent_directional_locations = [
        _directional_location(bar, delta_direction)
        for bar in recent_bars
    ]

    directional_quality = _mean(directional_locations)
    recent_directional_quality = _mean(
        recent_directional_locations
    )

    latest_directional_quality = _directional_location(
        latest,
        delta_direction,
    )

    opposing_quality = 1.0 - directional_quality
    recent_opposing_quality = (
        1.0 - recent_directional_quality
    )
    latest_opposing_quality = (
        1.0 - latest_directional_quality
    )

    if delta_direction == "LONG":
        progress = (
            progress_bars[-1]["close"]
            - progress_bars[0]["close"]
        )
    else:
        progress = (
            progress_bars[0]["close"]
            - progress_bars[-1]["close"]
        )

    average_range = max(
        _mean([_range(bar) for bar in progress_bars]),
        1e-12,
    )

    progress_ratio = progress / average_range

    return {
        "latest_volume": round(latest["volume"], 8),
        "average_volume": round(average_volume, 8),
        "volume_ratio": round(volume_ratio, 4),
        "directional_close_quality": round(
            directional_quality,
            4,
        ),
        "opposing_close_quality": round(
            opposing_quality,
            4,
        ),
        "recent_directional_close_quality": round(
            recent_directional_quality,
            4,
        ),
        "recent_opposing_close_quality": round(
            recent_opposing_quality,
            4,
        ),
        "latest_directional_close_quality": round(
            latest_directional_quality,
            4,
        ),
        "latest_opposing_close_quality": round(
            latest_opposing_quality,
            4,
        ),
        "progress_ratio": round(progress_ratio, 4),
        "response_window": RESPONSE_WINDOW,
        "recent_window": RECENT_WINDOW,
        "progress_window": PROGRESS_WINDOW,
    }


def classify_anti_delta(
    delta_direction: str,
    response: Mapping[str, Any],
    delta_meta: Mapping[str, str],
) -> tuple[str, str, str]:
    if delta_direction == "NONE":
        return (
            STATE_UNRESOLVED,
            "NONE",
            "Delta pressure is balanced; no dominant side exists.",
        )

    volume_ratio = float(response["volume_ratio"])
    progress_ratio = float(response["progress_ratio"])

    directional_quality = float(
        response["directional_close_quality"]
    )
    opposing_quality = float(
        response["opposing_close_quality"]
    )

    recent_directional_quality = float(
        response["recent_directional_close_quality"]
    )
    recent_opposing_quality = float(
        response["recent_opposing_close_quality"]
    )

    latest_directional_quality = float(
        response["latest_directional_close_quality"]
    )
    latest_opposing_quality = float(
        response["latest_opposing_close_quality"]
    )

    opposite_direction = (
        "SHORT"
        if delta_direction == "LONG"
        else "LONG"
    )

    if (
        progress_ratio <= -0.50
        and recent_opposing_quality >= 0.60
        and latest_opposing_quality >= 0.60
    ):
        return (
            STATE_CONTROL_FLIP,
            opposite_direction,
            (
                "Recent completed bars progressed against Delta "
                "and the opposing side is closing in control."
            ),
        )

    if (
        volume_ratio >= 1.25
        and latest_directional_quality <= 0.30
    ):
        return (
            STATE_ABSORPTION,
            "NONE",
            (
                "High participation printed but the latest completed "
                "bar closed near the opposing side of its range."
            ),
        )

    if (
        recent_opposing_quality >= 0.58
        and recent_opposing_quality
        > recent_directional_quality
        and progress_ratio < 0.50
    ):
        return (
            STATE_OPPOSITION_BUILDING,
            opposite_direction,
            (
                "Recent closes increasingly favor the opposing side "
                "while Delta-side progress is weakening."
            ),
        )

    if (
        volume_ratio >= 1.25
        and progress_ratio < 0.35
        and directional_quality < 0.62
    ):
        return (
            STATE_ABSORPTION,
            "NONE",
            (
                "Participation is elevated but Delta-side progress "
                "is weak across the response window."
            ),
        )

    if (
        delta_meta["participation_state"] == "CONTRACTING"
        and delta_meta["tempo_state"] == "CONTRACTING"
        and progress_ratio < 0.35
    ):
        return (
            STATE_ABSORPTION,
            "NONE",
            (
                "Participation and tempo are contracting while "
                "Delta-side progress is weak."
            ),
        )

    if (
        progress_ratio >= 0.75
        and directional_quality >= 0.55
        and opposing_quality <= 0.45
    ):
        return (
            STATE_QUIET,
            delta_direction,
            (
                "Delta-side pressure is producing proportional "
                "directional progress."
            ),
        )

    return (
        STATE_UNRESOLVED,
        "NONE",
        (
            "Completed-candle response is mixed; Anti-Delta "
            "does not identify control."
        ),
    )


def _unavailable(
    pair: str,
    timeframe: str,
    health_state: str,
    reason_codes: list[str],
    completed_bars: int,
) -> dict[str, Any]:
    return {
        "record_type": RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _now_utc(),
        "pair": pair,
        "timeframe": timeframe,
        "data_health": {
            "state": health_state,
            "reason_codes": reason_codes,
            "completed_bars": completed_bars,
            "required_bars": MIN_REQUIRED_BARS,
        },
        "delta_direction": "UNAVAILABLE",
        "anti_delta": {
            "state": STATE_UNAVAILABLE,
            "direction": "NONE",
            "reason": "Anti-Delta context is unavailable.",
        },
        "response": {
            "latest_volume": None,
            "average_volume": None,
            "volume_ratio": None,
            "directional_close_quality": None,
            "opposing_close_quality": None,
            "recent_directional_close_quality": None,
            "recent_opposing_close_quality": None,
            "latest_directional_close_quality": None,
            "latest_opposing_close_quality": None,
            "progress_ratio": None,
            "response_window": RESPONSE_WINDOW,
            "recent_window": RECENT_WINDOW,
            "progress_window": PROGRESS_WINDOW,
        },
        "manual_review_only": MANUAL_REVIEW_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
    }


def build_anti_delta(
    pair: str,
    candles: Sequence[Mapping[str, Any]],
    delta_context: Mapping[str, Any],
    timeframe: str = "5m",
) -> dict[str, Any]:
    if not isinstance(pair, str) or not pair.strip():
        raise ValueError("pair_must_be_nonempty_string")

    if not isinstance(timeframe, str) or not timeframe.strip():
        raise ValueError("timeframe_must_be_nonempty_string")

    completed_bars = (
        len(candles)
        if isinstance(candles, Sequence)
        else 0
    )

    if completed_bars < MIN_REQUIRED_BARS:
        return _unavailable(
            pair=pair,
            timeframe=timeframe,
            health_state=HEALTH_MISSING_BARS,
            reason_codes=[
                "ANTI_DELTA.DATA.MISSING_BARS"
            ],
            completed_bars=completed_bars,
        )

    try:
        validated = _validate_candles(candles)
    except ValueError as exc:
        return _unavailable(
            pair=pair,
            timeframe=timeframe,
            health_state=HEALTH_INVALID_CANDLES,
            reason_codes=[
                f"ANTI_DELTA.DATA.INVALID_CANDLES:{exc}"
            ],
            completed_bars=completed_bars,
        )

    try:
        delta_direction, delta_meta = _validate_delta_context(
            delta_context
        )
    except ValueError as exc:
        return _unavailable(
            pair=pair,
            timeframe=timeframe,
            health_state=HEALTH_INVALID_DELTA_CONTEXT,
            reason_codes=[
                f"ANTI_DELTA.DELTA.INVALID_CONTEXT:{exc}"
            ],
            completed_bars=completed_bars,
        )

    response = calculate_response(
        candles=validated,
        delta_direction=delta_direction,
    )

    state, direction, reason = classify_anti_delta(
        delta_direction=delta_direction,
        response=response,
        delta_meta=delta_meta,
    )

    return {
        "record_type": RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _now_utc(),
        "pair": pair,
        "timeframe": timeframe,
        "data_health": {
            "state": HEALTH_AVAILABLE,
            "reason_codes": [],
            "completed_bars": completed_bars,
            "required_bars": MIN_REQUIRED_BARS,
        },
        "delta_direction": delta_direction,
        "delta_meta": delta_meta,
        "anti_delta": {
            "state": state,
            "direction": direction,
            "reason": reason,
        },
        "response": response,
        "manual_review_only": MANUAL_REVIEW_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
    }