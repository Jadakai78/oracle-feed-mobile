from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any


WINDOW_SIZE = 365
FULL_HISTORY_COUNT = 25
FULL_BAR_COUNT = WINDOW_SIZE + FULL_HISTORY_COUNT


def _result(
    *,
    state: str,
    reason: str | None,
    timeframe: str,
    current_width: float | None = None,
    prior_widths: list[float] | None = None,
    history_state: str = "UNAVAILABLE",
    width_slope: str = "UNAVAILABLE",
    terrain_width_match: bool | None = None,
) -> dict[str, Any]:
    widths = list(prior_widths or [])
    return {
        "state": state,
        "reason": reason,
        "timeframe": timeframe,
        "window_size": WINDOW_SIZE,
        "current_width": current_width,
        "prior_widths": widths,
        "prior_width_count": len(widths),
        "history_state": history_state,
        "width_slope": width_slope,
        "terrain_width_match": terrain_width_match,
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
    }


def _timeframe_seconds(timeframe: str) -> int:
    if not isinstance(timeframe, str):
        raise ValueError("timeframe must be a string")

    normalized = timeframe.strip().lower()

    if normalized.endswith("m") and normalized[:-1].isdigit():
        minutes = int(normalized[:-1])
        if minutes > 0:
            return minutes * 60

    if normalized.endswith("h") and normalized[:-1].isdigit():
        hours = int(normalized[:-1])
        if hours > 0:
            return hours * 60 * 60

    raise ValueError(f"unsupported timeframe: {timeframe!r}")


def _as_finite_number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid number")

    number = float(value)

    if not math.isfinite(number):
        raise ValueError("number must be finite")

    return number


def _timestamp_seconds(value: Any) -> float:
    if isinstance(value, str):
        normalized = value.strip()

        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"

        parsed = datetime.fromisoformat(normalized)

        if parsed.tzinfo is None:
            raise ValueError("timestamp string must include a timezone")

        return parsed.astimezone(timezone.utc).timestamp()

    timestamp = _as_finite_number(value)

    if timestamp > 10_000_000_000:
        timestamp /= 1000.0

    return timestamp


def _validated_closes(bars: list[dict[str, Any]], timeframe: str) -> list[float]:
    if not isinstance(bars, list):
        raise ValueError("bars must be a list")

    if not bars:
        raise ValueError("bars cannot be empty")

    expected_step = _timeframe_seconds(timeframe)
    closes: list[float] = []
    previous_timestamp: float | None = None

    required_fields = {"timestamp", "open", "high", "low", "close", "volume"}

    for index, bar in enumerate(bars):
        if not isinstance(bar, dict):
            raise ValueError(f"bar {index} must be a mapping")

        missing = required_fields.difference(bar)
        if missing:
            raise ValueError(
                f"bar {index} missing required fields: {sorted(missing)}"
            )

        timestamp = _timestamp_seconds(bar["timestamp"])
        open_price = _as_finite_number(bar["open"])
        high_price = _as_finite_number(bar["high"])
        low_price = _as_finite_number(bar["low"])
        close_price = _as_finite_number(bar["close"])
        volume = _as_finite_number(bar["volume"])

        if min(open_price, high_price, low_price, close_price) <= 0.0:
            raise ValueError(f"bar {index} prices must be positive")

        if volume < 0.0:
            raise ValueError(f"bar {index} volume must be non-negative")

        if high_price < low_price:
            raise ValueError(f"bar {index} high is below low")

        if not low_price <= open_price <= high_price:
            raise ValueError(f"bar {index} open outside candle range")

        if not low_price <= close_price <= high_price:
            raise ValueError(f"bar {index} close outside candle range")

        if previous_timestamp is not None:
            step = timestamp - previous_timestamp
            if not math.isclose(
                step,
                expected_step,
                rel_tol=0.0,
                abs_tol=1e-6,
            ):
                raise ValueError(
                    f"bar {index} timestamp is not continuous for {timeframe}"
                )

        closes.append(close_price)
        previous_timestamp = timestamp

    return closes


def _width(closes: list[float]) -> float:
    if len(closes) != WINDOW_SIZE:
        raise ValueError(
            f"width requires exactly {WINDOW_SIZE} closes, got {len(closes)}"
        )

    return 6.0 * statistics.pstdev(closes)


def _slope(current_width: float, prior_widths: list[float]) -> str:
    if len(prior_widths) != FULL_HISTORY_COUNT:
        return "UNAVAILABLE"

    oldest_prior_width = prior_widths[0]

    if math.isclose(
        current_width,
        oldest_prior_width,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        return "FLAT"

    if current_width > oldest_prior_width:
        return "UP"

    return "DOWN"


def build_band_width_from_bars(
    bars: list[dict[str, Any]],
    timeframe: str = "15m",
    terrain: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        closes = _validated_closes(bars, timeframe)
    except (TypeError, ValueError) as exc:
        return _result(
            state="UNAVAILABLE",
            reason=f"invalid_bars: {exc}",
            timeframe=timeframe,
        )

    if len(closes) < WINDOW_SIZE:
        return _result(
            state="UNAVAILABLE",
            reason=f"insufficient_history: requires_{WINDOW_SIZE}_bars",
            timeframe=timeframe,
        )

    current_width = _width(closes[-WINDOW_SIZE:])

    prior_widths: list[float] = []
    current_start = len(closes) - WINDOW_SIZE

    for start in range(current_start):
        prior_widths.append(_width(closes[start:start + WINDOW_SIZE]))

    prior_widths = prior_widths[-FULL_HISTORY_COUNT:]

    if terrain is not None and terrain.get("state") == "AVAILABLE":
        try:
            terrain_width = _as_finite_number(terrain["bandwidth"])
        except (KeyError, TypeError, ValueError) as exc:
            return _result(
                state="UNAVAILABLE",
                reason=f"terrain_bandwidth_invalid: {exc}",
                timeframe=timeframe,
                terrain_width_match=False,
            )

        if not math.isclose(
            current_width,
            terrain_width,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            return _result(
                state="UNAVAILABLE",
                reason="terrain_bandwidth_mismatch",
                timeframe=timeframe,
                terrain_width_match=False,
            )

        terrain_width_match: bool | None = True
    else:
        terrain_width_match = None

    if len(prior_widths) == FULL_HISTORY_COUNT:
        state = "AVAILABLE"
        history_state = "AVAILABLE"
    else:
        state = "PARTIAL"
        history_state = "PARTIAL"

    return _result(
        state=state,
        reason=None,
        timeframe=timeframe,
        current_width=current_width,
        prior_widths=prior_widths,
        history_state=history_state,
        width_slope=_slope(current_width, prior_widths),
        terrain_width_match=terrain_width_match,
    )
