from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PRISM_LAB = ROOT / "prism_adapter_lab_v1" / "prism_v1"

if str(PRISM_LAB) not in sys.path:
    sys.path.insert(0, str(PRISM_LAB))

from analyzer_v1 import build_band_terrain
from band_width_regime_v1_1c import classify_band_width_regime


RECORDTYPE = "PRISMWIDTHREGIMEOBSERVATION"
SCHEMA_VERSION = "prismwidthregimev1"
OBSERVATION_SUFFIX = "PRISM_WIDTH_REGIME_V1"
SUPPORTED_TIMEFRAME = "15m"
HORIZONS_BARS = [1, 4, 16, 64]


def _valid_pair(pair: Any) -> str | None:
    if not isinstance(pair, str):
        return None

    normalized = pair.strip()

    if not normalized or "/" not in normalized:
        return None

    return normalized


def build_prism_width_regime_observation(
    pair: str,
    bars: list[dict[str, Any]],
    timeframe: str = SUPPORTED_TIMEFRAME,
) -> dict[str, Any] | None:
    """Build one immutable, direction-neutral PRISM width-regime observation.

    This function is pure and in-memory only. It does not write records,
    request market data, simulate an order, emit an alert, or authorize trade.
    """
    normalized_pair = _valid_pair(pair)

    if normalized_pair is None or timeframe != SUPPORTED_TIMEFRAME:
        return None

    terrain = build_band_terrain(bars, timeframe)

    if terrain.get("state") != "AVAILABLE":
        return None

    width_observation = terrain.get("band_width_v1_1c")

    if not isinstance(width_observation, dict):
        return None

    width_regime = classify_band_width_regime(width_observation)

    if width_regime.get("state") != "AVAILABLE":
        return None

    reference_bar_close_utc = terrain.get("last_completed_candle_utc")
    reference_price = terrain.get("current_close")

    if (
        not isinstance(reference_bar_close_utc, str)
        or not reference_bar_close_utc
        or not isinstance(reference_price, (int, float))
    ):
        return None

    observation_id = "|".join(
        [
            normalized_pair,
            timeframe,
            reference_bar_close_utc,
            OBSERVATION_SUFFIX,
        ]
    )

    terrain_snapshot = {
        "state": terrain["state"],
        "zone": terrain["zone"],
        "middle_slope": terrain["middle_slope"],
        "arrival_mode": terrain["arrival_mode"],
        "middle_role": terrain["middle_role"],
        "bandwidth": terrain["bandwidth"],
    }

    width_snapshot = {
        "state": width_observation["state"],
        "current_width": width_observation["current_width"],
        "prior_width_count": width_observation["prior_width_count"],
        "width_slope": width_regime["width_slope"],
        "width_percentile": width_regime["width_percentile"],
        "regime": width_regime["regime"],
    }

    return {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "observation_id": observation_id,
        "pair": normalized_pair,
        "timeframe": timeframe,
        "reference_bar_close_utc": reference_bar_close_utc,
        "reference_price": float(reference_price),
        "terrain": terrain_snapshot,
        "width": width_snapshot,
        "horizons_bars": list(HORIZONS_BARS),
        "status": "OPEN",
        "manual_review_only": True,
        "does_not_authorize_trade": True,
        "does_not_simulate_order": True,
    }
