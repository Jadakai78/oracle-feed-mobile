from pathlib import Path
from datetime import datetime, timezone
import json
import traceback

from shadow_tournament_arena import ShadowTournamentArena
from shadow_tournament_scanner_adapter_v3 import process

ROOT = Path(r"C:\Users\OneDrive\Desktop\jhl_v2\jhl_v2gimba")
SOURCE = ROOT / "signals.json"

if not SOURCE.exists():
    raise SystemExit(f"Missing scanner output: {SOURCE}")

snapshot = json.loads(SOURCE.read_text(encoding="utf-8"))
arena = ShadowTournamentArena(ROOT)
try:
    count = process(arena, ROOT, snapshot, set(), {})
    print(f"TRACE PASS: packets={count}")
except Exception:
    print(traceback.format_exc())
    raise
