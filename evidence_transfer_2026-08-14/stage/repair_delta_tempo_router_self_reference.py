from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "scanner.py"
FIELD = '"delta_tempo": delta_tempo,'
PULSE = '"gimba_pulse": pulse,'


def main() -> None:
    if not SCANNER.exists():
        raise SystemExit(f"Missing {SCANNER}")
    source = SCANNER.read_text(encoding="utf-8")
    if "delta_tempo = delta_tempo_prop_router.evaluate(" not in source:
        raise SystemExit("The Delta Tempo router block is missing; use the integration repair first.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / f"scanner_before_delta_tempo_selfref_repair_{stamp}.py"
    shutil.copy2(SCANNER, backup)

    # Remove every misplaced or duplicate field first. The field must appear only
    # in the final published results row, never in the router's input signals dict.
    source = source.replace(FIELD, "")
    results_start = source.find("results.append(")
    if results_start < 0:
        raise SystemExit("Could not find results.append() in scanner.py.")
    output_pulse = source.find(PULSE, results_start)
    if output_pulse < 0:
        raise SystemExit("Could not find the output gimba_pulse field in results.append().")
    insert_at = output_pulse + len(PULSE)
    source = source[:insert_at] + '\n            "delta_tempo": delta_tempo,' + source[insert_at:]

    SCANNER.write_text(source, encoding="utf-8", newline="\n")
    print(f"Repaired: {SCANNER.name}")
    print(f"Backup:   {backup.name}")
    print("Moved delta_tempo from router inputs to the published results row. No orders were enabled.")


if __name__ == "__main__":
    main()
