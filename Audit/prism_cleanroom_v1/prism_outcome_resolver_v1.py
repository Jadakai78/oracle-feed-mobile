"""
prism_outcome_resolver_v1.py — PRISM clean-room outcome resolver.

Pure, in-memory function that measures realized forward price behavior after
a frozen observation, strictly using future bars only. Emits no direction,
side, win/loss label, or trade geometry. No network access, no file writes,
no mutation of caller-owned inputs.
"""

from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any

from prism_common_v1 import SAFETY_FLAGS, is_finite_number, parse_utc, validate_bars_series

HORIZONS_BARS = (1, 4, 16, 64)
REQUIRED_FUTURE_BARS = 64
BAR_INTERVAL = timedelta(minutes=15)


def _valid_observation(observation: Any) -> bool:
    if not isinstance(observation, dict):
        return False
    if observation.get("recordtype") != "PRISM_WIDTH_REGIME_OBSERVATION":
        return False
    if observation.get("schema_version") != "prism_width_regime_v1":
        return False
    if observation.get("status") != "OPEN":
        return False
    reference_price = observation.get("reference_price")
    if not is_finite_number(reference_price) or reference_price <= 0:
        return False
    if parse_utc(observation.get("reference_bar_close_utc")) is None:
        return False
    if not isinstance(observation.get("terrain"), dict) or not isinstance(observation.get("width"), dict):
        return False
    return True


def resolve_prism_outcome(observation: dict, future_bars: list[dict]) -> dict | None:
    if not _valid_observation(observation):
        return None

    if not isinstance(future_bars, list) or len(future_bars) < REQUIRED_FUTURE_BARS:
        return None

    window = future_bars[:REQUIRED_FUTURE_BARS]
    ok, _reason = validate_bars_series(window)
    if not ok:
        return None

    reference_ts = parse_utc(observation["reference_bar_close_utc"])
    first_ts = parse_utc(window[0]["timestamp"])
    if first_ts != reference_ts + BAR_INTERVAL:
        return None

    reference_price = observation["reference_price"]

    samples: dict[str, dict[str, float]] = {}
    for horizon in HORIZONS_BARS:
        horizon_bars = window[:horizon]
        close_h = horizon_bars[-1]["close"]
        highs = [reference_price] + [bar["high"] for bar in horizon_bars]
        lows = [reference_price] + [bar["low"] for bar in horizon_bars]
        high_h = max(highs)
        low_h = min(lows)

        close_return_pct = 100.0 * ((close_h / reference_price) - 1.0)
        realized_range_pct = 100.0 * ((high_h - low_h) / reference_price)
        upside_excursion_pct = 100.0 * ((high_h - reference_price) / reference_price)
        downside_excursion_pct = 100.0 * ((low_h - reference_price) / reference_price)

        samples[f"{horizon}bar"] = {
            "close_return_pct": close_return_pct,
            "realized_range_pct": realized_range_pct,
            "upside_excursion_pct": upside_excursion_pct,
            "downside_excursion_pct": downside_excursion_pct,
        }

    return {
        "recordtype": "PRISM_WIDTH_REGIME_OUTCOME",
        "schema_version": "prism_width_regime_v1",
        "observation_id": observation["observation_id"],
        "pair": observation["pair"],
        "timeframe": observation["timeframe"],
        "reference_bar_close_utc": observation["reference_bar_close_utc"],
        "reference_price": reference_price,
        "terrain": copy.deepcopy(observation["terrain"]),
        "width": copy.deepcopy(observation["width"]),
        "horizons_bars": list(HORIZONS_BARS),
        "samples": samples,
        "status": "CLOSED",
        **SAFETY_FLAGS,
    }
