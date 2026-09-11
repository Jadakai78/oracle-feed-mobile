"""
bybit_market_data.py — JHL Holdings LLC
Read-only public Bybit V5 market-data adapter for linear USDT perpetuals.

Purpose:
- Research/scanner data only.
- Never places orders, reads accounts, or uses credentials.
- Every output is explicitly labeled data_venue="BYBIT".
- This does NOT provide BTCC market data or BTCC execution conditions.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

BYBIT_BASE_URL = "https://api.bybit.com"
BYBIT_DATA_VENUE = "BYBIT"
BYBIT_CATEGORY = "linear"
REQUEST_TIMEOUT_SECONDS = 12
INTER_REQUEST_DELAY_SECONDS = 0.10

_EP_INSTRUMENTS = "/v5/market/instruments-info"
_EP_TICKERS = "/v5/market/tickers"
_EP_KLINES = "/v5/market/kline"
_EP_MARK_KLINES = "/v5/market/mark-price-kline"
_EP_ORDERBOOK = "/v5/market/orderbook"
_EP_FUNDING = "/v5/market/funding/history"

UNAVAILABLE_NOT_IN_RESPONSE = "UNAVAILABLE_NOT_IN_RESPONSE"
UNAVAILABLE_REQUEST_FAILED = "UNAVAILABLE_REQUEST_FAILED"
UNAVAILABLE_PARSE_ERROR = "UNAVAILABLE_PARSE_ERROR"
UNAVAILABLE_NO_COMPLETED_CANDLES = "UNAVAILABLE_NO_COMPLETED_CANDLES"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params)
    url = f"{BYBIT_BASE_URL}{path}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "JHL-BybitResearchAdapter/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read()
        if not raw:
            raise RuntimeError(f"HTTP 200 but empty body from {url}")
        payload = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URL error from {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON parse error from {url}: {exc}") from exc

    if payload.get("retCode") != 0:
        raise RuntimeError(
            f"Bybit retCode={payload.get('retCode')} retMsg={payload.get('retMsg')} from {url}"
        )
    return payload


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


def get_active_linear_usdt_contracts() -> List[Dict[str, Any]]:
    """Return all trading, USDT-settled Bybit linear perpetual contracts."""
    rows: List[Dict[str, Any]] = []
    cursor: Optional[str] = None

    while True:
        params: Dict[str, Any] = {
            "category": BYBIT_CATEGORY,
            "limit": 1000,
        }
        if cursor:
            params["cursor"] = cursor

        payload = _get(_EP_INSTRUMENTS, params)
        result = payload.get("result") or {}
        instruments = result.get("list") or []

        for item in instruments:
            if (
                item.get("status") == "Trading"
                and item.get("contractType") == "LinearPerpetual"
                and item.get("quoteCoin") == "USDT"
                and item.get("settleCoin") == "USDT"
            ):
                rows.append(
                    {
                        "symbol": str(item.get("symbol") or "").upper(),
                        "base_asset": str(item.get("baseCoin") or "").upper(),
                        "quote_asset": "USDT",
                        "margin_asset": "USDT",
                        "contract_status": "ACTIVE",
                        "contract_type": "LINEAR_PERPETUAL",
                        "data_venue": BYBIT_DATA_VENUE,
                        "execution_venue": "BTCC",
                        "source_endpoint": BYBIT_BASE_URL + _EP_INSTRUMENTS,
                        "source_fetched_at_utc": _utc_now_iso(),
                        "tick_size": _as_float(
                            (item.get("priceFilter") or {}).get("tickSize"),
                            "tick_size",
                        ),
                        "qty_step": _as_float(
                            (item.get("lotSizeFilter") or {}).get("qtyStep"),
                            "qty_step",
                        ),
                        "min_order_qty": _as_float(
                            (item.get("lotSizeFilter") or {}).get("minOrderQty"),
                            "min_order_qty",
                        ),
                        "_raw": item,
                    }
                )

        cursor = result.get("nextPageCursor") or None
        if not cursor:
            break
        time.sleep(INTER_REQUEST_DELAY_SECONDS)

    return rows


def get_ticker(symbol: str) -> Dict[str, Any]:
    """Return Bybit ticker/mark/funding fields for one linear USDT perpetual."""
    symbol = symbol.upper()
    try:
        payload = _get(
            _EP_TICKERS,
            {"category": BYBIT_CATEGORY, "symbol": symbol},
        )
        items = (payload.get("result") or {}).get("list") or []
        item = items[0] if items else {}
        if not item:
            raise RuntimeError(f"No ticker row returned for {symbol}")

        return {
            "symbol": symbol,
            "data_venue": BYBIT_DATA_VENUE,
            "execution_venue": "BTCC",
            "last_price": _as_float(item.get("lastPrice"), "last_price"),
            "mark_price": _as_float(item.get("markPrice"), "mark_price"),
            "index_price": _as_float(item.get("indexPrice"), "index_price"),
            "best_bid": _as_float(item.get("bid1Price"), "best_bid"),
            "best_ask": _as_float(item.get("ask1Price"), "best_ask"),
            "volume_24h_base": _as_float(item.get("volume24h"), "volume_24h_base"),
            "turnover_24h_usdt": _as_float(item.get("turnover24h"), "turnover_24h_usdt"),
            "funding_rate_current": _as_float(item.get("fundingRate"), "funding_rate_current"),
            "next_funding_time_utc": _iso_from_ms(item.get("nextFundingTime")),
            "source_endpoint": BYBIT_BASE_URL + _EP_TICKERS,
            "source_fetched_at_utc": _utc_now_iso(),
            "_raw": item,
        }
    except RuntimeError as exc:
        return {
            "symbol": symbol,
            "data_venue": BYBIT_DATA_VENUE,
            "execution_venue": "BTCC",
            "last_price": UNAVAILABLE_REQUEST_FAILED,
            "mark_price": UNAVAILABLE_REQUEST_FAILED,
            "best_bid": UNAVAILABLE_REQUEST_FAILED,
            "best_ask": UNAVAILABLE_REQUEST_FAILED,
            "turnover_24h_usdt": UNAVAILABLE_REQUEST_FAILED,
            "funding_rate_current": UNAVAILABLE_REQUEST_FAILED,
            "source_endpoint": BYBIT_BASE_URL + _EP_TICKERS,
            "source_fetched_at_utc": _utc_now_iso(),
            "error": str(exc),
        }


def get_completed_klines(symbol: str, interval: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Return completed Bybit trade-price OHLCV candles only."""
    symbol = symbol.upper()
    payload = _get(
        _EP_KLINES,
        {
            "category": BYBIT_CATEGORY,
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
    )
    rows = (payload.get("result") or {}).get("list") or []
    now_ms = int(time.time() * 1000)
    interval_ms = {"5": 300_000, "15": 900_000}.get(str(interval))

    candles: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        open_ms = int(row[0])
        if interval_ms is not None and open_ms + interval_ms > now_ms:
            continue
        candles.append(
            {
                "symbol": symbol,
                "interval": str(interval),
                "open_time_epoch_ms": open_ms,
                "open_time_utc": _iso_from_ms(open_ms),
                "open": _as_float(row[1], "open"),
                "high": _as_float(row[2], "high"),
                "low": _as_float(row[3], "low"),
                "close": _as_float(row[4], "close"),
                "volume_base": _as_float(row[5], "volume_base"),
                "turnover_quote_usdt": _as_float(row[6], "turnover_quote_usdt")
                if len(row) > 6 else UNAVAILABLE_NOT_IN_RESPONSE,
                "data_venue": BYBIT_DATA_VENUE,
                "execution_venue": "BTCC",
                "source_endpoint": BYBIT_BASE_URL + _EP_KLINES,
                "source_fetched_at_utc": _utc_now_iso(),
            }
        )

    return sorted(candles, key=lambda candle: candle["open_time_epoch_ms"])


def get_mark_price_klines(symbol: str, interval: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Return completed Bybit mark-price candles only; never BTCC marks."""
    symbol = symbol.upper()
    payload = _get(
        _EP_MARK_KLINES,
        {
            "category": BYBIT_CATEGORY,
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
    )
    rows = (payload.get("result") or {}).get("list") or []
    now_ms = int(time.time() * 1000)
    interval_ms = {"5": 300_000, "15": 900_000}.get(str(interval))

    candles: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 5:
            continue
        open_ms = int(row[0])
        if interval_ms is not None and open_ms + interval_ms > now_ms:
            continue
        candles.append(
            {
                "symbol": symbol,
                "interval": str(interval),
                "open_time_epoch_ms": open_ms,
                "open_time_utc": _iso_from_ms(open_ms),
                "open": _as_float(row[1], "open"),
                "high": _as_float(row[2], "high"),
                "low": _as_float(row[3], "low"),
                "close": _as_float(row[4], "close"),
                "price_basis": "BYBIT_MARK_PRICE",
                "data_venue": BYBIT_DATA_VENUE,
                "execution_venue": "BTCC",
                "source_endpoint": BYBIT_BASE_URL + _EP_MARK_KLINES,
                "source_fetched_at_utc": _utc_now_iso(),
            }
        )

    return sorted(candles, key=lambda candle: candle["open_time_epoch_ms"])


def get_orderbook_top(symbol: str, limit: int = 1) -> Dict[str, Any]:
    """Return Bybit best bid/ask only; never treat it as BTCC depth."""
    symbol = symbol.upper()
    try:
        payload = _get(
            _EP_ORDERBOOK,
            {
                "category": BYBIT_CATEGORY,
                "symbol": symbol,
                "limit": max(1, min(int(limit), 50)),
            },
        )
        result = payload.get("result") or {}
        bids = result.get("b") or []
        asks = result.get("a") or []

        best_bid = _as_float(bids[0][0], "best_bid") if bids else UNAVAILABLE_NOT_IN_RESPONSE
        best_ask = _as_float(asks[0][0], "best_ask") if asks else UNAVAILABLE_NOT_IN_RESPONSE

        spread_absolute: Any = UNAVAILABLE_NOT_IN_RESPONSE
        spread_bps: Any = UNAVAILABLE_NOT_IN_RESPONSE
        if isinstance(best_bid, float) and isinstance(best_ask, float) and best_bid > 0:
            spread_absolute = best_ask - best_bid
            midpoint = (best_bid + best_ask) / 2
            spread_bps = (spread_absolute / midpoint) * 10_000 if midpoint else UNAVAILABLE_NOT_IN_RESPONSE

        return {
            "symbol": symbol,
            "data_venue": BYBIT_DATA_VENUE,
            "execution_venue": "BTCC",
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_absolute": spread_absolute,
            "spread_bps": spread_bps,
            "bid_levels": len(bids),
            "ask_levels": len(asks),
            "update_id": result.get("u"),
            "source_timestamp_utc": _iso_from_ms(result.get("ts")),
            "source_endpoint": BYBIT_BASE_URL + _EP_ORDERBOOK,
            "source_fetched_at_utc": _utc_now_iso(),
        }
    except RuntimeError as exc:
        return {
            "symbol": symbol,
            "data_venue": BYBIT_DATA_VENUE,
            "execution_venue": "BTCC",
            "best_bid": UNAVAILABLE_REQUEST_FAILED,
            "best_ask": UNAVAILABLE_REQUEST_FAILED,
            "spread_bps": UNAVAILABLE_REQUEST_FAILED,
            "source_endpoint": BYBIT_BASE_URL + _EP_ORDERBOOK,
            "source_fetched_at_utc": _utc_now_iso(),
            "error": str(exc),
        }


def get_funding_history(symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Return completed historical Bybit funding observations."""
    symbol = symbol.upper()
    payload = _get(
        _EP_FUNDING,
        {
            "category": BYBIT_CATEGORY,
            "symbol": symbol,
            "limit": max(1, min(int(limit), 200)),
        },
    )
    items = (payload.get("result") or {}).get("list") or []
    return [
        {
            "symbol": symbol,
            "data_venue": BYBIT_DATA_VENUE,
            "execution_venue": "BTCC",
            "funding_rate": _as_float(item.get("fundingRate"), "funding_rate"),
            "funding_time_epoch_ms": item.get("fundingRateTimestamp"),
            "funding_time_utc": _iso_from_ms(item.get("fundingRateTimestamp")),
            "source_endpoint": BYBIT_BASE_URL + _EP_FUNDING,
            "source_fetched_at_utc": _utc_now_iso(),
        }
        for item in items
    ]
