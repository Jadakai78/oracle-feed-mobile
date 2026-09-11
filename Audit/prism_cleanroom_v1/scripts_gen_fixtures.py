"""Dev-only fixture generator. Not part of the required module list; produces
deterministic synthetic fixtures/*.json for the clean-room test suite. Safe
to delete after fixtures are generated; kept here for reproducibility."""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_bars(n, amplitude_fn, base=100.0, period_bars=20, gap_at=None):
    bars = []
    ts = START
    for t in range(n):
        amp = amplitude_fn(t)
        close = base + amp * math.sin(2 * math.pi * t / period_bars)
        open_ = close - 0.01
        high = close + abs(amp) * 0.05 + 0.02
        low = close - abs(amp) * 0.05 - 0.02
        low = min(low, open_, close) - 0.01
        high = max(high, open_, close) + 0.01
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
            ts += timedelta(minutes=30)
        else:
            ts += timedelta(minutes=15)
    return bars


def write_fixture(name, pair, bars):
    payload = {"pair": pair, "timeframe": "15m", "bars": bars}
    (FIXTURES / name).write_text(json.dumps(payload, indent=2))
    print(f"wrote {name}: {len(bars)} bars")


def expanding_amp(t):
    return 0.5 + (t / 389) * 8.0


def contracting_amp(t):
    return 8.5 - (t / 389) * 8.0


def elevated_amp(t):
    # increases overall, but dips over the final window shift so current
    # width < immediately preceding prior width while staying high overall.
    if t <= 384:
        return 0.5 + (t / 384) * 8.0
    # tail dip for bars 385..389 (the last 5 bars entering the newest window)
    return 3.0


def neutral_amp(t):
    return 3.0 + 0.3 * math.sin(2 * math.pi * t / 130)


if __name__ == "__main__":
    write_fixture("prism_001_valid.json", "SOL/USD", make_bars(390, elevated_amp))
    write_fixture("prism_007_valid.json", "SOL/USD", make_bars(390, expanding_amp))
    write_fixture("prism_008_valid.json", "BTC/USD", make_bars(390, contracting_amp))
    write_fixture("prism_009_valid.json", "ETH/USD", make_bars(390, neutral_amp))
    write_fixture("prism_043_insufficient_history.json", "SOL/USD", make_bars(364, neutral_amp))
    write_fixture("prism_044_missing_bar.json", "SOL/USD", make_bars(390, neutral_amp, gap_at=200))
