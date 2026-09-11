from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "scanner.py"

if not TARGET.exists():
    raise SystemExit(f"scanner.py not found beside this patch script: {TARGET}")

source = TARGET.read_text(encoding="utf-8")

if "def _delta_eligibility(" in source:
    raise SystemExit("Delta eligibility feed classification already appears to be installed. Nothing changed.")

helper = r'''

def _delta_eligibility(
    delta: Dict[str, Any],
    volume_flow: Dict[str, Any],
    structure: Dict[str, Any],
) -> Dict[str, Any]:
    """Classify a Delta card for display/alert readiness only; never places orders."""
    event = str(delta.get("event") or "NO_DELTA")
    side = "LONG" if event.startswith("DELTA_LONG") else "SHORT" if event.startswith("DELTA_SHORT") else "NONE"
    shield_raw = delta.get("shield") or []
    shield = [str(item) for item in ([shield_raw] if isinstance(shield_raw, str) else shield_raw)]
    shield_lower = {item.lower() for item in shield}
    geometry_status = str(delta.get("geometry_status") or "PENDING")
    radar = str(delta.get("radar_state") or "NO_TARGET")
    executioner = str(delta.get("executioner_state") or "NO_TRADE")
    flow_ready = bool(volume_flow.get("ready", False))
    bos = bool(delta.get("bos", False))

    data_tokens = (
        "kraken_fetch_error",
        "trade_response_at_limit",
        "trade_pagination_",
        "local_15m_bars_unavailable",
        "local_bars_unavailable",
        "delta_unavailable",
    )
    has_data_failure = (
        not flow_ready
        or geometry_status in {"LOCAL_15M_BARS_UNAVAILABLE", "LOCAL_BARS_UNAVAILABLE"}
        or any(any(token in item for token in data_tokens) for item in shield_lower)
    )
    if has_data_failure:
        return {
            "eligibility_state": "NO_DATA",
            "eligibility_blockers": ["market_data_unavailable"],
            "eligibility_reason": "Market-data inputs are incomplete; card is not evaluable",
            "side": side,
        }

    location_tokens = {
        "range_long_into_premium",
        "range_short_into_discount",
        "range_midpoint_no_room",
    }
    has_location_failure = bool(shield_lower & location_tokens)
    geometry_valid = geometry_status == "LOCAL_STRUCTURE_VALID"
    try:
        room_to_risk = float(delta.get("room_to_risk"))
    except (TypeError, ValueError):
        room_to_risk = 0.0
    geometry_ok = geometry_valid and room_to_risk >= 1.50

    if side == "NONE" or event == "NO_DELTA":
        return {
            "eligibility_state": "BUILDING",
            "eligibility_blockers": ["no_directional_delta"],
            "eligibility_reason": "No directional Delta event yet",
            "side": side,
        }

    if has_location_failure or radar == "NO_TARGET":
        return {
            "eligibility_state": "REJECTED",
            "eligibility_blockers": [item for item in shield if item in location_tokens] or ["no_valid_target"],
            "eligibility_reason": "Location or target radar rejects this direction",
            "side": side,
        }

    if not geometry_ok:
        return {
            "eligibility_state": "BUILDING",
            "eligibility_blockers": ["geometry_below_minimum"],
            "eligibility_reason": "Directional idea exists but local geometry is below the 1.50R floor",
            "side": side,
        }

    confirmation_blockers = []
    if "pressure_not_aligned" in shield_lower:
        confirmation_blockers.append("pressure")
    if "cvd_not_aligned" in shield_lower:
        confirmation_blockers.append("cvd")
    if not bos:
        confirmation_blockers.append("bos")
    if executioner not in {"READY", "EXECUTION_READY"}:
        confirmation_blockers.append("executioner")

    if confirmation_blockers:
        return {
            "eligibility_state": "ELIGIBLE_WATCH",
            "eligibility_blockers": confirmation_blockers,
            "eligibility_reason": "Valid map and target; waiting for confirmation gates",
            "side": side,
        }

    return {
        "eligibility_state": "EXECUTION_ELIGIBLE",
        "eligibility_blockers": [],
        "eligibility_reason": "All observation gates are aligned; manual review only",
        "side": side,
    }
'''

helper_anchor = "\ndef _delta_candidate_repair("
if helper_anchor not in source:
    raise SystemExit("Could not find the candidate-repair function. Nothing changed.")
source = source.replace(helper_anchor, helper + "\n\ndef _delta_candidate_repair(", 1)

print_anchor = '''        print(f"║ SHIELD     {shield[:62]:<62}║")
        _, repair_text = _delta_candidate_repair(delta, structure)
'''
print_insert = '''        eligibility = _delta_eligibility(delta, pressure, structure)
        eligibility_state = str(eligibility.get("eligibility_state") or "BUILDING")
        blockers = eligibility.get("eligibility_blockers") or []
        blockers_text = "CLEAR" if not blockers else ", ".join(str(item) for item in blockers)
        print(f"║ STATUS     {eligibility_state[:62]:<62}║")
        print(f"║ GATES      {blockers_text[:62]:<62}║")
        print(f"║ SHIELD     {shield[:62]:<62}║")
        _, repair_text = _delta_candidate_repair(delta, structure)
'''
if print_anchor not in source:
    raise SystemExit("Could not find the terminal SHIELD/FIX display block. Nothing changed.")
source = source.replace(print_anchor, print_insert, 1)

run_anchor = '''        # 7. Log one observation per bot per completed pressure candle.
'''
run_insert = '''        delta_tempo["eligibility"] = _delta_eligibility(
            delta_tempo,
            volume_flow,
            structure,
        )

        # 7. Log one observation per bot per completed pressure candle.
'''
if run_anchor not in source:
    raise SystemExit("Could not find the run-cycle eligibility insertion point. Nothing changed.")
source = source.replace(run_anchor, run_insert, 1)

ledger_anchor = '''        "shield": shield,
        "next_condition": next_condition,
'''
ledger_insert = '''        "shield": shield,
        "eligibility": delta.get("eligibility") or _delta_eligibility(delta, volume_flow, structure),
        "next_condition": next_condition,
'''
if ledger_anchor not in source:
    raise SystemExit("Could not find the Delta ledger shield block. Nothing changed.")
source = source.replace(ledger_anchor, ledger_insert, 1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"scanner.pre_delta_eligibility_{stamp}.py")
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
print("Added feed-only Delta eligibility states: NO_DATA, REJECTED, BUILDING, ELIGIBLE_WATCH, EXECUTION_ELIGIBLE.")
print("Orders remain disabled; this patch only classifies and displays cards.")
