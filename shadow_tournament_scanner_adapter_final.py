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


def iso_epoch(value: Any) -> Optional[str]:
    try:
        value = float(value)
        if value > 10_000_000_000: value /= 1000
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError): return None


def as_float(value: Any) -> Optional[float]:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError): return None


def find_value(source: Any, names: set[str]) -> Any:
    if not isinstance(source, dict): return None
    for key, value in source.items():
        if str(key).lower() in names and value is not None: return value
    for value in source.values():
        if isinstance(value, dict):
            found = find_value(value, names)
            if found is not None: return found
    return None


def reject(root: Path, reason: str, **fields: Any) -> None:
    path = root / "training_logs" / "shadow_tournament" / "adapter_rejections.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"record_type": "ADAPTER_REJECTED", "rejection_reason": reason, **fields, "written_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"); f.flush()


def build_packet(row: Dict[str, Any], scan_ts: str) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    structure, flow = row.get("structure") or {}, row.get("volumeflow") or {}
    drive, state = row.get("gimbadrive") or {}, row.get("marketstate") or {}
    pair = str(row.get("pair") or "").replace("/", "")
    bar_ts = iso_epoch(flow.get("barend")) or iso_epoch(flow.get("bar_end")) or scan_ts
    quote = as_float(find_value({"drive": drive, "structure": structure, "state": state, "flow": flow}, {"close", "last_price", "price", "reference_price", "entry"}))
    if not pair: return None, "missing_pair"
    if quote is None or quote <= 0: return None, "missing_canonical_quote"
    condition = str(find_value(structure, {"market_condition", "marketcondition"}) or find_value(state, {"market_condition", "marketcondition"}) or "UNKNOWN").upper()
    tempo = str(find_value(structure, {"market_tempo", "markettempo"}) or find_value(state, {"market_tempo", "markettempo"}) or "UNKNOWN").upper()
    trend = str(find_value(structure, {"trend", "d1_trend", "d1trend"}) or "UNKNOWN").upper()
    return {"bar_end_ts": bar_ts, "pair": pair, "quote": quote, "quote_source": "scanner_completed_bar_or_signal_reference", "quote_timestamp": bar_ts, "quote_age_seconds": 0.0, "data_fresh": True, "d1_trend": str(find_value(structure, {"d1_trend", "d1trend", "trend"}) or "UNKNOWN").upper(), "h4_trend": str(find_value(structure, {"h4_trend", "h4trend"}) or "UNKNOWN").upper(), "market_condition": condition, "market_tempo": tempo, "territory": "LONG_ONLY" if trend == "UP" else "SHORT_ONLY" if trend == "DOWN" else "NO_TRADE", "zone": str(find_value(structure, {"zone"}) or "UNKNOWN").upper(), "oracle_state_version": "scanner_adapter_v1", "previous_state": None, "new_state": None, "transition_ts": None, "transition_reason": None}, None


def drive_decision(packet_key: str, row: Dict[str, Any], scan_ts: str, lane: str) -> Optional[Dict[str, Any]]:
    drive = row.get("gimbadrive") or {}
    action = str(drive.get("actionstate") or drive.get("action_state") or "").upper()
    side = str(drive.get("bias") or drive.get("side") or "").upper()
    entry, sl, tp = as_float(drive.get("entry")), as_float(drive.get("sl")), as_float(drive.get("tp"))
    if action != "WATCH" or side not in {"LONG", "SHORT"} or any(x is None for x in (entry, sl, tp)): return None
    return {"lane": lane, "oracle_event_key": packet_key, "decision_ts": scan_ts, "pair": row.get("pair"), "decision": "TAKE", "side": side, "entry": entry, "entry_reference": "published_drive_entry", "sl": sl, "tp": tp, "horizon_bars": HORIZON_BARS, "risk_distance": abs(entry - sl), "model_or_rule_version": "gimba_drive_frozen_v1" if lane == "ORACLE_DRIVE_FIXED_V1" else "drive_adaptive_mirror_v1", "feature_schema_version": "scanner_adapter_v1", "confidence": as_float(drive.get("conviction")), "reason": str(drive.get("why") or "gimba_drive_watch")}


def process(arena: ShadowTournamentArena, root: Path, snapshot: Dict[str, Any], seen: set[str], states: Dict[str, str]) -> int:
    scan_ts = str(snapshot.get("ts") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")); count = 0
    for row in snapshot.get("signals") or []:
        if not isinstance(row, dict): continue
        packet, why = build_packet(row, scan_ts)
        identity = f"{row.get('pair')}|{packet.get('bar_end_ts') if packet else scan_ts}"
        if identity in seen: continue
        seen.add(identity)
        if packet is None:
            reject(root, why or "packet_build_failed", pair=row.get("pair"), scan_ts=scan_ts); continue
        prior, current = states.get(packet["pair"]), packet["market_condition"]
        if prior is not None and prior != current:
            packet.update(previous_state=prior, new_state=current, transition_ts=packet["bar_end_ts"], transition_reason="canonical_market_condition_changed")
        states[packet["pair"]] = current
        packet_key = arena.write_oracle_packet(packet)
        for lane in ("ORACLE_DRIVE_FIXED_V1", "ORACLE_DRIVE_ADAPTIVE_V1"):
            decision = drive_decision(packet_key, row, scan_ts, lane)
            if decision is not None: arena.write_decision(decision)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only scanner-to-Shadow-Tournament adapter. No order functions exist.")
    parser.add_argument("--root", default=str(ROOT_DEFAULT)); parser.add_argument("--once", action="store_true"); parser.add_argument("--poll-seconds", type=int, default=15)
    args = parser.parse_args(); root = Path(args.root).expanduser().resolve(); source = root / "signals.json"; arena = ShadowTournamentArena(root)
    seen: set[str] = set(); states: Dict[str, str] = {}; last_mtime = None
    print(f"Shadow Tournament adapter ready\nSource: {source}\nOrders: disabled\nCtrl+C stops adapter only.")
    while True:
        try:
            if source.exists() and source.stat().st_mtime_ns != last_mtime:
                snapshot = json.loads(source.read_text(encoding="utf-8")); count = process(arena, root, snapshot, seen, states); last_mtime = source.stat().st_mtime_ns
                print(f"{datetime.now().isoformat(timespec='seconds')} packets={count}")
            elif not source.exists(): print(f"Waiting for {source}")
        except Exception as exc:
            reject(root, f"adapter_error:{type(exc).__name__}:{exc}"); print(f"Adapter error: {type(exc).__name__}: {exc}")
        if args.once: return
        time.sleep(max(5, args.poll_seconds))

if __name__ == "__main__": main()
