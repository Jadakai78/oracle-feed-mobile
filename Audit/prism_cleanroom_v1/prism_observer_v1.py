"""
prism_observer_v1.py — PRISM clean-room frozen observation builder.

Pure, in-memory composition of terrain + width + width-regime into one
frozen, descriptive-only observation record. No network access, no file
writes, no loops, no mutation of caller-owned inputs.
"""

from __future__ import annotations

from prism_common_v1 import SAFETY_FLAGS
from prism_terrain_v1 import build_terrain
from prism_width_regime_v1 import classify_width_regime
from prism_width_v1 import build_width_observation

TIMEFRAME = "15m"
HORIZONS_BARS = [1, 4, 16, 64]


def _normalize_pair(pair: object) -> str | None:
    """Validate and normalize a canonical pair string. Rejects whitespace-
    only components and strips surrounding whitespace from both sides of
    the single slash. Returns None if the pair is invalid."""
    if not isinstance(pair, str) or not pair:
        return None
    parts = pair.split("/")
    if len(parts) != 2:
        return None
    base, quote = parts[0].strip(), parts[1].strip()
    if not base or not quote:
        return None
    return f"{base}/{quote}"


def build_prism_observation(
    pair: str,
    bars: list[dict],
    timeframe: str = "15m",
) -> dict | None:
    normalized_pair = _normalize_pair(pair)
    if normalized_pair is None:
        return None
    if timeframe != TIMEFRAME:
        return None

    terrain = build_terrain(bars, timeframe)
    if terrain.get("state") != "AVAILABLE":
        return None

    width = build_width_observation(bars, timeframe, terrain=terrain)
    if width.get("state") != "AVAILABLE":
        return None

    regime = classify_width_regime(width)
    if regime.get("state") != "AVAILABLE":
        return None

    reference_bar_close_utc = terrain["last_completed_candle_utc"]
    reference_price = terrain["current_close"]

    observation_id = f"{normalized_pair}|{timeframe}|{reference_bar_close_utc}|PRISM_WIDTH_REGIME_V1"

    return {
        "recordtype": "PRISM_WIDTH_REGIME_OBSERVATION",
        "schema_version": "prism_width_regime_v1",
        "observation_id": observation_id,
        "pair": normalized_pair,
        "timeframe": timeframe,
        "reference_bar_close_utc": reference_bar_close_utc,
        "reference_price": reference_price,
        "terrain": {
            "state": terrain["state"],
            "zone": terrain["zone"],
            "middle_slope": terrain["middle_slope"],
            "bandwidth": terrain["bandwidth"],
        },
        "width": {
            "state": width["state"],
            "current_width": width["current_width"],
            "prior_width_count": width["prior_width_count"],
            "width_slope": width["width_slope"],
            "width_percentile": width["width_percentile"],
            "regime": regime["regime"],
        },
        "horizons_bars": list(HORIZONS_BARS),
        "status": "OPEN",
        **SAFETY_FLAGS,
    }
