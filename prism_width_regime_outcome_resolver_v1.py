from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any


RECORDTYPE = "PRISMWIDTHREGIMEOUTCOME"
SCHEMA_VERSION = "prismwidthregimev1"
SUPPORTED_TIMEFRAME = "15m"
INTERVAL_SECONDS = 15 * 60
HORIZONS_BARS = (1, 4, 16, 64)
REQUIRED_FUTURE_BARS = max(HORIZONS_BARS)


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return None

    return parsed.astimezone(timezone.utc)


def _finite_positive(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(number) or number <= 0.0:
        return None

    return number


def _validate_observation(
    observation: Any,
) -> tuple[str, str, str, float, dict[str, Any], dict[str, Any]] | None:
    if not isinstance(observation, dict):
        return None

    if observation.get("recordtype") != "PRISMWIDTHREGIMEOBSERVATION":
        return None

    if observation.get("schema_version") != SCHEMA_VERSION:
        return None

    if observation.get("status") != "OPEN":
        return None

    pair = observation.get("pair")
    timeframe = observation.get("timeframe")
    observation_id = observation.get("observation_id")
    reference_timestamp = observation.get("reference_bar_close_utc")
    reference_price = _finite_positive(observation.get("reference_price"))
    terrain = observation.get("terrain")
    width = observation.get("width")

    if (
        not isinstance(pair, str)
        or not pair
        or timeframe != SUPPORTED_TIMEFRAME
        or not isinstance(observation_id, str)
        or not observation_id
        or _parse_utc(reference_timestamp) is None
        or reference_price is None
        or not isinstance(terrain, dict)
        or not isinstance(width, dict)
    ):
        return None

    if observation.get("horizons_bars") != list(HORIZONS_BARS):
        return None

    if (
        observation.get("manual_review_only") is not True
        or observation.get("does_not_authorize_trade") is not True
        or observation.get("does_not_simulate_order") is not True
    ):
        return None

    return (
        observation_id,
        pair,
        reference_timestamp,
        reference_price,
        terrain,
        width,
    )


def _validate_future_bars(
    future_bars: Any,
    reference_timestamp: str,
) -> list[tuple[datetime, float, float, float]] | None:
    if not isinstance(future_bars, list):
        return None

    if len(future_bars) < REQUIRED_FUTURE_BARS:
        return None

    reference = _parse_utc(reference_timestamp)
    if reference is None:
        return None

    expected_timestamp = reference + timedelta(seconds=INTERVAL_SECONDS)
    parsed: list[tuple[datetime, float, float, float]] = []

    for bar in future_bars[:REQUIRED_FUTURE_BARS]:
        if not isinstance(bar, dict):
            return None

        timestamp = _parse_utc(bar.get("timestamp"))
        open_price = _finite_positive(bar.get("open"))
        high_price = _finite_positive(bar.get("high"))
        low_price = _finite_positive(bar.get("low"))
        close_price = _finite_positive(bar.get("close"))
        volume = _finite_positive(bar.get("volume"))

        if (
            timestamp is None
            or open_price is None
            or high_price is None
            or low_price is None
            or close_price is None
            or volume is None
        ):
            return None

        if timestamp != expected_timestamp:
            return None

        if low_price > min(open_price, close_price):
            return None

        if high_price < max(open_price, close_price):
            return None

        parsed.append((timestamp, high_price, low_price, close_price))
        expected_timestamp += timedelta(seconds=INTERVAL_SECONDS)

    return parsed


def _sample(
    bars: list[tuple[datetime, float, float, float]],
    reference_price: float,
    horizon_bars: int,
) -> dict[str, Any]:
    horizon = bars[:horizon_bars]
    timestamp, _, _, final_close = horizon[-1]

    highs = [reference_price] + [high for _, high, _, _ in horizon]
    lows = [reference_price] + [low for _, _, low, _ in horizon]

    highest = max(highs)
    lowest = min(lows)

    return {
        "horizon_bars": horizon_bars,
        "observed_at_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "close": final_close,
        "close_return_pct": ((final_close / reference_price) - 1.0) * 100.0,
        "realized_range_pct": ((highest - lowest) / reference_price) * 100.0,
        "upside_excursion_pct": (
            (highest - reference_price) / reference_price
        ) * 100.0,
        "downside_excursion_pct": (
            (lowest - reference_price) / reference_price
        ) * 100.0,
    }


def resolve_prism_width_regime_outcome(
    observation: dict[str, Any],
    future_bars: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Resolve a frozen PRISM observation using only subsequent completed bars.

    The result is direction-neutral research metadata. It does not represent a
    trade, fill, signal, recommendation, or authority of any kind.
    """
    validated = _validate_observation(observation)

    if validated is None:
        return None

    (
        observation_id,
        pair,
        reference_timestamp,
        reference_price,
        terrain,
        width,
    ) = validated

    parsed_bars = _validate_future_bars(future_bars, reference_timestamp)

    if parsed_bars is None:
        return None

    samples = {
        f"{horizon}bar": _sample(
            parsed_bars,
            reference_price,
            horizon,
        )
        for horizon in HORIZONS_BARS
    }

    max_upside = max(
        sample["upside_excursion_pct"]
        for sample in samples.values()
    )
    max_downside = min(
        sample["downside_excursion_pct"]
        for sample in samples.values()
    )

    return {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "observation_id": observation_id,
        "pair": pair,
        "timeframe": SUPPORTED_TIMEFRAME,
        "reference_bar_close_utc": reference_timestamp,
        "reference_price": reference_price,
        "terrain": terrain,
        "width": width,
        "horizons_bars": list(HORIZONS_BARS),
        "samples": samples,
        "max_upside_excursion_pct": max_upside,
        "max_downside_excursion_pct": max_downside,
        "status": "CLOSED",
        "manual_review_only": True,
        "does_not_authorize_trade": True,
        "does_not_simulate_order": True,
    }
