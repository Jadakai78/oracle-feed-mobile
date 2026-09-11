from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import argparse
import json
import math
import time

from shadow_tournament_arena import ShadowTournamentArena

ROOT_DEFAULT = Path(r"C:\Users\OneDrive\Desktop\jhl_v2\jhl_v2gimba")
HORIZON_BARS = 12


def as_float(value: Any) -> Optional[float]:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError): return None


def parse_epoch(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    try:
        if text.endswith("Z"): text = text[:-1] + "+00:00"
        stamp = datetime.fromisoformat(text)
        if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp()
    except ValueError: return None


def reject(root: Path, reason: str, **data: Any) -> None:
    path = root / "training_logs" / "shadow_tournament" / "adapter_rejections.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"record_type": "DRIVE_LOG_ADAPTER_REJECTED", "rejection_reason": reason, **data, "written_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"); f.flush()


def process_record(arena: ShadowTournamentArena, root: Path, row: Dict[str, Any]) -> bool:
    pair = str(row.get("pair") or "").replace("/", "")
    action = str(row.get("action") or row.get("action_state") or "").upper()
    side = str(row.get("bias") or row.get("side") or "").upper()
    entry, sl, tp = as_float(row.get("entry")), as_float(row.get("sl")), as_float(row.get("tp"))
    ts = str(row.get("ts") or "")
    if not pair or not ts:
        reject(root, "missing_pair_or_timestamp", event_key=row.get("event_key") or row.get("eventkey")); return False
    if action != "WATCH" or side not in {"LONG", "SHORT"} or any(x is None for x in (entry, sl, tp)):
        return False
    stamp = parse_epoch(ts)
    age = max(0.0, datetime.now(timezone.utc).timestamp() - stamp) if stamp is not None else 9_999_999.0
    structure = row.get("structure") or {}
    trend = str(structure.get("d1_trend") or structure.get("d1trend") or structure.get("trend") or "UNKNOWN").upper()
    packet = {
        "oracle_event_key": f"drive_{row.get('event_key') or row.get('eventkey') or pair + ts}",
        "bar_end_ts": ts,
        "pair": pair,
        "quote": entry,
        "quote_source": "published_drive_entry",
        "quote_timestamp": ts,
        "quote_age_seconds": round(age, 3),
        "data_fresh": age <= 1_200,
        "d1_trend": trend,
        "h4_trend": str(structure.get("h4_trend") or structure.get("h4trend") or "UNKNOWN").upper(),
        "market_condition": str(structure.get("market_condition") or structure.get("marketcondition") or "UNKNOWN").upper(),
        "market_tempo": str(structure.get("market_tempo") or structure.get("markettempo") or "UNKNOWN").upper(),
        "territory": "LONG_ONLY" if trend == "UP" else "SHORT_ONLY" if trend == "DOWN" else "NO_TRADE",
        "zone": str(structure.get("zone") or "UNKNOWN").upper(),
        "oracle_state_version": "drive_log_adapter_v1",
    }
    packet_key = arena.write_oracle_packet(packet)
    if not packet["data_fresh"]:
        reject(root, "stale_drive_event", pair=pair, oracle_event_key=packet_key, quote_age_seconds=packet["quote_age_seconds"]); return False
    for lane in ("ORACLE_DRIVE_FIXED_V1", "ORACLE_DRIVE_ADAPTIVE_V1"):
        arena.write_decision({
            "lane": lane, "oracle_event_key": packet_key, "decision_ts": ts, "pair": pair, "decision": "TAKE", "side": side,
            "entry": entry, "entry_reference": "published_drive_entry", "sl": sl, "tp": tp, "horizon_bars": HORIZON_BARS,
            "risk_distance": abs(entry - sl), "model_or_rule_version": "gimba_drive_frozen_v1" if lane.endswith("FIXED_V1") else "drive_adaptive_mirror_v1",
            "feature_schema_version": "drive_log_adapter_v1", "confidence": as_float(row.get("conviction")), "reason": str(row.get("why") or "gimba_drive_watch"),
        })
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only append-log Drive adapter. It cannot place orders.")
    parser.add_argument("--root", default=str(ROOT_DEFAULT)); parser.add_argument("--from-start", action="store_true"); parser.add_argument("--poll-seconds", type=int, default=10)
    args = parser.parse_args(); root = Path(args.root).expanduser().resolve(); source = root / "training_logs" / "gimba_drive.jsonl"; state_path = root / "training_logs" / "shadow_tournament" / ".drive_adapter_offset.json"
    arena = ShadowTournamentArena(root); offset = 0
    if state_path.exists() and not args.from_start:
        try: offset = int(json.loads(state_path.read_text(encoding="utf-8")).get("offset", 0))
        except Exception: offset = 0
    print(f"Drive log adapter: read-only\nSource: {source}\nOrders: disabled\nCtrl+C stops adapter only.")
    while True:
        try:
            if source.exists():
                size = source.stat().st_size
                if offset == 0 and not args.from_start: offset = size
                if size < offset: offset = 0
                if size > offset:
                    with source.open("r", encoding="utf-8") as f:
                        f.seek(offset); lines = f.readlines(); offset = f.tell()
                    accepted = 0
                    for line in lines:
                        try:
                            if process_record(arena, root, json.loads(line)): accepted += 1
                        except json.JSONDecodeError: reject(root, "malformed_drive_log_line")
                        except Exception as exc: reject(root, f"drive_record_error:{type(exc).__name__}:{exc}")
                    state_path.write_text(json.dumps({"offset": offset}), encoding="utf-8")
                    print(f"{datetime.now().isoformat(timespec='seconds')} new_records={len(lines)} accepted_drive_takes={accepted}")
            else: print(f"Waiting for {source}")
        except Exception as exc: print(f"Adapter error: {type(exc).__name__}: {exc}")
        time.sleep(max(5, args.poll_seconds))

if __name__ == "__main__": main()


