"""
prism_terrain_v1.py — PRISM clean-room terrain map builder.

Descriptive-only structural map of price displacement relative to a rolling
365-bar mean/stddev band. Never emits trade, execution, or ranking fields.
No network access, no file writes, no mutation of caller-owned inputs.
"""

from __future__ import annotations

import statistics
from typing import Any

from prism_common_v1 import (
    REASON_INSUFFICIENT_HISTORY,
    REASON_INVALID_OHLCV,
    REASON_MISSING_BARS,
    REASON_STDDEV_UNAVAILABLE,
    SAFETY_FLAGS,
    TOLERANCE,
    slope_from_values,
    validate_bars_series,
)

PERIOD = 365
DEVIATIONS = (1, 2, 3)
STDDEV_METHOD = "POPULATION"


def _unavailable(timeframe: str, reason_code: str) -> dict[str, Any]:
    return {
        "state": "UNAVAILABLE",
        "recordtype": "PRISM_TERRAIN_MAP",
        "schema_version": "prism_terrain_v1",
        "timeframe": timeframe,
        "last_completed_candle_utc": None,
        "input_bar_count": None,
        "required_bar_count": PERIOD,
        "configuration": {
            "period": PERIOD,
            "deviations": list(DEVIATIONS),
            "price_source": "close",
            "stddev_method": STDDEV_METHOD,
        },
        "reason_codes": [reason_code],
        "current_close": None,
        "middle_band": None,
        "prior_middle_band": None,
        "stddev": None,
        "z_score": None,
        "minus_3_sigma": None,
        "minus_2_sigma": None,
        "minus_1_sigma": None,
        "plus_1_sigma": None,
        "plus_2_sigma": None,
        "plus_3_sigma": None,
        "bandwidth": None,
        "middle_slope": None,
        "zone": None,
        **SAFETY_FLAGS,
    }


def _zone_for_z(z: float) -> str:
    if z <= -3:
        return "EXTREME_LOWER_DISPLACEMENT"
    if z <= -2:
        return "LOWER_OUTER_ZONE"
    if z <= -1:
        return "LOWER_VALUE_ZONE"
    if z < 1:
        return "CENTRAL_ROTATION_ZONE"
    if z < 2:
        return "UPPER_VALUE_ZONE"
    if z < 3:
        return "UPPER_OUTER_ZONE"
    return "EXTREME_UPPER_DISPLACEMENT"


def build_terrain(bars: list[dict], timeframe: str = "15m") -> dict:
    if not isinstance(bars, list) or len(bars) < PERIOD:
        if isinstance(bars, list) and bars:
            ok, reason = validate_bars_series(bars)
            if not ok:
                return _unavailable(timeframe, reason or REASON_INVALID_OHLCV)
        return _unavailable(timeframe, REASON_INSUFFICIENT_HISTORY)

    ok, reason = validate_bars_series(bars)
    if not ok:
        return _unavailable(timeframe, reason or REASON_INVALID_OHLCV)

    closes = [bar["close"] for bar in bars]
    current_window = closes[-PERIOD:]
    middle = statistics.fmean(current_window)
    stddev = statistics.pstdev(current_window)

    if stddev <= 0 or not (stddev == stddev):  # zero or NaN guard
        return _unavailable(timeframe, REASON_STDDEV_UNAVAILABLE)

    current_close = closes[-1]
    z_score = (current_close - middle) / stddev
    bandwidth = 6 * stddev

    if len(bars) >= PERIOD + 1:
        prior_window = closes[-(PERIOD + 1):-1]
        prior_middle = statistics.fmean(prior_window)
        middle_slope = slope_from_values(middle, prior_middle)
    else:
        prior_middle = None
        middle_slope = "UNAVAILABLE"

    result = {
        "state": "AVAILABLE",
        "recordtype": "PRISM_TERRAIN_MAP",
        "schema_version": "prism_terrain_v1",
        "timeframe": timeframe,
        "last_completed_candle_utc": bars[-1]["timestamp"],
        "input_bar_count": len(bars),
        "required_bar_count": PERIOD,
        "configuration": {
            "period": PERIOD,
            "deviations": list(DEVIATIONS),
            "price_source": "close",
            "stddev_method": STDDEV_METHOD,
        },
        "reason_codes": [],
        "current_close": current_close,
        "middle_band": middle,
        "prior_middle_band": prior_middle,
        "stddev": stddev,
        "z_score": z_score,
        "minus_3_sigma": middle - 3 * stddev,
        "minus_2_sigma": middle - 2 * stddev,
        "minus_1_sigma": middle - 1 * stddev,
        "plus_1_sigma": middle + 1 * stddev,
        "plus_2_sigma": middle + 2 * stddev,
        "plus_3_sigma": middle + 3 * stddev,
        "bandwidth": bandwidth,
        "middle_slope": middle_slope,
        "zone": _zone_for_z(z_score),
        **SAFETY_FLAGS,
    }
    return result
