from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "scanner.py"
MARKER = "# 7. Log one observation per bot per completed pressure candle."
IMPORT = "import delta_tempo_prop_router"
BLOCK = '''# 6b. Delta Tempo is the sole entry authority. Range, RTS, Drive, and
# Pulse contribute context and claims only; none emits its own entry card.
drv["training_only"] = False
drv["diagnostic_only"] = False
pulse["training_only"] = False
pulse["diagnostic_only"] = False
_apply_knn("gimba_pulse", pulse, structure, volume_flow)
delta_tempo = delta_tempo_prop_router.evaluate(
    pair=pair,
    kraken_pair=kraken_pair,
    volume_flow=volume_flow,
    market_timing=shared_market_timing,
    signals={
        "gimba_range": gr,
        "rts_liq": rts,
        "gimba_drive": drv,
        "gimba_pulse": pulse,
    },
    log_dir=LOG_DIR,
)

'''


def main() -> None:
    if not SCANNER.exists():
        raise SystemExit(f"Missing {SCANNER}")
    if not (ROOT / "delta_tempo_prop_router.py").exists():
        raise SystemExit("Put delta_tempo_prop_router.py beside scanner.py first.")

    source = SCANNER.read_text(encoding="utf-8")
    changed = False
    if IMPORT not in source:
        anchor = "import shadow_trend_recovery"
        if anchor not in source:
            raise SystemExit("Could not find the scanner import anchor.")
        source = source.replace(anchor, anchor + "\n" + IMPORT, 1)
        changed = True

    if "delta_tempo = delta_tempo_prop_router.evaluate(" not in source:
        if MARKER not in source:
            raise SystemExit("Could not find the scanner Delta Tempo insertion marker.")
        source = source.replace(MARKER, BLOCK + MARKER, 1)
        changed = True

    if '"delta_tempo": delta_tempo,' not in source:
        anchor = '"gimba_pulse": pulse,'
        if anchor not in source:
            raise SystemExit("Could not find the signals.json insertion anchor.")
        source = source.replace(anchor, anchor + '\n"delta_tempo": delta_tempo,', 1)
        changed = True

    if not changed:
        print("Scanner already has the complete Delta Tempo integration.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / f"scanner_before_delta_tempo_repair_{stamp}.py"
    shutil.copy2(SCANNER, backup)
    SCANNER.write_text(source, encoding="utf-8", newline="\n")
    print(f"Repaired: {SCANNER.name}")
    print(f"Backup:   {backup.name}")
    print("No orders were enabled.")


if __name__ == "__main__":
    main()
