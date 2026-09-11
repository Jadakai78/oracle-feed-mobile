"""
PRISM v1 deterministic offline fixture generator.

Reads PRISM YAML manifests and creates canonical 15-minute OHLCV fixtures.
No network reads, alerts, orders, queues, or manifest writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent
MANIFEST_DIR = ROOT / "manifests"
FIXTURE_DIR = ROOT / "fixtures"
INTERVAL_SECONDS = 900
CANONICALIZATION = "prism.ohlcv.canonical.v1"


def parse_utc(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError("start_timestamp_must_end_in_Z")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("start_timestamp_must_be_UTC")
    return parsed


def utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def clamp_positive(value: float, minimum: float) -> float:
    return max(minimum, value)


def profile_drift(profile: str, direction: str, index: int, total: int, rng: random.Random) -> float:
    progress = (index + 1) / max(total, 1)
    sign = 1.0 if direction == "bullish" else -1.0 if direction == "bearish" else 0.0

    if "compression" in profile:
        return sign * 0.015 * progress + rng.uniform(-0.040, 0.040)
    if "breakout" in profile:
        return sign * (0.060 + 0.180 * progress) + rng.uniform(-0.035, 0.035)
    if "stair_step" in profile:
        step = 0.095 if (index % 3) != 2 else -0.030
        return sign * step + rng.uniform(-0.020, 0.020)
    if "range" in profile or "balanced" in profile:
        return math.sin(index * 0.8) * 0.050 + rng.uniform(-0.035, 0.035)
    if "truncated" in profile or "unavailable" in profile:
        return rng.uniform(-0.030, 0.030)

    return sign * 0.035 + rng.uniform(-0.050, 0.050)


def generate_bars(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    timing = manifest["timing"]
    generation = manifest["generation"]
    completed_bars = timing["completed_bars"]
    interval = timing["bar_interval_seconds"]

    if interval != INTERVAL_SECONDS:
        raise ValueError(f"unsupported_interval:{interval}")
    if timing["as_of_bar_index"] != completed_bars - 1:
        raise ValueError("as_of_bar_index_must_equal_completed_bars_minus_one")
    if generation["canonicalization"] != CANONICALIZATION:
        raise ValueError("unsupported_canonicalization")

    segments = [
        generation["background"],
        generation["previous_segment"],
        generation["current_segment"],
    ]
    if sum(segment["bars"] for segment in segments) != completed_bars:
        raise ValueError("segment_bar_total_must_equal_completed_bars")

    baseline = generation["baseline"]
    price = float(baseline["price"])
    true_range = float(baseline["true_range"])
    baseline_volume = float(baseline["volume"])
    if price <= 0 or true_range <= 0 or baseline_volume < 0:
        raise ValueError("invalid_baseline")

    rng = random.Random(manifest["seed"])
    start = parse_utc(timing["start_timestamp"])
    bars: list[dict[str, Any]] = []
    global_index = 0

    for segment in segments:
        for local_index in range(segment["bars"]):
            open_price = price
            drift_units = profile_drift(
                segment["profile"],
                segment["direction"],
                local_index,
                segment["bars"],
                rng,
            )
            is_compression = "compression" in segment["profile"]
            movement_scale = 0.35 if is_compression else 1.0
            wick_scale = 0.35 if is_compression else 1.0

            close_price = clamp_positive(
                open_price + drift_units * true_range * movement_scale,
                0.00000001,
            )

            wick_up = true_range * (0.12 + rng.random() * 0.28) * wick_scale
            wick_down = true_range * (0.12 + rng.random() * 0.28) * wick_scale
            high_price = max(open_price, close_price) + wick_up
            low_price = clamp_positive(min(open_price, close_price) - wick_down, 0.00000001)

            if "compression" in segment["profile"]:
                volume_factor = 0.55 + 0.12 * rng.random()
            elif "breakout" in segment["profile"]:
                volume_factor = 1.65 + 0.65 * rng.random()
            elif "stair_step" in segment["profile"]:
                volume_factor = 1.10 + 0.30 * rng.random()
            else:
                volume_factor = 0.85 + 0.35 * rng.random()

            volume = max(0.0, baseline_volume * volume_factor)
            timestamp = start + timedelta(seconds=interval * global_index)

            bars.append(
                {
                    "timestamp": utc_z(timestamp),
                    "open": round(open_price, 8),
                    "high": round(high_price, 8),
                    "low": round(low_price, 8),
                    "close": round(close_price, 8),
                    "volume": round(volume, 8),
                }
            )

            price = close_price
            global_index += 1

    validate_bars(bars, completed_bars, interval, start)

    if manifest["kind"] == "missing_bar":
        missing_index = completed_bars // 2
        bars.pop(missing_index)

    return bars


def validate_bars(
    bars: list[dict[str, Any]],
    completed_bars: int,
    interval: int,
    start: datetime,
) -> None:
    if len(bars) != completed_bars:
        raise ValueError(f"wrong_bar_count:{len(bars)}")

    previous_timestamp: datetime | None = None
    total_volume = 0.0

    for index, bar in enumerate(bars):
        timestamp = parse_utc(bar["timestamp"])
        expected_timestamp = start + timedelta(seconds=interval * index)

        if timestamp != expected_timestamp:
            raise ValueError(f"timestamp_misaligned_at_index:{index}")
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise ValueError(f"timestamp_non_monotonic_at_index:{index}")

        open_price = bar["open"]
        high_price = bar["high"]
        low_price = bar["low"]
        close_price = bar["close"]
        volume = bar["volume"]

        if not (low_price <= min(open_price, close_price) <= max(open_price, close_price) <= high_price):
            raise ValueError(f"invalid_ohlc_at_index:{index}")
        if volume < 0:
            raise ValueError(f"invalid_volume_at_index:{index}")

        total_volume += volume
        previous_timestamp = timestamp

    if total_volume <= 0:
        raise ValueError("zero_total_volume")


def fixture_payload(manifest: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "recordtype": "PRISMOHLCVFIXTURE",
        "schema_version": "prism.ohlcv.fixture.v1",
        "canonicalization": CANONICALIZATION,
        "fixture_id": manifest["id"],
        "instrument": manifest["instrument"],
        "market_source": manifest["market_source"],
        "timeframe": manifest["timeframe"],
        "bar_interval_seconds": manifest["timing"]["bar_interval_seconds"],
        "completed_bars": manifest["timing"]["completed_bars"],
        "as_of_bar_index": manifest["timing"]["as_of_bar_index"],
        "bars": bars,
    }


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"manifest_not_object:{path.name}")
    return value


def generate_one(path: Path) -> tuple[str, str, Path]:
    manifest = load_manifest(path)
    bars = generate_bars(manifest)
    payload = fixture_payload(manifest, bars)
    digest = fingerprint(payload)

    destination = FIXTURE_DIR / f"{manifest['id']}.ohlcv.json"
    destination.write_bytes(canonical_bytes(payload))

    return manifest["id"], digest, destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", action="append", help="Manifest ID or YAML filename; repeatable.")
    args = parser.parse_args()

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    paths = sorted(MANIFEST_DIR.glob("PRISM-*.yaml"))

    if args.manifest:
        requested = set(args.manifest)
        paths = [
            path for path in paths
            if path.name in requested or path.stem in requested
        ]

    if not paths:
        raise SystemExit("no_manifests_selected")

    for path in paths:
        fixture_id, digest, destination = generate_one(path)
        print(f"{fixture_id} | sha256={digest} | {destination.as_posix()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
