"""
kraken_futures_data_smoke_test.py — JHL Holdings LLC
One-shot public-data validation for Kraken Futures research inputs.

No keys. No account calls. No orders. No BTCC mutations.
Run: py -3.14 .\kraken_futures_data_smoke_test.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import kraken_futures_market_data as kraken

LOG_DIR = "training_logs"


def _write_json(path: str, payload: Any) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def _unavailable(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.startswith("UNAVAILABLE")
    )


def main() -> int:
    failures = []
    report = {
        "schema_version": "1.0",
        "collection_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "data_venue": "KRAKEN_FUTURES",
        "execution_venue": "BTCC",
        "purpose": "RESEARCH_ONLY",
        "btcc_market_data_claim": "NONE",
    }

    try:
        contracts = kraken.get_active_linear_usd_perpetuals()
    except Exception as exc:
        print(f"FAIL: instrument discovery: {exc}")
        return 1

    print(f"Active Kraken linear perpetuals: {len(contracts)}")
    if not contracts:
        print("FAIL: no active Kraken linear perpetuals returned")
        return 1

    preferred = next(
        (row for row in contracts if row["canonical_symbol"] == "BTCUSDT"),
        contracts[0],
    )
    symbol = preferred["symbol"]
    print(f"Sample Kraken Futures symbol: {symbol}")
    print(f"Canonical research match: {preferred['canonical_symbol']}")

    try:
        ticker = kraken.get_ticker(symbol)
        candles_5m = kraken.get_completed_ohlc(symbol, 5, 30)
        candles_15m = kraken.get_completed_ohlc(symbol, 15, 20)
        book = kraken.get_orderbook_top(symbol)
        funding = kraken.get_funding_history(symbol)
    except Exception as exc:
        print(f"FAIL: data retrieval: {exc}")
        return 1

    checks = {
        "ticker_last_price": ticker.get("last_price"),
        "ticker_mark_price": ticker.get("mark_price"),
        "orderbook_best_bid": book.get("best_bid"),
        "orderbook_best_ask": book.get("best_ask"),
        "candles_5m_count": len(candles_5m),
        "candles_15m_count": len(candles_15m),
        "funding_history_count": len(funding),
    }

    for field in (
        "ticker_last_price",
        "ticker_mark_price",
        "orderbook_best_bid",
        "orderbook_best_ask",
    ):
        if _unavailable(checks[field]):
            failures.append(f"{field} unavailable: {checks[field]}")

    for field in (
        "candles_5m_count",
        "candles_15m_count",
        "funding_history_count",
    ):
        if checks[field] < 1:
            failures.append(f"{field} returned zero usable rows")

    report.update(
        {
            "sample_symbol": symbol,
            "canonical_symbol": preferred["canonical_symbol"],
            "active_contract_count": len(contracts),
            "checks": checks,
            "ticker": ticker,
            "orderbook_top": book,
            "completed_5m_candles_sample": candles_5m[-3:],
            "completed_15m_candles_sample": candles_15m[-3:],
            "funding_history_sample": funding[:10],
            "result": "PASS" if not failures else "FAIL",
            "failures": failures,
        }
    )

    output_path = os.path.join(LOG_DIR, "kraken_futures_data_smoke_test.json")
    _write_json(output_path, report)

    print(f"5m completed candles: {len(candles_5m)}")
    print(f"15m completed candles: {len(candles_15m)}")
    print(f"Funding observations: {len(funding)}")
    print(f"Wrote: {output_path}")

    if failures:
        print("RESULT: FAIL")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("RESULT: PASS — Kraken Futures public research fields verified.")
    print("DISCLOSURE: All values above are KRAKEN_FUTURES data, never BTCC data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
