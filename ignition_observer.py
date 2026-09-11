"""Read-only ignition observer for the JHL Relative-Velocity Ignition Arena."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"
ARENA_DIR = LOG_DIR / "ignition_arena"
QUEUE_AUDIT = LOG_DIR / "kraken_btcc_top3_queue_audit.jsonl"
QUEUE_STATE = LOG_DIR / "kraken_btcc_top3_queue_state.json"
MAP_LATEST = LOG_DIR / "kraken_btcc_top3_map_latest.json"
COVERAGE = LOG_DIR / "btcc_kraken_coverage_audit.json"
FIELD_LOG = ARENA_DIR / "field_observations.jsonl"
IGNITION_LOG = ARENA_DIR / "ignition_events.jsonl"
REJECTION_LOG = ARENA_DIR / "rejections.jsonl"
OFFSET_STATE = ARENA_DIR / ".observer_offset.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def append(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:20]}"


def coverage_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("kraken_symbol") or "").upper(): row for row in payload.get("included", []) if row.get("kraken_symbol")}


def map_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("kraken_symbol") or "").upper(): row for row in payload.get("candidates", []) if row.get("kraken_symbol")}


def map_context(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"status": "UNAVAILABLE"}
    h4, h1 = row.get("map_4h") or {}, row.get("map_1h") or {}
    return {
        "status": row.get("status"),
        "alignment": row.get("alignment"),
        "map_4h": {"zone": h4.get("location_zone"), "z_score": h4.get("z_score"), "close": h4.get("current_close")},
        "map_1h": {"zone": h1.get("location_zone"), "z_score": h1.get("z_score"), "close": h1.get("current_close")},
    }


def known_ids() -> set[str]:
    ids = set()
    try:
        for line in IGNITION_LOG.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if row.get("ignition_id"):
                    ids.add(str(row["ignition_id"]))
            except json.JSONDecodeError:
                pass
    except OSError:
        pass
    return ids


def read_new_lines() -> list[str]:
    state = read_json(OFFSET_STATE, {})
    offset = int(state.get("offset", 0) or 0)
    if not QUEUE_AUDIT.exists():
        return []
    size = QUEUE_AUDIT.stat().st_size
    if size < offset:
        offset = 0
    with QUEUE_AUDIT.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        lines = handle.readlines()
        new_offset = handle.tell()
    ARENA_DIR.mkdir(parents=True, exist_ok=True)
    OFFSET_STATE.write_text(json.dumps({"offset": new_offset, "updated_at_utc": now_iso()}), encoding="utf-8")
    return lines


def observe() -> tuple[int, int, int]:
    state = read_json(QUEUE_STATE, {})
    coverage = coverage_index(read_json(COVERAGE, {}))
    maps = map_index(read_json(MAP_LATEST, {}))
    queue = state.get("queue") if isinstance(state.get("queue"), list) else []
    history = state.get("price_history") if isinstance(state.get("price_history"), dict) else {}
    field = {
        "record_type": "FIELD_OBSERVATION",
        "observed_at_utc": now_iso(),
        "source_queue_last_run_at_utc": state.get("last_run_at_utc"),
        "mapped_assets": len(coverage),
        "price_history_symbols": len(history),
        "active_queue_count": len(queue),
        "active_queue_symbols": [str(row.get("kraken_symbol") or "").upper() for row in queue],
        "map_status": read_json(MAP_LATEST, {}).get("status", "UNAVAILABLE"),
        "market_tempo": "UNAVAILABLE_PENDING_RELATIVE_VELOCITY_LOGGING",
        "orders_enabled": False,
        "source_files": [str(QUEUE_AUDIT), str(QUEUE_STATE), str(MAP_LATEST), str(COVERAGE)],
    }
    field["field_observation_id"] = stable_id("field", {k: field[k] for k in ("source_queue_last_run_at_utc", "mapped_assets", "active_queue_count", "active_queue_symbols")})
    append(FIELD_LOG, field)

    existing = known_ids()
    processed = created = rejected = 0
    for line in read_new_lines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            append(REJECTION_LOG, {"record_type": "IGNITION_REJECTED", "reason": "MALFORMED_QUEUE_AUDIT_LINE", "observed_at_utc": now_iso()})
            rejected += 1
            continue
        if event.get("event_type") not in {"ADMISSION", "REPLACEMENT"}:
            continue
        processed += 1
        candidate = event.get("candidate") or {}
        symbol = str(candidate.get("kraken_symbol") or "").upper()
        event_time = str(event.get("timestamp_utc") or candidate.get("admitted_at_utc") or "")
        if not symbol or not event_time:
            append(REJECTION_LOG, {"record_type": "IGNITION_REJECTED", "reason": "MISSING_SYMBOL_OR_TIMESTAMP", "source_event": event, "observed_at_utc": now_iso()})
            rejected += 1
            continue
        ignition_id = stable_id("ignition", {"source_event_type": event.get("event_type"), "timestamp": event_time, "kraken_symbol": symbol, "btcc_symbol": candidate.get("btcc_symbol"), "admission_price": candidate.get("last_price")})
        if ignition_id in existing:
            continue
        cover = coverage.get(symbol, {})
        record = {
            "record_type": "IGNITION_EVENT",
            "ignition_id": ignition_id,
            "state": "SPIKE_MONITOR",
            "source_event_type": event.get("event_type"),
            "source_event_timestamp_utc": event.get("timestamp_utc"),
            "source_reason": event.get("reason"),
            "observed_at_utc": now_iso(),
            "kraken_symbol": symbol,
            "btcc_symbol": candidate.get("btcc_symbol") or cover.get("btcc_symbol"),
            "data_venue": candidate.get("data_venue") or "KRAKEN_FUTURES",
            "execution_venue": candidate.get("execution_venue") or "BTCC",
            "direction": candidate.get("direction"),
            "admission_price": candidate.get("last_price"),
            "mark_price": candidate.get("mark_price"),
            "best_bid": candidate.get("best_bid"),
            "best_ask": candidate.get("best_ask"),
            "score_pct": candidate.get("score_pct"),
            "admission_score_abs_pct": candidate.get("admission_score_abs_pct"),
            "ignition_origin_price": candidate.get("last_price"),
            "initial_extreme_price": candidate.get("favorable_extreme_price") or candidate.get("last_price"),
            "market_tempo": "UNAVAILABLE_PENDING_RELATIVE_VELOCITY_LOGGING",
            "relative_velocity": "UNAVAILABLE_PENDING_RELATIVE_VELOCITY_LOGGING",
            "map_context": map_context(maps.get(symbol)),
            "btcc_manual_preflight": cover.get("manual_btcc_checks_required", ["contract_active", "live_price", "funding", "spread_depth", "liquidation_safety"]),
            "quote_mismatch": candidate.get("quote_mismatch") or cover.get("quote_mismatch") or "KRAKEN_USD__BTCC_USDT",
            "orders_enabled": False,
        }
        append(IGNITION_LOG, record)
        existing.add(ignition_id)
        created += 1
    return processed, created, rejected


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only JHL ignition observer. No alerts or orders.")
    parser.add_argument("--once", action="store_true", help="Run one observation cycle (default).")
    args = parser.parse_args()
    del args
    processed, created, rejected = observe()
    print(f"Queue admission/replacement events read: {processed}")
    print(f"Ignition events created: {created}")
    print(f"Rejections: {rejected}")
    print(f"Field log: {FIELD_LOG}")
    print(f"Ignition log: {IGNITION_LOG}")
    print("RESULT: PASS — observer appended records only; queue, alerts, and orders unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
