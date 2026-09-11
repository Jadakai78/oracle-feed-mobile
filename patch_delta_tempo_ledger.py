from __future__ import annotations

import py_compile
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "scanner.py"

if not TARGET.exists():
    raise SystemExit(f"scanner.py not found beside this patch script: {TARGET}")

source = TARGET.read_text(encoding="utf-8")

if "def _append_delta_ledger(" in source:
    raise SystemExit("scanner.py already contains _append_delta_ledger(). Nothing changed.")

ledger_function = r'''

def _append_delta_ledger(
    pair: str,
    delta: Dict[str, Any],
    ts: str,
    volume_flow: Dict[str, Any],
    structure: Dict[str, Any],
    market_noise: Dict[str, Any],
    market_timing: Dict[str, Any],
    market_state: Dict[str, Any],
) -> None:
    """Write one canonical Delta 2.0 observation per completed pressure bar."""
    bar_start = volume_flow.get("bar_start")
    if bar_start is None:
        return

    event_key = f"{pair}|delta_tempo|{FLOW_INTERVAL_MINUTES}m|{bar_start}"
    ledger_path = LOG_DIR / "delta_tempo.jsonl"
    seen_path = LOG_DIR / "delta_tempo_seen.json"

    try:
        seen = set(json.loads(seen_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        seen = set()

    if event_key in seen:
        return

    shield = delta.get("shield") or []
    if isinstance(shield, str):
        shield = [shield]

    record = {
        "schema_version": 1,
        "event_key": event_key,
        "ts": ts,
        "pair": pair,
        "timeframe": f"{FLOW_INTERVAL_MINUTES}m",
        "bar_start": bar_start,
        "bar_end": volume_flow.get("bar_end"),
        "event": delta.get("event", "NO_DELTA"),
        "side": delta.get("side", "NONE"),
        "speed_score": delta.get("speed_score"),
        "speed_change_ratio": delta.get("speed_change_ratio"),
        "market_condition": (
            delta.get("market_condition")
            or structure.get("market_condition")
            or market_state.get("market_condition")
        ),
        "trend": delta.get("trend") or structure.get("trend", "unknown"),
        "zone": delta.get("zone") or structure.get("zone", "neutral"),
        "radar_state": delta.get("radar_state", "NO_TARGET"),
        "executioner_state": delta.get("executioner_state", "NO_TRADE"),
        "bos": bool(delta.get("bos", False)),
        "geometry_status": delta.get("geometry_status", "PENDING"),
        "geometry_reason": delta.get("geometry_reason"),
        "entry": delta.get("entry"),
        "sl": delta.get("sl"),
        "tp": delta.get("tp"),
        "room_to_risk": delta.get("room_to_risk"),
        "shield": shield,
        "timing_state": market_timing.get("timing_state", "OBSERVE"),
        "noise_regime": market_noise.get("regime", "unavailable"),
        "noise_score": market_noise.get("noise_score"),
        "flow_ready": bool(volume_flow.get("ready", False)),
        "flow_reason": volume_flow.get("reason"),
        "structure": structure,
        "market_state": market_state,
        "outcome": {
            "status": "pending",
            "label": None,
            "resolved_at": None,
            "first_touch": None,
            "bars_to_resolution": None,
        },
    }

    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    seen.add(event_key)
    seen_path.write_text(
        json.dumps(sorted(seen), ensure_ascii=False),
        encoding="utf-8",
    )
'''

function_anchor = "\ndef _apply_knn("
if function_anchor not in source:
    raise SystemExit("Could not find insertion point before _apply_knn(). Nothing changed.")
source = source.replace(function_anchor, ledger_function + "\n\ndef _apply_knn(", 1)

call_anchor = "\n        # 7. Log one observation per bot per completed pressure candle."
ledger_call = r'''

        _append_delta_ledger(
            pair=pair,
            delta=delta_tempo,
            ts=ts,
            volume_flow=volume_flow,
            structure=structure,
            market_noise=shared_market_noise,
            market_timing=shared_market_timing,
            market_state=market_state,
        )
'''
if call_anchor not in source:
    raise SystemExit("Could not find the Delta ledger call insertion point. Nothing changed.")
source = source.replace(call_anchor, ledger_call + call_anchor, 1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"scanner.pre_delta_ledger_{stamp}.py")
shutil.copy2(TARGET, backup)
TARGET.write_text(source, encoding="utf-8")

try:
    py_compile.compile(str(TARGET), doraise=True)
except Exception:
    shutil.copy2(backup, TARGET)
    raise

print(f"Patched: {TARGET.name}")
print(f"Backup:  {backup.name}")
print("Syntax check: PASS")
print("Next: run scanner.py, then inspect training_logs\\delta_tempo.jsonl")
