from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from speed_phase import analyze_completed_candles

ROOT = Path(__file__).resolve().parent

CONTEXT_PATH = ROOT / "oracle_prop_context_v1.json"
BARS_PATH = ROOT / "training_logs" / "episode_5m_bars_kraken_spot_v1.jsonl"
AUDIT_PATH = ROOT / "kraken_spot_context_symbol_audit_v1.json"
OUTPUT_PATH = ROOT / "speed_companion_kraken_spot_state_v1.json"

RECORDTYPE = "SPEEDCOMPANIONSTATE"
SCHEMA_VERSION = "speed_companion_kraken_spot_v1"
TIMEFRAME = "5m"

ATR_PERIOD = 14
MIN_CANDLES = ATR_PERIOD + 1
ANALYSIS_WINDOW_BARS = 30


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return None

    return parsed.astimezone(timezone.utc)


def canonical_pair(value: Any) -> str:
    return str(value or "").upper().strip()


def load_json_object(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")

    return payload


def load_context_pairs() -> List[str]:
    context = load_json_object(CONTEXT_PATH)
    records = context.get("pairs")

    if not isinstance(records, list):
        raise ValueError("Context payload must contain a list-valued 'pairs'")

    pairs: List[str] = []

    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Context pair records must be objects")

        pair = canonical_pair(record.get("pair"))
        if not pair or "/" not in pair:
            raise ValueError(f"Invalid context pair: {record.get('pair')!r}")

        pairs.append(pair)

    if len(pairs) != 49 or len(set(pairs)) != 49:
        raise ValueError(
            "Context universe must contain exactly 49 unique canonical pairs"
        )

    return pairs


def load_audit_reason_by_pair() -> Dict[str, str]:
    audit = load_json_object(AUDIT_PATH)
    rows = audit.get("rows")

    if not isinstance(rows, list):
        raise ValueError("Audit payload must contain a list-valued 'rows'")

    reasons: Dict[str, str] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        pair = canonical_pair(row.get("context_pair"))
        resolution_state = str(
            row.get("resolution_state") or ""
        ).upper().strip()

        if pair and resolution_state != "RESOLVED":
            reasons[pair] = str(
                row.get("reason")
                or "NO_ONLINE_KRAKEN_SPOT_USD_MARKET"
            )

    return reasons


def load_completed_bars() -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

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

            pair = canonical_pair(row.get("pair") or row.get("symbol"))
            bar_end = parse_utc(row.get("bar_end"))

            if not pair or bar_end is None:
                continue

            if str(row.get("source") or "") != "kraken_spot_ohlc":
                continue

            try:
                candle = {
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or 0.0),
                    "_bar_end": bar_end,
                    "_kraken_spot_pair": row.get("kraken_spot_pair"),
                    "_kraken_api_pair_key": row.get("kraken_api_pair_key"),
                    "_kraken_altname": row.get("kraken_altname"),
                    "_kraken_wsname": row.get("kraken_wsname"),
                }
            except (KeyError, TypeError, ValueError):
                continue

            values = [
                candle["open"],
                candle["high"],
                candle["low"],
                candle["close"],
                candle["volume"],
            ]

            if not all(math.isfinite(value) for value in values):
                continue

            if min(
                candle["open"],
                candle["high"],
                candle["low"],
                candle["close"],
            ) <= 0:
                continue

            if candle["high"] < candle["low"] or candle["volume"] < 0:
                continue

            grouped[pair].append(candle)

    for candles in grouped.values():
        candles.sort(key=lambda candle: candle["_bar_end"])

    return grouped


def unavailable_state(pair: str, reason: str) -> Dict[str, Any]:
    return {
        "pair": pair,
        "state": "UNAVAILABLE",
        "reason": reason,
        "input_timeframe": TIMEFRAME,
        "last_completed_candle_utc": None,
        "bar_count": 0,
        "analysis_window_bars": 0,
        "source": "kraken_spot_ohlc",
        "kraken_spot_pair": None,
        "kraken_api_pair_key": None,
        "kraken_altname": None,
        "kraken_wsname": None,
        "speed_phase": None,
        "manual_review_only": True,
        "entry_authority": False,
    }


def available_state(
    pair: str,
    candles_with_time: List[Dict[str, Any]],
) -> Dict[str, Any]:
    recent_with_time = candles_with_time[-ANALYSIS_WINDOW_BARS:]

    candles = [
        {
            "open": candle["open"],
            "high": candle["high"],
            "low": candle["low"],
            "close": candle["close"],
            "volume": candle["volume"],
        }
        for candle in recent_with_time
    ]

    phase = analyze_completed_candles(candles)
    newest = recent_with_time[-1]

    return {
        "pair": pair,
        "state": "AVAILABLE",
        "reason": None,
        "input_timeframe": TIMEFRAME,
        "last_completed_candle_utc": newest["_bar_end"].isoformat(),
        "bar_count": len(candles_with_time),
        "analysis_window_bars": len(recent_with_time),
        "source": "kraken_spot_ohlc",
        "kraken_spot_pair": newest["_kraken_spot_pair"],
        "kraken_api_pair_key": newest["_kraken_api_pair_key"],
        "kraken_altname": newest["_kraken_altname"],
        "kraken_wsname": newest["_kraken_wsname"],
        "speed_phase": phase,
        "manual_review_only": True,
        "entry_authority": False,
    }


def build_payload() -> Dict[str, Any]:
    context_pairs = load_context_pairs()
    unavailable_reasons = load_audit_reason_by_pair()
    bars_by_pair = load_completed_bars()

    states: List[Dict[str, Any]] = []

    for pair in context_pairs:
        candles = bars_by_pair.get(pair, [])

        if pair in unavailable_reasons:
            states.append(unavailable_state(pair, unavailable_reasons[pair]))
            continue

        if len(candles) < MIN_CANDLES:
            states.append(
                unavailable_state(
                    pair,
                    "INSUFFICIENT_COMPLETED_KRAKEN_SPOT_5M_BARS",
                )
            )
            continue

        states.append(available_state(pair, candles))

    available_count = sum(
        state["state"] == "AVAILABLE"
        for state in states
    )
    unavailable_count = len(states) - available_count

    latest_times = [
        parse_utc(state.get("last_completed_candle_utc"))
        for state in states
        if state["state"] == "AVAILABLE"
    ]
    latest_times = [
        value
        for value in latest_times
        if value is not None
    ]

    return {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "manual_review_only": True,
        "entry_authority": False,
        "does_not_authorize_trade": True,
        "does_not_change_queue": True,
        "source": {
            "bars_file": BARS_PATH.name,
            "bars_recordtype": "EPISODE5MBAR",
            "bars_schema_version": "episode5mbar_kraken_spot_v1",
            "symbol_audit_file": AUDIT_PATH.name,
            "context_file": CONTEXT_PATH.name,
            "market_data_source": "kraken_spot_ohlc",
            "input_timeframe": TIMEFRAME,
            "analysis_window_bars": ANALYSIS_WINDOW_BARS,
        },
        "health": {
            "context_pair_count": len(context_pairs),
            "available_count": available_count,
            "unavailable_count": unavailable_count,
            "analysis_window_bars": ANALYSIS_WINDOW_BARS,
            "latest_completed_candle_utc": (
                max(latest_times).isoformat()
                if latest_times
                else None
            ),
        },
        "states": states,
    }


def write_atomic(payload: Dict[str, Any]) -> None:
    temporary = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".tmp")

    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    temporary.replace(OUTPUT_PATH)


def main() -> None:
    payload = build_payload()
    write_atomic(payload)

    health = payload["health"]

    print(f"Wrote: {OUTPUT_PATH}")
    print(
        f"Context pairs: {health['context_pair_count']} | "
        f"Available: {health['available_count']} | "
        f"Unavailable: {health['unavailable_count']} | "
        f"Window: {health['analysis_window_bars']} bars | "
        f"Latest completed: {health['latest_completed_candle_utc']}"
    )


if __name__ == "__main__":
    main()