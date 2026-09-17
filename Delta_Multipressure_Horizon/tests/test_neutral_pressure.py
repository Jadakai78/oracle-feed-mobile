from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT))

from delta_multipressure_horizon import build_multipressure_readout


def make_neutral_candle(index: int) -> dict:
    price = 100.0 + (index * 0.01)

    return {
        "timestamp": (
            datetime(2026, 1, 1, tzinfo=timezone.utc)
            + timedelta(minutes=5 * index)
        ).isoformat().replace("+00:00", "Z"),
        "open": price,
        "high": price + 0.20,
        "low": price - 0.20,
        "close": price,
        "volume": 100.0 + (index % 7) * 10.0,
    }


# Full history is available, but every candle closes exactly at its open.
# No candle-volume directional pressure should be inferred.
candles = [
    make_neutral_candle(index)
    for index in range(390)
]

readout = build_multipressure_readout(
    candles=candles,
    pair="NEUTRAL_PRESSURE_TESTUSD",
    bar_timestamp_utc=candles[-1]["timestamp"],
)

assert readout["data_health"]["state"] == "AVAILABLE"

assert readout["pressure_12"]["state"] == "NEUTRAL"
assert readout["pressure_12"]["signed_pressure"] == 0.0
assert readout["pressure_12"]["imbalance_pct"] == 0.0

assert readout["pressure_100"]["state"] == "NEUTRAL"
assert readout["pressure_100"]["signed_pressure"] == 0.0
assert readout["pressure_100"]["imbalance_pct"] == 0.0

assert readout["pressure_390"]["state"] == "NEUTRAL"
assert readout["pressure_390"]["signed_pressure"] == 0.0
assert readout["pressure_390"]["imbalance_pct"] == 0.0

assert readout["alignment"]["short_vs_medium"] == "NEUTRAL"
assert readout["alignment"]["short_vs_prism_scale"] == "NEUTRAL"
assert readout["alignment"]["medium_vs_prism_scale"] == "NEUTRAL"
assert readout["alignment"]["all_three"] == "ALL_NEUTRAL"

print(json.dumps(readout, indent=2))
print(
    "\nTEST C PASSED: Neutral candle history "
    "is classified without directional bias."
)
