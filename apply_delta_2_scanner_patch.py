from pathlib import Path
from datetime import datetime
import shutil
import re
import py_compile

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "scanner.py"

if not TARGET.exists():
    raise SystemExit(f"Missing: {TARGET}")

source = TARGET.read_text(encoding="utf-8")


def matching_paren_end(text: str, open_pos: int) -> int:
    depth = 0
    quote = None
    escaped = False

    for pos in range(open_pos, len(text)):
        char = text[pos]

        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return pos

    raise ValueError("No matching closing parenthesis found.")


router_anchor = "delta_tempo = delta_tempo_prop_router.evaluate("
router_at = source.find(router_anchor)

if router_at < 0:
    raise SystemExit("Could not find delta_tempo_prop_router.evaluate() call.")

call_open = source.find("(", router_at)
call_close = matching_paren_end(source, call_open)
router_block = source[router_at:call_close + 1]

if "structure=structure" not in router_block:
    last_arg_line = router_block.rfind("\n", 0, router_block.rfind(")"))
    closing_line_start = router_block.rfind("\n", 0, len(router_block) - 1)
    closing_indent_match = re.search(r"\n([ \t]*)\)$", router_block)

    if not closing_indent_match:
        raise SystemExit("Could not infer router closing indentation.")

    closing_indent = closing_indent_match.group(1)

    arg_indents = re.findall(r"\n([ \t]+)[A-Za-z_][A-Za-z0-9_]*=", router_block)
    argument_indent = arg_indents[-1] if arg_indents else closing_indent + "    "

    insert_at = router_block.rfind("\n" + closing_indent + ")")

    if insert_at < 0:
        raise SystemExit("Could not locate router closing line.")

    before = router_block[:insert_at].rstrip()

    if not before.endswith(","):
        before += ","

    router_block = (
        before
        + f"\n{argument_indent}structure=structure,"
        + f"\n{argument_indent}market_state=market_state"
        + router_block[insert_at:]
    )

    source = source[:router_at] + router_block + source[call_close + 1:]


new_print_table = r'''def _print_table(results: List[Dict[str, Any]], cycle: int, ts: str) -> None:
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

        print(f"║ ── {pair:<9} EVENT {event:<28} SPEED {speed_text:<7} Δ {ratio_text:<6}║")
        print(
            f"║ STRUCTURE  {market_condition:<25} "
            f"TREND {trend:<8} ZONE {zone:<9}║"
        )
        print(
            f"║ RADAR      {radar:<22} EXECUTIONER {executioner:<20} "
            f"BOS {bos:<3}║"
        )
        print(
            f"║ GEOMETRY   {str(delta.get('geometry_status') or 'PENDING'):<62}║"
        )
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
    flags=re.DOTALL | re.MULTILINE,
)

if not pattern.search(source):
    raise SystemExit("Could not find complete _print_table() function; no changes made.")

source = pattern.sub(new_print_table + "\n\n", source, count=1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"scanner.pre_delta_2_{stamp}.py")
shutil.copy2(TARGET, backup)

TARGET.write_text(source, encoding="utf-8")
py_compile.compile(str(TARGET), doraise=True)

print(f"Patched: {TARGET}")
print(f"Backup:  {backup}")
print("Syntax check: PASS")