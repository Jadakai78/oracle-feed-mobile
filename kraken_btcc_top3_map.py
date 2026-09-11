"""
kraken_btcc_top3_map.py — JHL Holdings LLC

Read-only top-3 map reporter.

Inputs:
- training_logs/kraken_btcc_top3_queue_state.json
- Kraken Futures public chart candles

Map:
- 4H and 1H
- 365 completed candles
- SMA-365 + population standard deviation
- ±1σ, ±2σ, ±3σ zones

Output:
- training_logs/kraken_btcc_top3_map_latest.json
- training_logs/kraken_btcc_top3_map_audit.jsonl

No Pushover. No order placement. No BTCC mutation.
All prices and map values are KRAKEN_FUTURES USD research data.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"

QUEUE_STATE_PATH = LOG_DIR / "kraken_btcc_top3_queue_state.json"
LATEST_PATH = LOG_DIR / "kraken_btcc_top3_map_latest.json"
AUDIT_PATH = LOG_DIR / "kraken_btcc_top3_map_audit.jsonl"

KRAKEN_CHART_BASE_URL = "https://futures.kraken.com/api/charts/v1/trade"
DATA_VENUE = "KRAKEN_FUTURES"
EXECUTION_VENUE = "BTCC"

MAP_PERIOD = 365
TIMEFRAMES = {
    "4H": {"endpoint_resolution": "4h", "seconds": 4 * 60 * 60},
    "1H": {"endpoint_resolution": "1h", "seconds": 60 * 60},
}
REQUEST_TIMEOUT_SECONDS = 15


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def append_audit(payload: Dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str) + "\n")


def fetch_candles(kraken_symbol: str, resolution: str) -> List[Dict[str, Any]]:
    symbol = urllib.parse.quote(kraken_symbol.upper(), safe="")
    url = f"{KRAKEN_CHART_BASE_URL}/{symbol}/{resolution}"

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "JHL-KrakenBTCC-Top3Map/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URL error from {url}: {exc.reason}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON parse error from {url}: {exc}") from exc

    candles = payload.get("candles")
    if not isinstance(candles, list):
        raise RuntimeError(f"No candle list returned from {url}")

    return candles


def completed_closes(
    candles: List[Dict[str, Any]],
    timeframe_seconds: int,
) -> List[Dict[str, Any]]:
    now_ms = int(time.time() * 1000)
    interval_ms = timeframe_seconds * 1000
    completed: List[Dict[str, Any]] = []

    for candle in candles:
        try:
            open_ms = int(candle["time"])
            close = float(candle["close"])
        except (KeyError, TypeError, ValueError):
            continue

        if close <= 0:
            continue

        if open_ms + interval_ms > now_ms:
            continue

        completed.append(
            {
                "time_epoch_ms": open_ms,
                "time_utc": datetime.fromtimestamp(
                    open_ms / 1000,
                    tz=timezone.utc,
                ).isoformat(),
                "close": close,
            }
        )

    return sorted(completed, key=lambda row: row["time_epoch_ms"])


def population_mean(values: List[float]) -> float:
    return sum(values) / len(values)


def population_sigma(values: List[float], mean: float) -> float:
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def zone_for_z(z_score: float) -> str:
    if z_score >= 3:
        return "EXTREME_PREMIUM"
    if z_score >= 2:
        return "PREMIUM"
    if z_score >= 1:
        return "UPPER_VALUE"
    if z_score > -1:
        return "MEAN_NEUTRAL"
    if z_score > -2:
        return "LOWER_VALUE"
    if z_score > -3:
        return "DISCOUNT"
    return "EXTREME_DISCOUNT"


def build_frame_map(
    kraken_symbol: str,
    frame_name: str,
    frame_config: Dict[str, Any],
) -> Dict[str, Any]:
    candles = fetch_candles(
        kraken_symbol,
        frame_config["endpoint_resolution"],
    )
    completed = completed_closes(candles, frame_config["seconds"])

    if len(completed) < MAP_PERIOD:
        return {
            "status": "UNAVAILABLE_INSUFFICIENT_COMPLETED_BARS",
            "required_completed_bars": MAP_PERIOD,
            "available_completed_bars": len(completed),
            "data_venue": DATA_VENUE,
            "execution_venue": EXECUTION_VENUE,
            "timeframe": frame_name,
            "kraken_symbol": kraken_symbol,
        }

    window = completed[-MAP_PERIOD:]
    closes = [row["close"] for row in window]
    basis = population_mean(closes)
    sigma = population_sigma(closes, basis)
    current_close = closes[-1]
    z_score = (current_close - basis) / sigma if sigma > 0 else 0.0

    return {
        "status": "AVAILABLE",
        "timeframe": frame_name,
        "kraken_symbol": kraken_symbol,
        "data_venue": DATA_VENUE,
        "execution_venue": EXECUTION_VENUE,
        "price_basis": "KRAKEN_FUTURES_TRADE_CANDLES_USD",
        "calculation": {
            "period_bars": MAP_PERIOD,
            "mean_type": "SMA",
            "sigma_type": "POPULATION",
            "source_close": "COMPLETED_CANDLE_CLOSE",
        },
        "window": {
            "first_bar_utc": window[0]["time_utc"],
            "last_bar_utc": window[-1]["time_utc"],
            "completed_bar_count": len(window),
        },
        "current_close": current_close,
        "basis_sma_365": basis,
        "sigma_population_365": sigma,
        "upper_1_sigma": basis + sigma,
        "upper_2_sigma": basis + 2 * sigma,
        "upper_3_sigma": basis + 3 * sigma,
        "lower_1_sigma": basis - sigma,
        "lower_2_sigma": basis - 2 * sigma,
        "lower_3_sigma": basis - 3 * sigma,
        "z_score": z_score,
        "location_zone": zone_for_z(z_score),
        "source_endpoint": (
            f"{KRAKEN_CHART_BASE_URL}/"
            f"{kraken_symbol}/{frame_config['endpoint_resolution']}"
        ),
        "source_fetched_at_utc": utc_now_iso(),
    }


def alignment_for(map_4h: Dict[str, Any], map_1h: Dict[str, Any]) -> str:
    if map_4h.get("status") != "AVAILABLE" or map_1h.get("status") != "AVAILABLE":
        return "UNAVAILABLE"

    z_4h = float(map_4h["z_score"])
    z_1h = float(map_1h["z_score"])

    if z_4h >= 1 and z_1h >= 1:
        return "ALIGNED_UPPER_PREMIUM_SIDE"
    if z_4h <= -1 and z_1h <= -1:
        return "ALIGNED_LOWER_DISCOUNT_SIDE"
    if -1 < z_4h < 1 and -1 < z_1h < 1:
        return "ALIGNED_MEAN_NEUTRAL"
    return "TIMEFRAME_CONFLICT"


def main() -> int:
    state = read_json(QUEUE_STATE_PATH, {})
    queue = state.get("queue") if isinstance(state, dict) else None

    result: Dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at_utc": utc_now_iso(),
        "purpose": "TOP3_MAP_DISPLAY_ONLY",
        "data_venue": DATA_VENUE,
        "execution_venue": EXECUTION_VENUE,
        "map_contract": {
            "timeframes": ["4H", "1H"],
            "period_bars": MAP_PERIOD,
            "sigma_type": "POPULATION",
            "bands": ["+1σ", "+2σ", "+3σ", "-1σ", "-2σ", "-3σ"],
            "btcc_execution_disclosure": (
                "Kraken map values are USD research data, not BTCC USDT "
                "execution prices, funding, spread, depth, or liquidation."
            ),
        },
        "candidates": [],
    }

    if not isinstance(queue, list) or not queue:
        result["status"] = "NO_ACTIVE_TOP3_CANDIDATES"
        write_json_atomic(LATEST_PATH, result)
        append_audit(result)
        print("Active top-3 queue: 0")
        print("RESULT: PASS — no map generated because the candidate queue is empty.")
        print(f"Wrote: {LATEST_PATH}")
        return 0

    for candidate in queue[:3]:
        kraken_symbol = str(candidate.get("kraken_symbol") or "").upper()
        btcc_symbol = candidate.get("btcc_symbol")

        if not kraken_symbol:
            row = {
                "btcc_symbol": btcc_symbol,
                "status": "UNAVAILABLE_MISSING_KRAKEN_SYMBOL",
            }
            result["candidates"].append(row)
            continue

        try:
            map_4h = build_frame_map(
                kraken_symbol,
                "4H",
                TIMEFRAMES["4H"],
            )
            map_1h = build_frame_map(
                kraken_symbol,
                "1H",
                TIMEFRAMES["1H"],
            )
            alignment = alignment_for(map_4h, map_1h)

            row = {
                "btcc_symbol": btcc_symbol,
                "kraken_symbol": kraken_symbol,
                "queue_direction": candidate.get("direction"),
                "queue_score_pct": candidate.get("score_pct"),
                "status": "AVAILABLE",
                "alignment": alignment,
                "map_4h": map_4h,
                "map_1h": map_1h,
            }

            if map_4h.get("status") == "AVAILABLE":
                print(
                    f"{btcc_symbol} | 4H {map_4h['location_zone']} "
                    f"{map_4h['z_score']:+.2f}σ"
                )
            if map_1h.get("status") == "AVAILABLE":
                print(
                    f"{btcc_symbol} | 1H {map_1h['location_zone']} "
                    f"{map_1h['z_score']:+.2f}σ"
                )
            print(f"{btcc_symbol} | alignment: {alignment}")

        except Exception as exc:
            row = {
                "btcc_symbol": btcc_symbol,
                "kraken_symbol": kraken_symbol,
                "status": "UNAVAILABLE_FETCH_OR_CALC_ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            }
            print(f"{btcc_symbol} | MAP ERROR: {row['error']}")

        result["candidates"].append(row)

    result["status"] = "MAP_COMPLETE"
    write_json_atomic(LATEST_PATH, result)
    append_audit(result)

    print(f"Wrote: {LATEST_PATH}")
    print(f"Audit: {AUDIT_PATH}")
    print("RESULT: PASS — top-3 map report complete; no alerts or orders were sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
