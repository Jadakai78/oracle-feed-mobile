"""
Deterministic Speed Companion lab contract.

Completed 5-minute OHLCV candles only.
No I/O, no live-feed access, no scoring, and no trade execution.

V1 implements long impulse, WATCH, and CONTROLLED_PULLBACK states.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


ATR_PERIOD = 14

IMPULSE_MIN_ATR = 1.5
IMPULSE_MIN_BODY_FRACTION = 0.60
MAX_PULLBACK_FRACTION = 0.50
MAX_PULLBACK_BARS = 6
MAX_WATCH_BARS = 12
PULLBACK_VOLUME_MAX_FRACTION = 0.80
PULLBACK_MAX_FRACTION = 0.50
RECLAIM_MIN_BODY_FRACTION = 0.60


PHASE_NONE = "NONE"
PHASE_IMPULSE = "IMPULSE"
PHASE_WATCH = "WATCH"
PHASE_CONTROLLED_PULLBACK = "CONTROLLED_PULLBACK"
PHASE_REACCELERATION = "REACCELERATION"
PHASE_DECAY = "DECAY"


def _empty_result() -> Dict[str, Any]:
    return {
        "direction": "NONE",
        "phase": PHASE_NONE,
        "impulse_age_bars": None,
        "impulse_size_atr": None,
        "pullback_depth_fraction": None,
        "pullback_bars": None,
        "pullback_volume_vs_impulse": None,
        "reclaim_confirmed": False,
        "decay_reason": None,
    }


def _true_range(
    candle: Dict[str, float],
    previous_close: float,
) -> float:
    return max(
        candle["high"] - candle["low"],
        abs(candle["high"] - previous_close),
        abs(candle["low"] - previous_close),
    )


def _atr_before_index(
    candles: List[Dict[str, float]],
    index: int,
) -> Optional[float]:
    if index < ATR_PERIOD:
        return None

    start = index - ATR_PERIOD
    true_ranges: List[float] = []

    for candle_index in range(start, index):
        if candle_index == 0:
            continue

        true_ranges.append(
            _true_range(
                candles[candle_index],
                candles[candle_index - 1]["close"],
            )
        )

    if len(true_ranges) < ATR_PERIOD - 1:
        return None

    return sum(true_ranges) / len(true_ranges)


def _body_fraction(candle: Dict[str, float]) -> float:
    candle_range = candle["high"] - candle["low"]
    if candle_range <= 0:
        return 0.0

    return abs(candle["close"] - candle["open"]) / candle_range


def _find_latest_long_impulse(
    candles: List[Dict[str, float]],
) -> Optional[Dict[str, Any]]:
    for index in range(len(candles) - 1, ATR_PERIOD - 1, -1):
        candle = candles[index]
        atr = _atr_before_index(candles, index)

        if atr is None or atr <= 0:
            continue

        candle_range = candle["high"] - candle["low"]
        is_bullish = candle["close"] > candle["open"]
        has_strong_body = _body_fraction(candle) >= IMPULSE_MIN_BODY_FRACTION
        has_large_range = candle_range >= atr * IMPULSE_MIN_ATR

        if is_bullish and has_strong_body and has_large_range:
            return {
                "index": index,
                "size_atr": candle_range / atr,
            }

    return None


def _long_controlled_pullback(
    candles: List[Dict[str, float]],
    impulse_index: int,
) -> Optional[Dict[str, Any]]:
    """
    Return pullback measurements only when all completed post-impulse bars
    form a bounded, lower-participation, non-bullish pullback.
    """
    impulse = candles[impulse_index]
    pullback = candles[impulse_index + 1:]

    if not pullback or len(pullback) > MAX_PULLBACK_BARS:
        return None

    if any(candle["close"] > candle["open"] for candle in pullback):
        return None

    impulse_origin = impulse["open"]
    impulse_high = impulse["high"]
    impulse_distance = impulse_high - impulse_origin
    if impulse_distance <= 0 or impulse["volume"] <= 0:
        return None

    lowest_close = min(candle["close"] for candle in pullback)
    if lowest_close <= impulse_origin:
        return None

    pullback_depth_fraction = (impulse_high - lowest_close) / impulse_distance
    if pullback_depth_fraction > MAX_PULLBACK_FRACTION:
        return None

    average_pullback_volume = (
        sum(candle["volume"] for candle in pullback) / len(pullback)
    )
    pullback_volume_vs_impulse = (
        average_pullback_volume / impulse["volume"]
    )
    if pullback_volume_vs_impulse > PULLBACK_VOLUME_MAX_FRACTION:
        return None

    return {
        "pullback_depth_fraction": round(pullback_depth_fraction, 6),
        "pullback_bars": len(pullback),
        "pullback_volume_vs_impulse": round(
            pullback_volume_vs_impulse,
            6,
        ),
    }


def _find_latest_short_impulse(
    candles: List[Dict[str, float]],
) -> Optional[Dict[str, Any]]:
    for index in range(len(candles) - 1, ATR_PERIOD - 1, -1):
        candle = candles[index]
        atr = _atr_before_index(candles, index)

        if atr is None or atr <= 0:
            continue

        candle_range = candle["high"] - candle["low"]
        is_bearish = candle["close"] < candle["open"]
        has_strong_body = (
            _body_fraction(candle) >= IMPULSE_MIN_BODY_FRACTION
        )
        has_large_range = candle_range >= atr * IMPULSE_MIN_ATR

        if is_bearish and has_strong_body and has_large_range:
            return {
                "index": index,
                "size_atr": candle_range / atr,
            }

    return None


def _short_controlled_pullback(
    candles: List[Dict[str, float]],
    impulse_index: int,
) -> Optional[Dict[str, Any]]:
    impulse = candles[impulse_index]
    pullback = candles[impulse_index + 1:]

    if not pullback or len(pullback) > MAX_PULLBACK_BARS:
        return None

    if any(candle["close"] < candle["open"] for candle in pullback):
        return None

    impulse_origin = impulse["open"]
    impulse_low = impulse["low"]
    impulse_distance = impulse_origin - impulse_low

    if impulse_distance <= 0 or impulse["volume"] <= 0:
        return None

    highest_close = max(candle["close"] for candle in pullback)
    if highest_close >= impulse_origin:
        return None

    pullback_depth_fraction = (
        highest_close - impulse_low
    ) / impulse_distance

    if pullback_depth_fraction > MAX_PULLBACK_FRACTION:
        return None

    average_pullback_volume = (
        sum(candle["volume"] for candle in pullback) / len(pullback)
    )
    pullback_volume_vs_impulse = (
        average_pullback_volume / impulse["volume"]
    )

    if pullback_volume_vs_impulse > PULLBACK_VOLUME_MAX_FRACTION:
        return None

    return {
        "pullback_depth_fraction": round(pullback_depth_fraction, 6),
        "pullback_bars": len(pullback),
        "pullback_volume_vs_impulse": round(
            pullback_volume_vs_impulse,
            6,
        ),
    }
def analyze_completed_candles(
    candles: List[Dict[str, float]],
) -> Dict[str, Any]:
    """
    Analyze completed OHLCV candles.

    V1 behavior:
    - Identify the newest qualifying long impulse.
    - Return CONTROLLED_PULLBACK for a valid bounded pullback.
    - Otherwise return WATCH while the impulse remains in its watch window.
    """
    result = _empty_result()

    if len(candles) < ATR_PERIOD + 1:
        return result

    for impulse_index in range(ATR_PERIOD, len(candles) - 4):
        short_impulse_candle = candles[impulse_index]
        pullback_one = candles[impulse_index + 1]
        pullback_two = candles[impulse_index + 2]
        reclaim_one = candles[impulse_index + 3]
        reclaim_two = candles[impulse_index + 4]

        atr = _atr_before_index(candles, impulse_index)
        impulse_range = (
            short_impulse_candle["high"] - short_impulse_candle["low"]
        )

        if (
            atr is None
            or atr <= 0
            or short_impulse_candle["close"] >= short_impulse_candle["open"]
            or _body_fraction(short_impulse_candle) < IMPULSE_MIN_BODY_FRACTION
            or impulse_range < atr * IMPULSE_MIN_ATR
            or short_impulse_candle["volume"] <= 0
        ):
            continue

        impulse_low = short_impulse_candle["low"]
        impulse_origin = short_impulse_candle["open"]
        impulse_distance = impulse_origin - impulse_low

        if impulse_distance <= 0:
            continue

        if not (
            reclaim_one["close"] < reclaim_one["open"]
            and reclaim_two["close"] < reclaim_two["open"]
            and _body_fraction(reclaim_one) >= RECLAIM_MIN_BODY_FRACTION
            and _body_fraction(reclaim_two) >= RECLAIM_MIN_BODY_FRACTION
            and reclaim_one["close"] < impulse_low
            and reclaim_two["close"] < impulse_low
            and reclaim_two["close"] <= reclaim_one["close"]
        ):
            continue

        highest_pullback_close = max(
            pullback_one["close"],
            pullback_two["close"],
        )
        if highest_pullback_close >= impulse_origin:
            continue

        pullback_depth_fraction = (
            highest_pullback_close - impulse_low
        ) / impulse_distance

        average_pullback_volume = (
            pullback_one["volume"] + pullback_two["volume"]
        ) / 2
        pullback_volume_vs_impulse = (
            average_pullback_volume / short_impulse_candle["volume"]
        )

        if (
            pullback_depth_fraction > PULLBACK_MAX_FRACTION
            or pullback_volume_vs_impulse > PULLBACK_VOLUME_MAX_FRACTION
        ):
            continue

        result["direction"] = "SHORT"
        result["phase"] = PHASE_REACCELERATION
        result["impulse_age_bars"] = len(candles) - 1 - impulse_index
        result["impulse_size_atr"] = round(impulse_range / atr, 6)
        result["reclaim_confirmed"] = True
        result["decay_reason"] = None
        result["pullback_depth_fraction"] = round(
            pullback_depth_fraction,
            6,
        )
        result["pullback_bars"] = 2
        result["pullback_volume_vs_impulse"] = round(
            pullback_volume_vs_impulse,
            6,
        )
        return result
    for impulse_index in range(ATR_PERIOD, len(candles) - 4):
        impulse_candle = candles[impulse_index]
        pullback_one = candles[impulse_index + 1]
        pullback_two = candles[impulse_index + 2]
        reclaim_one = candles[impulse_index + 3]
        reclaim_two = candles[impulse_index + 4]

        impulse_high = impulse_candle["high"]
        impulse_origin = impulse_candle["open"]
        impulse_distance = impulse_high - impulse_origin

        if impulse_distance <= 0 or impulse_candle["volume"] <= 0:
            continue

        if not (
            reclaim_one["close"] > reclaim_one["open"]
            and reclaim_two["close"] > reclaim_two["open"]
            and _body_fraction(reclaim_one) >= IMPULSE_MIN_BODY_FRACTION
            and _body_fraction(reclaim_two) >= IMPULSE_MIN_BODY_FRACTION
            and reclaim_one["close"] > impulse_high
            and reclaim_two["close"] > impulse_high
            and reclaim_two["close"] >= reclaim_one["close"]
        ):
            continue

        lowest_pullback_close = min(
            pullback_one["close"],
            pullback_two["close"],
        )
        if lowest_pullback_close <= impulse_origin:
            continue

        pullback_depth_fraction = (
            impulse_high - lowest_pullback_close
        ) / impulse_distance

        average_pullback_volume = (
            pullback_one["volume"] + pullback_two["volume"]
        ) / 2
        pullback_volume_vs_impulse = (
            average_pullback_volume / impulse_candle["volume"]
        )

        if (
            pullback_depth_fraction > PULLBACK_MAX_FRACTION
            or pullback_volume_vs_impulse > PULLBACK_VOLUME_MAX_FRACTION
        ):
            continue

        result["direction"] = "LONG"
        result["phase"] = PHASE_REACCELERATION
        result["impulse_age_bars"] = len(candles) - 1 - impulse_index
        result["reclaim_confirmed"] = True
        result["decay_reason"] = None
        result["pullback_depth_fraction"] = round(
            pullback_depth_fraction,
            6,
        )
        result["pullback_bars"] = 2
        result["pullback_volume_vs_impulse"] = round(
            pullback_volume_vs_impulse,
            6,
        )
        return result
    short_impulse = _find_latest_short_impulse(candles)
    if short_impulse is not None:
        short_impulse_age_bars = (
            len(candles) - 1 - short_impulse["index"]
        )

        if short_impulse_age_bars > MAX_WATCH_BARS:
            result["direction"] = "SHORT"
            result["phase"] = PHASE_DECAY
            result["impulse_age_bars"] = short_impulse_age_bars
            result["impulse_size_atr"] = round(
                short_impulse["size_atr"],
                6,
            )
            result["reclaim_confirmed"] = False
            result["decay_reason"] = "watch_window_expired"
            return result

        result["direction"] = "SHORT"
        result["impulse_age_bars"] = short_impulse_age_bars
        result["impulse_size_atr"] = round(
            short_impulse["size_atr"],
            6,
        )

        short_pullback = _short_controlled_pullback(
            candles,
            short_impulse["index"],
        )
        if short_pullback is not None:
            result["phase"] = PHASE_CONTROLLED_PULLBACK
            result.update(short_pullback)
            return result

        result["phase"] = PHASE_WATCH
        return result
    expired_long_impulse = None

    for impulse_index in range(ATR_PERIOD, len(candles)):
        candidate = candles[impulse_index]
        atr = _atr_before_index(candles, impulse_index)

        if atr is None or atr <= 0:
            continue

        candidate_range = candidate["high"] - candidate["low"]

        if (
            candidate["close"] > candidate["open"]
            and _body_fraction(candidate) >= IMPULSE_MIN_BODY_FRACTION
            and candidate_range >= atr * IMPULSE_MIN_ATR
        ):
            candidate_age = len(candles) - 1 - impulse_index

            if candidate_age > MAX_WATCH_BARS:
                expired_long_impulse = {
                    "index": impulse_index,
                    "size_atr": candidate_range / atr,
                    "age": candidate_age,
                }
                break

    if expired_long_impulse is not None:
        result["direction"] = "LONG"
        result["phase"] = PHASE_DECAY
        result["impulse_age_bars"] = expired_long_impulse["age"]
        result["impulse_size_atr"] = round(
            expired_long_impulse["size_atr"],
            6,
        )
        result["reclaim_confirmed"] = False
        result["decay_reason"] = "watch_window_expired"
        return result
    impulse = _find_latest_long_impulse(candles)
    if impulse is None:
        return result

    impulse_age_bars = len(candles) - 1 - impulse["index"]
    if impulse_age_bars > MAX_WATCH_BARS:
        return result

    result["direction"] = "LONG"
    result["impulse_age_bars"] = impulse_age_bars
    result["impulse_size_atr"] = round(impulse["size_atr"], 6)

    pullback = _long_controlled_pullback(candles, impulse["index"])
    if pullback is not None:
        result["phase"] = PHASE_CONTROLLED_PULLBACK
        result.update(pullback)
        return result

    result["phase"] = PHASE_WATCH
    return result






