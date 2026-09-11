"""Shared test helpers for the PRISM clean-room test suite. Not itself a
test module (no Test* classes), so unittest discovery skips it directly."""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_bars(n, amplitude=3.0, period_bars=20, start=START, gap_at=None, gap_delta=timedelta(minutes=30)):
    bars = []
    ts = start
    for t in range(n):
        close = 100.0 + amplitude * math.sin(2 * math.pi * t / period_bars)
        open_ = close - 0.01
        high = max(open_, close) + abs(amplitude) * 0.05 + 0.02
        low = min(open_, close) - abs(amplitude) * 0.05 - 0.02
        bars.append(
            {
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "open": round(open_, 6),
                "high": round(high, 6),
                "low": round(low, 6),
                "close": round(close, 6),
                "volume": 1000.0 + t,
            }
        )
        if gap_at is not None and t == gap_at:
            ts += gap_delta
        else:
            ts += timedelta(minutes=15)
    return bars


def flat_bars(n, price=100.0, start=START):
    """All identical closes -> stddev == 0, used for the stddev-zero edge case."""
    bars = []
    ts = start
    for _ in range(n):
        bars.append(
            {
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "open": price,
                "high": price + 0.01,
                "low": price - 0.01,
                "close": price,
                "volume": 1000.0,
            }
        )
        ts += timedelta(minutes=15)
    return bars
