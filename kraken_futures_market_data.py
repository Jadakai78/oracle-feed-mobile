"""
kraken_futures_market_data.py — JHL Holdings LLC
Read-only Kraken Futures public market-data adapter.

Purpose:
- Research/scanner data only.
- No API keys, account calls, orders, transfers, or execution methods.
- All market values are explicitly KRAKEN_FUTURES data, never BTCC data.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

KRAKEN_FUTURES_BASE_URL = "https://futures.kraken.com"
KRAKEN_FUTURES_DATA_VENUE = "KRAKEN_FUTURES"
REQUEST_TIMEOUT_SECONDS = 15

_EP_INSTRUMENTS = "/derivatives/api/v3/instruments"
_EP_TICKERS = "/derivatives/api/v3/tickers"
_EP_OHLC = "/derivatives/api/v4/ohlc"
_EP_ORDERBOOK = "/derivatives/api/v3/orderbook"
_EP_FUNDING = "/derivatives/api/v3/historicalfundingrates"

UNAVAILABLE_NOT_IN_RESPONSE = "UNAVAILABLE_NOT_IN_RESPONSE"
UNAVAILABLE_REQUEST_FAILED = "UNAVAILABLE_REQUEST_FAILED"
UNAVAILABLE_PARSE_ERROR = "UNAVAILABLE_PARSE_ERROR"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    query = urllib.parse.urlencode(params or {})
    url = KRAKEN_FUTURES_BASE_URL + path
    if query:
        url = f"{url}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "JHL-KrakenFuturesResearchAdapter/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URL error from {url}: {exc.reason}") from exc

    if not raw:
        raise RuntimeError(f"HTTP 200 but empty body from {url}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON parse error from {url}: {exc}") from exc

    if isinstance(payload, dict) and payload.get("result") not in (None, "success"):
        raise RuntimeError(f"Kraken result={payload.get('result')} from {url}")

    return payload


def _as_float(value: Any, field_name: str) -> Any:
    if value is None or value == "":
        return UNAVAILABLE_NOT_IN_RESPONSE
    try:
        return float(value)
    except (TypeError, ValueError):
        return f"{UNAVAILABLE_PARSE_ERROR}:{field_name}"


def _iso_from_epoch(value: Any) -> str:
    try:
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return datetime.fromtimestamp(number, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return UNAVAILABLE_PARSE_ERROR


def _canonical_usdt_symbol(base_asset: str) -> str:
    return f"{base_asset.upper()}USDT"


def _find_venue_symbol(symbol: str, instruments: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    target = symbol.upper()
    for item in instruments:
        if item["symbol"].upper() == target:
            return item
    return None


def get_active_linear_usd_perpetuals() -> List[Dict[str, Any]]:
    """
    Return active Kraken Futures flexible USD contracts for research.

    Verified production taxonomy on 2026-08-18:
    - PF_<ASSET>USD = flexible_futures, tradeable, USD quoted
    - PI_<ASSET>USD = futures_inverse; excluded
    - FF_/FI_ products = dated futures; excluded

    `canonical_symbol` is an overlap key only. It does not claim Kraken
    trades or settles in USDT, and every market field remains KRAKEN_FUTURES.
    """
    payload = _get(_EP_INSTRUMENTS)
    raw_instruments = payload.get("instruments") or []
    rows: List[Dict[str, Any]] = []

    for item in raw_instruments:
        symbol = str(item.get("symbol") or "").upper()
        instrument_type = str(item.get("type") or "").lower()

        if item.get("tradeable") is not True:
            continue
        if instrument_type != "flexible_futures":
            continue
        if not (symbol.startswith("PF_") and symbol.endswith("USD")):
            continue

        base_asset = symbol[3:-3].upper()
        if not base_asset:
            continue

        canonical_base = "BTC" if base_asset == "XBT" else base_asset

        rows.append(
            {
                "symbol": symbol,
                "canonical_symbol": _canonical_usdt_symbol(canonical_base),
                "base_asset": base_asset,
                "canonical_base_asset": canonical_base,
                "quote_asset": "USD",
                "margin_asset": "USD",
                "contract_status": "ACTIVE",
                "contract_type": "FLEXIBLE_FUTURES",
                "data_venue": KRAKEN_FUTURES_DATA_VENUE,
                "execution_venue": "BTCC",
                "tick_size": _as_float(item.get("tickSize"), "tick_size"),
                "contract_size": _as_float(item.get("contractSize"), "contract_size"),
                "source_endpoint": KRAKEN_FUTURES_BASE_URL + _EP_INSTRUMENTS,
                "source_fetched_at_utc": _utc_now_iso(),
                "_raw": item,
            }
        )

    return rows

def get_tickers() -> List[Dict[str, Any]]:
    """Return normalized Kraken Futures ticker rows for all listed instruments."""
    payload = _get(_EP_TICKERS)
    raw_tickers = payload.get("tickers") or []
    return [
        {
            "symbol": str(item.get("symbol") or "").upper(),
            "last_price": _as_float(item.get("last"), "last_price"),
            "mark_price": _as_float(item.get("markPrice"), "mark_price"),
            "index_price": _as_float(item.get("index"), "index_price"),
            "best_bid": _as_float(item.get("bid"), "best_bid"),
            "best_ask": _as_float(item.get("ask"), "best_ask"),
            "volume_24h_base": _as_float(item.get("volume"), "volume_24h_base"),
            "open_interest": _as_float(item.get("openInterest"), "open_interest"),
            "funding_rate_current": _as_float(item.get("fundingRate"), "funding_rate_current"),
            "next_funding_time_utc": _iso_from_epoch(item.get("nextFundingRateTime")),
            "data_venue": KRAKEN_FUTURES_DATA_VENUE,
            "execution_venue": "BTCC",
            "source_endpoint": KRAKEN_FUTURES_BASE_URL + _EP_TICKERS,
            "source_fetched_at_utc": _utc_now_iso(),
            "_raw": item,
        }
        for item in raw_tickers
    ]


def get_ticker(symbol: str) -> Dict[str, Any]:
    """Return one Kraken Futures ticker record, explicitly labeled as Kraken data."""
    symbol = symbol.upper()
    try:
        rows = get_tickers()
        match = next((row for row in rows if row["symbol"] == symbol), None)
        if match is None:
            raise RuntimeError(f"No Kraken Futures ticker returned for {symbol}")
        return match
    except RuntimeError as exc:
        return {
            "symbol": symbol,
            "data_venue": KRAKEN_FUTURES_DATA_VENUE,
            "execution_venue": "BTCC",
            "last_price": UNAVAILABLE_REQUEST_FAILED,
            "mark_price": UNAVAILABLE_REQUEST_FAILED,
            "best_bid": UNAVAILABLE_REQUEST_FAILED,
            "best_ask": UNAVAILABLE_REQUEST_FAILED,
            "funding_rate_current": UNAVAILABLE_REQUEST_FAILED,
            "source_endpoint": KRAKEN_FUTURES_BASE_URL + _EP_TICKERS,
            "source_fetched_at_utc": _utc_now_iso(),
            "error": str(exc),
        }


def get_completed_ohlc(symbol: str, interval_minutes: int, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Return completed Kraken Futures OHLC rows only.

    The Kraken API response shape may vary by API version; this function
    validates and normalizes only rows containing timestamp + O/H/L/C.
    """
    symbol = symbol.upper()
    payload = _get(
        _EP_OHLC,
        {
            "symbol": symbol,
            "interval": int(interval_minutes),
        },
    )

    raw_rows: Any = payload.get("candles")
    if raw_rows is None:
        raw_rows = payload.get("ohlc")
    if raw_rows is None:
        raw_rows = payload.get("data")
    if not isinstance(raw_rows, list):
        return []

    now_epoch = time.time()
    interval_seconds = int(interval_minutes) * 60
    candles: List[Dict[str, Any]] = []

    for row in raw_rows[-max(1, int(limit)):]:
        if isinstance(row, dict):
            timestamp = row.get("time") or row.get("timestamp") or row.get("openTime")
            open_value = row.get("open")
            high_value = row.get("high")
            low_value = row.get("low")
            close_value = row.get("close")
            volume_value = row.get("volume")
        elif isinstance(row, list) and len(row) >= 5:
            timestamp = row[0]
            open_value, high_value, low_value, close_value = row[1:5]
            volume_value = row[5] if len(row) > 5 else None
        else:
            continue

        try:
            epoch = float(timestamp)
            if epoch > 10_000_000_000:
                epoch /= 1000.0
        except (TypeError, ValueError):
            continue

        if epoch + interval_seconds >= now_epoch:
            continue

        candles.append(
            {
                "symbol": symbol,
                "interval_minutes": int(interval_minutes),
                "open_time_epoch": epoch,
                "open_time_utc": _iso_from_epoch(epoch),
                "open": _as_float(open_value, "open"),
                "high": _as_float(high_value, "high"),
                "low": _as_float(low_value, "low"),
                "close": _as_float(close_value, "close"),
                "volume_base": _as_float(volume_value, "volume_base"),
                "data_venue": KRAKEN_FUTURES_DATA_VENUE,
                "execution_venue": "BTCC",
                "source_endpoint": KRAKEN_FUTURES_BASE_URL + _EP_OHLC,
                "source_fetched_at_utc": _utc_now_iso(),
            }
        )

    return sorted(candles, key=lambda row: row["open_time_epoch"])


def get_orderbook_top(symbol: str) -> Dict[str, Any]:
    """Return Kraken Futures best bid/ask; never labels it BTCC depth."""
    symbol = symbol.upper()
    base = {
        "symbol": symbol,
        "data_venue": KRAKEN_FUTURES_DATA_VENUE,
        "execution_venue": "BTCC",
        "source_endpoint": KRAKEN_FUTURES_BASE_URL + _EP_ORDERBOOK,
        "source_fetched_at_utc": _utc_now_iso(),
    }

    try:
        payload = _get(_EP_ORDERBOOK, {"symbol": symbol})
        bids = payload.get("bids") or []
        asks = payload.get("asks") or []

        def price(level: Any) -> Any:
            if isinstance(level, dict):
                return _as_float(level.get("price"), "book_price")
            if isinstance(level, list) and level:
                return _as_float(level[0], "book_price")
            return UNAVAILABLE_NOT_IN_RESPONSE

        best_bid = price(bids[0]) if bids else UNAVAILABLE_NOT_IN_RESPONSE
        best_ask = price(asks[0]) if asks else UNAVAILABLE_NOT_IN_RESPONSE

        spread_absolute: Any = UNAVAILABLE_NOT_IN_RESPONSE
        spread_bps: Any = UNAVAILABLE_NOT_IN_RESPONSE
        if isinstance(best_bid, float) and isinstance(best_ask, float) and best_bid > 0:
            spread_absolute = best_ask - best_bid
            midpoint = (best_bid + best_ask) / 2
            spread_bps = (spread_absolute / midpoint) * 10_000 if midpoint else UNAVAILABLE_NOT_IN_RESPONSE

        return {
            **base,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_absolute": spread_absolute,
            "spread_bps": spread_bps,
            "bid_levels": len(bids),
            "ask_levels": len(asks),
        }
    except RuntimeError as exc:
        return {
            **base,
            "best_bid": UNAVAILABLE_REQUEST_FAILED,
            "best_ask": UNAVAILABLE_REQUEST_FAILED,
            "spread_bps": UNAVAILABLE_REQUEST_FAILED,
            "error": str(exc),
        }


def get_funding_history(symbol: str) -> List[Dict[str, Any]]:
    """Return Kraken Futures historical funding observations."""
    symbol = symbol.upper()
    payload = _get(_EP_FUNDING, {"symbol": symbol})
    rows = payload.get("rates") or payload.get("fundingRates") or []

    if not isinstance(rows, list):
        return []

    results: List[Dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        timestamp = item.get("timestamp") or item.get("time")
        results.append(
            {
                "symbol": symbol,
                "data_venue": KRAKEN_FUTURES_DATA_VENUE,
                "execution_venue": "BTCC",
                "funding_rate": _as_float(
                    item.get("fundingRate", item.get("rate")),
                    "funding_rate",
                ),
                "funding_time_utc": _iso_from_epoch(timestamp),
                "source_endpoint": KRAKEN_FUTURES_BASE_URL + _EP_FUNDING,
                "source_fetched_at_utc": _utc_now_iso(),
            }
        )
    return results

