"""
Activity-Aware Sizing v1

Shadow-only, completed-candle activity-aware exposure-cap calculator.

This module:
- Performs no market reads.
- Performs no order, alert, queue, scoring, or execution action.
- Does not alter any existing runtime allocation.
- Does not claim live order-book depth or market-impact prediction.
- Does not use leverage assumptions.
- Returns an explanatory provisional exposure cap for manual review only.

The output is a capacity estimate based on completed-candle activity and
configured limits. It is not an execution instruction.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

RECORDTYPE = "ACTIVITYAWARESIZING"
SCHEMA_VERSION = "activity.aware.sizing.v1"

MIN_REQUIRED_BARS = 40
ACTIVITY_WINDOW = 20

STATUS_ALLOW = "ALLOW"
STATUS_REDUCE = "REDUCE"
STATUS_BLOCK = "BLOCK"

HEALTH_AVAILABLE = "AVAILABLE"
HEALTH_MISSING_BARS = "MISSING_BARS"
HEALTH_INVALID_CANDLES = "INVALID_CANDLES"
HEALTH_INVALID_PRISM_CONTEXT = "INVALID_PRISM_CONTEXT"
HEALTH_INVALID_DELTA_TEMPO = "INVALID_DELTA_TEMPO"
HEALTH_INVALID_STOP_DISTANCE = "INVALID_STOP_DISTANCE"
HEALTH_INVALID_CONFIG = "INVALID_CONFIG"

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


def _as_nonnegative_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid_{field_name}")

    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"invalid_{field_name}")

    return numeric


def _as_positive_number(value: Any, field_name: str) -> float:
    numeric = _as_nonnegative_number(value, field_name)
    if numeric <= 0:
        raise ValueError(f"invalid_{field_name}")
    return numeric


def _validate_candle(candle: Mapping[str, Any], index: int) -> dict[str, float]:
    if not isinstance(candle, Mapping):
        raise ValueError(f"candle_{index}_must_be_object")

    required = ("open", "high", "low", "close", "volume")
    missing = [field for field in required if field not in candle]
    if missing:
        raise ValueError(f"candle_{index}_missing_{'_'.join(missing)}")

    open_price = _as_nonnegative_number(candle["open"], f"open_{index}")
    high = _as_nonnegative_number(candle["high"], f"high_{index}")
    low = _as_nonnegative_number(candle["low"], f"low_{index}")
    close = _as_nonnegative_number(candle["close"], f"close_{index}")
    volume = _as_nonnegative_number(candle["volume"], f"volume_{index}")

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


def _candle_notional_proxy(candle: Mapping[str, float]) -> float:
    """
    Conservative completed-candle activity proxy.

    Uses close × volume. This is not order-book liquidity, fillable depth,
    or a market-impact estimate. It is only a completed-bar notional-activity
    reference for shadow capacity reporting.
    """
    return candle["close"] * candle["volume"]


def calculate_activity(
    candles: Sequence[Mapping[str, float]],
    window: int = ACTIVITY_WINDOW,
) -> dict[str, Any]:
    recent = candles[-window:]
    latest = recent[-1]
    baseline = recent[:-1]

    latest_notional_proxy = _candle_notional_proxy(latest)
    baseline_notional_proxies = [
        _candle_notional_proxy(candle)
        for candle in baseline
    ]

    average_notional_proxy = (
        _mean(baseline_notional_proxies)
        if baseline_notional_proxies
        else latest_notional_proxy
    )

    activity_ratio = latest_notional_proxy / max(average_notional_proxy, 1e-12)

    if activity_ratio >= 1.25:
        state = "EXPANDING"
    elif activity_ratio <= 0.75:
        state = "CONTRACTING"
    else:
        state = "NORMAL"

    return {
        "latest_volume": round(latest["volume"], 8),
        "average_volume": round(
            _mean([candle["volume"] for candle in baseline])
            if baseline
            else latest["volume"],
            8,
        ),
        "latest_notional_proxy": round(latest_notional_proxy, 8),
        "average_notional_proxy": round(average_notional_proxy, 8),
        "activity_ratio": round(activity_ratio, 4),
        "activity_state": state,
        "window": window,
    }


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name}_must_be_object")
    return value


def _extract_prism_state(prism_context: Mapping[str, Any]) -> dict[str, str]:
    prism_context = _require_mapping(prism_context, "prism_context")

    if prism_context.get("recordtype") != "PRISMCONTEXT":
        raise ValueError("unexpected_prism_recordtype")

    if prism_context.get("schema_version") != "prism.context.v1":
        raise ValueError("unexpected_prism_schema_version")

    if prism_context.get("manual_review_only") is not True:
        raise ValueError("prism_not_manual_review_only")

    if prism_context.get("trade_authority") is not False:
        raise ValueError("prism_has_trade_authority")

    if prism_context.get("entry_authority") is not False:
        raise ValueError("prism_has_entry_authority")

    health = _require_mapping(prism_context.get("data_health"), "prism_data_health")
    terrain = _require_mapping(prism_context.get("terrain"), "prism_terrain")

    return {
        "health_state": str(health.get("state", "INVALID")),
        "noise_regime": str(terrain.get("noise_regime", "UNKNOWN")),
        "route": str(terrain.get("route", "NO_ROUTE")),
        "terrain_state": str(terrain.get("terrain_state", "UNAVAILABLE")),
    }


def _extract_delta_state(delta_tempo: Mapping[str, Any]) -> dict[str, str]:
    delta_tempo = _require_mapping(delta_tempo, "delta_tempo")

    if delta_tempo.get("recordtype") != "DELTATEMPO":
        raise ValueError("unexpected_delta_recordtype")

    if delta_tempo.get("schema_version") != "delta.tempo.v1":
        raise ValueError("unexpected_delta_schema_version")

    if delta_tempo.get("manual_review_only") is not True:
        raise ValueError("delta_not_manual_review_only")

    if delta_tempo.get("trade_authority") is not False:
        raise ValueError("delta_has_trade_authority")

    if delta_tempo.get("entry_authority") is not False:
        raise ValueError("delta_has_entry_authority")

    health = _require_mapping(delta_tempo.get("data_health"), "delta_data_health")
    participation = _require_mapping(
        delta_tempo.get("participation"),
        "delta_participation",
    )
    tempo = _require_mapping(delta_tempo.get("tempo"), "delta_tempo_state")
    alignment = _require_mapping(
        delta_tempo.get("prism_alignment"),
        "delta_prism_alignment",
    )

    return {
        "health_state": str(health.get("state", "INVALID")),
        "participation_state": str(participation.get("state", "UNKNOWN")),
        "tempo_state": str(tempo.get("state", "UNKNOWN")),
        "transition_state": str(tempo.get("transition", "UNAVAILABLE")),
        "alignment_state": str(alignment.get("state", "UNAVAILABLE")),
    }


def _validate_config(config: Mapping[str, Any]) -> dict[str, float]:
    config = _require_mapping(config, "config")

    account_risk_cap_usd = _as_positive_number(
        config.get("account_risk_cap_usd"),
        "account_risk_cap_usd",
    )
    max_notional_cap_usd = _as_positive_number(
        config.get("max_notional_cap_usd"),
        "max_notional_cap_usd",
    )
    max_activity_participation = _as_positive_number(
        config.get("max_activity_participation"),
        "max_activity_participation",
    )

    if max_activity_participation > 1.0:
        raise ValueError("invalid_max_activity_participation")

    minimum_activity_ratio = _as_nonnegative_number(
        config.get("minimum_activity_ratio", 0.50),
        "minimum_activity_ratio",
    )
    if minimum_activity_ratio > 1.0:
        raise ValueError("invalid_minimum_activity_ratio")

    reduced_capacity_multiplier = _as_nonnegative_number(
        config.get("reduced_capacity_multiplier", 0.50),
        "reduced_capacity_multiplier",
    )
    if reduced_capacity_multiplier > 1.0:
        raise ValueError("invalid_reduced_capacity_multiplier")

    noisy_regime_multiplier = _as_nonnegative_number(
        config.get("noisy_regime_multiplier", 0.50),
        "noisy_regime_multiplier",
    )
    if noisy_regime_multiplier > 1.0:
        raise ValueError("invalid_noisy_regime_multiplier")

    high_dispersion_multiplier = _as_nonnegative_number(
        config.get("high_dispersion_multiplier", 0.75),
        "high_dispersion_multiplier",
    )
    if high_dispersion_multiplier > 1.0:
        raise ValueError("invalid_high_dispersion_multiplier")

    return {
        "account_risk_cap_usd": account_risk_cap_usd,
        "max_notional_cap_usd": max_notional_cap_usd,
        "max_activity_participation": max_activity_participation,
        "minimum_activity_ratio": minimum_activity_ratio,
        "reduced_capacity_multiplier": reduced_capacity_multiplier,
        "noisy_regime_multiplier": noisy_regime_multiplier,
        "high_dispersion_multiplier": high_dispersion_multiplier,
    }


def _unavailable_result(
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
        "activity": {
            "latest_volume": None,
            "average_volume": None,
            "latest_notional_proxy": None,
            "average_notional_proxy": None,
            "activity_ratio": None,
            "activity_state": "UNKNOWN",
            "window": ACTIVITY_WINDOW,
        },
        "caps": {
            "account_risk_cap_usd": None,
            "stop_distance_cap_usd": None,
            "activity_participation_cap_usd": None,
            "configured_notional_cap_usd": None,
            "final_provisional_notional_cap_usd": None,
            "binding_cap": None,
        },
        "decision": {
            "status": STATUS_BLOCK,
            "reason": "Activity-aware capacity is unavailable.",
            "first_block": reason_codes[0] if reason_codes else "UNKNOWN",
        },
        "limitations": [
            "Shadow-only output.",
            "No live order-book depth.",
            "No market-impact prediction.",
            "No leverage or margin validation.",
            "No execution authority.",
        ],
        "manual_review_only": MANUAL_REVIEW_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
        "does_not_change_runtime_sizing": True,
    }


def _minimum_cap(caps: Mapping[str, float]) -> tuple[str, float]:
    binding_name = min(caps, key=caps.get)
    return binding_name, caps[binding_name]


def build_activity_aware_sizing(
    pair: str,
    candles: Sequence[Mapping[str, Any]],
    prism_context: Mapping[str, Any],
    delta_tempo: Mapping[str, Any],
    stop_distance_pct: float,
    config: Mapping[str, Any],
    timeframe: str = "5m",
) -> dict[str, Any]:
    """
    Produce a shadow-only provisional exposure capacity estimate.

    stop_distance_pct is a positive decimal fraction:
    - 0.01 means a 1% stop distance
    - 0.015 means a 1.5% stop distance

    The output is explanatory only and must not alter live sizing.
    """
    if not isinstance(pair, str) or not pair.strip():
        raise ValueError("pair_must_be_nonempty_string")

    if not isinstance(timeframe, str) or not timeframe.strip():
        raise ValueError("timeframe_must_be_nonempty_string")

    completed_bars = len(candles) if isinstance(candles, Sequence) else 0

    if completed_bars < MIN_REQUIRED_BARS:
        return _unavailable_result(
            pair=pair,
            timeframe=timeframe,
            state=HEALTH_MISSING_BARS,
            reason_codes=["ACTIVITY_SIZING.DATA.MISSING_BARS"],
            completed_bars=completed_bars,
        )

    try:
        validated_candles = _validate_candles(candles)
    except ValueError as exc:
        return _unavailable_result(
            pair=pair,
            timeframe=timeframe,
            state=HEALTH_INVALID_CANDLES,
            reason_codes=[f"ACTIVITY_SIZING.DATA.INVALID_CANDLES:{exc}"],
            completed_bars=completed_bars,
        )

    try:
        prism = _extract_prism_state(prism_context)
    except ValueError as exc:
        return _unavailable_result(
            pair=pair,
            timeframe=timeframe,
            state=HEALTH_INVALID_PRISM_CONTEXT,
            reason_codes=[f"ACTIVITY_SIZING.PRISM.INVALID_CONTEXT:{exc}"],
            completed_bars=completed_bars,
        )

    try:
        delta = _extract_delta_state(delta_tempo)
    except ValueError as exc:
        return _unavailable_result(
            pair=pair,
            timeframe=timeframe,
            state=HEALTH_INVALID_DELTA_TEMPO,
            reason_codes=[f"ACTIVITY_SIZING.DELTA.INVALID_CONTEXT:{exc}"],
            completed_bars=completed_bars,
        )

    try:
        validated_stop_distance = _as_positive_number(
            stop_distance_pct,
            "stop_distance_pct",
        )
    except ValueError as exc:
        return _unavailable_result(
            pair=pair,
            timeframe=timeframe,
            state=HEALTH_INVALID_STOP_DISTANCE,
            reason_codes=[f"ACTIVITY_SIZING.INVALID_STOP_DISTANCE:{exc}"],
            completed_bars=completed_bars,
        )

    try:
        limits = _validate_config(config)
    except ValueError as exc:
        return _unavailable_result(
            pair=pair,
            timeframe=timeframe,
            state=HEALTH_INVALID_CONFIG,
            reason_codes=[f"ACTIVITY_SIZING.INVALID_CONFIG:{exc}"],
            completed_bars=completed_bars,
        )

    if prism["health_state"] != HEALTH_AVAILABLE:
        return _unavailable_result(
            pair=pair,
            timeframe=timeframe,
            state=HEALTH_INVALID_PRISM_CONTEXT,
            reason_codes=["ACTIVITY_SIZING.PRISM.DATA_NOT_AVAILABLE"],
            completed_bars=completed_bars,
        )

    if delta["health_state"] != HEALTH_AVAILABLE:
        return _unavailable_result(
            pair=pair,
            timeframe=timeframe,
            state=HEALTH_INVALID_DELTA_TEMPO,
            reason_codes=["ACTIVITY_SIZING.DELTA.DATA_NOT_AVAILABLE"],
            completed_bars=completed_bars,
        )

    activity = calculate_activity(validated_candles)

    if activity["activity_ratio"] < limits["minimum_activity_ratio"]:
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
            "activity": activity,
            "caps": {
                "account_risk_cap_usd": round(limits["account_risk_cap_usd"], 2),
                "stop_distance_cap_usd": round(
                    limits["account_risk_cap_usd"] / validated_stop_distance,
                    2,
                ),
                "activity_participation_cap_usd": round(
                    activity["latest_notional_proxy"]
                    * limits["max_activity_participation"],
                    2,
                ),
                "configured_notional_cap_usd": round(
                    limits["max_notional_cap_usd"],
                    2,
                ),
                "final_provisional_notional_cap_usd": 0.0,
                "binding_cap": "MINIMUM_ACTIVITY_RATIO",
            },
            "decision": {
                "status": STATUS_BLOCK,
                "reason": (
                    "Observed completed-bar activity is below the configured "
                    "minimum capacity threshold."
                ),
                "first_block": "ACTIVITY_BELOW_MINIMUM",
            },
            "limitations": [
                "Shadow-only output.",
                "No live order-book depth.",
                "No market-impact prediction.",
                "No leverage or margin validation.",
                "No execution authority.",
            ],
            "manual_review_only": MANUAL_REVIEW_ONLY,
            "trade_authority": TRADE_AUTHORITY,
            "entry_authority": ENTRY_AUTHORITY,
            "does_not_send_alerts": True,
            "does_not_change_queue": True,
            "does_not_change_runtime_sizing": True,
        }

    stop_distance_cap = limits["account_risk_cap_usd"] / validated_stop_distance
    activity_cap = (
        activity["latest_notional_proxy"]
        * limits["max_activity_participation"]
    )
    configured_notional_cap = limits["max_notional_cap_usd"]

    cap_multipliers: list[tuple[str, float, str]] = []

    if prism["noise_regime"] == "CHOPPY_NOISE":
        cap_multipliers.append(
            (
                "NOISY_REGIME_REDUCTION",
                limits["noisy_regime_multiplier"],
                "PRISM noise regime is choppy; capacity is reduced.",
            )
        )
    elif prism["noise_regime"] == "HIGH_DISPERSION":
        cap_multipliers.append(
            (
                "HIGH_DISPERSION_REDUCTION",
                limits["high_dispersion_multiplier"],
                "PRISM regime has high dispersion; capacity is reduced.",
            )
        )

    if delta["alignment_state"] in {"CONFLICT", "RESTRICTED", "UNAVAILABLE"}:
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
            "activity": activity,
            "caps": {
                "account_risk_cap_usd": round(limits["account_risk_cap_usd"], 2),
                "stop_distance_cap_usd": round(stop_distance_cap, 2),
                "activity_participation_cap_usd": round(activity_cap, 2),
                "configured_notional_cap_usd": round(
                    configured_notional_cap,
                    2,
                ),
                "final_provisional_notional_cap_usd": 0.0,
                "binding_cap": "PRISM_DELTA_ALIGNMENT",
            },
            "decision": {
                "status": STATUS_BLOCK,
                "reason": (
                    "PRISM and Delta/Tempo are not aligned; activity capacity "
                    "cannot promote exposure."
                ),
                "first_block": "PRISM_DELTA_NOT_ALIGNED",
            },
            "limitations": [
                "Shadow-only output.",
                "No live order-book depth.",
                "No market-impact prediction.",
                "No leverage or margin validation.",
                "No execution authority.",
            ],
            "manual_review_only": MANUAL_REVIEW_ONLY,
            "trade_authority": TRADE_AUTHORITY,
            "entry_authority": ENTRY_AUTHORITY,
            "does_not_send_alerts": True,
            "does_not_change_queue": True,
            "does_not_change_runtime_sizing": True,
        }

    if delta["participation_state"] == "CONTRACTING":
        cap_multipliers.append(
            (
                "CONTRACTING_PARTICIPATION_REDUCTION",
                limits["reduced_capacity_multiplier"],
                "Delta/Tempo participation is contracting; capacity is reduced.",
            )
        )

    if delta["transition_state"] in {"FADING", "DETERIORATING", "UNRESOLVED"}:
        cap_multipliers.append(
            (
                "UNCONFIRMED_TRANSITION_REDUCTION",
                limits["reduced_capacity_multiplier"],
                "Delta/Tempo transition is not confirming; capacity is reduced.",
            )
        )

    raw_caps = {
        "ACCOUNT_RISK_CAP": stop_distance_cap,
        "ACTIVITY_PARTICIPATION_CAP": activity_cap,
        "CONFIGURED_NOTIONAL_CAP": configured_notional_cap,
    }

    binding_cap, base_cap = _minimum_cap(raw_caps)

    applied_multipliers: list[dict[str, Any]] = []
    final_cap = base_cap

    for name, multiplier, reason in cap_multipliers:
        final_cap *= multiplier
        applied_multipliers.append(
            {
                "name": name,
                "multiplier": multiplier,
                "reason": reason,
            }
        )

    final_cap = max(0.0, final_cap)

    if final_cap <= 0:
        status = STATUS_BLOCK
        reason = "No provisional activity capacity remains after constraints."
        first_block = "ZERO_CAPACITY"
    elif applied_multipliers:
        status = STATUS_REDUCE
        reason = (
            "Provisional exposure capacity is reduced by PRISM and/or "
            "Delta/Tempo constraints."
        )
        first_block = None
    else:
        status = STATUS_ALLOW
        reason = (
            "Provisional exposure capacity is available within configured "
            "risk, activity, and notional caps."
        )
        first_block = None

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
        "activity": activity,
        "caps": {
            "account_risk_cap_usd": round(limits["account_risk_cap_usd"], 2),
            "stop_distance_pct": round(validated_stop_distance, 8),
            "stop_distance_cap_usd": round(stop_distance_cap, 2),
            "activity_participation_cap_usd": round(activity_cap, 2),
            "configured_notional_cap_usd": round(configured_notional_cap, 2),
            "base_cap_usd": round(base_cap, 2),
            "final_provisional_notional_cap_usd": round(final_cap, 2),
            "binding_cap": binding_cap,
            "applied_reductions": applied_multipliers,
        },
        "decision": {
            "status": status,
            "reason": reason,
            "first_block": first_block,
        },
        "limitations": [
            "Shadow-only output.",
            "No live order-book depth.",
            "No market-impact prediction.",
            "No leverage or margin validation.",
            "No execution authority.",
            "Completed-candle activity is only a conservative capacity proxy.",
        ],
        "manual_review_only": MANUAL_REVIEW_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
        "does_not_change_runtime_sizing": True,
    }
