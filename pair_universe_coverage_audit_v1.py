import csv
from datetime import datetime, timezone

from pair_universe import MarketDataSource, PROP_SYMBOLS


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def main():
    source = MarketDataSource()
    rows = []

    for symbol in PROP_SYMBOLS:
        checked_at = utc_now()

        try:
            candles = source.fetch_5m_candles(symbol, min_candles=60)
        except Exception as exc:
            candles = None
            error = str(exc)
        else:
            error = None

        if not candles:
            rows.append(
                {
                    "symbol": symbol,
                    "status": "UNAVAILABLE",
                    "bar_count": 0,
                    "first_close": None,
                    "last_close": None,
                    "last_volume": None,
                    "checked_at_utc": checked_at,
                    "error": error or "No Kraken USD 5m candle response.",
                }
            )
            continue

        rows.append(
            {
                "symbol": symbol,
                "status": "AVAILABLE",
                "bar_count": len(candles),
                "first_close": candles[0]["close"],
                "last_close": candles[-1]["close"],
                "last_volume": candles[-1]["volume"],
                "checked_at_utc": checked_at,
                "error": "",
            }
        )

    rows.sort(key=lambda row: (row["status"] != "AVAILABLE", row["symbol"]))

    path = "pair_universe_coverage_audit_v1.csv"
    fields = [
        "symbol",
        "status",
        "bar_count",
        "first_close",
        "last_close",
        "last_volume",
        "checked_at_utc",
        "error",
    ]

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    available = [row for row in rows if row["status"] == "AVAILABLE"]
    unavailable = [row for row in rows if row["status"] != "AVAILABLE"]

    print("=" * 72)
    print("49-PAIR KRAKEN 5M COVERAGE AUDIT")
    print("=" * 72)
    print(f"Configured symbols: {len(PROP_SYMBOLS)}")
    print(f"Available symbols:  {len(available)}")
    print(f"Unavailable:        {len(unavailable)}")
    print()

    for row in rows:
        print(
            f"{row['symbol']:10} "
            f"{row['status']:12} "
            f"bars={row['bar_count']:3} "
            f"last_close={row['last_close']} "
            f"{row['error']}"
        )

    print()
    print(f"Wrote: {path}")


if __name__ == "__main__":
    main()
