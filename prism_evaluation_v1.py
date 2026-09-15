"""
PRISM Evaluation v1

Read-only evaluator that combines a PRISM Context v1 record with a
Delta/Tempo v1 record into one manual-review-only decision event.

This module:
- Performs no market reads.
- Performs no order, alert, queue, scoring, sizing, or execution action.
- Does not create entry, stop, target, or position-size instructions.
- Does not use Oracle, Eight Gates, KNN, Sentinel, or Arbiter.
- Emits only BLOCK, WATCH, or CANDIDATE for manual review.

Input records:
- PRISMCONTEXT / prism.context.v1
- DELTATEMPO / delta.tempo.v1
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

RECORDTYPE = "PRISMEVALUATION"
SCHEMA_VERSION = "prism.evaluation.v1"

PRISM_RECORDTYPE = "PRISMCONTEXT"
PRISM_SCHEMA_VERSION = "prism.context.v1"

DELTA_RECORDTYPE = "DELTATEMPO"
DELTA_SCHEMA_VERSION = "delta.tempo.v1"

STATUS_BLOCK = "BLOCK"
STATUS_WATCH = "WATCH"
STATUS_CANDIDATE = "CANDIDATE"

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


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name}_must_be_object")
    return value


def _require_nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}_must_be_nonempty_string")
    return value


def _require_false(value: Any, name: str) -> None:
    if value is not False:
        raise ValueError(f"{name}_must_be_false")


def _require_true(value: Any, name: str) -> None:
    if value is not True:
        raise ValueError(f"{name}_must_be_true")


def _validate_prism_context(prism_context: Mapping[str, Any]) -> dict[str, Any]:
    prism_context = _require_mapping(prism_context, "prism_context")

    if prism_context.get("recordtype") != PRISM_RECORDTYPE:
        raise ValueError("unexpected_prism_recordtype")

    if prism_context.get("schema_version") != PRISM_SCHEMA_VERSION:
        raise ValueError("unexpected_prism_schema_version")

    _require_true(prism_context.get("manual_review_only"), "prism_manual_review_only")
    _require_false(prism_context.get("trade_authority"), "prism_trade_authority")
    _require_false(prism_context.get("entry_authority"), "prism_entry_authority")

    pair = _require_nonempty_string(prism_context.get("pair"), "prism_pair")
    timeframe = _require_nonempty_string(
        prism_context.get("timeframe"),
        "prism_timeframe",
    )

    data_health = _require_mapping(prism_context.get("data_health"), "prism_data_health")
    terrain = _require_mapping(prism_context.get("terrain"), "prism_terrain")

    return {
        "pair": pair,
        "timeframe": timeframe,
        "data_health": data_health,
        "terrain": terrain,
    }


def _validate_delta_tempo(delta_tempo: Mapping[str, Any]) -> dict[str, Any]:
    delta_tempo = _require_mapping(delta_tempo, "delta_tempo")

    if delta_tempo.get("recordtype") != DELTA_RECORDTYPE:
        raise ValueError("unexpected_delta_recordtype")

    if delta_tempo.get("schema_version") != DELTA_SCHEMA_VERSION:
        raise ValueError("unexpected_delta_schema_version")

    _require_true(delta_tempo.get("manual_review_only"), "delta_manual_review_only")
    _require_false(delta_tempo.get("trade_authority"), "delta_trade_authority")
    _require_false(delta_tempo.get("entry_authority"), "delta_entry_authority")

    pair = _require_nonempty_string(delta_tempo.get("pair"), "delta_pair")
    timeframe = _require_nonempty_string(
        delta_tempo.get("timeframe"),
        "delta_timeframe",
    )

    data_health = _require_mapping(delta_tempo.get("data_health"), "delta_data_health")
    pressure = _require_mapping(delta_tempo.get("pressure"), "delta_pressure")
    participation = _require_mapping(
        delta_tempo.get("participation"),
        "delta_participation",
    )
    tempo = _require_mapping(delta_tempo.get("tempo"), "delta_tempo_state")
    prism_alignment = _require_mapping(
        delta_tempo.get("prism_alignment"),
        "delta_prism_alignment",
    )

    return {
        "pair": pair,
        "timeframe": timeframe,
        "data_health": data_health,
        "pressure": pressure,
        "participation": participation,
        "tempo": tempo,
        "speed_phase": delta_tempo.get("speed_phase", "NONE"),
        "prism_alignment": prism_alignment,
    }


def _health_state(record: Mapping[str, Any]) -> str:
    data_health = record["data_health"]
    state = data_health.get("state")

    if not isinstance(state, str) or not state:
        return "INVALID"

    return state


def _reason_codes(record: Mapping[str, Any]) -> list[str]:
    reason_codes = record["data_health"].get("reason_codes", [])

    if not isinstance(reason_codes, list):
        return ["INVALID_REASON_CODES"]

    return [
        code
        for code in reason_codes
        if isinstance(code, str) and code.strip()
    ]


def _copy_prism(prism: Mapping[str, Any]) -> dict[str, Any]:
    terrain = prism["terrain"]

    return {
        "data_health": {
            "state": _health_state(prism),
            "reason_codes": _reason_codes(prism),
            "completed_bars": prism["data_health"].get("completed_bars"),
            "required_bars": prism["data_health"].get("required_bars"),
        },
        "terrain": {
            "trend_alignment": terrain.get("trend_alignment", "NEUTRAL"),
            "supertrend_value": terrain.get("supertrend_value"),
            "supertrend_distance_pct": terrain.get("supertrend_distance_pct"),
            "structural_zone": terrain.get("structural_zone", "NEUTRAL"),
            "noise_regime": terrain.get("noise_regime", "UNKNOWN"),
            "location_sigma": terrain.get("location_sigma"),
            "distance_from_mean_pct": terrain.get("distance_from_mean_pct"),
            "terrain_state": terrain.get("terrain_state", "UNAVAILABLE"),
            "route": terrain.get("route", "NO_ROUTE"),
            "route_reason": terrain.get("route_reason", "Unavailable."),
        },
    }


def _copy_delta(delta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "data_health": {
            "state": _health_state(delta),
            "reason_codes": _reason_codes(delta),
            "completed_bars": delta["data_health"].get("completed_bars"),
            "required_bars": delta["data_health"].get("required_bars"),
        },
        "pressure": {
            "state": delta["pressure"].get("state", "UNAVAILABLE"),
            "buyer_pressure": delta["pressure"].get("buyer_pressure"),
            "seller_pressure": delta["pressure"].get("seller_pressure"),
            "balance": delta["pressure"].get("balance"),
        },
        "participation": {
            "state": delta["participation"].get("state", "UNKNOWN"),
            "volume_expansion_ratio": delta["participation"].get(
                "volume_expansion_ratio"
            ),
        },
        "tempo": {
            "state": delta["tempo"].get("state", "UNKNOWN"),
            "range_expansion_ratio": delta["tempo"].get(
                "range_expansion_ratio"
            ),
            "transition": delta["tempo"].get("transition", "UNAVAILABLE"),
            "transition_reason": delta["tempo"].get(
                "transition_reason",
                "Unavailable.",
            ),
        },
        "speed_phase": delta.get("speed_phase", "NONE"),
        "prism_alignment": {
            "state": delta["prism_alignment"].get("state", "UNAVAILABLE"),
            "reason": delta["prism_alignment"].get(
                "reason",
                "Unavailable.",
            ),
        },
    }


def determine_decision(
    prism: Mapping[str, Any],
    delta: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Return a decision with no trade authority.

    Decision priority:
    1. Missing/invalid source data → BLOCK.
    2. PRISM explicitly has no route/no-chase/unavailable terrain → BLOCK.
    3. Delta/Tempo explicitly conflicts or is restricted → BLOCK.
    4. PRISM + Delta/Tempo aligned and confirming → CANDIDATE.
    5. All remaining observable conditions → WATCH.
    """
    prism_health = _health_state(prism)
    delta_health = _health_state(delta)

    if prism_health != "AVAILABLE":
        return {
            "status": STATUS_BLOCK,
            "reason": "PRISM context is not available for evaluation.",
            "first_block": "PRISM_DATA_HEALTH",
        }

    if delta_health != "AVAILABLE":
        return {
            "status": STATUS_BLOCK,
            "reason": "Delta/Tempo context is not available for evaluation.",
            "first_block": "DELTA_TEMPO_DATA_HEALTH",
        }

    terrain = prism["terrain"]
    route = terrain.get("route", "NO_ROUTE")
    terrain_state = terrain.get("terrain_state", "UNAVAILABLE")

    if terrain_state == "UNAVAILABLE":
        return {
            "status": STATUS_BLOCK,
            "reason": "PRISM terrain is unavailable.",
            "first_block": "PRISM_TERRAIN_UNAVAILABLE",
        }

    if route == "NO_ROUTE":
        return {
            "status": STATUS_BLOCK,
            "reason": "PRISM terrain does not provide a proactive route.",
            "first_block": "PRISM_NO_ROUTE",
        }

    if route == "NO_CHASE":
        return {
            "status": STATUS_BLOCK,
            "reason": "PRISM terrain is extended; no chase route is permitted.",
            "first_block": "PRISM_NO_CHASE",
        }

    alignment = delta["prism_alignment"].get("state", "UNAVAILABLE")

    if alignment == "CONFLICT":
        return {
            "status": STATUS_BLOCK,
            "reason": "Delta/Tempo pressure conflicts with PRISM terrain.",
            "first_block": "PRISM_DELTA_CONFLICT",
        }

    if alignment == "RESTRICTED":
        return {
            "status": STATUS_BLOCK,
            "reason": "PRISM route restricts Delta/Tempo from promoting the condition.",
            "first_block": "PRISM_ROUTE_RESTRICTED",
        }

    if alignment == "UNAVAILABLE":
        return {
            "status": STATUS_BLOCK,
            "reason": "PRISM and Delta/Tempo alignment cannot be established.",
            "first_block": "PRISM_DELTA_ALIGNMENT_UNAVAILABLE",
        }

    transition = delta["tempo"].get("transition", "UNAVAILABLE")
    pressure_state = delta["pressure"].get("state", "UNAVAILABLE")
    participation_state = delta["participation"].get("state", "UNKNOWN")

    if (
        alignment == "ALIGNED"
        and transition == "CONFIRMING"
        and pressure_state in {"BUYER_FAVORING", "SELLER_FAVORING"}
        and participation_state != "CONTRACTING"
    ):
        return {
            "status": STATUS_CANDIDATE,
            "reason": (
                "PRISM terrain and Delta/Tempo confirmation agree; "
                "manual structural review is eligible."
            ),
            "first_block": None,
        }

    if transition == "DETERIORATING":
        return {
            "status": STATUS_WATCH,
            "reason": (
                "PRISM remains observable, but Delta/Tempo is deteriorating; "
                "no candidate status."
            ),
            "first_block": None,
        }

    if transition == "FADING":
        return {
            "status": STATUS_WATCH,
            "reason": (
                "PRISM terrain remains observable, but participation and tempo "
                "are fading."
            ),
            "first_block": None,
        }

    return {
        "status": STATUS_WATCH,
        "reason": (
            "PRISM terrain is observable, but Delta/Tempo confirmation is "
            "incomplete."
        ),
        "first_block": None,
    }


def build_prism_evaluation(
    prism_context: Mapping[str, Any],
    delta_tempo: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Build one manual-review-only PRISM evaluation event.

    The input records must be valid outputs from:
    - prism_context_v1.build_prism_context()
    - delta_tempo_v1.build_delta_tempo()
    """
    prism = _validate_prism_context(prism_context)
    delta = _validate_delta_tempo(delta_tempo)

    if prism["pair"] != delta["pair"]:
        raise ValueError("pair_mismatch_between_prism_and_delta")

    if prism["timeframe"] != delta["timeframe"]:
        raise ValueError("timeframe_mismatch_between_prism_and_delta")

    decision = determine_decision(prism, delta)

    return {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _now_utc(),
        "pair": prism["pair"],
        "timeframe": prism["timeframe"],
        "prism": _copy_prism(prism),
        "delta_tempo": _copy_delta(delta),
        "structure": {
            "status": "NOT_EVALUATED",
            "entry_zone": None,
            "invalidation": None,
            "target": None,
            "target_r": None,
            "reason": (
                "Structure and geometry are intentionally outside "
                "prism.evaluation.v1."
            ),
        },
        "decision": decision,
        "manual_review_only": MANUAL_REVIEW_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
        "does_not_size_positions": True,
        "does_not_create_trade_geometry": True,
    }
