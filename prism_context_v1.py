"""
PRISM Context v1

Deterministic, completed-candle-only terrain context for PRISM Lab.

This module:
- Performs no live market reads.
- Performs no order, alert, queue, scoring, sizing, or execution action.
- Does not select trades or grant entry authority.
- Returns a structured terrain/context record for manual review only.

Expected candle shape:
{
    "open": float,
    "high": float,
    "low": float,
    "close": float,
    "volume": float,
    optional "timestamp": str
}
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

RECORDTYPE = "PRISMCONTEXT"
SCHEMA_VERSION = "prism.context.v1"

MIN_REQUIRED_BARS = 40
SUPER_TREND_PERIOD = 10
SUPER_TREND_MULTIPLIER = 3.0
REGIME_WINDOW = 20
LOCATION_WINDOW = 40
VOLUME_WINDOW = 20

HEALTH_AVAILABLE = "AVAILABLE"
HEALTH_MISSING_BARS = "MISSING_BARS"
HEALTH_INVALID_CANDLES = "INVALID_CANDLES"

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


def _as_positive_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid_{field_name}")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"invalid_{field_name}")
    return numeric


def _validate_candle(candle: Mapping[str, Any], index: int) -> dict[str, float]:
    if not isinstance(candle, Mapping):
        raise ValueError(f"candle_{index}_must_be_object")

    required = ("open", "high", "low", "close", "volume")
    missing = [field for field in required if field not in candle]
    if missing:
        raise ValueError(f"candle_{index}_missing_{'_'.join(missing)}")

    open_price = _as_positive_number(candle["open"], f"open_{index}")
    high = _as_positive_number(candle["high"], f"high_{index}")
    low = _as_positive_number(candle["low"], f"low_{index}")
    close = _as_positive_number(candle["close"], f"close_{index}")
    volume = _as_positive_number(candle["volume"], f"volume_{index}")

    if high < low:
        raise ValueError(f"candle_{index}_high_below_low")
    if high < max(open_price, close):
        raise ValueError(f"candle_{index}_high_below_open_or_close")
    if low > min(open_price, close):
        raise ValueError(f"candle_{index}_low_above_open_or_close")

    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _validate_candles(candles: Sequence[Mapping[str, Any]]) -> list[dict[str, float]]:
    if not isinstance(candles, Sequence) or isinstance(candles, (str, bytes)):
        raise ValueError("candles_must_be_sequence")

    return [_validate_candle(candle, index) for index, candle in enumerate(candles)]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _stddev(values: Sequence[float], mean_value: float) -> float:
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def _true_range(current: Mapping[str, float], previous_close: float) -> float:
    return max(
        current["high"] - current["low"],
        abs(current["high"] - previous_close),
        abs(current["low"] - previous_close),
    )


def calculate_supertrend(
    candles: Sequence[Mapping[str, float]],
    period: int = SUPER_TREND_PERIOD,
    multiplier: float = SUPER_TREND_MULTIPLIER,
) -> dict[str, Any]:
    if len(candles) <= period:
        return {
            "value": None,
            "direction": "NEUTRAL",
            "distance_pct": None,
            "atr": None,
        }

    true_ranges = [
        _true_range(candles[index], candles[index - 1]["close"])
        for index in range(1, len(candles))
    ]
    recent_true_ranges = true_ranges[-period:]
    atr = _mean(recent_true_ranges)

    current = candles[-1]
    close = current["close"]
    midpoint = (current["high"] + current["low"]) / 2.0
    upper_band = midpoint + (multiplier * atr)
    lower_band = midpoint - (multiplier * atr)

    direction = "LONG" if close >= lower_band else "SHORT"
    value = lower_band if direction == "LONG" else upper_band
    distance_pct = 0.0 if close == 0 else abs(close - value) / close * 100.0

    return {
        "value": round(value, 8),
        "direction": direction,
        "distance_pct": round(distance_pct, 4),
        "atr": round(atr, 8),
    }


def evaluate_regime_and_zone(
    candles: Sequence[Mapping[str, float]],
    window: int = REGIME_WINDOW,
) -> dict[str, Any]:
    if len(candles) < window:
        return {
            "noise_regime": "UNKNOWN",
            "structural_zone": "NEUTRAL",
            "noise_multiplier": 1.0,
            "price_range_pct": None,
            "volume_ratio": None,
        }

    recent = candles[-window:]
    closes = [candle["close"] for candle in recent]
    volumes = [candle["volume"] for candle in recent]

    mean_close = _mean(closes)
    stddev = _stddev(closes, mean_close)
    range_high = max(candle["high"] for candle in recent)
    range_low = min(candle["low"] for candle in recent)
    price_range_pct = 0.0 if mean_close == 0 else (range_high - range_low) / mean_close
    average_volume = _mean(volumes)
    latest_volume = recent[-1]["volume"]
    volume_ratio = latest_volume / max(average_volume, 1.0)
    latest_close = recent[-1]["close"]

    if price_range_pct < 0.003 and volume_ratio < 0.7:
        noise_regime = "CHOPPY_NOISE"
        noise_multiplier = 0.5
    elif price_range_pct > 0.02:
        noise_regime = "HIGH_DISPERSION"
        noise_multiplier = 0.8
    else:
        noise_regime = "NORMAL_TAPE"
        noise_multiplier = 1.0

    extension = 1.5 * stddev
    if latest_close > mean_close + extension:
        structural_zone = "UPPER_EXTENDED"
    elif latest_close < mean_close - extension:
        structural_zone = "LOWER_EXTENDED"
    else:
        structural_zone = "CENTRAL_VALUE"

    return {
        "noise_regime": noise_regime,
        "structural_zone": structural_zone,
        "noise_multiplier": noise_multiplier,
        "price_range_pct": round(price_range_pct * 100.0, 4),
        "volume_ratio": round(volume_ratio, 4),
    }


def calculate_location(
    candles: Sequence[Mapping[str, float]],
    window: int = LOCATION_WINDOW,
) -> dict[str, Any]:
    if len(candles) < window:
        return {
            "mean_close": None,
            "stddev": None,
            "location_sigma": None,
            "distance_from_mean_pct": None,
        }

    recent = candles[-window:]
    closes = [candle["close"] for candle in recent]
    latest_close = closes[-1]
    mean_close = _mean(closes)
    stddev = _stddev(closes, mean_close)

    if stddev == 0:
        location_sigma = 0.0
    else:
        location_sigma = (latest_close - mean_close) / stddev

    distance_from_mean_pct = (
        0.0 if mean_close == 0 else (latest_close - mean_close) / mean_close * 100.0
    )

    return {
        "mean_close": round(mean_close, 8),
        "stddev": round(stddev, 8),
        "location_sigma": round(location_sigma, 4),
        "distance_from_mean_pct": round(distance_from_mean_pct, 4),
    }


def calculate_participation(
    candles: Sequence[Mapping[str, float]],
    window: int = VOLUME_WINDOW,
) -> dict[str, Any]:
    if len(candles) < window:
        return {
            "latest_volume": None,
            "average_volume": None,
            "volume_expansion_ratio": None,
            "participation_state": "UNKNOWN",
        }

    recent = candles[-window:]
    latest_volume = recent[-1]["volume"]
    average_volume = _mean([candle["volume"] for candle in recent])
    ratio = latest_volume / max(average_volume, 1.0)

    if ratio >= 1.25:
        participation_state = "EXPANDING"
    elif ratio <= 0.75:
        participation_state = "CONTRACTING"
    else:
        participation_state = "NORMAL"

    return {
        "latest_volume": round(latest_volume, 8),
        "average_volume": round(average_volume, 8),
        "volume_expansion_ratio": round(ratio, 4),
        "participation_state": participation_state,
    }


def derive_terrain_state(
    speed_phase: str,
    trend_alignment: str,
    structural_zone: str,
    noise_regime: str,
) -> str:
    normalized_phase = (speed_phase or "NONE").upper()

    if noise_regime == "CHOPPY_NOISE":
        return "NOISY_RANGE"

    if normalized_phase == "REACCELERATION":
        return "PULLBACK_REACCELERATION"

    if normalized_phase == "CONTROLLED_PULLBACK":
        return "CONTROLLED_PULLBACK"

    if normalized_phase == "DECAY":
        return "DECAY"

    if structural_zone in {"UPPER_EXTENDED", "LOWER_EXTENDED"}:
        return "EXTENDED_TERRAIN"

    if trend_alignment == "NEUTRAL":
        return "UNRESOLVED"

    return "BALANCED_TERRAIN"


def derive_route(
    terrain_state: str,
    trend_alignment: str,
    structural_zone: str,
    noise_regime: str,
) -> tuple[str, str]:
    if noise_regime == "CHOPPY_NOISE":
        return (
            "RANGE_FADE",
            "Choppy regime restricts routing to range/fade observation only.",
        )

    if terrain_state == "PULLBACK_REACCELERATION":
        return (
            "RECLAIM_REVERSAL",
            "Reacceleration terrain supports reclaim/reversal inspection.",
        )

    if terrain_state == "CONTROLLED_PULLBACK":
        return (
            "EXPANSION_CONTINUATION",
            "Controlled pullback may support continuation inspection when timing confirms.",
        )

    if terrain_state == "DECAY":
        return (
            "NO_ROUTE",
            "Decay terrain does not provide a proactive route.",
        )

    if terrain_state == "EXTENDED_TERRAIN":
        return (
            "NO_CHASE",
            "Extended location requires restraint and does not authorize a chase route.",
        )

    if structural_zone == "CENTRAL_VALUE" and trend_alignment != "NEUTRAL":
        return (
            "OBSERVE",
            "Central-value terrain is observable but requires Delta/Tempo confirmation.",
        )

    return (
        "OBSERVE",
        "Terrain is unresolved; preserve observation without route authority.",
    )


def _unavailable_context(
    pair: str,
    timeframe: str,
    state: str,
    reason_codes: list[str],
    completed_bars: int,
) -> dict[str, Any]:
    return {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _now_utc(),
        "pair": pair,
        "timeframe": timeframe,
        "data_health": {
            "state": state,
            "reason_codes": reason_codes,
            "completed_bars": completed_bars,
            "required_bars": MIN_REQUIRED_BARS,
        },
        "terrain": {
            "trend_alignment": "NEUTRAL",
            "supertrend_value": None,
            "supertrend_distance_pct": None,
            "structural_zone": "NEUTRAL",
            "noise_regime": "UNKNOWN",
            "location_sigma": None,
            "distance_from_mean_pct": None,
            "terrain_state": "UNAVAILABLE",
            "route": "NO_ROUTE",
            "route_reason": "PRISM context unavailable.",
        },
        "participation": {
            "latest_volume": None,
            "average_volume": None,
            "volume_expansion_ratio": None,
            "participation_state": "UNKNOWN",
        },
        "manual_review_only": MANUAL_REVIEW_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
    }


def build_prism_context(
    pair: str,
    candles: Sequence[Mapping[str, Any]],
    speed_phase: str,
    timeframe: str = "5m",
) -> dict[str, Any]:
    """
    Build a deterministic PRISM terrain context.

    `candles` must contain completed candles only. This module trusts the caller
    to provide completed bars; it does not fetch data or infer bar completion.
    """
    if not isinstance(pair, str) or not pair.strip():
        raise ValueError("pair_must_be_nonempty_string")

    if not isinstance(timeframe, str) or not timeframe.strip():
        raise ValueError("timeframe_must_be_nonempty_string")

    if not isinstance(speed_phase, str) or not speed_phase.strip():
        speed_phase = "NONE"

    completed_bars = len(candles) if isinstance(candles, Sequence) else 0

    if completed_bars < MIN_REQUIRED_BARS:
        return _unavailable_context(
            pair=pair,
            timeframe=timeframe,
            state=HEALTH_MISSING_BARS,
            reason_codes=["PRISM.DATA.MISSING_BARS"],
            completed_bars=completed_bars,
        )

    try:
        validated = _validate_candles(candles)
    except ValueError as exc:
        return _unavailable_context(
            pair=pair,
            timeframe=timeframe,
            state=HEALTH_INVALID_CANDLES,
            reason_codes=[f"PRISM.DATA.INVALID_CANDLES:{exc}"],
            completed_bars=completed_bars,
        )

    supertrend = calculate_supertrend(validated)
    regime = evaluate_regime_and_zone(validated)
    location = calculate_location(validated)
    participation = calculate_participation(validated)

    trend_alignment = supertrend["direction"]
    terrain_state = derive_terrain_state(
        speed_phase=speed_phase,
        trend_alignment=trend_alignment,
        structural_zone=regime["structural_zone"],
        noise_regime=regime["noise_regime"],
    )
    route, route_reason = derive_route(
        terrain_state=terrain_state,
        trend_alignment=trend_alignment,
        structural_zone=regime["structural_zone"],
        noise_regime=regime["noise_regime"],
    )

    return {
        "recordtype": RECORDTYPE,
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
        "terrain": {
            "trend_alignment": trend_alignment,
            "supertrend_value": supertrend["value"],
            "supertrend_distance_pct": supertrend["distance_pct"],
            "structural_zone": regime["structural_zone"],
            "noise_regime": regime["noise_regime"],
            "location_sigma": location["location_sigma"],
            "distance_from_mean_pct": location["distance_from_mean_pct"],
            "terrain_state": terrain_state,
            "route": route,
            "route_reason": route_reason,
        },
        "participation": participation,
        "speed_phase": speed_phase.upper(),
        "manual_review_only": MANUAL_REVIEW_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
    }
