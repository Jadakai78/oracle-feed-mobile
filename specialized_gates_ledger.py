"""
specialized_gates_ledger.py — Append-only, idempotent ledger for JHL gate families.

Shadow-only. This module does not send alerts, place orders, alter routing,
or change any existing Eight Gates decision.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

LOG_DIR = Path(__file__).parent / "training_logs"
LANES_PATH = LOG_DIR / "specialized_gates_lanes.jsonl"


def lane_key(record: Dict[str, Any]) -> str:
    geometry = record.get("geometry") or {}
    payload = {
        "family": record.get("family"),
        "version": record.get("version"),
        "pair": record.get("pair"),
        "side": record.get("side"),
        "entry_zone": geometry.get("entry_zone"),
        "invalidation": geometry.get("invalidation"),
        "target_1": geometry.get("target_1"),
        "reason": record.get("reason"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _existing_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = record.get("lane_key")
        if key:
            keys.add(str(key))
    return keys


def append_lane_once(record: Dict[str, Any], path: Path = LANES_PATH) -> bool:
    """Append a lane once. Returns True only when a new lane is written."""
    if record.get("record_type") != "lane_observed":
        raise ValueError("only lane_observed records may be appended")

    path.parent.mkdir(parents=True, exist_ok=True)
    key = lane_key(record)

    if key in _existing_keys(path):
        return False

    stored = dict(record)
    stored["lane_key"] = key
    stored["shadow_mode"] = True
    stored["diagnostic_only"] = True

    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(stored, ensure_ascii=False, separators=(",", ":")) + "\n")

    return True
