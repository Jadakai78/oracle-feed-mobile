from __future__ import annotations

import py_compile
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "scanner.py"

if not TARGET.exists():
    raise SystemExit(f"scanner.py not found beside this repair script: {TARGET}")

source = TARGET.read_text(encoding="utf-8")

if 'event.startswith("DELTA_LONG")' in source and 'event.startswith("DELTA_SHORT")' in source:
    raise SystemExit("Prefix-based Delta side normalization is already installed. Nothing changed.")

anchor = '    record = {\n        "schema_version": 1,'
if anchor not in source:
    raise SystemExit("Could not find the Delta ledger record block. Nothing changed.")

normalizer = '''    event = str(delta.get("event") or "NO_DELTA")
    router_side = str(delta.get("side") or "NONE").upper()
    if event.startswith("DELTA_LONG"):
        side = "LONG"
    elif event.startswith("DELTA_SHORT"):
        side = "SHORT"
    else:
        side = router_side

'''
source = source.replace(anchor, normalizer + anchor, 1)

first_field = '        "event": delta.get("event", "NO_DELTA"),\n'
if first_field not in source:
    raise SystemExit("Could not find the Delta ledger event field. Nothing changed.")
source = source.replace(first_field, '        "event": event,\n', 1)

side_field_pattern = re.compile(r'^        "side": .*?\n', flags=re.MULTILINE)
match = side_field_pattern.search(source, source.find('        "event": event,'))
if not match:
    raise SystemExit("Could not find the Delta ledger side field. Nothing changed.")
source = source[:match.start()] + '        "side": side,\n' + source[match.end():]

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"scanner.pre_delta_ledger_side_repair_{stamp}.py")
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
print("Delta side now derives from event prefixes: DELTA_LONG* -> LONG, DELTA_SHORT* -> SHORT.")
