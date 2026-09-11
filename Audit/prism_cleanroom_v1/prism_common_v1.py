"""
prism_common_v1.py — shared, standard-library-only helpers for the PRISM
clean-room build. Not part of the numbered required-file list, but kept as a
small internal helper module per section 3 ("You may add small helper
modules, but every module must remain standard-library-only and must be
covered by tests.").

No network access. No file writes. No mutation of caller-owned data.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

TOLERANCE = 1e-9
BAR_INTERVAL = timedelta(minutes=15)

REASON_INVALID_OHLCV = "PRISM.DATA.INVALID_OHLCV"
REASON_INSUFFICIENT_HISTORY = "PRISM.DATA.INSUFFICIENT_HISTORY"
REASON_MISSING_BARS = "PRISM.DATA.MISSING_BARS"
REASON_STDDEV_UNAVAILABLE = "PRISM.RUNTIME.BAND_STDDEV_UNAVAILABLE"
REASON_TERRAIN_WIDTH_MISMATCH = "PRISM.RUNTIME.TERRAIN_WIDTH_MISMATCH"

SAFETY_FLAGS = {
    "manual_review_only": True,
    "does_not_authorize_trade": True,
    "does_not_simulate_order": True,
}

# Recursively forbidden anywhere in a public output record.
FORBIDDEN_KEYS = {
    "side",
    "entry",
    "stop",
    "target",
    "tp",
    "sl",
    "take_profit",
    "stop_loss",
    "score",
    "rank",
    "ranking",
    "route",
    "signal",
    "signal_type",
    "execution_eligible",
    "trade_authority",
    "entry_authority",
    "order",
    "position",
    "position_size",
    "leverage",
    "alert",
    "webhook",
    "notification",
    "buy",
    "sell",
    "long",
    "short",
    "recommended_action",
    "confidence_score",
    "trade_setup",
}


def parse_utc(value: Any) -> datetime | None:
    """Parse an explicit-timezone UTC ISO-8601 timestamp. Returns None on failure."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _bar_shape_valid(bar: Any) -> bool:
    if not isinstance(bar, dict):
        return False
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required.issubset(bar):
        return False
    if parse_utc(bar["timestamp"]) is None:
        return False
    for key in ("open", "high", "low", "close", "volume"):
        if not is_finite_number(bar[key]):
            return False
        if bar[key] <= 0:
            return False
    open_, high, low, close = bar["open"], bar["high"], bar["low"], bar["close"]
    if low > min(open_, close) + TOLERANCE:
        return False
    if high < max(open_, close) - TOLERANCE:
        return False
    if high < low - TOLERANCE:
        return False
    return True


def validate_bars_series(bars: Any) -> tuple[bool, str | None]:
    """
    Validate a canonical, oldest-to-newest, fully-completed 15-minute bar
    series. Returns (ok, reason_code). Does not mutate `bars`.
    """
    if not isinstance(bars, list) or len(bars) == 0:
        return False, REASON_INVALID_OHLCV

    for bar in bars:
        if not _bar_shape_valid(bar):
            return False, REASON_INVALID_OHLCV

    timestamps = [parse_utc(bar["timestamp"]) for bar in bars]
    for earlier, later in zip(timestamps, timestamps[1:]):
        if later - earlier != BAR_INTERVAL:
            return False, REASON_MISSING_BARS

    return True, None


def scan_forbidden_keys(obj: Any, path: str = "$") -> list[str]:
    """Recursively find any forbidden trade/execution-shaped key in obj."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = str(key).lower()
            if key_lower in FORBIDDEN_KEYS:
                found.append(f"{path}.{key}")
            found.extend(scan_forbidden_keys(value, f"{path}.{key}"))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            found.extend(scan_forbidden_keys(item, f"{path}[{index}]"))
    return found


def slope_from_values(current: float, prior: float) -> str:
    if math.isclose(current, prior, rel_tol=TOLERANCE, abs_tol=TOLERANCE):
        return "FLAT"
    return "UP" if current > prior else "DOWN"
