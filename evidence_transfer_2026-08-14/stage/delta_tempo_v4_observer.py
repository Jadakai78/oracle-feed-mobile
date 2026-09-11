from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = Path(r"C:\Users\OneDrive\Desktop\jhl_v2\jhl_v2gimba")
INPUT_NAME = "ltf_shadow_5m_v3.jsonl"
OUTPUT_NAME = "delta_tempo_v4_observations.jsonl"
POLL_SECONDS = 15
EPSILON = 1e-12


def parse_iso(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_jsonl(path):
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def output_keys(path):
    return {
        row.get("source_event_key")
        for row in read_jsonl(path)
        if row.get("record_type") == "delta_tempo_v4_observation"
        and row.get("source_event_key")
    }


def number(value):
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def direction(delta):
    if delta is None:
        return "MISSING"
    if delta > 0:
        return "UP"
    if delta < 0:
        return "DOWN"
    return "FLAT"


def lifecycle(current, prior, flat_tolerance):
    if current is None:
        return "SPEED_MISSING"
    if prior is None:
        return "SPEED_INITIALIZED"
    if prior <= EPSILON:
        return "SPEED_STARTED" if current > EPSILON else "SPEED_FLAT"
    relative_change = (current - prior) / prior
    if relative_change > flat_tolerance:
        return "SPEED_INCREASING"
    if relative_change < -flat_tolerance:
        return "SPEED_DECREASING"
    return "SPEED_FLAT"


def observation(source, prior_by_pair, max_lag_seconds, flat_tolerance):
    pair = source.get("pair")
    bar = source.get("bar_5m") or {}
    flow = source.get("classified_flow_5m") or {}
    source_key = source.get("event_key")
    bar_end = number(bar.get("bar_end"))
    recorded_at = parse_iso(source.get("recorded_at"))

    ready = flow.get("ready") is True
    volume = number(bar.get("volume"))
    delta = number(flow.get("delta"))
    buy_volume = number(flow.get("buy_volume"))
    sell_volume = number(flow.get("sell_volume"))

    speed_available = bool(ready and volume is not None and volume > EPSILON and delta is not None)
    speed_score = abs(delta) / volume if speed_available else None
    delta_per_minute = delta / 5.0 if delta is not None else None
    volume_per_minute = volume / 5.0 if volume is not None else None

    prior = prior_by_pair.get(pair)
    prior_speed = prior.get("speed_score") if prior else None
    prior_direction = prior.get("direction") if prior else None
    ratio = speed_score / prior_speed if speed_score is not None and prior_speed and prior_speed > EPSILON else None
    change = speed_score - prior_speed if speed_score is not None and prior_speed is not None else None
    change_pct = (100.0 * change / prior_speed) if change is not None and prior_speed and prior_speed > EPSILON else None

    lag_seconds = None
    if recorded_at is not None and bar_end is not None:
        lag_seconds = recorded_at.timestamp() - bar_end
    timely = bool(speed_available and lag_seconds is not None and 0 <= lag_seconds <= max_lag_seconds)

    now = datetime.now(timezone.utc).isoformat()
    record = {
        "schema_version": 4,
        "record_type": "delta_tempo_v4_observation",
        "observed_at": now,
        "source_event_key": source_key,
        "source_schema_version": source.get("schema_version"),
        "source_recorded_at": source.get("recorded_at"),
        "pair": pair,
        "bar_timeframe": bar.get("timeframe"),
        "bar_start": bar.get("bar_start"),
        "bar_end": bar.get("bar_end"),
        "close": bar.get("close"),
        "volume": volume,
        "trade_count": bar.get("trade_count"),
        "flow_ready": ready,
        "flow_reason": flow.get("reason"),
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "delta": delta,
        "delta_direction": direction(delta),
        "native_speed_method": "abs_delta_divided_by_completed_5m_volume",
        "speed_score": speed_score,
        "delta_per_minute": delta_per_minute,
        "volume_per_minute": volume_per_minute,
        "prior_speed_score": prior_speed,
        "speed_change_absolute": change,
        "speed_change_ratio": ratio,
        "speed_change_pct": change_pct,
        "speed_lifecycle": lifecycle(speed_score, prior_speed, flat_tolerance),
        "prior_delta_direction": prior_direction,
        "direction_reversal": bool(prior_direction in {"UP", "DOWN"} and direction(delta) in {"UP", "DOWN"} and prior_direction != direction(delta)),
        "descriptive_speed_at_least_0_20": speed_score is not None and speed_score >= 0.20,
        "descriptive_speed_increase_at_least_20pct": ratio is not None and ratio >= 1.20,
        "measurement_lag_seconds": lag_seconds,
        "max_permitted_lag_seconds": max_lag_seconds,
        "speed_available": speed_available,
        "timely_for_next_bar": timely,
        "eligible_for_paper_entry": timely,
        "orders_enabled": False,
        "notes": "Read-only observer. Lifecycle labels are descriptive measurements, not trade-quality labels. No orders are created.",
    }
    if speed_available:
        prior_by_pair[pair] = {"speed_score": speed_score, "direction": direction(delta)}
    return record


def process(input_path, output_path, max_lag_seconds, flat_tolerance):
    rows = [
        row for row in read_jsonl(input_path)
        if row.get("record_type") == "completed_5m_shadow_bar" and row.get("event_key") and row.get("pair")
    ]
    rows.sort(key=lambda row: (row.get("bar_5m") or {}).get("bar_end", 0))
    existing = output_keys(output_path)
    prior_by_pair = defaultdict(dict)
    new_rows = []

    for row in rows:
        result = observation(row, prior_by_pair, max_lag_seconds, flat_tolerance)
        if row["event_key"] not in existing:
            new_rows.append(result)

    if new_rows:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as handle:
            for row in new_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows), len(new_rows)


def main():
    parser = argparse.ArgumentParser(description="Read-only Delta Tempo v4 lifecycle observer.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--poll-seconds", type=int, default=POLL_SECONDS)
    parser.add_argument("--max-lag-seconds", type=float, default=30.0)
    parser.add_argument("--flat-tolerance", type=float, default=0.01)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    input_path = args.root / "training_logs" / INPUT_NAME
    output_path = args.root / "training_logs" / OUTPUT_NAME
    print("Delta Tempo v4 observer: read-only")
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print("Orders: disabled")
    print("Speed: abs(completed 5m delta) / completed 5m volume")
    print("Ctrl+C stops observer only.")

    while True:
        try:
            total, written = process(input_path, output_path, args.max_lag_seconds, args.flat_tolerance)
            stamp = datetime.now().strftime("%H:%M:%S")
            print(f"{stamp} source_records={total} new_observations={written}")
        except Exception as exc:
            print(f"{datetime.now().strftime('%H:%M:%S')} error:{type(exc).__name__}: {exc}")
        if args.once:
            break
        time.sleep(max(1, args.poll_seconds))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDelta Tempo v4 observer stopped.")
