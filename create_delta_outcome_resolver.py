from __future__ import annotations

from pathlib import Path

CONTENT = r'''"""Delta 2.0 observation-only outcome resolver.

Reads training_logs/delta_tempo.jsonl and appends outcome-resolution events to
training_logs/delta_tempo_outcomes.jsonl. It never edits ledger history, emits
signals, changes scanner decisions, or places orders.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

KRAKEN_API = "https://api.kraken.com/0/public"
TIMEFRAME_MINUTES = 15
EVALUATION_BARS = 16
MIN_ROOM_TO_RISK = 1.50
PAIR_MAP = {
    "SOL/USD": "SOLUSD",
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
    "XRP/USD": "XRPUSD",
    "ADA/USD": "ADAUSD",
    "DOGE/USD": "XDGUSD",
    "LINK/USD": "LINKUSD",
    "AVAX/USD": "AVAXUSD",
    "DOT/USD": "DOTUSD",
    "MATIC/USD": "MATICUSD",
    "AAVE/USD": "AAVEUSD",
    "LTC/USD": "XLTCZUSD",
}

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"
LEDGER_PATH = LOG_DIR / "delta_tempo.jsonl"
OUTCOME_PATH = LOG_DIR / "delta_tempo_outcomes.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{KRAKEN_API}{path}?{query}", timeout=12) as response:
        payload = json.loads(response.read())
    if payload.get("error"):
        raise RuntimeError("; ".join(payload["error"]))
    return payload.get("result") or {}


def _ohlc_rows(pair: str) -> List[list]:
    kraken_pair = PAIR_MAP.get(pair)
    if not kraken_pair:
        raise ValueError(f"unsupported_pair:{pair}")
    result = _request("/OHLC", {"pair": kraken_pair, "interval": TIMEFRAME_MINUTES})
    key = next((name for name in result if name != "last"), None)
    if not key:
        return []
    rows = list(result.get(key) or [])
    # Kraken's final row is the in-progress candle. It cannot resolve an outcome.
    return rows[:-1] if len(rows) > 1 else []


def _eligible(record: Dict[str, Any]) -> Tuple[bool, str]:
    side = str(record.get("side") or "NONE").upper()
    if side not in {"LONG", "SHORT"}:
        return False, "side_unavailable"
    if str(record.get("geometry_status") or "") != "LOCAL_STRUCTURE_VALID":
        return False, "geometry_not_valid"
    try:
        entry = float(record["entry"])
        sl = float(record["sl"])
        tp = float(record["tp"])
        room = float(record["room_to_risk"])
    except (KeyError, TypeError, ValueError):
        return False, "levels_unavailable"
    if entry <= 0 or sl <= 0 or tp <= 0 or room < MIN_ROOM_TO_RISK:
        return False, "invalid_or_subminimum_geometry"
    if side == "LONG" and not (sl < entry < tp):
        return False, "long_level_order_invalid"
    if side == "SHORT" and not (tp < entry < sl):
        return False, "short_level_order_invalid"
    return True, "eligible"


def _existing_keys() -> set[str]:
    if not OUTCOME_PATH.exists():
        return set()
    keys: set[str] = set()
    with OUTCOME_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                key = row.get("event_key")
                if key:
                    keys.add(str(key))
            except json.JSONDecodeError:
                continue
    return keys


def _resolve(record: Dict[str, Any], rows: List[list]) -> Dict[str, Any]:
    event_key = str(record["event_key"])
    pair = str(record["pair"])
    bar_start = int(record["bar_start"])
    side = str(record["side"]).upper()
    entry = float(record["entry"])
    sl = float(record["sl"])
    tp = float(record["tp"])
    end_ts = bar_start + EVALUATION_BARS * TIMEFRAME_MINUTES * 60

    completed = [row for row in rows if int(float(row[0])) > bar_start]
    horizon = [row for row in completed if int(float(row[0])) <= end_ts]
    latest_completed_ts = int(float(rows[-1][0])) if rows else 0

    for index, row in enumerate(horizon, start=1):
        bar_ts = int(float(row[0]))
        high = float(row[2])
        low = float(row[3])
        open_price = float(row[1])
        close = float(row[4])

        if side == "LONG":
            hit_tp = high >= tp
            hit_sl = low <= sl
        else:
            hit_tp = low <= tp
            hit_sl = high >= sl

        if hit_tp and hit_sl:
            # OHLC cannot establish intrabar sequence. Preserve the ambiguity.
            label = "AMBIGUOUS_BOTH_TOUCHED"
            first_touch = "both"
        elif hit_tp:
            label = "TP_FIRST"
            first_touch = "tp"
        elif hit_sl:
            label = "SL_FIRST"
            first_touch = "sl"
        else:
            continue

        return {
            "schema_version": 1,
            "event_key": event_key,
            "pair": pair,
            "resolved_at": _now_iso(),
            "source_bar_start": bar_start,
            "resolution_bar_start": bar_ts,
            "evaluation_bars": EVALUATION_BARS,
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "room_to_risk": record.get("room_to_risk"),
            "label": label,
            "status": "resolved",
            "first_touch": first_touch,
            "bars_to_resolution": index,
            "bar_open": open_price,
            "bar_high": high,
            "bar_low": low,
            "bar_close": close,
            "method": "completed_15m_ohlc_first_touch",
        }

    if latest_completed_ts >= end_ts:
        return {
            "schema_version": 1,
            "event_key": event_key,
            "pair": pair,
            "resolved_at": _now_iso(),
            "source_bar_start": bar_start,
            "resolution_bar_start": end_ts,
            "evaluation_bars": EVALUATION_BARS,
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "room_to_risk": record.get("room_to_risk"),
            "label": "EXPIRED",
            "status": "resolved",
            "first_touch": None,
            "bars_to_resolution": EVALUATION_BARS,
            "method": "completed_15m_ohlc_first_touch",
        }

    return {
        "schema_version": 1,
        "event_key": event_key,
        "pair": pair,
        "status": "pending",
        "reason": "evaluation_window_not_complete",
    }


def main() -> None:
    if not LEDGER_PATH.exists():
        raise SystemExit(f"Ledger not found: {LEDGER_PATH}")

    LOG_DIR.mkdir(exist_ok=True)
    existing = _existing_keys()
    records: List[Dict[str, Any]] = []
    with LEDGER_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(record.get("event_key") or "") not in existing:
                records.append(record)

    eligible: List[Dict[str, Any]] = []
    skipped: Dict[str, int] = {}
    for record in records:
        ok, reason = _eligible(record)
        if ok:
            eligible.append(record)
        else:
            skipped[reason] = skipped.get(reason, 0) + 1

    rows_by_pair: Dict[str, List[list]] = {}
    resolved: List[Dict[str, Any]] = []
    pending = 0
    failures = 0

    for record in eligible:
        pair = str(record["pair"])
        try:
            if pair not in rows_by_pair:
                rows_by_pair[pair] = _ohlc_rows(pair)
            outcome = _resolve(record, rows_by_pair[pair])
            if outcome.get("status") == "resolved":
                resolved.append(outcome)
            else:
                pending += 1
        except Exception as exc:
            failures += 1
            print(f"[WARN] {pair} {record.get('event_key')}: {type(exc).__name__}")
        time.sleep(0.15)

    if resolved:
        with OUTCOME_PATH.open("a", encoding="utf-8") as handle:
            for outcome in resolved:
                handle.write(json.dumps(outcome, ensure_ascii=False) + "\n")

    print(f"Ledger rows checked: {len(records)}")
    print(f"Eligible geometry rows: {len(eligible)}")
    print(f"Resolved outcomes written: {len(resolved)}")
    print(f"Still pending horizon: {pending}")
    print(f"Fetch/resolve warnings: {failures}")
    if skipped:
        print("Skipped: " + ", ".join(f"{key}={value}" for key, value in sorted(skipped.items())))
    print(f"Outcome file: {OUTCOME_PATH}")


if __name__ == "__main__":
    main()
'''

script_path = Path(__file__).resolve().parent / "delta_outcome_resolver.py"
if script_path.exists():
    raise SystemExit("delta_outcome_resolver.py already exists. Nothing changed.")
script_path.write_text(CONTENT, encoding="utf-8")
print(f"Created: {script_path.name}")
'''

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "delta_outcome_resolver.py"

if TARGET.exists():
    raise SystemExit("delta_outcome_resolver.py already exists. Nothing changed.")

TARGET.write_text(CONTENT, encoding="utf-8")
print(f"Created: {TARGET.name}")
