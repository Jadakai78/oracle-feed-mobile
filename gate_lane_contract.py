"""
Shared contract for all JHL specialized gate families.

Every family emits a zone-touch, manual-review lane.
This module has no execution or routing capability.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid


LANE_SCHEMA_VERSION = 1
ZONE_TOUCH_POLICY = "zone_touch_v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_lane(
    *,
    family: str,
    version: str,
    pair: str,
    side: str,
    entry_zone: list[float],
    invalidation: float,
    target_1: float,
    target_2: float | None = None,
    score: int | float | None = None,
    gates: dict[str, Any] | None = None,
    features: dict[str, Any] | None = None,
    reason: str = "",
    observed_at: str | None = None,
) -> dict[str, Any]:
    family = str(family).upper().strip()
    side = str(side).upper().strip()

    if not family:
        raise ValueError("family is required")
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    if len(entry_zone) != 2:
        raise ValueError("entry_zone must have exactly two prices")

    zone_low, zone_high = sorted(float(v) for v in entry_zone)
    if zone_low <= 0 or zone_high <= 0:
        raise ValueError("entry zone must be positive")

    invalidation = float(invalidation)
    target_1 = float(target_1)
    if invalidation <= 0 or target_1 <= 0:
        raise ValueError("invalidation and target_1 must be positive")

    midpoint = (zone_low + zone_high) / 2
    if side == "LONG" and not (invalidation < midpoint < target_1):
        raise ValueError("LONG geometry must be invalidation < entry < target")
    if side == "SHORT" and not (target_1 < midpoint < invalidation):
        raise ValueError("SHORT geometry must be target < entry < invalidation")

    return {
        "record_type": "lane_observed",
        "schema_version": LANE_SCHEMA_VERSION,
        "observation_id": str(uuid.uuid4()),
        "family": family,
        "version": str(version),
        "observed_at": observed_at or utc_now(),
        "pair": pair,
        "side": side,
        "score": score,
        "reason": reason,
        "gates": gates or {},
        "features": features or {},
        "geometry": {
            "entry_zone": [zone_low, zone_high],
            "entry_midpoint": midpoint,
            "invalidation": invalidation,
            "target_1": target_1,
            "target_2": float(target_2) if target_2 else None,
        },
        "evaluation_policy": ZONE_TOUCH_POLICY,
        "outcome": {"status": "pending", "label": None},
    }
