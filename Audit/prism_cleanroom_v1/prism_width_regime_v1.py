"""
prism_width_regime_v1.py — PRISM clean-room width regime classifier.

Purely descriptive dispersion-regime label derived from a width observation.
Never bullish/bearish; never trade-authorizing. Does not mutate its input.
No network access, no file writes.
"""

from __future__ import annotations

from typing import Any

from prism_common_v1 import SAFETY_FLAGS, is_finite_number

VALID_SLOPES = {"UP", "DOWN", "FLAT"}


def _result(state: str, percentile: Any, slope: Any, regime: str, reason_codes: list[str]) -> dict:
    return {
        "state": state,
        "recordtype": "PRISM_WIDTH_REGIME",
        "schema_version": "prism_width_regime_v1",
        "width_percentile": percentile,
        "width_slope": slope,
        "regime": regime,
        "reason_codes": reason_codes,
        **SAFETY_FLAGS,
    }


def classify_width_regime(width_observation: dict) -> dict:
    if not isinstance(width_observation, dict):
        return _result("UNAVAILABLE", None, None, "WIDTH_UNAVAILABLE", ["PRISM.DATA.INVALID_OHLCV"])

    if width_observation.get("state") != "AVAILABLE":
        return _result("UNAVAILABLE", None, None, "WIDTH_UNAVAILABLE", ["PRISM.DATA.INSUFFICIENT_HISTORY"])

    if width_observation.get("prior_width_count") != 25:
        return _result("UNAVAILABLE", None, None, "WIDTH_UNAVAILABLE", ["PRISM.DATA.INSUFFICIENT_HISTORY"])

    current_width = width_observation.get("current_width")
    if not is_finite_number(current_width):
        return _result("UNAVAILABLE", None, None, "WIDTH_UNAVAILABLE", ["PRISM.DATA.INVALID_OHLCV"])

    percentile = width_observation.get("width_percentile")
    if not is_finite_number(percentile) or not (0.0 <= percentile <= 1.0):
        return _result("UNAVAILABLE", None, None, "WIDTH_UNAVAILABLE", ["PRISM.DATA.INVALID_OHLCV"])

    slope = width_observation.get("width_slope")
    if slope not in VALID_SLOPES:
        return _result("UNAVAILABLE", None, None, "WIDTH_UNAVAILABLE", ["PRISM.DATA.INVALID_OHLCV"])

    if percentile <= 0.20:
        regime = "WIDTH_CONTRACTING" if slope == "DOWN" else "WIDTH_COMPRESSED"
    elif percentile >= 0.80:
        regime = "WIDTH_EXPANDING" if slope == "UP" else "WIDTH_ELEVATED"
    else:
        regime = "WIDTH_NEUTRAL"

    return _result("AVAILABLE", percentile, slope, regime, [])
