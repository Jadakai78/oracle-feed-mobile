"""Resolve raw ignition behavior from completed Kraken Futures 5m and 15m candles."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"
ARENA_DIR = LOG_DIR / "ignition_arena"
IGNITION_LOG = ARENA_DIR / "ignition_events.jsonl"
SETTLEMENT_LOG = ARENA_DIR / "ignition_settlements.jsonl"
REJECTION_LOG = ARENA_DIR / "settlement_rejections.jsonl"
KRAKEN_CHART_BASE = "https://futures.kraken.com/api/charts/v1/trade"
TIMEFRAMES = {"5m": 300, "15m": 900}
HORIZONS_SECONDS = {"5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "4h": 14400}
REQUEST_TIMEOUT_SECONDS = 15


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def parse_time(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
        if number > 10_000_000_000:
            number /= 1000.0
        if number > 100_000_000:
            return number
    except ValueError:
        pass
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def stable_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "settlement_" + hashlib.sha256(raw).hexdigest()[:20]


def fetch_candles(symbol: str, resolution: str) -> list[dict[str, Any]]:
    url = f"{KRAKEN_CHART_BASE}/{urllib.parse.quote(symbol.upper(), safe='')}/{resolution}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": "JHL-IgnitionOutcomeResolver/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"candle_fetch_error:{type(exc).__name__}:{exc}") from exc
    candles = payload.get("candles")
    if not isinstance(candles, list):
        raise RuntimeError("candle_fetch_error:no_candles")
    return candles


def completed_bars(candles: list[dict[str, Any]], seconds: int) -> list[dict[str, Any]]:
    now_ms = int(time.time() * 1000)
    out = []
    for candle in candles:
        try:
            start_ms = int(candle["time"])
            high, low, close = float(candle["high"]), float(candle["low"]), float(candle["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if start_ms + seconds * 1000 > now_ms or min(high, low, close) <= 0:
            continue
        out.append({"start_epoch": start_ms / 1000.0, "end_epoch": (start_ms / 1000.0) + seconds, "high": high, "low": low, "close": close})
    return sorted(out, key=lambda row: row["end_epoch"])


def behavior(path: list[dict[str, Any]], entry: float, side: str, origin: float, extreme: float) -> dict[str, Any]:
    if not path:
        return {"status": "PENDING"}
    highs, lows = [row["high"] for row in path], [row["low"] for row in path]
    if side == "UP":
        mfe = (max(highs) - entry) / entry * 100
        mae = (min(lows) - entry) / entry * 100
        ret = (path[-1]["close"] - entry) / entry * 100
        origin_status = "HELD" if min(lows) >= origin else "LOST"
        extreme_status = "EXCEEDED" if max(highs) > extreme else "NOT_EXCEEDED"
    else:
        mfe = (entry - min(lows)) / entry * 100
        mae = (entry - max(highs)) / entry * 100
        ret = (entry - path[-1]["close"]) / entry * 100
        origin_status = "HELD" if max(highs) <= origin else "LOST"
        extreme_status = "EXCEEDED" if min(lows) < extreme else "NOT_EXCEEDED"
    return {"status": "COMPLETE", "bar_count": len(path), "directional_return_pct": round(ret, 8), "mfe_pct": round(mfe, 8), "mae_pct": round(mae, 8), "origin_status": origin_status, "extreme_status": extreme_status, "final_close": path[-1]["close"], "final_bar_end_utc": datetime.fromtimestamp(path[-1]["end_epoch"], tz=timezone.utc).isoformat()}


def structural_context(path: list[dict[str, Any]], entry: float, side: str, origin: float, extreme: float) -> dict[str, Any]:
    base = behavior(path, entry, side, origin, extreme)
    if base.get("status") != "COMPLETE":
        return base
    if base["origin_status"] == "LOST":
        label = "FAILED"
    elif base["extreme_status"] == "EXCEEDED":
        label = "BUILDING"
    else:
        label = "HOLDING"
    base["structural_label"] = label
    return base


def existing_pairs() -> set[tuple[str, str]]:
    return {(str(row.get("ignition_id")), str(row.get("settlement_version"))) for row in read_jsonl(SETTLEMENT_LOG)}


def settle() -> tuple[int, int, int]:
    known = existing_pairs()
    created = pending = rejected = 0
    cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for ignition in read_jsonl(IGNITION_LOG):
        ignition_id = str(ignition.get("ignition_id") or "")
        if not ignition_id or (ignition_id, "ignition_settlement_v1") in known:
            continue
        symbol = str(ignition.get("kraken_symbol") or "").upper()
        side = str(ignition.get("direction") or "").upper()
        entry = finite(ignition.get("admission_price"))
        origin = finite(ignition.get("ignition_origin_price")) or entry
        extreme = finite(ignition.get("initial_extreme_price")) or entry
        start = parse_time(ignition.get("source_event_timestamp_utc") or ignition.get("observed_at_utc"))
        if not symbol or side not in {"UP", "DOWN"} or entry is None or origin is None or extreme is None or start is None:
            append(REJECTION_LOG, {"record_type": "SETTLEMENT_REJECTED", "ignition_id": ignition_id, "reason": "INVALID_IGNITION_IDENTITY_OR_PRICE", "written_at_utc": now_iso()})
            rejected += 1
            continue
        try:
            bars5 = cache.setdefault((symbol, "5m"), completed_bars(fetch_candles(symbol, "5m"), TIMEFRAMES["5m"]))
            bars15 = cache.setdefault((symbol, "15m"), completed_bars(fetch_candles(symbol, "15m"), TIMEFRAMES["15m"]))
        except RuntimeError as exc:
            append(REJECTION_LOG, {"record_type": "SETTLEMENT_REJECTED", "ignition_id": ignition_id, "reason": str(exc), "written_at_utc": now_iso()})
            rejected += 1
            continue
        outcomes = {}
        all_complete = True
        for name, seconds in HORIZONS_SECONDS.items():
            finish = start + seconds
            path = [bar for bar in bars5 if start < bar["end_epoch"] <= finish]
            if not bars5 or max(bar["end_epoch"] for bar in bars5) < finish:
                outcomes[name] = {"status": "PENDING", "required_until_utc": datetime.fromtimestamp(finish, tz=timezone.utc).isoformat()}
                all_complete = False
            else:
                outcomes[name] = behavior(path, entry, side, origin, extreme)
        structural_finish = start + 3600
        structural_path = [bar for bar in bars15 if start < bar["end_epoch"] <= structural_finish]
        if not bars15 or max(bar["end_epoch"] for bar in bars15) < structural_finish:
            structure = {"status": "PENDING", "required_until_utc": datetime.fromtimestamp(structural_finish, tz=timezone.utc).isoformat()}
            all_complete = False
        else:
            structure = structural_context(structural_path, entry, side, origin, extreme)
        record = {"record_type": "IGNITION_SETTLEMENT", "settlement_version": "ignition_settlement_v1", "settlement_id": stable_id({"ignition_id": ignition_id, "version": "ignition_settlement_v1"}), "ignition_id": ignition_id, "kraken_symbol": symbol, "btcc_symbol": ignition.get("btcc_symbol"), "direction": side, "entry_reference_price": entry, "ignition_origin_price": origin, "initial_extreme_price": extreme, "ignition_timestamp_utc": ignition.get("source_event_timestamp_utc"), "status": "COMPLETE" if all_complete else "PENDING", "outcomes_5m_primary": outcomes, "context_15m_secondary": structure, "source": "KRAKEN_FUTURES_COMPLETED_CANDLES", "orders_enabled": False, "written_at_utc": now_iso()}
        append(SETTLEMENT_LOG, record)
        created += 1
        if not all_complete:
            pending += 1
    return created, pending, rejected


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only ignition outcome resolver. No orders.")
    parser.parse_args()
    created, pending, rejected = settle()
    print(f"Settlement records written: {created}")
    print(f"Pending horizon completion: {pending}")
    print(f"Rejections: {rejected}")
    print(f"Settlement log: {SETTLEMENT_LOG}")
    print("RESULT: PASS — completed Kraken candles evaluated; source logs, queue, alerts, and orders unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
