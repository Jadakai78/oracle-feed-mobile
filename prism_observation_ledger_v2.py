"""
PRISM Observation Ledger v2

Append-only JSONL ledger with completed-bar identity and analytical
content-fingerprint protection.

V2 fixes the v1 identity flaw:

- observation_key is the stable natural bar key:
      PAIR|TIMEFRAME|OBSERVED_AT_UTC

- observation_id is a deterministic hash of observation_key only.

- content_fingerprint hashes analytical content only. It explicitly excludes
  volatile generated_at_utc and written_at_utc fields.

- Same observation_key + same content_fingerprint:
      DUPLICATE

- Same observation_key + different content_fingerprint:
      CONFLICT
  The differing record is not silently appended.

- New observation_key:
      WRITTEN

This module:
- Is append-only.
- Never modifies prior rows.
- Does not call market data, create orders, alerts, queues, or sizing changes.
- Accepts only manual-review-only, non-authoritative upstream records.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

RECORDTYPE = "PRISMOBSERVATION"
SCHEMA_VERSION = "prism.observation.ledger.v2"

EVALUATION_RECORDTYPE = "PRISMEVALUATION"
EVALUATION_SCHEMA_VERSION = "prism.evaluation.v1"

SIZING_RECORDTYPE = "ACTIVITYAWARESIZING"
SIZING_SCHEMA_VERSION = "activity.aware.sizing.v1"

STATUS_WRITTEN = "WRITTEN"
STATUS_DUPLICATE = "DUPLICATE"
STATUS_CONFLICT = "CONFLICT"

MANUAL_REVIEW_ONLY = True
TRADE_AUTHORITY = False
ENTRY_AUTHORITY = False

VOLATILE_KEYS = frozenset(
    {
        "generated_at_utc",
        "written_at_utc",
    }
)


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
    return value.strip()


def _require_true(value: Any, name: str) -> None:
    if value is not True:
        raise ValueError(f"{name}_must_be_true")


def _require_false(value: Any, name: str) -> None:
    if value is not False:
        raise ValueError(f"{name}_must_be_false")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _content_hash(value: Any) -> str:
    payload = _canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _strip_volatile_fields(value: Any) -> Any:
    """
    Return a recursively copied value with volatile audit-time fields removed.

    This is used only for analytical fingerprinting. The original upstream
    records and their generated timestamps remain preserved in the written
    observation record for traceability.
    """
    if isinstance(value, Mapping):
        return {
            key: _strip_volatile_fields(child)
            for key, child in value.items()
            if key not in VOLATILE_KEYS
        }

    if isinstance(value, list):
        return [_strip_volatile_fields(item) for item in value]

    if isinstance(value, tuple):
        return [_strip_volatile_fields(item) for item in value]

    return value


def _normalize_observed_at_utc(value: Any) -> str:
    timestamp = _require_nonempty_string(value, "observed_at_utc")
    normalized = timestamp.replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("observed_at_utc_must_be_iso8601_utc") from exc

    if parsed.tzinfo is None:
        raise ValueError("observed_at_utc_must_include_timezone")

    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def build_observation_key(
    pair: str,
    timeframe: str,
    observed_at_utc: str,
) -> str:
    """
    Create the natural identity for one pair/timeframe/completed bar.
    """
    pair = _require_nonempty_string(pair, "pair")
    timeframe = _require_nonempty_string(timeframe, "timeframe")
    observed_at_utc = _normalize_observed_at_utc(observed_at_utc)

    return f"{pair}|{timeframe}|{observed_at_utc}"


def _validate_evaluation(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    evaluation = _require_mapping(evaluation, "evaluation")

    if evaluation.get("recordtype") != EVALUATION_RECORDTYPE:
        raise ValueError("unexpected_evaluation_recordtype")

    if evaluation.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        raise ValueError("unexpected_evaluation_schema_version")

    _require_true(
        evaluation.get("manual_review_only"),
        "evaluation_manual_review_only",
    )
    _require_false(
        evaluation.get("trade_authority"),
        "evaluation_trade_authority",
    )
    _require_false(
        evaluation.get("entry_authority"),
        "evaluation_entry_authority",
    )

    pair = _require_nonempty_string(evaluation.get("pair"), "evaluation_pair")
    timeframe = _require_nonempty_string(
        evaluation.get("timeframe"),
        "evaluation_timeframe",
    )

    prism = _require_mapping(evaluation.get("prism"), "evaluation_prism")
    delta_tempo = _require_mapping(
        evaluation.get("delta_tempo"),
        "evaluation_delta_tempo",
    )
    structure = _require_mapping(
        evaluation.get("structure"),
        "evaluation_structure",
    )
    decision = _require_mapping(
        evaluation.get("decision"),
        "evaluation_decision",
    )

    decision_status = _require_nonempty_string(
        decision.get("status"),
        "evaluation_decision_status",
    )
    decision_reason = _require_nonempty_string(
        decision.get("reason"),
        "evaluation_decision_reason",
    )

    return {
        "pair": pair,
        "timeframe": timeframe,
        "prism": dict(prism),
        "delta_tempo": dict(delta_tempo),
        "structure": dict(structure),
        "decision": {
            "status": decision_status,
            "reason": decision_reason,
            "first_block": decision.get("first_block"),
        },
        "generated_at_utc": evaluation.get("generated_at_utc"),
        "recordtype": evaluation.get("recordtype"),
        "schema_version": evaluation.get("schema_version"),
    }


def _validate_sizing(
    sizing: Mapping[str, Any] | None,
    pair: str,
    timeframe: str,
) -> dict[str, Any] | None:
    if sizing is None:
        return None

    sizing = _require_mapping(sizing, "sizing")

    if sizing.get("recordtype") != SIZING_RECORDTYPE:
        raise ValueError("unexpected_sizing_recordtype")

    if sizing.get("schema_version") != SIZING_SCHEMA_VERSION:
        raise ValueError("unexpected_sizing_schema_version")

    _require_true(
        sizing.get("manual_review_only"),
        "sizing_manual_review_only",
    )
    _require_false(
        sizing.get("trade_authority"),
        "sizing_trade_authority",
    )
    _require_false(
        sizing.get("entry_authority"),
        "sizing_entry_authority",
    )

    sizing_pair = _require_nonempty_string(sizing.get("pair"), "sizing_pair")
    sizing_timeframe = _require_nonempty_string(
        sizing.get("timeframe"),
        "sizing_timeframe",
    )

    if sizing_pair != pair:
        raise ValueError("pair_mismatch_between_evaluation_and_sizing")

    if sizing_timeframe != timeframe:
        raise ValueError("timeframe_mismatch_between_evaluation_and_sizing")

    data_health = _require_mapping(sizing.get("data_health"), "sizing_data_health")
    activity = _require_mapping(sizing.get("activity"), "sizing_activity")
    caps = _require_mapping(sizing.get("caps"), "sizing_caps")
    decision = _require_mapping(sizing.get("decision"), "sizing_decision")

    return {
        "data_health": dict(data_health),
        "activity": dict(activity),
        "caps": dict(caps),
        "decision": dict(decision),
        "generated_at_utc": sizing.get("generated_at_utc"),
        "recordtype": sizing.get("recordtype"),
        "schema_version": sizing.get("schema_version"),
    }


def build_observation(
    evaluation: Mapping[str, Any],
    sizing: Mapping[str, Any] | None = None,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    """
    Build one canonical v2 observation record.

    The record preserves source generated timestamps for auditability, but
    `content_fingerprint` removes those volatile fields before hashing.

    `observed_at_utc` should be the final completed candle timestamp supplied
    by the passive observer, never a scanner loop or wall-clock timestamp.
    """
    validated_evaluation = _validate_evaluation(evaluation)
    validated_sizing = _validate_sizing(
        sizing=sizing,
        pair=validated_evaluation["pair"],
        timeframe=validated_evaluation["timeframe"],
    )

    if observed_at_utc is None:
        observed_at_utc = _now_utc()

    observed_at_utc = _normalize_observed_at_utc(observed_at_utc)

    observation_key = build_observation_key(
        pair=validated_evaluation["pair"],
        timeframe=validated_evaluation["timeframe"],
        observed_at_utc=observed_at_utc,
    )

    observation_id = _content_hash(
        {
            "recordtype": RECORDTYPE,
            "schema_version": SCHEMA_VERSION,
            "observation_key": observation_key,
        }
    )

    analytical_payload = {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "observation_key": observation_key,
        "pair": validated_evaluation["pair"],
        "timeframe": validated_evaluation["timeframe"],
        "observed_at_utc": observed_at_utc,
        "prism": validated_evaluation["prism"],
        "delta_tempo": validated_evaluation["delta_tempo"],
        "structure": validated_evaluation["structure"],
        "decision": validated_evaluation["decision"],
        "activity_aware_sizing": validated_sizing,
    }

    content_fingerprint = _content_hash(
        _strip_volatile_fields(analytical_payload)
    )

    return {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "observation_key": observation_key,
        "observation_id": observation_id,
        "content_fingerprint": content_fingerprint,
        "observed_at_utc": observed_at_utc,
        "written_at_utc": _now_utc(),
        "pair": validated_evaluation["pair"],
        "timeframe": validated_evaluation["timeframe"],
        "sources": {
            "evaluation": {
                "recordtype": validated_evaluation["recordtype"],
                "schema_version": validated_evaluation["schema_version"],
                "generated_at_utc": validated_evaluation["generated_at_utc"],
            },
            "activity_aware_sizing": (
                {
                    "recordtype": validated_sizing["recordtype"],
                    "schema_version": validated_sizing["schema_version"],
                    "generated_at_utc": validated_sizing["generated_at_utc"],
                }
                if validated_sizing is not None
                else None
            ),
        },
        "prism": validated_evaluation["prism"],
        "delta_tempo": validated_evaluation["delta_tempo"],
        "structure": validated_evaluation["structure"],
        "decision": validated_evaluation["decision"],
        "activity_aware_sizing": validated_sizing,
        "outcome": {
            "status": "PENDING",
            "resolver": None,
            "resolved_at_utc": None,
            "label": None,
        },
        "manual_review_only": MANUAL_REVIEW_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
        "does_not_change_runtime_sizing": True,
    }


def iter_observations(path: str | Path) -> list[dict[str, Any]]:
    """
    Read all JSONL rows from a v2 ledger.

    Missing/empty files return an empty list.
    Invalid JSON or non-object records fail closed.
    """
    ledger_path = Path(path)

    if not ledger_path.exists():
        return []

    observations: list[dict[str, Any]] = []

    with ledger_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()

            if not stripped:
                continue

            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid_ledger_json_line_{line_number}:{exc.msg}"
                ) from exc

            if not isinstance(record, dict):
                raise ValueError(f"invalid_ledger_record_line_{line_number}")

            observations.append(record)

    return observations


def existing_observations_by_key(
    path: str | Path,
) -> dict[str, dict[str, Any]]:
    """
    Index existing v2 records by their stable observation_key.

    Duplicate keys already present inside a v2 ledger are treated as ledger
    corruption and fail closed rather than allowing ambiguous idempotency.
    """
    indexed: dict[str, dict[str, Any]] = {}

    for record in iter_observations(path):
        if record.get("recordtype") != RECORDTYPE:
            raise ValueError("unexpected_ledger_recordtype")

        if record.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unexpected_ledger_schema_version")

        observation_key = _require_nonempty_string(
            record.get("observation_key"),
            "ledger_observation_key",
        )

        if observation_key in indexed:
            raise ValueError("duplicate_observation_key_in_ledger")

        indexed[observation_key] = record

    return indexed


def append_observation(
    path: str | Path,
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Append one v2 observation using stable bar identity and fingerprint checks.

    Returns:
    - WRITTEN for a new observation_key.
    - DUPLICATE for the same key and same analytical fingerprint.
    - CONFLICT for the same key and different analytical fingerprint.

    CONFLICT does not append a second row.
    """
    observation = _require_mapping(observation, "observation")

    if observation.get("recordtype") != RECORDTYPE:
        raise ValueError("unexpected_observation_recordtype")

    if observation.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unexpected_observation_schema_version")

    _require_true(
        observation.get("manual_review_only"),
        "observation_manual_review_only",
    )
    _require_false(
        observation.get("trade_authority"),
        "observation_trade_authority",
    )
    _require_false(
        observation.get("entry_authority"),
        "observation_entry_authority",
    )

    observation_key = _require_nonempty_string(
        observation.get("observation_key"),
        "observation_key",
    )
    observation_id = _require_nonempty_string(
        observation.get("observation_id"),
        "observation_id",
    )
    content_fingerprint = _require_nonempty_string(
        observation.get("content_fingerprint"),
        "content_fingerprint",
    )

    ledger_path = Path(path)
    existing_by_key = existing_observations_by_key(ledger_path)
    existing = existing_by_key.get(observation_key)

    if existing is not None:
        existing_fingerprint = _require_nonempty_string(
            existing.get("content_fingerprint"),
            "ledger_content_fingerprint",
        )

        base_result = {
            "observation_key": observation_key,
            "observation_id": observation_id,
            "path": str(ledger_path),
        }

        if existing_fingerprint == content_fingerprint:
            return {
                "status": STATUS_DUPLICATE,
                "existing_observation_id": existing.get("observation_id"),
                **base_result,
            }

        return {
            "status": STATUS_CONFLICT,
            "existing_observation_id": existing.get("observation_id"),
            "existing_content_fingerprint": existing_fingerprint,
            "incoming_content_fingerprint": content_fingerprint,
            **base_result,
        }

    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    serialized = _canonical_json(dict(observation)) + "\n"

    with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(serialized)
        handle.flush()

    return {
        "status": STATUS_WRITTEN,
        "observation_key": observation_key,
        "observation_id": observation_id,
        "path": str(ledger_path),
    }


def record_observation(
    path: str | Path,
    evaluation: Mapping[str, Any],
    sizing: Mapping[str, Any] | None = None,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    """
    Build and append one v2 observation.

    The returned dict includes the canonical observation object whether the
    append result is WRITTEN, DUPLICATE, or CONFLICT.
    """
    observation = build_observation(
        evaluation=evaluation,
        sizing=sizing,
        observed_at_utc=observed_at_utc,
    )

    result = append_observation(
        path=path,
        observation=observation,
    )

    result["observation"] = observation

    return result
