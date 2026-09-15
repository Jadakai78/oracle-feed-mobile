"""
Delta/Tempo v1

Deterministic, completed-candle-only pressure and timing context.

This module:
- Performs no market reads.
- Performs no order, alert, queue, scoring, sizing, or execution action.
- Does not select trades or grant entry authority.
- Uses a caller-supplied PRISM context only to describe alignment/conflict.
- Returns a structured Delta/Tempo record for manual review only.

Expected candle shape:
{
    "open": float,
    "high": float,
    "low": float,
    "close": float,
    "volume": float,
    optional "timestamp": str
}
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

RECORDTYPE = "DELTATEMPO"
SCHEMA_VERSION = "delta.tempo.v1"

MIN_REQUIRED_BARS = 40
PRESSURE_WINDOW = 12
VOLUME_WINDOW = 20
RANGE_WINDOW = 20

HEALTH_AVAILABLE = "AVAILABLE"
HEALTH_MISSING_BARS = "MISSING_BARS"
HEALTH_INVALID_CANDLES = "INVALID_CANDLES"
HEALTH_INVALID_PRISM_CONTEXT = "INVALID_PRISM_CONTEXT"

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


def _candle_range(candle: Mapping[str, float]) -> float:
    return candle["high"] - candle["low"]


def _normalised_buyer_seller_pressure(
    candle: Mapping[str, float],
) -> tuple[float, float]:
    """
    Uses the completed candle's close location within its range, weighted by volume.

    This is a transparent candle-pressure proxy. It is not exchange order-flow
    CVD and should not be labeled as CVD.
    """
    candle_range = _candle_range(candle)

    if candle_range <= 0:
        return 0.5 * candle["volume"], 0.5 * candle["volume"]

    close_location = (candle["close"] - candle["low"]) / candle_range
    close_location = max(0.0, min(1.0, close_location))

    buyer_pressure = candle["volume"] * close_location
    seller_pressure = candle["volume"] * (1.0 - close_location)

    return buyer_pressure, seller_pressure


def calculate_pressure(
    candles: Sequence[Mapping[str, float]],
    window: int = PRESSURE_WINDOW,
) -> dict[str, Any]:
    recent = candles[-window:]

    buyer_total = 0.0
    seller_total = 0.0

    for candle in recent:
        buyer, seller = _normalised_buyer_seller_pressure(candle)
        buyer_total += buyer
        seller_total += seller

    total = buyer_total + seller_total

    if total <= 0:
        buyer_share = 0.5
        seller_share = 0.5
    else:
        buyer_share = buyer_total / total
        seller_share = seller_total / total

    balance = buyer_share - seller_share

    if balance >= 0.12:
        state = "BUYER_FAVORING"
    elif balance <= -0.12:
        state = "SELLER_FAVORING"
    else:
        state = "BALANCED"

    return {
        "state": state,
        "buyer_pressure": round(buyer_share, 4),
        "seller_pressure": round(seller_share, 4),
        "balance": round(balance, 4),
        "window": window,
    }


def calculate_participation(
    candles: Sequence[Mapping[str, float]],
    window: int = VOLUME_WINDOW,
) -> dict[str, Any]:
    recent = candles[-window:]
    latest_volume = recent[-1]["volume"]
    baseline_volumes = [candle["volume"] for candle in recent[:-1]]

    average_volume = _mean(baseline_volumes) if baseline_volumes else latest_volume
    ratio = latest_volume / max(average_volume, 1.0)

    if ratio >= 1.25:
        state = "EXPANDING"
    elif ratio <= 0.75:
        state = "CONTRACTING"
    else:
        state = "NORMAL"

    return {
        "latest_volume": round(latest_volume, 8),
        "average_volume": round(average_volume, 8),
        "volume_expansion_ratio": round(ratio, 4),
        "state": state,
        "window": window,
    }


def calculate_tempo(
    candles: Sequence[Mapping[str, float]],
    window: int = RANGE_WINDOW,
) -> dict[str, Any]:
    recent = candles[-window:]
    latest_range = _candle_range(recent[-1])
    baseline_ranges = [_candle_range(candle) for candle in recent[:-1]]

    average_range = _mean(baseline_ranges) if baseline_ranges else latest_range
    ratio = latest_range / max(average_range, 1e-12)

    if ratio >= 1.20:
        state = "EXPANDING"
    elif ratio <= 0.80:
        state = "CONTRACTING"
    else:
        state = "BALANCED"

    return {
        "latest_range": round(latest_range, 8),
        "average_range": round(average_range, 8),
        "range_expansion_ratio": round(ratio, 4),
        "state": state,
        "window": window,
    }


def derive_transition(
    pressure_state: str,
    participation_state: str,
    tempo_state: str,
    speed_phase: str,
) -> tuple[str, str]:
    phase = speed_phase.upper()

    if phase == "DECAY":
        return (
            "DETERIORATING",
            "Speed phase is DECAY; timing is not treated as confirming.",
        )

    if (
        pressure_state == "BUYER_FAVORING"
        and participation_state == "EXPANDING"
        and tempo_state in {"EXPANDING", "BALANCED"}
    ):
        return (
            "CONFIRMING",
            "Buyer pressure and participation support an improving transition.",
        )

    if (
        pressure_state == "SELLER_FAVORING"
        and participation_state == "EXPANDING"
        and tempo_state in {"EXPANDING", "BALANCED"}
    ):
        return (
            "CONFIRMING",
            "Seller pressure and participation support an improving transition.",
        )

    if participation_state == "CONTRACTING" and tempo_state == "CONTRACTING":
        return (
            "FADING",
            "Participation and range are both contracting.",
        )

    if pressure_state == "BALANCED":
        return (
            "UNRESOLVED",
            "Pressure is balanced and does not confirm a directional transition.",
        )

    return (
        "WATCH",
        "Pressure exists but participation and tempo do not yet confirm it.",
    )


def _expected_pressure_for_route(route: str) -> str:
    """
    PRISM route alone does not encode long/short direction.

    This helper only tells us whether the terrain is expected to have a
    directional Delta/Tempo confirmation. Direction is inferred from PRISM
    trend alignment in derive_prism_alignment().
    """
    if route in {"RECLAIM_REVERSAL", "EXPANSION_CONTINUATION"}:
        return "DIRECTIONAL"
    if route in {"RANGE_FADE", "NO_CHASE", "NO_ROUTE", "OBSERVE"}:
        return "NON_DIRECTIONAL"
    return "UNKNOWN"


def derive_prism_alignment(
    prism_context: Mapping[str, Any],
    pressure_state: str,
    participation_state: str,
    transition_state: str,
) -> dict[str, str]:
    """
    Describe agreement or conflict with PRISM. This function does not authorize
    an action and does not create a score.
    """
    if not isinstance(prism_context, Mapping):
        return {
            "state": "UNAVAILABLE",
            "reason": "PRISM context was not supplied.",
        }

    terrain = prism_context.get("terrain")
    if not isinstance(terrain, Mapping):
        return {
            "state": "UNAVAILABLE",
            "reason": "PRISM terrain object is unavailable.",
        }

    trend_alignment = terrain.get("trend_alignment", "NEUTRAL")
    route = terrain.get("route", "NO_ROUTE")
    terrain_state = terrain.get("terrain_state", "UNAVAILABLE")

    if terrain_state == "UNAVAILABLE":
        return {
            "state": "UNAVAILABLE",
            "reason": "PRISM terrain is unavailable.",
        }

    if route in {"NO_ROUTE", "NO_CHASE"}:
        return {
            "state": "RESTRICTED",
            "reason": f"PRISM route is {route}; Delta/Tempo cannot promote it.",
        }

    expected = _expected_pressure_for_route(route)

    if expected == "NON_DIRECTIONAL":
        return {
            "state": "OBSERVE",
            "reason": "PRISM route is observational; Delta/Tempo remains descriptive.",
        }

    if trend_alignment == "LONG":
        if pressure_state == "SELLER_FAVORING":
            return {
                "state": "CONFLICT",
                "reason": "Seller-favoring pressure conflicts with long PRISM alignment.",
            }

        if (
            pressure_state == "BUYER_FAVORING"
            and participation_state != "CONTRACTING"
            and transition_state == "CONFIRMING"
        ):
            return {
                "state": "ALIGNED",
                "reason": "Buyer pressure and participation support long PRISM terrain.",
            }

        return {
            "state": "WATCH",
            "reason": "Long PRISM terrain exists, but timing confirmation is incomplete.",
        }

    if trend_alignment == "SHORT":
        if pressure_state == "BUYER_FAVORING":
            return {
                "state": "CONFLICT",
                "reason": "Buyer-favoring pressure conflicts with short PRISM alignment.",
            }

        if (
            pressure_state == "SELLER_FAVORING"
            and participation_state != "CONTRACTING"
            and transition_state == "CONFIRMING"
        ):
            return {
                "state": "ALIGNED",
                "reason": "Seller pressure and participation support short PRISM terrain.",
            }

        return {
            "state": "WATCH",
            "reason": "Short PRISM terrain exists, but timing confirmation is incomplete.",
        }

    return {
        "state": "UNRESOLVED",
        "reason": "PRISM trend alignment is neutral or unavailable.",
    }


def _unavailable_context(
    pair: str,
    timeframe: str,
    health_state: str,
    reason_codes: list[str],
    completed_bars: int,
    speed_phase: str,
) -> dict[str, Any]:
    return {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _now_utc(),
        "pair": pair,
        "timeframe": timeframe,
        "data_health": {
            "state": health_state,
            "reason_codes": reason_codes,
            "completed_bars": completed_bars,
            "required_bars": MIN_REQUIRED_BARS,
        },
        "pressure": {
            "state": "UNAVAILABLE",
            "buyer_pressure": None,
            "seller_pressure": None,
            "balance": None,
            "window": PRESSURE_WINDOW,
        },
        "participation": {
            "latest_volume": None,
            "average_volume": None,
            "volume_expansion_ratio": None,
            "state": "UNKNOWN",
            "window": VOLUME_WINDOW,
        },
        "tempo": {
            "latest_range": None,
            "average_range": None,
            "range_expansion_ratio": None,
            "state": "UNKNOWN",
            "transition": "UNAVAILABLE",
            "transition_reason": "Delta/Tempo context unavailable.",
            "window": RANGE_WINDOW,
        },
        "speed_phase": speed_phase.upper(),
        "prism_alignment": {
            "state": "UNAVAILABLE",
            "reason": "Delta/Tempo context unavailable.",
        },
        "manual_review_only": MANUAL_REVIEW_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
    }


def build_delta_tempo(
    pair: str,
    candles: Sequence[Mapping[str, Any]],
    speed_phase: str,
    prism_context: Mapping[str, Any] | None = None,
    timeframe: str = "5m",
) -> dict[str, Any]:
    """
    Build a deterministic Delta/Tempo context from completed candles.

    The caller is responsible for passing completed bars only. This function
    does not fetch market data, infer bar completion, or grant authority.
    """
    if not isinstance(pair, str) or not pair.strip():
        raise ValueError("pair_must_be_nonempty_string")

    if not isinstance(timeframe, str) or not timeframe.strip():
        raise ValueError("timeframe_must_be_nonempty_string")

    if not isinstance(speed_phase, str) or not speed_phase.strip():
        speed_phase = "NONE"

    completed_bars = len(candles) if isinstance(candles, Sequence) else 0

    if completed_bars < MIN_REQUIRED_BARS:
        return _unavailable_context(
            pair=pair,
            timeframe=timeframe,
            health_state=HEALTH_MISSING_BARS,
            reason_codes=["DELTA_TEMPO.DATA.MISSING_BARS"],
            completed_bars=completed_bars,
            speed_phase=speed_phase,
        )

    try:
        validated = _validate_candles(candles)
    except ValueError as exc:
        return _unavailable_context(
            pair=pair,
            timeframe=timeframe,
            health_state=HEALTH_INVALID_CANDLES,
            reason_codes=[f"DELTA_TEMPO.DATA.INVALID_CANDLES:{exc}"],
            completed_bars=completed_bars,
            speed_phase=speed_phase,
        )

    if prism_context is not None and not isinstance(prism_context, Mapping):
        return _unavailable_context(
            pair=pair,
            timeframe=timeframe,
            health_state=HEALTH_INVALID_PRISM_CONTEXT,
            reason_codes=["DELTA_TEMPO.PRISM.INVALID_CONTEXT"],
            completed_bars=completed_bars,
            speed_phase=speed_phase,
        )

    pressure = calculate_pressure(validated)
    participation = calculate_participation(validated)
    tempo = calculate_tempo(validated)

    transition, transition_reason = derive_transition(
        pressure_state=pressure["state"],
        participation_state=participation["state"],
        tempo_state=tempo["state"],
        speed_phase=speed_phase,
    )

    prism_alignment = derive_prism_alignment(
        prism_context=prism_context or {},
        pressure_state=pressure["state"],
        participation_state=participation["state"],
        transition_state=transition,
    )

    tempo["transition"] = transition
    tempo["transition_reason"] = transition_reason

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
        "pressure": pressure,
        "participation": participation,
        "tempo": tempo,
        "speed_phase": speed_phase.upper(),
        "prism_alignment": prism_alignment,
        "manual_review_only": MANUAL_REVIEW_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
    }
