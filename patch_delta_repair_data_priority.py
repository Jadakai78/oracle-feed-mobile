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

if 'return "restore_data", "Restore market-data inputs; do not evaluate this card"' in source:
    raise SystemExit("Data-first repair priority is already installed. Nothing changed.")

anchor = '''    needs_location = (
        "range_long_into_premium" in shield
'''
insert = '''    data_unavailable = (
        event == "NO_DELTA"
        and any(
            token in " ".join(shield).lower()
            for token in (
                "kraken_fetch_error",
                "trade_response_at_limit",
                "local_15m_bars_unavailable",
                "local_bars_unavailable",
                "delta_unavailable",
            )
        )
    ) or any(
        token in " ".join(shield).lower()
        for token in (
            "kraken_fetch_error",
            "trade_response_at_limit",
            "local_15m_bars_unavailable",
            "local_bars_unavailable",
        )
    ) or geometry in {"LOCAL_15M_BARS_UNAVAILABLE", "LOCAL_BARS_UNAVAILABLE"}

    if data_unavailable:
        return "restore_data", "Restore market-data inputs; do not evaluate this card"

    needs_location = (
        "range_long_into_premium" in shield
'''

if anchor not in source:
    raise SystemExit("Could not find the candidate-repair priority insertion point. Nothing changed.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"scanner.pre_repair_data_priority_{stamp}.py")
shutil.copy2(TARGET, backup)
TARGET.write_text(source.replace(anchor, insert, 1), encoding="utf-8")

try:
    py_compile.compile(str(TARGET), doraise=True)
except Exception:
    shutil.copy2(backup, TARGET)
    raise

print(f"Patched: {TARGET.name}")
print(f"Backup:  {backup.name}")
print("Syntax check: PASS")
print("Candidate FIX now prioritizes missing/capped market data over later signal conditions.")
