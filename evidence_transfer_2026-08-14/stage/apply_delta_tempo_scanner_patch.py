from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "scanner.py"


def sub_once(text: str, pattern: str, replacement: str, label: str, flags: int = re.MULTILINE) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return updated


def main() -> None:
    if not SCANNER.exists():
        raise SystemExit(f"Missing {SCANNER}")
    if not (ROOT / "delta_tempo_prop_router.py").exists():
        raise SystemExit("Put delta_tempo_prop_router.py beside scanner.py first.")
    source = SCANNER.read_text(encoding="utf-8")
    if "import delta_tempo_prop_router" in source:
        raise SystemExit("scanner.py already contains the Delta Tempo integration.")

    source = sub_once(source, r"^import shadow_trend_recovery\s*$", "import shadow_trend_recovery\nimport delta_tempo_prop_router", "router import")
    source = sub_once(
        source,
        r'^(?P<i>\s*)pulse\["training_only"\]\s*=\s*True\s*$',
        '\\g<i># Drive and Pulse are Delta Tempo contributors only; neither has entry authority.\n\\g<i>drv["training_only"] = False\n\\g<i>drv["diagnostic_only"] = False\n\\g<i>pulse["training_only"] = False',
        "Pulse training role",
    )
    source = sub_once(source, r'^(?P<i>\s*)pulse\["diagnostic_only"\]\s*=\s*True\s*$', '\\g<i>pulse["diagnostic_only"] = False', "Pulse diagnostic role")
    source = sub_once(
        source,
        r"^(?P<i>\s*)# 7\. Log one observation per bot per completed pressure candle\.\s*$",
        '''\\g<i># 6b. Delta Tempo is the sole entry authority. Range, RTS, Drive, and
\\g<i># Pulse contribute context and claims only; none emits its own entry card.
\\g<i>_apply_knn("gimba_pulse", pulse, structure, volume_flow)
\\g<i>delta_tempo = delta_tempo_prop_router.evaluate(
\\g<i>    pair=pair,
\\g<i>    kraken_pair=kraken_pair,
\\g<i>    volume_flow=volume_flow,
\\g<i>    market_timing=shared_market_timing,
\\g<i>    signals={
\\g<i>        "gimba_range": gr,
\\g<i>        "rts_liq": rts,
\\g<i>        "gimba_drive": drv,
\\g<i>        "gimba_pulse": pulse,
\\g<i>    },
\\g<i>    log_dir=LOG_DIR,
\\g<i>)

\\g<i># 7. Log one observation per bot per completed pressure candle.''',
        "Delta Tempo router",
    )
    source = sub_once(
        source,
        r'^(?P<i>\s*)"gimba_pulse"\s*:\s*pulse,\s*$',
        '\\g<i>"gimba_pulse": pulse,\n\\g<i>"delta_tempo": delta_tempo,',
        "signals.json Delta Tempo field",
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / f"scanner_before_delta_tempo_{stamp}.py"
    shutil.copy2(SCANNER, backup)
    SCANNER.write_text(source, encoding="utf-8", newline="\n")
    print(f"Patched: {SCANNER.name}")
    print(f"Backup:  {backup.name}")
    print("No orders were enabled. Compile scanner.py before starting it.")


if __name__ == "__main__":
    main()
