from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT))

from delta_multipressure_horizon import build_multipressure_readout


def make_candle(index: int) -> dict:
    open_price = 100.0 + (index * 0.01)
    close_price = open_price + (
        0.20 if index % 3 != 0 else -0.10
    )

    return {
        "timestamp": (
            datetime(2026, 1, 1, tzinfo=timezone.utc)
            + timedelta(minutes=5 * index)
        ).isoformat().replace("+00:00", "Z"),
        "open": open_price,
        "high": max(open_price, close_price) + 0.05,
        "low": min(open_price, close_price) - 0.05,
        "close": close_price,
        "volume": 100.0 + (index % 5) * 10.0,
    }


# Exactly 100 completed bars:
# 12 and 100 horizons are valid; the 390 horizon is not.
candles = [make_candle(index) for index in range(100)]

readout = build_multipressure_readout(
    candles=candles,
    pair="INSUFFICIENT_HISTORY_TESTUSD",
    bar_timestamp_utc=candles[-1]["timestamp"],
)

assert readout["data_health"]["state"] == "UNAVAILABLE"
assert (
    "INSUFFICIENT_COMPLETED_BARS_FOR_390"
    in readout["data_health"]["reason_codes"]
)

assert readout["pressure_12"]["state"] != "UNAVAILABLE"
assert readout["pressure_12"]["completed_bars"] == 12

assert readout["pressure_100"]["state"] != "UNAVAILABLE"
assert readout["pressure_100"]["completed_bars"] == 100

assert readout["pressure_390"]["state"] == "UNAVAILABLE"
assert readout["pressure_390"]["completed_bars"] == 100
assert (
    readout["pressure_390"]["reason"]
    == "INSUFFICIENT_COMPLETED_BARS"
)

assert readout["alignment"]["short_vs_medium"] in {
    "ALIGNED",
    "CONFLICT",
    "NEUTRAL",
}

assert readout["alignment"]["short_vs_prism_scale"] == "UNAVAILABLE"
assert readout["alignment"]["medium_vs_prism_scale"] == "UNAVAILABLE"
assert readout["alignment"]["all_three"] == "UNAVAILABLE"

print(json.dumps(readout, indent=2))
print(
    "\nTEST B PASSED: Incomplete 390-bar history "
    "is correctly withheld."
)
