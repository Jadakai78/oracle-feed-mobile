from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from speed_phase import analyze_completed_candles

ROOT = Path(__file__).resolve().parent
BARS_PATH = ROOT / "training_logs" / "episode_5m_bars_v1.jsonl"
OUTPUT_PATH = ROOT / "speed_companion_state_v1.json"

RECORDTYPE = "SPEEDCOMPANIONSTATE"
SCHEMA_VERSION = "speed_companion_v1"
TIMEFRAME = "5m"
MIN_CANDLES = 15


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def canonical_pair(value: Any) -> Optional[str]:
    symbol = str(value or "").upper().strip()
    if not symbol.startswith("PF_"):
        return None

    compact = symbol[3:]
    if not compact.endswith("USD") or len(compact) <= 3:
        return None

    base = compact[:-3]
    aliases = {
        "XBT": "BTC",
        "XDG": "DOGE",
    }
    base = aliases.get(base, base)

    return f"{base}/USD"


def empty_phase() -> Dict[str, Any]:
    return {
        "direction": "NONE",
        "phase": "NONE",
        "decay_reason": None,
        "impulse_age_bars": None,
        "impulse_size_atr": None,
        "pullback_bars": None,
        "pullback_depth_fraction": None,
        "pullback_volume_vs_impulse": None,
        "reclaim_confirmed": False,
    }


def unavailable_state(pair: str, reason: str) -> Dict[str, Any]:
    return {
        "pair": pair,
        "state": "UNAVAILABLE",
        "reason": reason,
        "input_timeframe": TIMEFRAME,
        "last_completed_candle_utc": None,
        "speed_phase": None,
        "manual_review_only": True,
        "entry_authority": False,
    }


def load_bars() -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    if not BARS_PATH.exists():
        return grouped

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

            pair = canonical_pair(row.get("kraken_symbol") or row.get("symbol"))
            bar_end = parse_utc(row.get("bar_end"))
            if pair is None or bar_end is None:
                continue

            try:
                candle = {
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or 0.0),
                    "_bar_end": bar_end,
                }
            except (KeyError, TypeError, ValueError):
                continue

            values = [candle["open"], candle["high"], candle["low"], candle["close"], candle["volume"]]
            if not all(math.isfinite(value) for value in values):
                continue

            if min(candle["open"], candle["high"], candle["low"], candle["close"]) <= 0:
                continue

            grouped[pair].append(candle)

    for candles in grouped.values():
        candles.sort(key=lambda candle: candle["_bar_end"])

    return grouped


def build_payload() -> Dict[str, Any]:
    grouped = load_bars()
    generated_at = now_utc()
    states: List[Dict[str, Any]] = []

    for pair in sorted(grouped):
        candles_with_time = grouped[pair]
        candles = [
            {
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
            }
            for candle in candles_with_time
        ]

        if len(candles) < MIN_CANDLES:
            states.append(unavailable_state(pair, "INSUFFICIENT_COMPLETED_5M_BARS"))
            continue

        phase = analyze_completed_candles(candles)
        states.append(
            {
                "pair": pair,
                "state": "AVAILABLE",
                "reason": None,
                "input_timeframe": TIMEFRAME,
                "last_completed_candle_utc": candles_with_time[-1]["_bar_end"].isoformat(),
                "speed_phase": phase,
                "manual_review_only": True,
                "entry_authority": False,
            }
        )

    return {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "manual_review_only": True,
        "entry_authority": False,
        "does_not_authorize_trade": True,
        "does_not_change_queue": True,
        "source": {
            "file": str(BARS_PATH.name),
            "recordtype": "EPISODE5MBAR",
            "input_timeframe": TIMEFRAME,
        },
        "health": {
            "state_count": len(states),
            "available_count": sum(state["state"] == "AVAILABLE" for state in states),
            "unavailable_count": sum(state["state"] == "UNAVAILABLE" for state in states),
        },
        "states": states,
    }


def write_payload(payload: Dict[str, Any]) -> None:
    temporary = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(OUTPUT_PATH)


def main() -> None:
    payload = build_payload()
    write_payload(payload)

    health = payload["health"]
    print(f"Speed Companion wrote: {OUTPUT_PATH}")
    print(
        f"States: {health['state_count']} | "
        f"Available: {health['available_count']} | "
        f"Unavailable: {health['unavailable_count']}"
    )


if __name__ == "__main__":
    main()
