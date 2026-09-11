from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "scanner.py"


def main() -> None:
    if not SCANNER.exists():
        raise SystemExit(f"Missing {SCANNER}")
    if not (ROOT / "delta_tempo_defense.py").exists():
        raise SystemExit("Put delta_tempo_defense.py beside scanner.py first.")
    source = SCANNER.read_text(encoding="utf-8")
    if "delta_tempo_defense.apply(" in source:
        raise SystemExit("scanner.py already contains the Delta Tempo defense integration.")
    if "import delta_tempo_prop_router" not in source:
        raise SystemExit("Missing Delta Tempo router import. Repair scanner integration first.")

    source = source.replace(
        "import delta_tempo_prop_router",
        "import delta_tempo_prop_router\nimport delta_tempo_defense",
        1,
    )

    pattern = r"(?P<end>^(?P<i>[ \t]*)log_dir=LOG_DIR,\s*\n(?P=i)\)\s*\n)(?P<marker>^[ \t]*# 7\. Log one observation per bot per completed pressure candle\.)"
    addition = """\\g<end>\\g<i>delta_tempo = delta_tempo_defense.apply(
\\g<i>    candidate=delta_tempo,
\\g<i>    market_noise=shared_market_noise,
\\g<i>    structure=structure,
\\g<i>)

\\g<marker>"""
    source, count = re.subn(pattern, addition, source, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit("Could not locate the router-call end with the current scanner formatting. No files were changed.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / f"scanner_before_delta_tempo_defense_{stamp}.py"
    shutil.copy2(SCANNER, backup)
    SCANNER.write_text(source, encoding="utf-8", newline="\n")
    print(f"Patched: {SCANNER.name}")
    print(f"Backup:  {backup.name}")
    print("Defense added: noise-unavailable veto, Drive-alone veto, and 0.25R late-entry veto.")
    print("Orders remain disabled.")


if __name__ == "__main__":
    main()
