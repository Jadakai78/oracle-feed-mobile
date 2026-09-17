from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT))

from delta_multipressure_horizon import build_multipressure_readout


def make_candle(
    index: int,
    direction: str,
) -> dict:
    open_price = 100.0

    if direction == "BUY":
        close_price = 100.80
    elif direction == "SELL":
        close_price = 99.20
    else:
        close_price = 100.00

    return {
        "timestamp": (
            datetime(2026, 1, 1, tzinfo=timezone.utc)
            + timedelta(minutes=5 * index)
        ).isoformat().replace("+00:00", "Z"),
        "open": open_price,
        "high": max(open_price, close_price) + 0.10,
        "low": min(open_price, close_price) - 0.10,
        "close": close_price,
        "volume": 100.0,
    }


# First 290 candles establish the slow seller regime.
# Final 100 candles establish buyer pressure across both
# the immediate 12-bar and intermediate 100-bar horizons.
candles = [
    make_candle(index, "SELL")
    for index in range(290)
] + [
    make_candle(index, "BUY")
    for index in range(290, 390)
]

readout = build_multipressure_readout(
    candles=candles,
    pair="MEDIUM_TRANSITION_TESTUSD",
    bar_timestamp_utc=candles[-1]["timestamp"],
)

assert readout["data_health"]["state"] == "AVAILABLE"

assert readout["pressure_12"]["state"] == "BUYER_DOMINANT"
assert readout["pressure_100"]["state"] == "BUYER_DOMINANT"
assert readout["pressure_390"]["state"] == "SELLER_DOMINANT"

assert readout["alignment"]["short_vs_medium"] == "ALIGNED"
assert readout["alignment"]["short_vs_prism_scale"] == "CONFLICT"
assert readout["alignment"]["medium_vs_prism_scale"] == "CONFLICT"

assert readout["alignment"]["all_three"] == "MEDIUM_TERM_BULLISH_TRANSITION"

print(json.dumps(readout, indent=2))
print(
    "\nTEST D PASSED: 12/100 bullish transition "
    "against seller-dominant 390 regime classified correctly."
)
