from pathlib import Path
from datetime import datetime
import py_compile
import re
import shutil

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "scanner.py"

source = TARGET.read_text(encoding="utf-8")

new_function = r'''def _print_table(results: List[Dict[str, Any]], cycle: int, ts: str) -> None:
    os.system("cls" if os.name == "nt" else "clear")
    counts = _log_counts()

    print("╔══════════════════════════════════════════════════════════════════════════════╗")
    print(f"║ JHL DELTA 2.0 │ Cycle {cycle:03d} │ {ts:<43}║")
    print(
        f"║ Logs: GV={counts['gimba_volatile']:>4} GR={counts['gimba_range']:>4} "
        f"RTS={counts['rts_liquidation']:>4} DRV={counts['gimba_drive']:>4} "
        f"PUL={counts['gimba_pulse']:>4} │ ORDERS DISABLED{'':>17}║"
    )
    print("╠══════════════════════════════════════════════════════════════════════════════╣")

    for row in results:
        pair = row["pair"]
        delta = row.get("delta_tempo") or {}
        structure = row.get("structure") or {}
        timing = row.get("market_timing") or {}
        noise = row.get("market_noise") or {}
        pressure = row.get("volume_flow") or {}

        event = str(delta.get("event") or "NO_DELTA")
        radar = str(delta.get("radar_state") or "NO_TARGET")
        executioner = str(delta.get("executioner_state") or "NO_TRADE")
        shield = ", ".join(str(item) for item in (delta.get("shield") or [])) or "clear"

        speed = delta.get("speed_score")
        speed_text = "—" if speed is None else f"{float(speed):.3f}"

        ratio = delta.get("speed_change_ratio")
        ratio_text = "—" if ratio is None else f"{float(ratio):.2f}x"

        market_condition = str(
            delta.get("market_condition")
            or structure.get("market_condition")
            or "UNKNOWN"
        )
        trend = str(delta.get("trend") or structure.get("trend") or "unknown")
        zone = str(delta.get("zone") or structure.get("zone") or "neutral")
        bos = "YES" if delta.get("bos") else "NO"

        geometry_status = str(delta.get("geometry_status") or "PENDING")

        if geometry_status == "LOCAL_STRUCTURE_VALID":
            entry = delta.get("entry")
            stop = delta.get("sl")
            target = delta.get("tp")
            room = delta.get("room_to_risk")

            if all(value is not None for value in (entry, stop, target, room)):
                geometry_text = (
                    f"Entry {float(entry):.6g} | Stop {float(stop):.6g} | "
                    f"Target {float(target):.6g} | {float(room):.2f}R"
                )
            else:
                geometry_text = "VALID but one or more numeric levels missing"
        elif geometry_status == "GEOMETRY_REJECTED":
            geometry_text = f"REJECTED: {delta.get('geometry_reason', 'unknown')}"
        else:
            geometry_text = str(delta.get("geometry_reason") or geometry_status)

        print(f"║ ── {pair:<9} EVENT {event:<28} SPEED {speed_text:<7} Δ {ratio_text:<6}║")
        print(
            f"║ STRUCTURE  {market_condition:<25} "
            f"TREND {trend:<8} ZONE {zone:<9}║"
        )
        print(
            f"║ RADAR      {radar:<22} EXECUTIONER {executioner:<20} "
            f"BOS {bos:<3}║"
        )
        print(f"║ GEOMETRY   {geometry_text[:62]:<62}║")
        print(f"║ SHIELD     {shield[:62]:<62}║")

        if noise.get("available"):
            noise_text = (
                f"{noise.get('regime', 'UNKNOWN')} "
                f"{float(noise.get('noise_score', 0.0)):.2f}"
            )
        else:
            noise_text = "unavailable"

        print(
            f"║ CONTEXT    timing={timing.get('timing_state', 'OBSERVE')} "
            f"noise={noise_text} "
            f"KNN({delta.get('knn_samples', 0)}) "
            f"{float(delta.get('knn_adjustment', 0.0)):+.3f}║"
        )

        pulse = row.get("gimba_pulse") or {}
        drive = row.get("gimba_drive") or {}
        rts = row.get("rts_liq") or {}
        gr = row.get("gimba_range") or {}

        pulse_label = pulse.get("pulse_state") or pulse.get("setup_type") or "—"
        drive_label = drive.get("setup_type") or "—"
        range_label = gr.get("setup_type") or "—"
        rts_label = rts.get("setup_type") or "—"

        telemetry = (
            f"Pulse={pulse_label} | Drive={drive_label} | "
            f"Range={range_label} | RTS={rts_label}"
        )
        print(f"║ TELEMETRY  {telemetry[:62]:<62}║")

        status = (
            "READY"
            if pressure.get("ready")
            else f"OFF:{pressure.get('reason', 'unknown')}"
        )
        print(f"║ FLOW       {status[:68]:<68}║")
        print("║")

    print("╚══════════════════════════════════════════════════════════════════════════════╝")
    print(
        f"Next scan in {SCAN_INTERVAL}s │ Flow candle {FLOW_INTERVAL_MINUTES}m │ "
        "Delta 2.0 observation only │ Ctrl+C to stop"
    )
'''

pattern = re.compile(
    r"^def _print_table\(.*?(?=^def _apply_structure_amplifier\()",
    flags=re.MULTILINE | re.DOTALL,
)

if not pattern.search(source):
    raise SystemExit("Could not find _print_table() boundaries. Nothing changed.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"scanner.pre_delta2_display_{stamp}.py")
shutil.copy2(TARGET, backup)

patched = pattern.sub(new_function + "\n\n", source, count=1)
TARGET.write_text(patched, encoding="utf-8")
py_compile.compile(str(TARGET), doraise=True)

print(f"Patched: {TARGET.name}")
print(f"Backup:  {backup.name}")
print("Syntax check: PASS")