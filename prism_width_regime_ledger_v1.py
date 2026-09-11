from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "prismwidthregimeledgerv1"
OBSERVATION_RECORDTYPE = "PRISMWIDTHREGIMEOBSERVATION"
OUTCOME_RECORDTYPE = "PRISMWIDTHREGIMEOUTCOME"


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_ids": [],
        "outcome_ids": [],
    }


def _valid_id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    ids: list[str] = []
    seen: set[str] = set()

    for item in value:
        if isinstance(item, str) and item and item not in seen:
            ids.append(item)
            seen.add(item)

    return ids


def load_state(state_path: Path) -> dict[str, Any]:
    """Load operational dedupe state without creating or modifying any file."""
    if not isinstance(state_path, Path) or not state_path.exists():
        return _empty_state()

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_state()

    if not isinstance(payload, dict):
        return _empty_state()

    return {
        "schema_version": SCHEMA_VERSION,
        "observation_ids": _valid_id_list(payload.get("observation_ids")),
        "outcome_ids": _valid_id_list(payload.get("outcome_ids")),
    }


def _save_state(state_path: Path, state: dict[str, Any]) -> None:
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "observation_ids": _valid_id_list(state.get("observation_ids")),
        "outcome_ids": _valid_id_list(state.get("outcome_ids")),
    }

    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = state_path.with_suffix(state_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary_path.replace(state_path)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _observation_id(record: Any, recordtype: str) -> str | None:
    if not isinstance(record, dict):
        return None

    if record.get("recordtype") != recordtype:
        return None

    if record.get("schema_version") != "prismwidthregimev1":
        return None

    observation_id = record.get("observation_id")

    if not isinstance(observation_id, str) or not observation_id:
        return None

    return observation_id


def append_observation(
    record: dict[str, Any],
    *,
    observations_path: Path,
    state_path: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Append one immutable PRISM observation once, keyed by observation_id."""
    observation_id = _observation_id(record, OBSERVATION_RECORDTYPE)

    if observation_id is None:
        return {"status": "INVALID_RECORD", "observation_id": None}

    state = load_state(state_path)

    if observation_id in state["observation_ids"]:
        return {"status": "DUPLICATE", "observation_id": observation_id}

    if dry_run:
        return {"status": "DRY_RUN", "observation_id": observation_id}

    _append_jsonl(observations_path, record)
    state["observation_ids"].append(observation_id)
    _save_state(state_path, state)

    return {"status": "APPENDED", "observation_id": observation_id}


def append_closed_outcome(
    record: dict[str, Any],
    *,
    outcomes_path: Path,
    state_path: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Append one closed PRISM outcome once, only after its observation exists."""
    observation_id = _observation_id(record, OUTCOME_RECORDTYPE)

    if observation_id is None or record.get("status") != "CLOSED":
        return {"status": "INVALID_RECORD", "observation_id": None}

    state = load_state(state_path)

    if observation_id not in state["observation_ids"]:
        return {"status": "UNKNOWN_OBSERVATION", "observation_id": observation_id}

    if observation_id in state["outcome_ids"]:
        return {"status": "DUPLICATE", "observation_id": observation_id}

    if dry_run:
        return {"status": "DRY_RUN", "observation_id": observation_id}

    _append_jsonl(outcomes_path, record)
    state["outcome_ids"].append(observation_id)
    _save_state(state_path, state)

    return {"status": "APPENDED", "observation_id": observation_id}
