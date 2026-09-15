"""
PRISM LAR Annotation Ledger v1

Append-only JSONL persistence for passive Liquidity Acceptance / Rejection
(LAR-Gate v1.1) annotations linked to a PRISM observation.

Identity rules:
- annotation_key is:
      observation_key|lar_gate_v1

- annotation_id is a deterministic hash of annotation_key only.

- content_fingerprint hashes LAR analytical content and source metadata.

- Same annotation_key + same content_fingerprint:
      DUPLICATE

- Same annotation_key + different content_fingerprint:
      CONFLICT
  The differing annotation is not silently appended.

- New annotation_key:
      WRITTEN

This module:
- Does not modify PRISM observation ledgers.
- Does not modify LAR output.
- Does not create trade, entry, sizing, alert, queue, or execution authority.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

RECORDTYPE = "PRISMLARANNOTATION"
SCHEMA_VERSION = "prism.lar.annotation.ledger.v1"

LAR_GATE_VERSION = "lar_gate_v1"

STATUS_WRITTEN = "WRITTEN"
STATUS_DUPLICATE = "DUPLICATE"
STATUS_CONFLICT = "CONFLICT"

MANUAL_REVIEW_ONLY = True
TRADE_AUTHORITY = False
ENTRY_AUTHORITY = False

LAR_REQUIRED_GATE_FIELDS = (
    "pair",
    "timeframe",
    "reference_bar_close_utc",
    "source_bar_count",
    "state",
    "pool_side",
    "pool_level",
    "pool_type",
    "touch_count",
    "sweep_extreme",
    "penetration_pct",
    "reclaim_close",
    "reclaim_confirmed",
    "acceptance_confirmed",
    "entry_permission",
    "reason",
)

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
    return hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _strip_volatile_fields(value: Any) -> Any:
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


def build_annotation_key(observation_key: str) -> str:
    observation_key = _require_nonempty_string(
        observation_key,
        "observation_key",
    )
    return f"{observation_key}|{LAR_GATE_VERSION}"


def _validate_lar_result(lar_result: Mapping[str, Any]) -> dict[str, Any]:
    lar_result = _require_mapping(lar_result, "lar_result")

    liquidity_gate = _require_mapping(
        lar_result.get("liquidity_gate"),
        "liquidity_gate",
    )

    for field in LAR_REQUIRED_GATE_FIELDS:
        if field not in liquidity_gate:
            raise ValueError(f"liquidity_gate_missing_{field}")

    pair = _require_nonempty_string(
        liquidity_gate.get("pair"),
        "liquidity_gate_pair",
    )
    timeframe = _require_nonempty_string(
        liquidity_gate.get("timeframe"),
        "liquidity_gate_timeframe",
    )
    state = _require_nonempty_string(
        liquidity_gate.get("state"),
        "liquidity_gate_state",
    )
    pool_side = _require_nonempty_string(
        liquidity_gate.get("pool_side"),
        "liquidity_gate_pool_side",
    )
    pool_type = _require_nonempty_string(
        liquidity_gate.get("pool_type"),
        "liquidity_gate_pool_type",
    )
    entry_permission = _require_nonempty_string(
        liquidity_gate.get("entry_permission"),
        "liquidity_gate_entry_permission",
    )
    reason = _require_nonempty_string(
        liquidity_gate.get("reason"),
        "liquidity_gate_reason",
    )

    if not isinstance(liquidity_gate.get("source_bar_count"), int):
        raise ValueError("liquidity_gate_source_bar_count_must_be_integer")

    if liquidity_gate["source_bar_count"] < 0:
        raise ValueError("liquidity_gate_source_bar_count_must_not_be_negative")

    if not isinstance(liquidity_gate.get("touch_count"), int):
        raise ValueError("liquidity_gate_touch_count_must_be_integer")

    if liquidity_gate["touch_count"] < 0:
        raise ValueError("liquidity_gate_touch_count_must_not_be_negative")

    if not isinstance(liquidity_gate.get("reclaim_confirmed"), bool):
        raise ValueError("liquidity_gate_reclaim_confirmed_must_be_boolean")

    if not isinstance(liquidity_gate.get("acceptance_confirmed"), bool):
        raise ValueError("liquidity_gate_acceptance_confirmed_must_be_boolean")

    pending_sweep = lar_result.get("pending_sweep")

    if pending_sweep is not None and not isinstance(pending_sweep, Mapping):
        raise ValueError("pending_sweep_must_be_object_or_null")

    return {
        "gate": dict(liquidity_gate),
        "pending_sweep": (
            dict(pending_sweep)
            if pending_sweep is not None
            else None
        ),
        "pair": pair,
        "timeframe": timeframe,
        "state": state,
        "pool_side": pool_side,
        "pool_type": pool_type,
        "entry_permission": entry_permission,
        "reason": reason,
    }


def build_lar_annotation(
    observation_key: str,
    observation_id: str,
    lar_result: Mapping[str, Any],
    source_label: str,
    source_completed_bar_timestamp_utc: str,
) -> dict[str, Any]:
    """
    Build a passive LAR annotation record.

    The annotation is descriptive only. `entry_permission` is preserved exactly
    as LAR output but has no execution, queue, sizing, or promotion authority.
    """
    observation_key = _require_nonempty_string(
        observation_key,
        "observation_key",
    )
    observation_id = _require_nonempty_string(
        observation_id,
        "observation_id",
    )
    source_label = _require_nonempty_string(
        source_label,
        "source_label",
    )
    source_completed_bar_timestamp_utc = _require_nonempty_string(
        source_completed_bar_timestamp_utc,
        "source_completed_bar_timestamp_utc",
    )

    validated_lar = _validate_lar_result(lar_result)
    annotation_key = build_annotation_key(observation_key)

    annotation_id = _content_hash(
        {
            "recordtype": RECORDTYPE,
            "schema_version": SCHEMA_VERSION,
            "annotation_key": annotation_key,
        }
    )

    analytical_payload = {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "annotation_key": annotation_key,
        "observation_key": observation_key,
        "observation_id": observation_id,
        "source": {
            "label": source_label,
            "completed_bar_timestamp_utc": (
                source_completed_bar_timestamp_utc
            ),
            "lar_gate_version": LAR_GATE_VERSION,
        },
        "lar": {
            "liquidity_gate": validated_lar["gate"],
            "pending_sweep": validated_lar["pending_sweep"],
        },
    }

    content_fingerprint = _content_hash(
        _strip_volatile_fields(analytical_payload)
    )

    return {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "annotation_key": annotation_key,
        "annotation_id": annotation_id,
        "content_fingerprint": content_fingerprint,
        "observation_key": observation_key,
        "observation_id": observation_id,
        "source": {
            "label": source_label,
            "completed_bar_timestamp_utc": (
                source_completed_bar_timestamp_utc
            ),
            "lar_gate_version": LAR_GATE_VERSION,
        },
        "lar": {
            "liquidity_gate": validated_lar["gate"],
            "pending_sweep": validated_lar["pending_sweep"],
        },
        "annotation": {
            "state": validated_lar["state"],
            "pool_side": validated_lar["pool_side"],
            "pool_type": validated_lar["pool_type"],
            "entry_permission_descriptive_only": (
                validated_lar["entry_permission"]
            ),
            "reason": validated_lar["reason"],
            "pending_sweep_present": (
                validated_lar["pending_sweep"] is not None
            ),
        },
        "written_at_utc": _now_utc(),
        "manual_review_only": MANUAL_REVIEW_ONLY,
        "trade_authority": TRADE_AUTHORITY,
        "entry_authority": ENTRY_AUTHORITY,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
        "does_not_change_runtime_sizing": True,
        "does_not_override_prism_evaluation": True,
    }


def iter_lar_annotations(path: str | Path) -> list[dict[str, Any]]:
    """
    Read LAR annotation JSONL rows.

    Missing/nonexistent ledgers return an empty list.
    Invalid JSON or non-object records fail closed.
    """
    ledger_path = Path(path)

    if not ledger_path.exists():
        return []

    annotations: list[dict[str, Any]] = []

    with ledger_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()

            if not stripped:
                continue

            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid_lar_ledger_json_line_{line_number}:{exc.msg}"
                ) from exc

            if not isinstance(record, dict):
                raise ValueError(
                    f"invalid_lar_ledger_record_line_{line_number}"
                )

            annotations.append(record)

    return annotations


def existing_annotations_by_key(
    path: str | Path,
) -> dict[str, dict[str, Any]]:
    """
    Index existing LAR annotations by annotation_key.

    Duplicate annotation keys in an existing ledger fail closed, since one
    completed PRISM observation must have at most one canonical LAR annotation.
    """
    indexed: dict[str, dict[str, Any]] = {}

    for record in iter_lar_annotations(path):
        if record.get("recordtype") != RECORDTYPE:
            raise ValueError("unexpected_lar_ledger_recordtype")

        if record.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unexpected_lar_ledger_schema_version")

        annotation_key = _require_nonempty_string(
            record.get("annotation_key"),
            "ledger_annotation_key",
        )

        if annotation_key in indexed:
            raise ValueError("duplicate_annotation_key_in_lar_ledger")

        indexed[annotation_key] = record

    return indexed


def append_lar_annotation(
    path: str | Path,
    annotation: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Append one canonical LAR annotation.

    Returns WRITTEN, DUPLICATE, or CONFLICT.

    A conflict does not append a second annotation row for the same
    observation_key and LAR-Gate version.
    """
    annotation = _require_mapping(annotation, "annotation")

    if annotation.get("recordtype") != RECORDTYPE:
        raise ValueError("unexpected_annotation_recordtype")

    if annotation.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unexpected_annotation_schema_version")

    _require_true(
        annotation.get("manual_review_only"),
        "annotation_manual_review_only",
    )
    _require_false(
        annotation.get("trade_authority"),
        "annotation_trade_authority",
    )
    _require_false(
        annotation.get("entry_authority"),
        "annotation_entry_authority",
    )

    annotation_key = _require_nonempty_string(
        annotation.get("annotation_key"),
        "annotation_key",
    )
    annotation_id = _require_nonempty_string(
        annotation.get("annotation_id"),
        "annotation_id",
    )
    content_fingerprint = _require_nonempty_string(
        annotation.get("content_fingerprint"),
        "content_fingerprint",
    )
    observation_key = _require_nonempty_string(
        annotation.get("observation_key"),
        "annotation_observation_key",
    )
    observation_id = _require_nonempty_string(
        annotation.get("observation_id"),
        "annotation_observation_id",
    )

    ledger_path = Path(path)
    existing_by_key = existing_annotations_by_key(ledger_path)
    existing = existing_by_key.get(annotation_key)

    base_result = {
        "annotation_key": annotation_key,
        "annotation_id": annotation_id,
        "observation_key": observation_key,
        "observation_id": observation_id,
        "path": str(ledger_path),
    }

    if existing is not None:
        existing_fingerprint = _require_nonempty_string(
            existing.get("content_fingerprint"),
            "ledger_lar_content_fingerprint",
        )

        if existing_fingerprint == content_fingerprint:
            return {
                "status": STATUS_DUPLICATE,
                "existing_annotation_id": existing.get("annotation_id"),
                **base_result,
            }

        return {
            "status": STATUS_CONFLICT,
            "existing_annotation_id": existing.get("annotation_id"),
            "existing_content_fingerprint": existing_fingerprint,
            "incoming_content_fingerprint": content_fingerprint,
            **base_result,
        }

    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical_json(dict(annotation)) + "\n")
        handle.flush()

    return {
        "status": STATUS_WRITTEN,
        **base_result,
    }


def record_lar_annotation(
    path: str | Path,
    observation_key: str,
    observation_id: str,
    lar_result: Mapping[str, Any],
    source_label: str,
    source_completed_bar_timestamp_utc: str,
) -> dict[str, Any]:
    """
    Build and append one LAR annotation.

    The returned object includes the canonical annotation for inspection whether
    the result is WRITTEN, DUPLICATE, or CONFLICT.
    """
    annotation = build_lar_annotation(
        observation_key=observation_key,
        observation_id=observation_id,
        lar_result=lar_result,
        source_label=source_label,
        source_completed_bar_timestamp_utc=(
            source_completed_bar_timestamp_utc
        ),
    )

    result = append_lar_annotation(
        path=path,
        annotation=annotation,
    )

    result["annotation"] = annotation

    return result
