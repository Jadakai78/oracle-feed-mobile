from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

ROOT = Path(__file__).resolve().parent

CONTEXT_PATH = ROOT / "oracle_prop_context_v1.json"
SPEED_PATH = ROOT / "speed_companion_state_v1.json"
BARS_PATH = ROOT / "training_logs" / "episode_5m_bars_v1.jsonl"

OUTPUT_JSON_PATH = ROOT / "speed_companion_coverage_audit_v1.json"
OUTPUT_CSV_PATH = ROOT / "speed_companion_coverage_audit_v1.csv"


def now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return payload


def context_pair(value: Any) -> str:
    return str(value or "").upper().strip()


def expected_futures_symbol(pair: str) -> str:
    base, quote = pair.split("/", 1)
    aliases = {
        "BTC": "XBT",
        "DOGE": "XDG",
    }
    return f"PF_{aliases.get(base, base)}{quote}"


def raw_symbols_in_ledger() -> Set[str]:
    symbols: Set[str] = set()

    if not BARS_PATH.exists():
        return symbols

    with BARS_PATH.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not isinstance(row, dict):
                continue

            symbol = str(
                row.get("kraken_symbol")
                or row.get("krakensymbol")
                or row.get("symbol")
                or ""
            ).upper().strip()

            if symbol:
                symbols.add(symbol)

    return symbols


def write_json(payload: Dict[str, Any]) -> None:
    temporary = OUTPUT_JSON_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(OUTPUT_JSON_PATH)


def csv_escape(value: Any) -> str:
    text = str(value if value is not None else "")
    return '"' + text.replace('"', '""') + '"'


def write_csv(rows: List[Dict[str, Any]]) -> None:
    columns = [
        "pair",
        "expected_kraken_futures_symbol",
        "m5_state_present",
        "m5_state",
        "m5_reason",
        "expected_symbol_in_raw_ledger",
        "coverage_status",
    ]

    lines = [
        ",".join(columns),
        *[
            ",".join(csv_escape(row.get(column)) for column in columns)
            for row in rows
        ],
    ]

    temporary = OUTPUT_CSV_PATH.with_suffix(".csv.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT_CSV_PATH)


def build_audit() -> Dict[str, Any]:
    context = load_json(CONTEXT_PATH)
    speed = load_json(SPEED_PATH)

    context_records = context.get("pairs")
    speed_records = speed.get("states")

    if not isinstance(context_records, list):
        raise ValueError("Context payload must contain a list-valued 'pairs'")
    if not isinstance(speed_records, list):
        raise ValueError("Speed payload must contain a list-valued 'states'")

    speed_by_pair: Dict[str, Dict[str, Any]] = {}
    for record in speed_records:
        if not isinstance(record, dict):
            continue
        pair = context_pair(record.get("pair"))
        if pair:
            speed_by_pair[pair] = record

    ledger_symbols = raw_symbols_in_ledger()
    rows: List[Dict[str, Any]] = []

    for record in context_records:
        if not isinstance(record, dict):
            raise ValueError("Context pair records must be JSON objects")

        pair = context_pair(record.get("pair"))
        if not pair or "/" not in pair:
            raise ValueError(f"Invalid context pair: {record.get('pair')!r}")

        expected_symbol = expected_futures_symbol(pair)
        speed_state = speed_by_pair.get(pair)
        expected_in_ledger = expected_symbol in ledger_symbols

        if speed_state is not None:
            coverage_status = "M5_STATE_PRESENT"
        elif expected_in_ledger:
            coverage_status = "LEDGER_PRESENT_STATE_MISSING"
        else:
            coverage_status = "EXPECTED_SYMBOL_ABSENT_FROM_LEDGER"

        rows.append(
            {
                "pair": pair,
                "expected_kraken_futures_symbol": expected_symbol,
                "m5_state_present": speed_state is not None,
                "m5_state": speed_state.get("state") if speed_state else None,
                "m5_reason": speed_state.get("reason") if speed_state else None,
                "expected_symbol_in_raw_ledger": expected_in_ledger,
                "coverage_status": coverage_status,
            }
        )

    counts = Counter(row["coverage_status"] for row in rows)

    payload = {
        "recordtype": "SPEEDCOMPANIONCOVERAGEAUDIT",
        "schema_version": "speed_companion_coverage_audit_v1",
        "generated_at_utc": now_utc(),
        "manual_review_only": True,
        "entry_authority": False,
        "does_not_authorize_trade": True,
        "does_not_change_queue": True,
        "source": {
            "context_file": CONTEXT_PATH.name,
            "speed_state_file": SPEED_PATH.name,
            "raw_bars_file": BARS_PATH.name,
        },
        "health": {
            "context_pair_count": len(rows),
            "speed_state_count": len(speed_records),
            "raw_ledger_symbol_count": len(ledger_symbols),
            "coverage_status_counts": dict(sorted(counts.items())),
        },
        "rows": rows,
    }

    write_csv(rows)
    return payload


def main() -> None:
    payload = build_audit()
    write_json(payload)

    health = payload["health"]
    print(f"Wrote: {OUTPUT_JSON_PATH}")
    print(f"Wrote: {OUTPUT_CSV_PATH}")
    print(f"Context pairs: {health['context_pair_count']}")
    print(f"Raw ledger symbols: {health['raw_ledger_symbol_count']}")

    for status, count in health["coverage_status_counts"].items():
        print(f"{status}: {count}")


if __name__ == "__main__":
    main()
