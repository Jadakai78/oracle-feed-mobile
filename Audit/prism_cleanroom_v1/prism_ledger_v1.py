"""
prism_ledger_v1.py — PRISM clean-room append-only ledger.

Read-only state loads; append-only, idempotent, atomic-write observation and
outcome ledgers. No network access, no background loop. Never writes to a
default/production path — every path is explicitly passed by the caller.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "prism_width_regime_ledger_v1"


def _empty_state() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_ids": [],
        "outcome_ids": [],
    }


def load_state(state_path: Path) -> dict:
    """Read-only. Never creates a file. Missing/invalid state normalizes
    safely to the empty state."""
    state_path = Path(state_path)
    if not state_path.exists():
        return _empty_state()
    try:
        raw = state_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return _empty_state()

    if not isinstance(data, dict):
        return _empty_state()

    observation_ids = data.get("observation_ids")
    outcome_ids = data.get("outcome_ids")
    if not isinstance(observation_ids, list) or not isinstance(outcome_ids, list):
        return _empty_state()
    if not all(isinstance(item, str) for item in observation_ids):
        return _empty_state()
    if not all(isinstance(item, str) for item in outcome_ids):
        return _empty_state()

    return {
        "schema_version": SCHEMA_VERSION,
        "observation_ids": list(observation_ids),
        "outcome_ids": list(outcome_ids),
    }


def _atomic_write_state(state: dict, state_path: Path) -> None:
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".tmp_state_", suffix=".json", dir=str(state_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
        os.replace(tmp_name, state_path)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def _append_line(path: Path, record: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True))
        handle.write("\n")


def _id_exists_in_jsonl(path: Path, observation_id: str) -> bool:
    """Read-only scan of an existing JSONL ledger file for a given
    observation_id. Used for recovery-safe idempotency: if a prior append
    wrote the JSONL row but a subsequent atomic state replace failed (or the
    process crashed between the two steps), a retry must still detect the
    row already present in the JSONL file itself, not only in state."""
    path = Path(path)
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and record.get("observation_id") == observation_id:
                    return True
    except OSError:
        return False
    return False


def append_observation(
    record: dict,
    observations_path: Path,
    state_path: Path,
    dry_run: bool = False,
) -> dict:
    if (
        not isinstance(record, dict)
        or record.get("recordtype") != "PRISM_WIDTH_REGIME_OBSERVATION"
        or record.get("status") != "OPEN"
        or not isinstance(record.get("observation_id"), str)
        or not record.get("observation_id")
    ):
        return {"status": "INVALID_RECORD"}

    state = load_state(state_path)
    observation_id = record["observation_id"]

    if observation_id in state["observation_ids"] or _id_exists_in_jsonl(observations_path, observation_id):
        return {"status": "DUPLICATE"}

    if dry_run:
        return {"status": "DRY_RUN"}

    _append_line(observations_path, record)
    state["observation_ids"].append(observation_id)
    _atomic_write_state(state, state_path)
    return {"status": "APPENDED", "observation_id": observation_id}


def append_closed_outcome(
    record: dict,
    outcomes_path: Path,
    state_path: Path,
    dry_run: bool = False,
) -> dict:
    if (
        not isinstance(record, dict)
        or record.get("recordtype") != "PRISM_WIDTH_REGIME_OUTCOME"
        or record.get("status") != "CLOSED"
        or not isinstance(record.get("observation_id"), str)
        or not record.get("observation_id")
    ):
        return {"status": "INVALID_RECORD"}

    state = load_state(state_path)
    observation_id = record["observation_id"]

    if observation_id not in state["observation_ids"]:
        return {"status": "UNKNOWN_OBSERVATION"}

    if observation_id in state["outcome_ids"] or _id_exists_in_jsonl(outcomes_path, observation_id):
        return {"status": "DUPLICATE"}

    if dry_run:
        return {"status": "DRY_RUN"}

    _append_line(outcomes_path, record)
    state["outcome_ids"].append(observation_id)
    _atomic_write_state(state, state_path)
    return {"status": "APPENDED", "observation_id": observation_id}
