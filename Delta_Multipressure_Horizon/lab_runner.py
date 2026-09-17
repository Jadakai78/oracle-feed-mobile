from datetime import datetime, timedelta, timezone
import json

from delta_multipressure_horizon import build_multipressure_readout


def make_candle(index: int) -> dict:
    open_price = 100.0 + (index * 0.02)
    close_price = open_price + (
        0.08 if index % 4 != 0 else -0.03
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
        "volume": 100.0 + (index % 11) * 10.0,
    }


candles = [make_candle(index) for index in range(450)]

readout = build_multipressure_readout(
    candles=candles,
    pair="LABTESTUSD",
    bar_timestamp_utc=candles[-1]["timestamp"],
)

assert readout["data_health"]["state"] == "AVAILABLE"
assert readout["pressure_12"]["state"] != "UNAVAILABLE"
assert readout["pressure_100"]["state"] != "UNAVAILABLE"
assert readout["pressure_390"]["state"] != "UNAVAILABLE"

print(json.dumps(readout, indent=2))
