from __future__ import annotations

import math
from typing import Any


FULL_HISTORY_COUNT = 25
LOW_PERCENTILE_THRESHOLD = 0.20
HIGH_PERCENTILE_THRESHOLD = 0.80
REL_TOLERANCE = 1e-12
ABS_TOLERANCE = 1e-12
VALID_SLOPES = {"UP", "DOWN", "FLAT"}


def _result(
    *,
    state: str,
    reason: str | None,
    current_width: float | None = None,
    prior_width_count: int = 0,
    width_percentile: float | None = None,
    width_slope: str = "UNAVAILABLE",
    regime: str = "WIDTH_UNAVAILABLE",
) -> dict[str, Any]:
    return {
        "state": state,
        "reason": reason,
        "current_width": current_width,
        "prior_width_count": prior_width_count,
        "width_percentile": width_percentile,
        "width_slope": width_slope,
        "regime": regime,
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
    }


def _finite_positive_number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid width")

    number = float(value)

    if not math.isfinite(number):
        raise ValueError("width must be finite")

    if number <= 0.0:
        raise ValueError("width must be positive")

    return number


def _midpoint_percentile(
    current_width: float,
    prior_widths: list[float],
) -> float:
    lower_count = 0
    equal_count = 0

    for width in prior_widths:
        if math.isclose(
            width,
            current_width,
            rel_tol=REL_TOLERANCE,
            abs_tol=ABS_TOLERANCE,
        ):
            equal_count += 1
        elif width < current_width:
            lower_count += 1

    return (lower_count + 0.5 * equal_count) / len(prior_widths)


def classify_band_width_regime(
    width_observation: dict[str, Any],
) -> dict[str, Any]:
    """Classify a descriptive width regime from a complete v1.1C observation."""
    if not isinstance(width_observation, dict):
        return _result(
            state="UNAVAILABLE",
            reason="invalid_width_observation",
        )

    if width_observation.get("state") != "AVAILABLE":
        return _result(
            state="UNAVAILABLE",
            reason="width_observation_unavailable",
        )

    if width_observation.get("history_state") != "AVAILABLE":
        return _result(
            state="UNAVAILABLE",
            reason="width_history_unavailable",
        )

    try:
        current_width = _finite_positive_number(
            width_observation["current_width"]
        )
        raw_prior_widths = width_observation["prior_widths"]

        if not isinstance(raw_prior_widths, list):
            raise ValueError("prior_widths must be a list")

        prior_widths = [
            _finite_positive_number(width)
            for width in raw_prior_widths
        ]
    except (KeyError, TypeError, ValueError) as exc:
        return _result(
            state="UNAVAILABLE",
            reason=f"invalid_width_values: {exc}",
        )

    if len(prior_widths) != FULL_HISTORY_COUNT:
        return _result(
            state="UNAVAILABLE",
            reason=(
                "invalid_prior_width_count: "
                f"expected_{FULL_HISTORY_COUNT}_got_{len(prior_widths)}"
            ),
        )

    reported_count = width_observation.get("prior_width_count")
    if reported_count != FULL_HISTORY_COUNT:
        return _result(
            state="UNAVAILABLE",
            reason="prior_width_count_mismatch",
        )

    width_slope = width_observation.get("width_slope")
    if width_slope not in VALID_SLOPES:
        return _result(
            state="UNAVAILABLE",
            reason="invalid_width_slope",
        )

    percentile = _midpoint_percentile(current_width, prior_widths)

    if percentile <= LOW_PERCENTILE_THRESHOLD:
        regime = (
            "WIDTH_CONTRACTING"
            if width_slope == "DOWN"
            else "WIDTH_COMPRESSED"
        )
    elif percentile >= HIGH_PERCENTILE_THRESHOLD:
        regime = (
            "WIDTH_EXPANDING"
            if width_slope == "UP"
            else "WIDTH_ELEVATED"
        )
    else:
        regime = "WIDTH_NEUTRAL"

    return _result(
        state="AVAILABLE",
        reason=None,
        current_width=current_width,
        prior_width_count=len(prior_widths),
        width_percentile=percentile,
        width_slope=width_slope,
        regime=regime,
    )
