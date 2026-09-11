from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import argparse
import json
import time

from shadow_tournament_arena import ShadowTournamentArena
from shadow_tournament_scanner_adapter_final import build_packet, drive_decision, reject

ROOT_DEFAULT = Path(r"C:\Users\OneDrive\Desktop\jhl_v2\jhl_v2gimba")


def epoch(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text: return None
    try:
        if text.endswith("Z"): text = text[:-1] + "+00:00"
        stamp = datetime.fromisoformat(text)
        if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp()
    except ValueError: return None


def process(arena: ShadowTournamentArena, root: Path, snapshot: Dict[str, Any], seen: set[str], states: Dict[str, str]) -> int:
    scan_ts = str(snapshot.get("ts") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    scan_epoch = epoch(scan_ts) or datetime.now(timezone.utc).timestamp()
    count = 0
    for row in snapshot.get("signals") or []:
        if not isinstance(row, dict): continue
        packet, why = build_packet(row, scan_ts)
        identity = f"{row.get('pair')}|{packet.get('bar_end_ts') if packet else scan_ts}"
        if identity in seen: continue
        seen.add(identity)
        if packet is None:
            reject(root, why or "packet_build_failed", pair=row.get("pair"), scan_ts=scan_ts); continue
        bar_epoch = epoch(packet["bar_end_ts"])
        age = max(0.0, scan_epoch - bar_epoch) if bar_epoch is not None else 9_999_999.0
        packet["quote_age_seconds"] = round(age, 3)
        packet["data_fresh"] = age <= 1_200
        prior, current = states.get(packet["pair"]), packet["market_condition"]
        if prior is not None and prior != current:
            packet.update(previous_state=prior, new_state=current, transition_ts=packet["bar_end_ts"], transition_reason="canonical_market_condition_changed")
        states[packet["pair"]] = current
        packet_key = arena.write_oracle_packet(packet)
        if not packet["data_fresh"]:
            reject(root, "stale_oracle_packet", pair=packet["pair"], oracle_event_key=packet_key, quote_age_seconds=packet["quote_age_seconds"])
            count += 1; continue
        for lane in ("ORACLE_DRIVE_FIXED_V1", "ORACLE_DRIVE_ADAPTIVE_V1"):
            decision = drive_decision(packet_key, row, scan_ts, lane)
            if decision is not None: arena.write_decision(decision)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only scanner-to-Shadow-Tournament adapter v3. No order functions exist.")
    parser.add_argument("--root", default=str(ROOT_DEFAULT)); parser.add_argument("--once", action="store_true"); parser.add_argument("--poll-seconds", type=int, default=15)
    args = parser.parse_args(); root = Path(args.root).expanduser().resolve(); source = root / "signals.json"; arena = ShadowTournamentArena(root)
    seen: set[str] = set(); states: Dict[str, str] = {}; last_mtime = None
    print(f"Shadow Tournament adapter v3 ready\nSource: {source}\nOrders: disabled\nCtrl+C stops adapter only.")
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
