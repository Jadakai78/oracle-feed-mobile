"""
Append-only Eight Gates outcome tracker.

Reads:
  training_logs/eight_gates_brain.jsonl

Appends:
  training_logs/eight_gates_outcomes.jsonl

No orders. Does not alter source observations.
Uses completed Kraken 15-minute OHLC and a 16-bar first-touch horizon.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from trade_diagnostics_v1 import classify

KRAKEN_API = "https://api.kraken.com/0/public"
INTERVAL_MINUTES = 15
HORIZON_BARS = 16
REFRESH_SECONDS = 300

ROOT = Path(__file__).parent
LOG_DIR = ROOT / "training_logs"
SOURCE_LOG = LOG_DIR / "eight_gates_brain.jsonl"
OUTCOME_LOG = LOG_DIR / "eight_gates_outcomes.jsonl"

PAIR_MAP = {
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
    "SOL/USD": "SOLUSD",
    "XRP/USD": "XRPUSD",
    "ADA/USD": "ADAUSD",
    "DOGE/USD": "XDGUSD",
    "LINK/USD": "LINKUSD",
    "AVAX/USD": "AVAXUSD",
    "DOT/USD": "DOTUSD",
    "AAVE/USD": "AAVEUSD",
    "LTC/USD": "XLTCZUSD",
    "MATIC/USD": "MATICUSD",
}


def _n(value: Any) -> Optional[float]:
    try:
        value = float(value)
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_ts(value: Any) -> Optional[datetime]:
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _request(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{KRAKEN_API}{path}?{query}")
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read())
    if payload.get("error"):
        raise RuntimeError("; ".join(payload["error"]))
    return payload.get("result") or {}


def _ohlc(pair: str, since_epoch: int) -> List[List[Any]]:
    kraken_pair = PAIR_MAP.get(pair)
    if not kraken_pair:
        return []

    result = _request("/OHLC", {
        "pair": kraken_pair,
        "interval": INTERVAL_MINUTES,
        "since": max(0, since_epoch),
    })
    key = next((key for key in result if key != "last"), None)
    return list(result.get(key) or []) if key else []


def _source_records() -> List[Dict[str, Any]]:
    if not SOURCE_LOG.exists():
        return []

    records = []
    with SOURCE_LOG.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("record_type") == "lane_observed":
                records.append(record)
    return records


def _resolved_ids() -> set[str]:
    if not OUTCOME_LOG.exists():
        return set()

    ids: set[str] = set()
    with OUTCOME_LOG.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            observation_id = record.get("observation_id")
            if observation_id:
                ids.add(str(observation_id))
    return ids


def _geometry(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    geometry = record.get("geometry") or {}
    zone = geometry.get("entry_zone") or []

    entry = _n(zone[0] if zone else None)
    sl = _n(geometry.get("invalidation"))
    tp = _n(geometry.get("target_1"))
    side = str(record.get("side") or "").upper()

    if side not in {"LONG", "SHORT"} or None in {entry, sl, tp}:
        return None

    if side == "LONG" and not (sl < entry < tp):
        return None
    if side == "SHORT" and not (tp < entry < sl):
        return None

    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0 or reward <= 0:
        return None

    return {
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "room_to_risk": reward / risk,
    }


def _resolve(record: Dict[str, Any], now_epoch: int) -> Optional[Dict[str, Any]]:
    observed_at = _parse_ts(record.get("observed_at"))
    geometry = _geometry(record)

    if observed_at is None or geometry is None:
        outcome = {
            "schema_version": 1,
            "record_type": "lane_resolved",
            "observation_id": record.get("observation_id"),
            "event_key": record.get("observation_id"),
            "pair": record.get("pair"),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "status": "resolved",
            "label": "SKIPPED",
            "reason": "geometry_or_timestamp_invalid",
            "geometry_version": "atr_local_v1",
            "entry_version": "zone_touch_v1",
        }
        outcome["diagnostic"] = classify(outcome)
        return outcome

    start_epoch = int(
        observed_at.timestamp() // (INTERVAL_MINUTES * 60) * (INTERVAL_MINUTES * 60)
    )
    if now_epoch < start_epoch + HORIZON_BARS * INTERVAL_MINUTES * 60:
        return None

    try:
        rows = _ohlc(str(record.get("pair")), start_epoch)
    except Exception as exc:
        print(f"FETCH_WARNING {record.get('pair')}: {type(exc).__name__}: {exc}")
        return None

    candles = [
        row for row in rows
        if len(row) >= 5 and int(float(row[0])) > start_epoch
    ][:HORIZON_BARS]

    if len(candles) < HORIZON_BARS:
        return None

    source_geometry = record.get("geometry") or {}
    zone = source_geometry.get("entry_zone") or []
    if len(zone) != 2:
        return None

    zone_low = min(float(zone[0]), float(zone[1]))
    zone_high = max(float(zone[0]), float(zone[1]))
    fill_price = (zone_low + zone_high) / 2.0

    side = geometry["side"]
    sl = geometry["sl"]
    tp = geometry["tp"]
    risk = abs(fill_price - sl)

    if risk <= 0:
        return None

    base = {
        "schema_version": 1,
        "record_type": "lane_resolved",
        "observation_id": record.get("observation_id"),
        "event_key": record.get("observation_id"),
        "pair": record.get("pair"),
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "source_bar_start": start_epoch,
        "evaluation_bars": HORIZON_BARS,
        "side": side,
        "entry_zone": [zone_low, zone_high],
        "fill_price": round(fill_price, 10),
        "sl": sl,
        "tp": tp,
        "room_to_risk": round(abs(tp - fill_price) / risk, 4),
        "method": "completed_15m_ohlc_zone_touch_first_touch",
        "evaluation_policy": "zone_touch_v1",
        "geometry_version": "atr_local_v1",
        "entry_version": "zone_touch_v1",
    }

    fill_index = None
    mfe_r = 0.0
    mae_r = 0.0

    for index, row in enumerate(candles, start=1):
        timestamp = int(float(row[0]))
        bar_open = float(row[1])
        bar_high = float(row[2])
        bar_low = float(row[3])
        bar_close = float(row[4])

        if fill_index is None:
            if not (bar_low <= zone_high and bar_high >= zone_low):
                continue
            fill_index = index

        if side == "LONG":
            mfe_r = max(mfe_r, (bar_high - fill_price) / risk)
            mae_r = min(mae_r, (bar_low - fill_price) / risk)
            target_hit = bar_high >= tp
            stop_hit = bar_low <= sl
        else:
            mfe_r = max(mfe_r, (fill_price - bar_low) / risk)
            mae_r = min(mae_r, (fill_price - bar_high) / risk)
            target_hit = bar_low <= tp
            stop_hit = bar_high >= sl

        outcome = {
            **base,
            "resolution_bar_start": timestamp,
            "bars_to_resolution": index,
            "fill_status": "FILLED",
            "fill_bar": fill_index,
            "fill_timestamp": datetime.fromtimestamp(
                int(float(candles[fill_index - 1][0])), tz=timezone.utc
            ).isoformat(),
            "bar_open": bar_open,
            "bar_high": bar_high,
            "bar_low": bar_low,
            "bar_close": bar_close,
            "mfe_r": round(mfe_r, 6),
            "mae_r": round(mae_r, 6),
        }

        if target_hit and stop_hit:
            outcome.update({
                "status": "resolved",
                "label": "AMBIGUOUS",
                "first_touch": None,
                "exit_status": "AMBIGUOUS",
                "reason": "ambiguous_target_and_invalidation_same_candle",
                "gross_r": None,
            })
            outcome["diagnostic"] = classify(outcome)
            return outcome

        if target_hit:
            outcome.update({
                "status": "resolved",
                "label": "TP_FIRST",
                "first_touch": "tp",
                "exit_status": "TARGET",
                "reason": "target_after_zone_touch",
                "gross_r": round(abs(tp - fill_price) / risk, 6),
            })
            outcome["diagnostic"] = classify(outcome)
            return outcome

        if stop_hit:
            outcome.update({
                "status": "resolved",
                "label": "SL_FIRST",
                "first_touch": "sl",
                "exit_status": "INVALIDATION",
                "reason": "invalidation_after_zone_touch",
                "gross_r": -1.0,
            })
            outcome["diagnostic"] = classify(outcome)
            return outcome

    if fill_index is None:
        outcome = {
            **base,
            "status": "resolved",
            "label": "EXPIRED",
            "first_touch": None,
            "exit_status": "UNFILLED",
            "fill_status": "UNFILLED",
            "reason": "unfilled_horizon_expired",
            "gross_r": None,
            "mfe_r": None,
            "mae_r": None,
        }
        outcome["diagnostic"] = classify(outcome)
        return outcome

    last = candles[-1]
    outcome = {
        **base,
        "status": "resolved",
        "label": "EXPIRED",
        "first_touch": None,
        "exit_status": "TIMEOUT",
        "fill_status": "FILLED",
        "fill_bar": fill_index,
        "fill_timestamp": datetime.fromtimestamp(
            int(float(candles[fill_index - 1][0])), tz=timezone.utc
        ).isoformat(),
        "resolution_bar_start": int(float(last[0])),
        "bars_to_resolution": HORIZON_BARS,
        "bar_open": float(last[1]),
        "bar_high": float(last[2]),
        "bar_low": float(last[3]),
        "bar_close": float(last[4]),
        "mfe_r": round(mfe_r, 6),
        "mae_r": round(mae_r, 6),
        "reason": "filled_horizon_expired",
        "gross_r": 0.0,
    }
    outcome["diagnostic"] = classify(outcome)
    return outcome

def run_once() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    resolved = _resolved_ids()
    checked = 0
    appended = 0
    pending = 0
    skipped = 0
    now_epoch = int(time.time())

    with OUTCOME_LOG.open("a", encoding="utf-8", newline="\n") as output:
        for record in _source_records():
            observation_id = str(record.get("observation_id") or "")
            if not observation_id or observation_id in resolved:
                continue

            checked += 1
            outcome = _resolve(record, now_epoch)

            if outcome is None:
                pending += 1
                continue

            if outcome.get("label") == "SKIPPED":
                skipped += 1

            output.write(json.dumps(outcome, ensure_ascii=False, separators=(",", ":")) + "\n")
            resolved.add(observation_id)
            appended += 1

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(
        f"[{stamp}] Eight Gates tracker: checked={checked} "
        f"appended={appended} pending={pending} skipped={skipped}"
    )


def main() -> None:
    print(
        "Eight Gates outcome tracker — append-only, "
        f"{INTERVAL_MINUTES}m bars, {HORIZON_BARS}-bar horizon"
    )
    while True:
        try:
            run_once()
        except Exception as exc:
            print(f"TRACKER_ERROR {type(exc).__name__}: {exc}")
        time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nEight Gates tracker stopped.")
