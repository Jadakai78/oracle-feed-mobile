"""
bybit_data_smoke_test.py — JHL Holdings LLC
One-shot validation for Bybit public linear-USDT research data.

No credentials. No account calls. No orders. No BTCC mutation.
Run: py -3.14 .\bybit_data_smoke_test.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import bybit_market_data as bybit

LOG_DIR = "training_logs"
SAMPLE_PREFERRED = "BTCUSDT"


def write_json(path: str, payload: Any) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def unavailable(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.startswith("UNAVAILABLE")
    )


def main() -> int:
    failures = []
    report = {
        "schema_version": "1.0",
        "collection_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "data_venue": "BYBIT",
        "execution_venue": "BTCC",
        "purpose": "RESEARCH_ONLY",
        "btcc_market_data_claim": "NONE",
    }

    try:
        contracts = bybit.get_active_linear_usdt_contracts()
    except Exception as exc:
        print(f"FAIL: instrument discovery: {exc}")
        return 1

    print(f"Active Bybit linear USDT perpetuals: {len(contracts)}")
    if not contracts:
        print("FAIL: no active linear USDT perpetuals returned")
        return 1

    symbols = {row["symbol"] for row in contracts}
    symbol = SAMPLE_PREFERRED if SAMPLE_PREFERRED in symbols else contracts[0]["symbol"]
    print(f"Sample symbol: {symbol}")

    try:
        ticker = bybit.get_ticker(symbol)
        candles_5m = bybit.get_completed_klines(symbol, "5", 30)
        candles_15m = bybit.get_completed_klines(symbol, "15", 20)
        mark_5m = bybit.get_mark_price_klines(symbol, "5", 20)
        book = bybit.get_orderbook_top(symbol)
        funding = bybit.get_funding_history(symbol, 5)
    except Exception as exc:
        print(f"FAIL: data retrieval: {exc}")
        return 1

    checks = {
        "ticker_last_price": ticker.get("last_price"),
        "ticker_mark_price": ticker.get("mark_price"),
        "ticker_turnover_24h_usdt": ticker.get("turnover_24h_usdt"),
        "ticker_current_funding": ticker.get("funding_rate_current"),
        "orderbook_best_bid": book.get("best_bid"),
        "orderbook_best_ask": book.get("best_ask"),
        "candles_5m_count": len(candles_5m),
        "candles_15m_count": len(candles_15m),
        "mark_candles_5m_count": len(mark_5m),
        "funding_history_count": len(funding),
    }

    for field in (
        "ticker_last_price",
        "ticker_mark_price",
        "ticker_turnover_24h_usdt",
        "ticker_current_funding",
        "orderbook_best_bid",
        "orderbook_best_ask",
    ):
        if unavailable(checks[field]):
            failures.append(f"{field} unavailable: {checks[field]}")

    for field in (
        "candles_5m_count",
        "candles_15m_count",
        "mark_candles_5m_count",
        "funding_history_count",
    ):
        if checks[field] < 1:
            failures.append(f"{field} returned zero usable rows")

    report.update(
        {
            "sample_symbol": symbol,
            "active_contract_count": len(contracts),
            "checks": checks,
            "ticker": ticker,
            "orderbook_top": book,
            "completed_5m_candles_sample": candles_5m[-3:],
            "completed_15m_candles_sample": candles_15m[-3:],
            "completed_mark_5m_candles_sample": mark_5m[-3:],
            "funding_history_sample": funding[:5],
            "result": "PASS" if not failures else "FAIL",
            "failures": failures,
        }
    )

    output_path = os.path.join(LOG_DIR, "bybit_data_smoke_test.json")
    write_json(output_path, report)

    print(f"5m completed candles: {len(candles_5m)}")
    print(f"15m completed candles: {len(candles_15m)}")
    print(f"Mark-price 5m candles: {len(mark_5m)}")
    print(f"Funding observations: {len(funding)}")
    print(f"Wrote: {output_path}")

    if failures:
        print("RESULT: FAIL")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("RESULT: PASS — Bybit public research fields verified.")
    print("DISCLOSURE: All market values above are BYBIT data, not BTCC data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
