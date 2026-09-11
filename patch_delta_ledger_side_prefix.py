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

old = '''    if side == "NONE":
        if event == "DELTA_LONG":
            side = "LONG"
        elif event == "DELTA_SHORT":
            side = "SHORT"
'''
new = '''    if side == "NONE":
        if event.startswith("DELTA_LONG"):
            side = "LONG"
        elif event.startswith("DELTA_SHORT"):
            side = "SHORT"
'''

if new in source:
    raise SystemExit("Prefix-based Delta side normalization is already installed. Nothing changed.")

if old not in source:
    raise SystemExit(
        "Could not find the exact existing side-normalization block in scanner.py. "
        "Nothing changed."
    )

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"scanner.pre_delta_ledger_side_prefix_{stamp}.py")
shutil.copy2(TARGET, backup)

TARGET.write_text(source.replace(old, new, 1), encoding="utf-8")

try:
    py_compile.compile(str(TARGET), doraise=True)
except Exception:
    shutil.copy2(backup, TARGET)
    raise

print(f"Patched: {TARGET.name}")
print(f"Backup:  {backup.name}")
print("Syntax check: PASS")
print("New rows will map DELTA_LONG_* to LONG and DELTA_SHORT_* to SHORT.")
