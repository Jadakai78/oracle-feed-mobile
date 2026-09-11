"""
episode_momentum_telemetry_v1.py

Read-only episode momentum telemetry.

Reads:
- training_logs/episode_context_events.jsonl

Writes:
- training_logs/episode_momentum_events.jsonl
- training_logs/episode_momentum_state.json

No queue mutation.
No Pushover.
No order placement.
No BTCC endpoint.
No thresholds, gates, ranking changes, or trade decisions.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"

SOURCE_PATH = LOG_DIR / "episode_context_events.jsonl"
STATE_PATH = LOG_DIR / "episode_momentum_state.json"
OUTPUT_PATH = LOG_DIR / "episode_momentum_events.jsonl"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str) + "\n")


def finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def initial_state() -> Dict[str, Any]:
    return {
        "schema_version": "momentum_telemetry_v1",
        "source_offset": 0,
        "episodes": {},
        "created_at_utc": utc_now_iso(),
        "last_run_at_utc": None,
    }


def load_state() -> Dict[str, Any]:
    state = read_json(STATE_PATH, initial_state())
    if not isinstance(state, dict):
        return initial_state()
    state.setdefault("schema_version", "momentum_telemetry_v1")
    state.setdefault("source_offset", 0)
    state.setdefault("episodes", {})
    state.setdefault("created_at_utc", utc_now_iso())
    return state


def lifecycle_for(
    episode_direction: str,
    current_move: float | None,
    prior_move: float | None,
) -> tuple[str, bool | None, float | None, float | None]:
    if current_move is None:
        return "UNAVAILABLE", None, None, None

    direction = str(episode_direction or "").upper()
    aligned = (
        current_move > 0 if direction == "UP"
        else current_move < 0 if direction == "DOWN"
        else None
    )

    if prior_move is None:
        return "INITIALIZED", aligned, None, None

    change_points = current_move - prior_move

    prior_abs = abs(prior_move)
    current_abs = abs(current_move)
    ratio = (current_abs / prior_abs) if prior_abs > 0 else None

    if aligned is False:
        return "REVERSING", aligned, change_points, ratio

    epsilon = 0.000001
    if current_abs > prior_abs + epsilon:
        return "INCREASING", aligned, change_points, ratio
    if current_abs < prior_abs - epsilon:
        return "DECAYING", aligned, change_points, ratio

    return "FLAT", aligned, change_points, ratio


def process_event(
    state: Dict[str, Any],
    row: Dict[str, Any],
) -> Dict[str, Any] | None:
    event_type = str(row.get("event_type") or "").upper()
    episode = row.get("episode")

    if event_type not in {"EPISODE_OPEN", "EPISODE_UPDATE", "EPISODE_CLOSE"}:
        return None
    if not isinstance(episode, dict):
        return None

    episode_id = str(episode.get("episode_id") or "").strip()
    if not episode_id:
        return None

    current_move = finite_float(episode.get("current_move_pct"))
    episode_direction = str(episode.get("direction") or "").upper()

    episodes = state["episodes"]
    prior = episodes.get(episode_id) if isinstance(episodes, dict) else None
    prior_move = finite_float(prior.get("current_5m_move_pct")) if isinstance(prior, dict) else None

    lifecycle, aligned, change_points, ratio = lifecycle_for(
        episode_direction,
        current_move,
        prior_move,
    )

    record = {
        "record_type": "EPISODE_MOMENTUM_TELEMETRY",
        "schema_version": "momentum_telemetry_v1",
        "written_at_utc": utc_now_iso(),
        "source_event_type": event_type,
        "source_timestamp_utc": row.get("timestamp_utc"),
        "episode_id": episode_id,
        "btcc_symbol": episode.get("btcc_symbol"),
        "kraken_symbol": episode.get("kraken_symbol"),
        "episode_direction": episode_direction,
        "episode_stage": episode.get("stage"),
        "episode_status": episode.get("status"),
        "current_5m_move_pct": current_move,
        "prior_5m_move_pct": prior_move,
        "move_change_pct_points": (
            round(change_points, 6) if change_points is not None else None
        ),
        "move_change_ratio": round(ratio, 6) if ratio is not None else None,
        "abs_acceleration_pct_points": (
            round(abs(change_points), 6) if change_points is not None else None
        ),
        "momentum_lifecycle": lifecycle,
        "directional_momentum_aligned": aligned,
        "observation_only": True,
        "does_not_change_queue": True,
        "does_not_authorize_trade": True,
    }

    episodes[episode_id] = {
        "current_5m_move_pct": current_move,
        "last_seen_utc": row.get("timestamp_utc"),
        "last_lifecycle": lifecycle,
    }

    return record


def main() -> int:
    if not SOURCE_PATH.exists():
        print(f"FAIL: Missing episode source log: {SOURCE_PATH}")
        return 1

    state = load_state()
    offset = int(state.get("source_offset", 0))
    source_size = SOURCE_PATH.stat().st_size

    if offset > source_size:
        offset = 0

    with SOURCE_PATH.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        lines = handle.readlines()
        new_offset = handle.tell()

    processed = 0
    emitted = 0

    for line in lines:
        text = line.strip()
        if not text:
            continue

        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue

        if not isinstance(row, dict):
            continue

        processed += 1
        record = process_event(state, row)

        if record is not None:
            append_jsonl(OUTPUT_PATH, record)
            emitted += 1

    state["source_offset"] = new_offset
    state["last_run_at_utc"] = utc_now_iso()
    write_json_atomic(STATE_PATH, state)

    print(f"Source: {SOURCE_PATH}")
    print(f"Source records read: {processed}")
    print(f"Momentum telemetry records written: {emitted}")
    print(f"State: {STATE_PATH}")
    print(f"Audit: {OUTPUT_PATH}")
    print("RESULT: PASS — momentum telemetry observation complete; no queue changes, alerts, or orders were sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
