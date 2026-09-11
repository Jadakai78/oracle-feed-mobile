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

if "def _notify_execution_eligible(" in source:
    raise SystemExit("Pushover execution-eligible alerts already appear to be installed. Nothing changed.")

imports_anchor = "import urllib.request\n"
imports_insert = "import urllib.request\nimport urllib.error\n"
if imports_anchor not in source:
    raise SystemExit("Could not find urllib.request import. Nothing changed.")
source = source.replace(imports_anchor, imports_insert, 1)

state_anchor = "_SEEN_EVENT_KEYS: set[str] = set()\n"
state_insert = '''_SEEN_EVENT_KEYS: set[str] = set()
_ALERT_STATE_FILE = LOG_DIR / "delta_execution_alert_state.json"
_ALERT_LOG_FILE = LOG_DIR / "delta_execution_alerts.jsonl"

'''
if state_anchor not in source:
    raise SystemExit("Could not find scanner state declarations. Nothing changed.")
source = source.replace(state_anchor, state_insert, 1)

helper = r'''

def _load_dotenv_if_present() -> None:
    """Load simple KEY=VALUE lines from local .env without overwriting real env vars."""
    dotenv_path = Path(__file__).parent / ".env"
    if not dotenv_path.exists():
        return
    try:
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        return


def _load_alert_state() -> Dict[str, str]:
    try:
        payload = json.loads(_ALERT_STATE_FILE.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in dict(payload).items()}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _save_alert_state(state: Dict[str, str]) -> None:
    _ALERT_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _append_execution_alert_log(record: Dict[str, Any]) -> None:
    with _ALERT_LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _pushover_send(title: str, message: str, priority: int = 1) -> tuple[bool, str]:
    """Send a Pushover HTTPS message. Returns status; never interrupts scanning."""
    token = os.getenv("PUSHOVER_APP_TOKEN", "").strip()
    user = os.getenv("PUSHOVER_USER_KEY", "").strip()
    if not token or not user:
        return False, "pushover_not_configured"

    payload = urllib.parse.urlencode({
        "token": token,
        "user": user,
        "title": title[:250],
        "message": message[:1024],
        "priority": str(priority),
        "sound": "siren",
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.pushover.net/1/messages.json",
        data=payload,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            if 200 <= response.status < 300:
                return True, "sent"
            return False, f"http_{response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}"


def _execution_alert_message(
    pair: str,
    delta: Dict[str, Any],
    eligibility: Dict[str, Any],
    structure: Dict[str, Any],
    volume_flow: Dict[str, Any],
) -> tuple[str, str]:
    side = str(eligibility.get("side") or "NONE")
    entry = delta.get("entry")
    sl = delta.get("sl")
    tp = delta.get("tp")
    room = delta.get("room_to_risk")
    levels = "Levels unavailable"
    if all(value is not None for value in (entry, sl, tp, room)):
        levels = (
            f"Entry {float(entry):.6g} | Stop {float(sl):.6g} | "
            f"Target {float(tp):.6g} | {float(room):.2f}R"
        )
    title = f"JHL READY — {pair} {side}"
    message = "\n".join((
        f"Event: {delta.get('event', 'NO_DELTA')}",
        levels,
        f"Structure: {structure.get('market_condition', 'UNKNOWN')} | {structure.get('zone', 'neutral')}",
        f"Radar: {delta.get('radar_state', 'NO_TARGET')} | BOS: {'YES' if delta.get('bos') else 'NO'}",
        f"Flow: {'READY' if volume_flow.get('ready') else 'OFF'} | Gates: CLEAR",
        "Orders disabled — manual review only.",
    ))
    return title, message


def _notify_execution_eligible(
    pair: str,
    delta: Dict[str, Any],
    eligibility: Dict[str, Any],
    structure: Dict[str, Any],
    volume_flow: Dict[str, Any],
    ts: str,
) -> None:
    """Notify once when a pair transitions into EXECUTION_ELIGIBLE."""
    state = _load_alert_state()
    current = str(eligibility.get("eligibility_state") or "BUILDING")
    previous = state.get(pair, "")
    state[pair] = current
    _save_alert_state(state)

    if current != "EXECUTION_ELIGIBLE" or previous == "EXECUTION_ELIGIBLE":
        return

    title, message = _execution_alert_message(pair, delta, eligibility, structure, volume_flow)
    sent, result = _pushover_send(title, message, priority=1)
    _append_execution_alert_log({
        "ts": ts,
        "pair": pair,
        "event_key": f"{pair}|{volume_flow.get('bar_start')}",
        "eligibility_state": current,
        "channel": "pushover",
        "sent": sent,
        "result": result,
        "title": title,
        "message": message,
    })
    print(f"[ALERT] {pair} EXECUTION_ELIGIBLE | Pushover: {result}")


def _send_pushover_test_alert() -> None:
    title = "JHL TEST — Pushover Connected"
    message = "Test alert path is working. No trade, signal, or order was created."
    sent, result = _pushover_send(title, message, priority=0)
    _append_execution_alert_log({
        "ts": _ts_iso(),
        "pair": "TEST",
        "event_key": "test",
        "eligibility_state": "TEST",
        "channel": "pushover",
        "sent": sent,
        "result": result,
        "title": title,
        "message": message,
    })
    print(f"[ALERT TEST] Pushover: {result}")
'''

helper_anchor = "\ndef _get_volume_state("
if helper_anchor not in source:
    raise SystemExit("Could not find the helper insertion point. Nothing changed.")
source = source.replace(helper_anchor, helper + "\n\ndef _get_volume_state(", 1)

eligibility_anchor = '''        delta_tempo["eligibility"] = _delta_eligibility(
            delta_tempo,
            volume_flow,
            structure,
        )

        # 7. Log one observation per bot per completed pressure candle.
'''
eligibility_insert = '''        delta_tempo["eligibility"] = _delta_eligibility(
            delta_tempo,
            volume_flow,
            structure,
        )
        _notify_execution_eligible(
            pair=pair,
            delta=delta_tempo,
            eligibility=delta_tempo["eligibility"],
            structure=structure,
            volume_flow=volume_flow,
            ts=ts,
        )

        # 7. Log one observation per bot per completed pressure candle.
'''
if eligibility_anchor not in source:
    raise SystemExit("Could not find the eligibility block in run_cycle(). Nothing changed.")
source = source.replace(eligibility_anchor, eligibility_insert, 1)

main_anchor = '''def main() -> None:
    cycle = 1
    print("Starting JHL Gimba Scanner — 12 pairs, canonical logs active...")
'''
main_insert = '''def main() -> None:
    _load_dotenv_if_present()
    if os.getenv("TEST_ALERTS", "0").strip() == "1":
        _send_pushover_test_alert()
        return
    cycle = 1
    print("Starting JHL Gimba Scanner — 12 pairs, canonical logs active...")
'''
if main_anchor not in source:
    raise SystemExit("Could not find main() startup block. Nothing changed.")
source = source.replace(main_anchor, main_insert, 1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"scanner.pre_pushover_alerts_{stamp}.py")
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
print("Added transition-only Pushover alerts for EXECUTION_ELIGIBLE; Outlook is intentionally deferred.")
print("Create .env with PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY, then use TEST_ALERTS=1 for a safe test.")
