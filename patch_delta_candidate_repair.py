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

if "def _delta_candidate_repair(" in source:
    raise SystemExit("Candidate repair already appears to be installed. Nothing changed.")

helper = r'''

def _delta_candidate_repair(delta: Dict[str, Any], structure: Dict[str, Any]) -> tuple[str, str]:
    """Return a machine key and concise next-step text for an observation-only Delta card."""
    shield_raw = delta.get("shield") or []
    shield = {str(item) for item in ([shield_raw] if isinstance(shield_raw, str) else shield_raw)}
    event = str(delta.get("event") or "NO_DELTA")
    side = "LONG" if event.startswith("DELTA_LONG") else "SHORT" if event.startswith("DELTA_SHORT") else "NONE"
    trend = str(delta.get("trend") or structure.get("trend") or "unknown")
    zone = str(delta.get("zone") or structure.get("zone") or "neutral")
    geometry = str(delta.get("geometry_status") or "PENDING")
    room = delta.get("room_to_risk")
    bos = bool(delta.get("bos", False))

    needs_location = (
        "range_long_into_premium" in shield
        or "range_short_into_discount" in shield
        or "range_midpoint_no_room" in shield
    )
    if needs_location:
        if side == "LONG":
            return "await_discount_edge", "Wait for a verified discount-edge reclaim"
        if side == "SHORT":
            return "await_premium_edge", "Wait for a verified premium-edge rejection"
        return "await_range_edge", "Wait for a verified range-edge test"

    insufficient_room = "room_to_risk_below_1.50" in shield or geometry == "GEOMETRY_REJECTED"
    if insufficient_room or (isinstance(room, (int, float)) and room < 1.50):
        return "rebuild_geometry", "Wait for a new local map with at least 1.50R"

    if "pressure_not_aligned" in shield and "cvd_not_aligned" in shield:
        return "await_pressure_and_cvd", "Wait for completed-bar pressure and CVD alignment"
    if "pressure_not_aligned" in shield:
        return "await_pressure_alignment", "Wait for completed-bar pressure alignment"
    if "cvd_not_aligned" in shield:
        return "await_cvd_alignment", "Wait for completed-bar CVD alignment"

    if not bos and str(delta.get("radar_state") or "") in {"TARGET_RECLAIM", "TARGET_REVERSAL"}:
        if trend == "up" and side == "LONG":
            return "await_reclaim_bos", "Wait for reclaim/BOS confirmation"
        if trend == "down" and side == "SHORT":
            return "await_reclaim_bos", "Wait for reclaim/BOS confirmation"
        return "await_reclaim_confirmation", "Wait for local reclaim or BOS confirmation"

    if event == "NO_DELTA":
        return "no_action", "No Delta pressure event; continue observing"

    return "observe", "Continue observing for confirmation or invalidation"
'''

anchor = "\ndef _append_delta_ledger("
if anchor not in source:
    raise SystemExit("Could not find the Delta ledger function. Nothing changed.")
source = source.replace(anchor, helper + "\n\ndef _append_delta_ledger(", 1)

ledger_anchor = '''    record = {
        "schema_version": 1,
'''
ledger_insert = '''    next_condition, repair_text = _delta_candidate_repair(delta, structure)

    record = {
        "schema_version": 1,
'''
if ledger_anchor not in source:
    raise SystemExit("Could not find the Delta ledger record start. Nothing changed.")
source = source.replace(ledger_anchor, ledger_insert, 1)

ledger_fields_anchor = '''        "shield": shield,
        "timing_state": market_timing.get("timing_state", "OBSERVE"),
'''
ledger_fields_insert = '''        "shield": shield,
        "next_condition": next_condition,
        "repair_text": repair_text,
        "timing_state": market_timing.get("timing_state", "OBSERVE"),
'''
if ledger_fields_anchor not in source:
    raise SystemExit("Could not find the Delta ledger shield fields. Nothing changed.")
source = source.replace(ledger_fields_anchor, ledger_fields_insert, 1)

print_anchor = '''        print(f"║ SHIELD     {shield[:62]:<62}║")

        if noise.get("available"):
'''
print_insert = '''        print(f"║ SHIELD     {shield[:62]:<62}║")
        _, repair_text = _delta_candidate_repair(delta, structure)
        print(f"║ FIX        {repair_text[:62]:<62}║")

        if noise.get("available"):
'''
if print_anchor not in source:
    raise SystemExit("Could not find the terminal SHIELD display block. Nothing changed.")
source = source.replace(print_anchor, print_insert, 1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"scanner.pre_candidate_repair_{stamp}.py")
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
print("Added observation-only Delta candidate repair to terminal cards and delta_tempo.jsonl.")
