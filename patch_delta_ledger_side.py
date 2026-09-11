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

if "event = str(delta.get(\"event\") or \"NO_DELTA\")" in source:
    raise SystemExit("The Delta ledger side-normalization patch appears to be installed already. Nothing changed.")

anchor = '''    shield = delta.get("shield") or []
    if isinstance(shield, str):
        shield = [shield]

    record = {
'''
replacement = '''    shield = delta.get("shield") or []
    if isinstance(shield, str):
        shield = [shield]

    event = str(delta.get("event") or "NO_DELTA")
    side = str(delta.get("side") or "NONE").upper()
    if side == "NONE":
        if event == "DELTA_LONG":
            side = "LONG"
        elif event == "DELTA_SHORT":
            side = "SHORT"

    record = {
'''

if anchor not in source:
    raise SystemExit("Could not locate the expected Delta ledger block. Nothing changed.")
source = source.replace(anchor, replacement, 1)

old_fields = '''        "event": delta.get("event", "NO_DELTA"),
        "side": delta.get("side", "NONE"),
'''
new_fields = '''        "event": event,
        "side": side,
'''
if old_fields not in source:
    raise SystemExit("Could not locate the event/side fields in the Delta ledger. Nothing changed.")
source = source.replace(old_fields, new_fields, 1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"scanner.pre_delta_ledger_side_{stamp}.py")
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
print("New ledger rows will derive LONG/SHORT from DELTA_LONG/DELTA_SHORT when router side is NONE.")
