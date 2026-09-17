from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from experiment_config import (
    ENTRY_AUTHORITY,
    MEDIUM_WINDOW_BARS,
    MIN_REQUIRED_BARS,
    NEUTRAL_PRESSURE_ZONE,
    PRISM_SCALE_WINDOW_BARS,
    RECORD_TYPE,
    RESEARCH_ONLY,
    SCHEMA_VERSION,
    SHORT_WINDOW_BARS,
    SOURCE,
    TIMEFRAME,
    TRADE_AUTHORITY,
)


EPSILON = 1e-12


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def candle_field(candle: Any, name: str) -> float:
    if isinstance(candle, dict):
        return as_float(candle.get(name))
    return as_float(getattr(candle, name, 0.0))


def pressure_state(
    signed_pressure: float,
    neutral_zone: float = NEUTRAL_PRESSURE_ZONE,
) -> str:
    if signed_pressure > neutral_zone:
        return "BUYER_DOMINANT"
    if signed_pressure < -neutral_zone:
        return "SELLER_DOMINANT"
    return "NEUTRAL"


def calculate_pressure(
    candles: Iterable[Any],
    window_bars: int,
) -> dict[str, Any]:
    window = list(candles)[-window_bars:]

    if len(window) < window_bars:
        return {
            "window_bars": window_bars,
            "completed_bars": len(window),
            "state": "UNAVAILABLE",
            "signed_pressure": None,
            "imbalance_pct": None,
            "total_volume": None,
            "reason": "INSUFFICIENT_COMPLETED_BARS",
        }

    signed_volume = 0.0
    total_volume = 0.0

    for candle in window:
        open_price = candle_field(candle, "open")
        high_price = candle_field(candle, "high")
        low_price = candle_field(candle, "low")
        close_price = candle_field(candle, "close")
        volume = max(0.0, candle_field(candle, "volume"))

        price_range = max(high_price - low_price, EPSILON)
        close_location_change = (close_price - open_price) / price_range

        signed_volume += volume * close_location_change
        total_volume += volume

    signed_pressure = (
        max(-1.0, min(1.0, signed_volume / total_volume))
        if total_volume > EPSILON
        else 0.0
    )

    return {
        "window_bars": window_bars,
        "completed_bars": len(window),
        "state": pressure_state(signed_pressure),
        "signed_pressure": round(signed_pressure, 6),
        "imbalance_pct": round(abs(signed_pressure) * 100, 4),
        "total_volume": round(total_volume, 8),
        "reason": None,
    }


def pair_alignment(left: str, right: str) -> str:
    if "UNAVAILABLE" in {left, right}:
        return "UNAVAILABLE"
    if "NEUTRAL" in {left, right}:
        return "NEUTRAL"
    if left == right:
        return "ALIGNED"
    return "CONFLICT"


def three_horizon_state(
    short_state: str,
    medium_state: str,
    prism_state: str,
) -> str:
    states = {short_state, medium_state, prism_state}

    if "UNAVAILABLE" in states:
        return "UNAVAILABLE"

    if states == {"NEUTRAL"}:
        return "ALL_NEUTRAL"

    if short_state == "NEUTRAL":
        return "SHORT_NEUTRAL"

    if medium_state == "NEUTRAL":
        return "MEDIUM_NEUTRAL"

    if prism_state == "NEUTRAL":
        return "PRISM_SCALE_NEUTRAL"

    if states == {"BUYER_DOMINANT"}:
        return "FULL_ALIGNMENT_LONG"

    if states == {"SELLER_DOMINANT"}:
        return "FULL_ALIGNMENT_SHORT"

    if (
        short_state == "BUYER_DOMINANT"
        and medium_state == "BUYER_DOMINANT"
        and prism_state == "SELLER_DOMINANT"
    ):
        return "MEDIUM_TERM_BULLISH_TRANSITION"

    if (
        short_state == "SELLER_DOMINANT"
        and medium_state == "SELLER_DOMINANT"
        and prism_state == "BUYER_DOMINANT"
    ):
        return "MEDIUM_TERM_BEARISH_TRANSITION"

    if (
        short_state == "BUYER_DOMINANT"
        and medium_state == "SELLER_DOMINANT"
        and prism_state == "SELLER_DOMINANT"
    ):
        return "COUNTER_REGIME_BUY_BURST"

    if (
        short_state == "SELLER_DOMINANT"
        and medium_state == "BUYER_DOMINANT"
        and prism_state == "BUYER_DOMINANT"
    ):
        return "COUNTER_REGIME_SELL_BURST"

    return "MIXED_ALIGNMENT"


def build_multipressure_readout(
    candles: Iterable[Any],
    pair: str,
    bar_timestamp_utc: str | None = None,
    timeframe: str = TIMEFRAME,
) -> dict[str, Any]:
    completed_candles = list(candles)

    pressure_12 = calculate_pressure(
        completed_candles,
        SHORT_WINDOW_BARS,
    )
    pressure_100 = calculate_pressure(
        completed_candles,
        MEDIUM_WINDOW_BARS,
    )
    pressure_390 = calculate_pressure(
        completed_candles,
        PRISM_SCALE_WINDOW_BARS,
    )

    state_12 = pressure_12["state"]
    state_100 = pressure_100["state"]
    state_390 = pressure_390["state"]

    health_state = (
        "AVAILABLE"
        if len(completed_candles) >= MIN_REQUIRED_BARS
        else "UNAVAILABLE"
    )

    return {
        "record_type": RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "pair": pair,
        "timeframe": timeframe,
        "bar_timestamp_utc": bar_timestamp_utc,
        "source": SOURCE,
        "true_bid_ask_delta_available": False,
        "research_only": RESEARCH_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
        "data_health": {
            "state": health_state,
            "completed_bars": len(completed_candles),
            "required_bars": MIN_REQUIRED_BARS,
            "reason_codes": (
                []
                if health_state == "AVAILABLE"
                else ["INSUFFICIENT_COMPLETED_BARS_FOR_390"]
            ),
        },
        "pressure_12": pressure_12,
        "pressure_100": pressure_100,
        "pressure_390": pressure_390,
        "alignment": {
            "short_vs_medium": pair_alignment(state_12, state_100),
            "short_vs_prism_scale": pair_alignment(state_12, state_390),
            "medium_vs_prism_scale": pair_alignment(
                state_100,
                state_390,
            ),
            "all_three": three_horizon_state(
                state_12,
                state_100,
                state_390,
            ),
        },
    }
