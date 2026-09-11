"""
binance_market_data.py — JHL Holdings LLC
Read-only public Binance USDⓈ-M Futures market-data adapter.

Purpose:
- Research/scanner data only.
- No API keys, accounts, orders, transfers, or execution methods.
- All market values are explicitly BINANCE data, never BTCC data.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List

BINANCE_BASE_URL = "https://fapi.binance.com"
BINANCE_DATA_VENUE = "BINANCE"
REQUEST_TIMEOUT_SECONDS = 12

_EP_EXCHANGE_INFO = "/fapi/v1/exchangeInfo"
_EP_TICKER_24H = "/fapi/v1/ticker/24hr"
_EP_PREMIUM_INDEX = "/fapi/v1/premiumIndex"
_EP_KLINES = "/fapi/v1/klines"
_EP_DEPTH = "/fapi/v1/depth"
_EP_FUNDING_RATE = "/fapi/v1/fundingRate"

UNAVAILABLE_NOT_IN_RESPONSE = "UNAVAILABLE_NOT_IN_RESPONSE"
UNAVAILABLE_REQUEST_FAILED = "UNAVAILABLE_REQUEST_FAILED"
UNAVAILABLE_PARSE_ERROR = "UNAVAILABLE_PARSE_ERROR"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(path: str, params: Dict[str, Any] | None = None) -> Any:
    query = urllib.parse.urlencode(params or {})
    url = f"{BINANCE_BASE_URL}{path}"
    if query:
        url = f"{url}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "JHL-BinanceResearchAdapter/1.0",
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
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON parse error from {url}: {exc}") from exc


def _as_float(value: Any, field_name: str) -> Any:
    if value is None or value == "":
        return UNAVAILABLE_NOT_IN_RESPONSE
    try:
        return float(value)
    except (TypeError, ValueError):
        return f"{UNAVAILABLE_PARSE_ERROR}:{field_name}"


def _iso_from_ms(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return UNAVAILABLE_PARSE_ERROR


def _filter_value(filters: List[Dict[str, Any]], name: str, key: str) -> Any:
    for item in filters:
        if item.get("filterType") == name:
            return item.get(key)
    return None


def get_active_usdt_perpetuals() -> List[Dict[str, Any]]:
    """Return active Binance USDⓈ-M USDT perpetual contracts."""
    payload = _get(_EP_EXCHANGE_INFO)
    symbols = payload.get("symbols") or []
    rows: List[Dict[str, Any]] = []

    for item in symbols:
        if not (
            item.get("status") == "TRADING"
            and item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT"
            and item.get("marginAsset") == "USDT"
        ):
            continue

        filters = item.get("filters") or []
        rows.append(
            {
                "symbol": str(item.get("symbol") or "").upper(),
                "base_asset": str(item.get("baseAsset") or "").upper(),
                "quote_asset": "USDT",
                "margin_asset": "USDT",
                "contract_status": "ACTIVE",
                "contract_type": "LINEAR_PERPETUAL",
                "data_venue": BINANCE_DATA_VENUE,
                "execution_venue": "BTCC",
                "tick_size": _as_float(
                    _filter_value(filters, "PRICE_FILTER", "tickSize"),
                    "tick_size",
                ),
                "qty_step": _as_float(
                    _filter_value(filters, "LOT_SIZE", "stepSize"),
                    "qty_step",
                ),
                "min_order_qty": _as_float(
                    _filter_value(filters, "LOT_SIZE", "minQty"),
                    "min_order_qty",
                ),
                "source_endpoint": BINANCE_BASE_URL + _EP_EXCHANGE_INFO,
                "source_fetched_at_utc": _utc_now_iso(),
                "_raw": item,
            }
        )

    return rows


def get_ticker(symbol: str) -> Dict[str, Any]:
    """Return Binance ticker and mark/funding fields for one perpetual."""
    symbol = symbol.upper()
    base = {
        "symbol": symbol,
        "data_venue": BINANCE_DATA_VENUE,
        "execution_venue": "BTCC",
        "source_fetched_at_utc": _utc_now_iso(),
    }

    try:
        ticker = _get(_EP_TICKER_24H, {"symbol": symbol})
        premium = _get(_EP_PREMIUM_INDEX, {"symbol": symbol})

        return {
            **base,
            "last_price": _as_float(ticker.get("lastPrice"), "last_price"),
            "best_bid": _as_float(ticker.get("bidPrice"), "best_bid"),
            "best_ask": _as_float(ticker.get("askPrice"), "best_ask"),
            "volume_24h_base": _as_float(ticker.get("volume"), "volume_24h_base"),
            "turnover_24h_usdt": _as_float(ticker.get("quoteVolume"), "turnover_24h_usdt"),
            "mark_price": _as_float(premium.get("markPrice"), "mark_price"),
            "index_price": _as_float(premium.get("indexPrice"), "index_price"),
            "funding_rate_current": _as_float(premium.get("lastFundingRate"), "funding_rate_current"),
            "next_funding_time_utc": _iso_from_ms(premium.get("nextFundingTime")),
            "source_endpoint_ticker": BINANCE_BASE_URL + _EP_TICKER_24H,
            "source_endpoint_mark": BINANCE_BASE_URL + _EP_PREMIUM_INDEX,
            "_raw_ticker": ticker,
            "_raw_premium": premium,
        }
    except RuntimeError as exc:
        return {
            **base,
            "last_price": UNAVAILABLE_REQUEST_FAILED,
            "mark_price": UNAVAILABLE_REQUEST_FAILED,
            "best_bid": UNAVAILABLE_REQUEST_FAILED,
            "best_ask": UNAVAILABLE_REQUEST_FAILED,
            "turnover_24h_usdt": UNAVAILABLE_REQUEST_FAILED,
            "funding_rate_current": UNAVAILABLE_REQUEST_FAILED,
            "error": str(exc),
        }


def get_completed_klines(symbol: str, interval: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Return completed Binance trade-price OHLCV candles only."""
    symbol = symbol.upper()
    rows = _get(
        _EP_KLINES,
        {"symbol": symbol, "interval": interval, "limit": max(1, min(int(limit), 1500))},
    )

    now_ms = int(time.time() * 1000)
    candles: List[Dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            continue

        open_ms = int(row[0])
        close_ms = int(row[6])

        if close_ms >= now_ms:
            continue

        candles.append(
            {
                "symbol": symbol,
                "interval": str(interval),
                "open_time_epoch_ms": open_ms,
                "close_time_epoch_ms": close_ms,
                "open_time_utc": _iso_from_ms(open_ms),
                "close_time_utc": _iso_from_ms(close_ms),
                "open": _as_float(row[1], "open"),
                "high": _as_float(row[2], "high"),
                "low": _as_float(row[3], "low"),
                "close": _as_float(row[4], "close"),
                "volume_base": _as_float(row[5], "volume_base"),
                "turnover_quote_usdt": _as_float(row[7], "turnover_quote_usdt"),
                "data_venue": BINANCE_DATA_VENUE,
                "execution_venue": "BTCC",
                "source_endpoint": BINANCE_BASE_URL + _EP_KLINES,
                "source_fetched_at_utc": _utc_now_iso(),
            }
        )

    return sorted(candles, key=lambda item: item["open_time_epoch_ms"])


def get_orderbook_top(symbol: str, limit: int = 5) -> Dict[str, Any]:
    """Return Binance L1/L2 values, explicitly not BTCC order-book data."""
    symbol = symbol.upper()
    base = {
        "symbol": symbol,
        "data_venue": BINANCE_DATA_VENUE,
        "execution_venue": "BTCC",
        "source_endpoint": BINANCE_BASE_URL + _EP_DEPTH,
        "source_fetched_at_utc": _utc_now_iso(),
    }

    try:
        payload = _get(
            _EP_DEPTH,
            {"symbol": symbol, "limit": max(5, min(int(limit), 100))},
        )
        bids = payload.get("bids") or []
        asks = payload.get("asks") or []

        best_bid = _as_float(bids[0][0], "best_bid") if bids else UNAVAILABLE_NOT_IN_RESPONSE
        best_ask = _as_float(asks[0][0], "best_ask") if asks else UNAVAILABLE_NOT_IN_RESPONSE

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
            "last_update_id": payload.get("lastUpdateId"),
        }
    except RuntimeError as exc:
        return {
            **base,
            "best_bid": UNAVAILABLE_REQUEST_FAILED,
            "best_ask": UNAVAILABLE_REQUEST_FAILED,
            "spread_bps": UNAVAILABLE_REQUEST_FAILED,
            "error": str(exc),
        }


def get_funding_history(symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Return completed historical Binance funding records."""
    symbol = symbol.upper()
    rows = _get(
        _EP_FUNDING_RATE,
        {"symbol": symbol, "limit": max(1, min(int(limit), 1000))},
    )

    return [
        {
            "symbol": symbol,
            "data_venue": BINANCE_DATA_VENUE,
            "execution_venue": "BTCC",
            "funding_rate": _as_float(item.get("fundingRate"), "funding_rate"),
            "funding_time_epoch_ms": item.get("fundingTime"),
            "funding_time_utc": _iso_from_ms(item.get("fundingTime")),
            "source_endpoint": BINANCE_BASE_URL + _EP_FUNDING_RATE,
            "source_fetched_at_utc": _utc_now_iso(),
        }
        for item in rows
    ]
