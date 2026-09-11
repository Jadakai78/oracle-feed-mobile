"""
prism_width_v1.py — PRISM clean-room width observation builder.

Descriptive-only dispersion (bandwidth) observation over a rolling 365-bar
window, plus a short window-history for slope/percentile context. Never
emits trade, execution, or ranking fields. No network access, no file
writes, no mutation of caller-owned inputs.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from prism_common_v1 import (
    REASON_INSUFFICIENT_HISTORY,
    REASON_INVALID_OHLCV,
    REASON_TERRAIN_WIDTH_MISMATCH,
    SAFETY_FLAGS,
    TOLERANCE,
    slope_from_values,
    validate_bars_series,
)

PERIOD = 365
MAX_PRIOR_WINDOWS = 25


def _base(state: str, timeframe: str, reason_codes: list[str], **overrides: Any) -> dict:
    result = {
        "state": state,
        "recordtype": "PRISM_WIDTH_OBSERVATION",
        "schema_version": "prism_width_v1",
        "timeframe": timeframe,
        "last_completed_candle_utc": None,
        "current_width": None,
        "prior_widths": [],
        "prior_width_count": 0,
        "width_slope": "UNAVAILABLE",
        "width_percentile": None,
        "reason_codes": reason_codes,
        **SAFETY_FLAGS,
    }
    result.update(overrides)
    return result


def _rolling_widths(closes: list[float], max_windows: int) -> list[float]:
    """Widths for rolling 365-close windows ending before the final window,
    most-recent-first-trimmed to `max_windows`, returned oldest-to-newest."""
    widths: list[float] = []
    total = len(closes)
    # number of prior complete windows available, excluding the current one
    available = total - PERIOD
    available = min(available, max_windows)
    for offset in range(available, 0, -1):
        window = closes[total - PERIOD - offset: total - offset]
        widths.append(6 * statistics.pstdev(window))
    return widths


def build_width_observation(
    bars: list[dict],
    timeframe: str = "15m",
    terrain: dict | None = None,
) -> dict:
    if not isinstance(bars, list) or len(bars) < PERIOD:
        return _base("UNAVAILABLE", timeframe, [REASON_INSUFFICIENT_HISTORY])

    ok, reason = validate_bars_series(bars)
    if not ok:
        return _base("UNAVAILABLE", timeframe, [reason or REASON_INVALID_OHLCV])

    closes = [bar["close"] for bar in bars]
    current_width = 6 * statistics.pstdev(closes[-PERIOD:])
    last_ts = bars[-1]["timestamp"]

    if terrain is not None and isinstance(terrain, dict) and terrain.get("state") == "AVAILABLE":
        terrain_bandwidth = terrain.get("bandwidth")
        if not isinstance(terrain_bandwidth, (int, float)) or isinstance(terrain_bandwidth, bool):
            return _base("UNAVAILABLE", timeframe, [REASON_TERRAIN_WIDTH_MISMATCH])
        if not math.isclose(terrain_bandwidth, current_width, rel_tol=TOLERANCE, abs_tol=TOLERANCE):
            return _base("UNAVAILABLE", timeframe, [REASON_TERRAIN_WIDTH_MISMATCH])

    n = len(bars)

    if n == PERIOD:
        return _base(
            "PARTIAL",
            timeframe,
            [],
            last_completed_candle_utc=last_ts,
            current_width=current_width,
            prior_widths=[],
            prior_width_count=0,
            width_slope="UNAVAILABLE",
            width_percentile=None,
        )

    prior_widths = _rolling_widths(closes, MAX_PRIOR_WINDOWS)
    prior_count = len(prior_widths)

    width_slope = "UNAVAILABLE"
    if prior_count > 0:
        width_slope = slope_from_values(current_width, prior_widths[-1])

    if n < PERIOD + MAX_PRIOR_WINDOWS:
        return _base(
            "PARTIAL",
            timeframe,
            [],
            last_completed_candle_utc=last_ts,
            current_width=current_width,
            prior_widths=prior_widths,
            prior_width_count=prior_count,
            width_slope=width_slope,
            width_percentile=None,
        )

    less = sum(1 for w in prior_widths if w < current_width)
    equal = sum(1 for w in prior_widths if w == current_width)
    percentile = (less + 0.5 * equal) / MAX_PRIOR_WINDOWS

    return _base(
        "AVAILABLE",
        timeframe,
        [],
        last_completed_candle_utc=last_ts,
        current_width=current_width,
        prior_widths=prior_widths,
        prior_width_count=prior_count,
        width_slope=width_slope,
        width_percentile=percentile,
    )
