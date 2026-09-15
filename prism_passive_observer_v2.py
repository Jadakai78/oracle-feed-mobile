"""
PRISM Passive Observer v2

Passive, dual-ledger integration adapter for caller-supplied completed
timestamped OHLCV candles.

For one completed bar it:
1. Validates normalized timestamped candles.
2. Builds PRISM Context, Delta/Tempo, PRISM Evaluation, and shadow sizing.
3. Writes one v2 PRISM observation using stable bar identity.
4. Makes a copied timestamp-adapted candle payload for LAR-Gate v1.1.
5. Records one passive LAR annotation linked to the observation.

This module does not:
- Import master_engine.py.
- Fetch network data or poll an exchange.
- Send alerts, webhooks, or messages.
- Modify scanner state, queues, execution, or runtime sizing.
- Generate trade geometry or resolve outcomes.
- Allow LAR entry_permission to override PRISM evaluation.

Important:
- If the observation ledger returns CONFLICT, no LAR annotation is written.
- LAR receives a separately constructed candle list with `timestamp`, leaving
  the PRISM candle contract and original source candle objects untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from activity_aware_sizing_v1 import build_activity_aware_sizing
from delta_tempo_v1 import build_delta_tempo
from liquidity_acceptance_rejection_v1 import (
    analyze_liquidity_acceptance_rejection,
)
from prism_context_v1 import build_prism_context
from prism_evaluation_v1 import build_prism_evaluation
from prism_lar_annotation_ledger_v1 import record_lar_annotation
from prism_observation_ledger_v2 import record_observation

RECORDTYPE = "PRISMPASSIVEOBSERVERRESULT"
SCHEMA_VERSION = "prism.passive.observer.v2"

TIMEFRAME_5M = "5m"

STATUS_WRITTEN = "WRITTEN"
STATUS_DUPLICATE = "DUPLICATE"
STATUS_CONFLICT = "CONFLICT"
STATUS_NOT_WRITTEN = "NOT_WRITTEN"

MANUAL_REVIEW_ONLY = True
TRADE_AUTHORITY = False
ENTRY_AUTHORITY = False


def _require_nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}_must_be_nonempty_string")
    return value.strip()


def _require_finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}_must_be_number")

    result = float(value)

    if result != result:
        raise ValueError(f"{name}_must_not_be_nan")

    if result in (float("inf"), float("-inf")):
        raise ValueError(f"{name}_must_be_finite")

    return result


def _parse_utc_timestamp(value: Any, name: str) -> str:
    timestamp = _require_nonempty_string(value, name)
    normalized = timestamp.replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name}_must_be_iso8601_utc") from exc

    if parsed.tzinfo is None:
        raise ValueError(f"{name}_must_include_timezone")

    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def canonical_pair_from_symbol(symbol: str, quote: str = "USD") -> str:
    """
    Convert SOL -> SOLUSD while leaving SOLUSD as SOLUSD.
    """
    symbol = _require_nonempty_string(symbol, "symbol").upper()
    quote = _require_nonempty_string(quote, "quote").upper()

    if symbol.endswith(quote):
        base = symbol[: -len(quote)]

        if not base:
            raise ValueError("symbol_must_include_base_before_quote")

        return symbol

    return f"{symbol}{quote}"


def _normalize_candle(
    candle: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    if not isinstance(candle, Mapping):
        raise ValueError(f"candle_{index}_must_be_object")

    timestamp_utc = _parse_utc_timestamp(
        candle.get("timestamp_utc"),
        f"candle_{index}_timestamp_utc",
    )

    open_price = _require_finite_number(
        candle.get("open"),
        f"candle_{index}_open",
    )
    high_price = _require_finite_number(
        candle.get("high"),
        f"candle_{index}_high",
    )
    low_price = _require_finite_number(
        candle.get("low"),
        f"candle_{index}_low",
    )
    close_price = _require_finite_number(
        candle.get("close"),
        f"candle_{index}_close",
    )
    volume = _require_finite_number(
        candle.get("volume"),
        f"candle_{index}_volume",
    )

    if low_price > high_price:
        raise ValueError(f"candle_{index}_low_must_not_exceed_high")

    if open_price < low_price or open_price > high_price:
        raise ValueError(f"candle_{index}_open_must_be_within_range")

    if close_price < low_price or close_price > high_price:
        raise ValueError(f"candle_{index}_close_must_be_within_range")

    if volume < 0:
        raise ValueError(f"candle_{index}_volume_must_not_be_negative")

    return {
        "timestamp_utc": timestamp_utc,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    }


def normalize_completed_candles(
    candles: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Validate a chronological batch of completed normalized candles.

    Timestamps must be strictly increasing. This module does not infer whether
    bars are complete; the caller must supply a completed-bar-only batch.
    """
    if not isinstance(candles, Sequence) or isinstance(candles, (str, bytes)):
        raise ValueError("candles_must_be_sequence")

    if not candles:
        raise ValueError("candles_must_not_be_empty")

    normalized = [
        _normalize_candle(candle=candle, index=index)
        for index, candle in enumerate(candles)
    ]

    previous_timestamp: str | None = None

    for index, candle in enumerate(normalized):
        timestamp = candle["timestamp_utc"]

        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise ValueError(
                f"candle_{index}_timestamp_must_be_strictly_increasing"
            )

        previous_timestamp = timestamp

    return normalized


def build_lar_candles(
    normalized_candles: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Build an independent LAR-compatible candle copy.

    LAR v1.1 expects `timestamp`; PRISM source candles use `timestamp_utc`.
    This translation occurs only in new copied dictionaries.
    """
    return [
        {
            "timestamp": candle["timestamp_utc"],
            "open": candle["open"],
            "high": candle["high"],
            "low": candle["low"],
            "close": candle["close"],
            "volume": candle["volume"],
        }
        for candle in normalized_candles
    ]


def _validate_sizing_config(
    sizing_config: Mapping[str, Any],
) -> Mapping[str, Any]:
    if not isinstance(sizing_config, Mapping):
        raise ValueError("sizing_config_must_be_object")

    if not sizing_config:
        raise ValueError("sizing_config_must_not_be_empty")

    return sizing_config


def _not_written_lar_result(reason: str) -> dict[str, Any]:
    return {
        "status": STATUS_NOT_WRITTEN,
        "reason": reason,
        "annotation_key": None,
        "annotation_id": None,
        "path": None,
    }


def observe_completed_bar(
    observation_ledger_path: str | Path,
    lar_annotation_ledger_path: str | Path,
    symbol: str,
    candles: Sequence[Mapping[str, Any]],
    speed_phase: str,
    sizing_config: Mapping[str, Any],
    stop_distance_pct: float,
    timeframe: str = TIMEFRAME_5M,
    quote: str = "USD",
    source_label: str = "caller_supplied_completed_ohlcv",
    lar_atr_multiplier: float = 0.15,
    lar_pending_sweep: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run one completed-bar passive observation and LAR annotation attempt.

    Observation result:
    - WRITTEN: new canonical PRISM observation was persisted.
    - DUPLICATE: same bar and same PRISM analytical fingerprint exists.
    - CONFLICT: same bar identity exists with different PRISM analysis.

    LAR annotation behavior:
    - WRITTEN / DUPLICATE / CONFLICT only if observation result is not CONFLICT.
    - NOT_WRITTEN if observation result is CONFLICT.

    `lar_pending_sweep` is caller-managed state. This observer does not keep
    memory between processes or silently invent pending state.
    """
    observation_ledger_path = Path(observation_ledger_path)
    lar_annotation_ledger_path = Path(lar_annotation_ledger_path)

    timeframe = _require_nonempty_string(timeframe, "timeframe")
    speed_phase = _require_nonempty_string(speed_phase, "speed_phase")
    source_label = _require_nonempty_string(source_label, "source_label")

    if timeframe != TIMEFRAME_5M:
        raise ValueError("timeframe_must_be_5m")

    if lar_pending_sweep is not None and not isinstance(
        lar_pending_sweep,
        Mapping,
    ):
        raise ValueError("lar_pending_sweep_must_be_object_or_null")

    lar_atr_multiplier = _require_finite_number(
        lar_atr_multiplier,
        "lar_atr_multiplier",
    )

    if lar_atr_multiplier <= 0:
        raise ValueError("lar_atr_multiplier_must_be_positive")

    stop_distance_pct = _require_finite_number(
        stop_distance_pct,
        "stop_distance_pct",
    )

    if stop_distance_pct <= 0:
        raise ValueError("stop_distance_pct_must_be_positive")

    pair = canonical_pair_from_symbol(symbol=symbol, quote=quote)
    normalized_candles = normalize_completed_candles(candles)
    sizing_config = _validate_sizing_config(sizing_config)

    completed_bar_timestamp_utc = normalized_candles[-1]["timestamp_utc"]

    prism_context = build_prism_context(
        pair=pair,
        candles=normalized_candles,
        speed_phase=speed_phase,
    )

    delta_tempo = build_delta_tempo(
        pair=pair,
        candles=normalized_candles,
        speed_phase=speed_phase,
        prism_context=prism_context,
    )

    evaluation = build_prism_evaluation(
        prism_context=prism_context,
        delta_tempo=delta_tempo,
    )

    sizing = build_activity_aware_sizing(
        pair=pair,
        candles=normalized_candles,
        prism_context=prism_context,
        delta_tempo=delta_tempo,
        stop_distance_pct=stop_distance_pct,
        config=dict(sizing_config),
    )

    observation_result = record_observation(
        path=observation_ledger_path,
        evaluation=evaluation,
        sizing=sizing,
        observed_at_utc=completed_bar_timestamp_utc,
    )

    observation_status = observation_result["status"]
    observation = observation_result["observation"]

    lar_result: dict[str, Any] | None = None
    lar_annotation_result: dict[str, Any]

    if observation_status == STATUS_CONFLICT:
        lar_annotation_result = _not_written_lar_result(
            "observation_conflict_prevents_lar_annotation_write"
        )
    else:
        lar_candles = build_lar_candles(normalized_candles)

        lar_result = analyze_liquidity_acceptance_rejection(
            candles=lar_candles,
            pair=pair,
            timeframe=timeframe,
            atr_multiplier=lar_atr_multiplier,
            pending_sweep=(
                dict(lar_pending_sweep)
                if lar_pending_sweep is not None
                else None
            ),
        )

        lar_annotation_result = record_lar_annotation(
            path=lar_annotation_ledger_path,
            observation_key=observation["observation_key"],
            observation_id=observation["observation_id"],
            lar_result=lar_result,
            source_label=source_label,
            source_completed_bar_timestamp_utc=completed_bar_timestamp_utc,
        )

    return {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "pair": pair,
        "timeframe": timeframe,
        "source": {
            "label": source_label,
            "completed_bar_timestamp_utc": completed_bar_timestamp_utc,
            "candle_count": len(normalized_candles),
            "caller_supplied": True,
            "network_reads_performed": False,
        },
        "prism_context": prism_context,
        "delta_tempo": delta_tempo,
        "evaluation": evaluation,
        "activity_aware_sizing": sizing,
        "observation_ledger": {
            "status": observation_result["status"],
            "observation_key": observation_result["observation_key"],
            "observation_id": observation_result["observation_id"],
            "path": observation_result["path"],
            "existing_observation_id": observation_result.get(
                "existing_observation_id"
            ),
        },
        "lar": {
            "result": lar_result,
            "pending_sweep_for_next_bar": (
                lar_result.get("pending_sweep")
                if lar_result is not None
                else None
            ),
            "annotation_ledger": {
                "status": lar_annotation_result["status"],
                "reason": lar_annotation_result.get("reason"),
                "annotation_key": lar_annotation_result.get(
                    "annotation_key"
                ),
                "annotation_id": lar_annotation_result.get(
                    "annotation_id"
                ),
                "path": lar_annotation_result.get("path"),
                "existing_annotation_id": lar_annotation_result.get(
                    "existing_annotation_id"
                ),
            },
        },
        "manual_review_only": MANUAL_REVIEW_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
        "does_not_change_runtime_sizing": True,
        "lar_entry_permission_is_descriptive_only": True,
        "lar_does_not_override_prism_evaluation": True,
    }
