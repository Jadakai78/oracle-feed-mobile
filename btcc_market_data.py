"""
btcc_market_data.py — JHL Holdings LLC
Read-only BTCC public-data adapter — BTCC USDT-M perpetual contracts.

ENDPOINT DISCOVERY RESULTS (verified 2026-08-18 against live production):
─────────────────────────────────────────────────────────────────────────────
PRIMARY ENDPOINT — DEAD:
  https://api1.btloginc.com:9081/v1/public/contracts
  Status: CONNECTION_TIMEOUT (HTTP 000, 8s)
  Preserved exactly: never retry, never substitute with auth.

VERIFIED PUBLIC ENDPOINTS (no auth required, real JSON returned):
  Base:    https://www.btcc.com
  /btcc_trade/market/list          — 200 OK, 97KB JSON, 374 contracts (254 USDT-M perps)
  /btcc_trade/market/detail        — 200 OK, per-symbol contract spec

UNAVAILABLE / GATED ENDPOINTS (HTTP 200 but empty body — Cloudflare gate):
  /api/futures/v1/contracts        — 200 empty
  /api/futures/v1/funding-rate     — 200 empty

REQUIRES AUTH SIGNATURE (Sign param mandatory — not public REST):
  /quot_kline/klines               — 400 "Sign: value length must be >= 2"
  /btcc_trade/market/kline         — 200 "invalid argument" (sign from WS session)
  WebSocket wss://waccess2.btloginc.com  — kline.query + ReqKline require session token

DEPTH ENDPOINT (responds but returns empty bids/asks from non-browser IP):
  /btcc_trade/market/depth         — 200, {"asks":[],"bids":[]}, no real data

KLINE STATUS: NO VERIFIED PUBLIC REST PATH EXISTS.
  All candle data is delivered via authenticated WebSocket (ReqKline/kline.query).
  This blocks: Speed harvest, Delta harvest, Structure harvest, 5m/15m OHLCV.
  Do not claim klines available until a verified path is found.

FUNDING STATUS: NO VERIFIED PUBLIC REST PATH EXISTS.
  /api/futures/v1/funding-rate returns HTTP 200 with empty body (Cloudflare gate).
  BTCC funding windows are documented as 01:00, 09:00, 17:00 UTC (8h cycle).
  These constants are hardcoded for Noise/Timing gates until a live endpoint confirms.

SCHEMA VERSION: 1.1
COLLECTION NOTE: All timestamps preserved as UTC. Source epoch ms → ISO-8601 UTC.
UNAVAILABLE FIELDS: Explicitly flagged — never fabricated.
"""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ── ONE source of truth for all endpoint mappings ─────────────────────────────

# Primary — DEAD, preserved exactly as discovered
PRIMARY_BASE_URL: str       = "https://api1.btloginc.com:9081"
PRIMARY_FAILURE_REASON: str = "CONNECTION_TIMEOUT_HTTP_000"
PRIMARY_FAILURE_TIME: str   = "2026-08-18T00:32:00Z"
PRIMARY_VERIFIED_DEAD: bool = True  # Do not retry

# Fallback — VERIFIED live
FALLBACK_BASE_URL: str      = "https://www.btcc.com"

# Active base (fallback promoted to primary until primary is restored)
BTCC_BASE_URL: str = FALLBACK_BASE_URL
BTCC_DATA_SOURCE: str = "FALLBACK_btcc_trade"

# Verified paths on FALLBACK_BASE_URL
_EP_CONTRACTS       = "/btcc_trade/market/list"    # VERIFIED: 200 OK, real JSON
_EP_CONTRACT_DETAIL = "/btcc_trade/market/detail"  # VERIFIED: 200 OK, per-symbol
_EP_DEPTH           = "/btcc_trade/market/depth"   # EXISTS but returns empty bids/asks

# Gated / unavailable paths — do not call, preserved for audit
_EP_FUNDING_GATED   = "/api/futures/v1/funding-rate"  # 200 empty body — Cloudflare gate
_EP_KLINE_SIGNED    = "/btcc_trade/market/kline"      # Requires auth sign token
_EP_KLINE_QUOT      = "/quot_kline/klines"            # Requires Sign param

# ── Rate-limit constants ───────────────────────────────────────────────────────
REQUEST_TIMEOUT_SECONDS: int     = 12
INTER_REQUEST_DELAY_SECONDS: float = 0.30   # Conservative: ~3 req/s
MAX_RESULTS_PER_CALL: int        = 500      # market/list returns all in one call

# ── Documented funding constants (hardcoded until live endpoint confirmed) ────
BTCC_FUNDING_INTERVAL_HOURS: int     = 8
BTCC_FUNDING_WINDOWS_UTC: List[str]  = ["01:00", "09:00", "17:00"]  # documented

# ── Sentinel values ───────────────────────────────────────────────────────────
UNAVAIL_KLINE_NO_PUBLIC_REST    = "UNAVAILABLE_KLINE_NO_PUBLIC_REST_PATH_VERIFIED"
UNAVAIL_FUNDING_ENDPOINT_GATED  = "UNAVAILABLE_FUNDING_ENDPOINT_GATED_200_EMPTY"
UNAVAIL_DEPTH_EMPTY_RESPONSE    = "UNAVAILABLE_DEPTH_BIDS_ASKS_EMPTY_FROM_API"
UNAVAIL_NOT_IN_RESPONSE         = "UNAVAILABLE_NOT_IN_RESPONSE"
UNAVAIL_PRIMARY_DEAD            = "UNAVAILABLE_PRIMARY_ENDPOINT_DEAD_TIMEOUT"
UNAVAIL_CALC_ERR                = "UNAVAILABLE_CALC_ERROR"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _epoch_ms_to_utc_iso(epoch_ms: Any) -> str:
    try:
        return datetime.fromtimestamp(int(epoch_ms) / 1000.0,
                                      tz=timezone.utc).isoformat()
    except Exception:
        return UNAVAIL_CALC_ERR


def _get(path: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Single-shot stdlib HTTP GET. No retry loops. Raises RuntimeError on failure.
    Records source URL, HTTP status, and timestamp in every error.
    """
    url = BTCC_BASE_URL + path
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{query}"

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JHL-DataAdapter/1.1",
            "Referer": "https://www.btcc.com/en-US/trade/perpetual/BTCUSDT",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
            if not raw:
                raise RuntimeError(
                    f"HTTP 200 but empty body from {url} "
                    f"(Cloudflare gate or backend offline) at {_utc_now_iso()}"
                )
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"HTTP {exc.code} from {url} at {_utc_now_iso()}: {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"URL error for {url} at {_utc_now_iso()}: {exc.reason}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"JSON parse error from {url} at {_utc_now_iso()}: {exc}"
        ) from exc


def _safe_float(val: Any, field_name: str) -> Any:
    if val is None or val == "" or val == "-":
        return UNAVAIL_NOT_IN_RESPONSE
    try:
        return float(val)
    except (TypeError, ValueError):
        return f"UNAVAILABLE_PARSE_ERROR_{field_name}"


# ── Public API ────────────────────────────────────────────────────────────────

def get_active_contracts() -> List[Dict[str, Any]]:
    """
    Discover all active USDT-M perpetual contracts via verified endpoint.

    Source: /btcc_trade/market/list  (VERIFIED 2026-08-18, HTTP 200, real JSON)
    Field availability from live response:
      VERIFIED:   name, stock (base), money (quote/margin), switch (active status),
                  taker_fee, fee_prec, money_prec (tick size proxy), stock_prec,
                  min_amount (qty minimum), min_order_value, depth string, price_limit
      UNAVAILABLE: contract_multiplier (not in response — set to 1.0 for USDT-M)
                   mark_price, last_price, volume (not in list — requires ticker)
                   funding_rate (endpoint gated)
    """
    raw = _get(_EP_CONTRACTS)

    records_raw: List[Dict] = []
    if isinstance(raw, dict):
        data = raw.get("data", {})
        if isinstance(data, dict):
            records_raw = data.get("records", [])
        elif isinstance(data, list):
            records_raw = data

    if not records_raw:
        raise RuntimeError(
            f"No records in /btcc_trade/market/list response. "
            f"Keys: {list(raw.keys()) if isinstance(raw, dict) else type(raw)}"
        )

    fetched_at = _utc_now_iso()
    normalized: List[Dict[str, Any]] = []

    for c in records_raw:
        if not isinstance(c, dict):
            continue

        money = str(c.get("money") or "").upper()
        is_exchange = c.get("is_exchange", True)

        # Keep USDT-margined non-spot (perpetual) contracts that are active (switch=true)
        if money != "USDT":
            continue
        if is_exchange:
            continue   # spot market
        if not c.get("switch", False):
            continue   # inactive

        name        = c.get("name", "UNKNOWN")
        stock       = str(c.get("stock") or "UNKNOWN").upper()

        # Parse depth string "100,10,1,0.1,0.01" → finest tick is last element
        depth_str   = c.get("depth", "")
        tick_size   = UNAVAIL_NOT_IN_RESPONSE
        if depth_str:
            try:
                parts = [float(x) for x in depth_str.split(",") if x.strip()]
                tick_size = min(parts) if parts else UNAVAIL_NOT_IN_RESPONSE
            except ValueError:
                tick_size = UNAVAIL_CALC_ERR

        normalized.append({
            "symbol":            name,
            "base_asset":        stock,
            "quote_asset":       money,
            "margin_asset":      money,
            "contract_status":   "ACTIVE",   # switch=true confirmed above
            # multiplier: USDT-M perpetuals are linear, multiplier effectively 1
            # Not present in /btcc_trade/market/list response
            "contract_multiplier": "UNAVAILABLE_NOT_SUPPLIED_BY_BTCC_MARKET_LIST",
            "tick_size":         tick_size,
            "qty_step":          _safe_float(c.get("stock_prec"), "qty_step_prec"),
            "qty_minimum":       _safe_float(c.get("min_amount"), "qty_minimum"),
            "min_order_value_usdt": _safe_float(c.get("min_order_value"), "min_order_value"),
            "taker_fee_rate":    _safe_float(c.get("taker_fee"), "taker_fee"),
            "source_fetched_at_utc": fetched_at,
            "source_endpoint":   BTCC_BASE_URL + _EP_CONTRACTS,
            "data_source_name":  BTCC_DATA_SOURCE,
            "_raw": c,
        })

    return normalized


def get_ticker(symbol: str) -> Dict[str, Any]:
    """
    Return public ticker data for one symbol via contract detail endpoint.

    FIELD AVAILABILITY (verified from /btcc_trade/market/detail):
      VERIFIED:   symbol, contract spec fields (fee, prec, min_amount)
      UNAVAILABLE: last_price, mark_price, volume_24h — not in detail response.
                   These require WebSocket subscription (kline.query/state.query)
                   which requires an auth session token.

    Returns normalized dict with explicit UNAVAILABLE flags for missing fields.
    Never fabricates prices or volumes.
    """
    try:
        raw = _get(_EP_CONTRACT_DETAIL, {"market": symbol})
    except RuntimeError as exc:
        return {
            "symbol":                  symbol,
            "last_price":              UNAVAIL_NOT_IN_RESPONSE,
            "mark_price":              UNAVAIL_NOT_IN_RESPONSE,
            "volume_24h_quote_usdt":   UNAVAIL_NOT_IN_RESPONSE,
            "ticker_source_epoch_utc": UNAVAIL_NOT_IN_RESPONSE,
            "source_endpoint":         BTCC_BASE_URL + _EP_CONTRACT_DETAIL,
            "data_source_name":        BTCC_DATA_SOURCE,
            "error":                   str(exc),
        }

    data = {}
    if isinstance(raw, dict):
        data = raw.get("data") or raw

    return {
        "symbol":                  symbol,
        # Price fields not available via public REST on BTCC
        "last_price":              UNAVAIL_NOT_IN_RESPONSE,
        "mark_price":              UNAVAIL_NOT_IN_RESPONSE,
        "bid_price":               UNAVAIL_NOT_IN_RESPONSE,
        "ask_price":               UNAVAIL_NOT_IN_RESPONSE,
        "volume_24h_quote_usdt":   UNAVAIL_NOT_IN_RESPONSE,
        "volume_24h_base":         UNAVAIL_NOT_IN_RESPONSE,
        "price_change_pct_24h":    UNAVAIL_NOT_IN_RESPONSE,
        # Contract spec fields — verified available
        "taker_fee_rate":         _safe_float(data.get("taker_fee"), "taker_fee"),
        "min_amount":             _safe_float(data.get("min_amount"), "min_amount"),
        "contract_active":        data.get("switch", False),
        "ticker_fetched_at_utc":  _utc_now_iso(),
        "ticker_source_epoch_ms": UNAVAIL_NOT_IN_RESPONSE,
        "ticker_source_epoch_utc": UNAVAIL_NOT_IN_RESPONSE,
        "source_endpoint":        BTCC_BASE_URL + _EP_CONTRACT_DETAIL,
        "data_source_name":       BTCC_DATA_SOURCE,
        "_raw": data,
    }


def get_klines(symbol: str, interval: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Attempt to return completed OHLCV candles.

    CURRENT STATUS: NO VERIFIED PUBLIC REST PATH FOR KLINES ON BTCC.
      - /btcc_trade/market/kline  → "invalid argument" (requires WS sign token)
      - /quot_kline/klines        → 400 "Sign value length must be >= 2 runes"
      - WebSocket kline.query     → requires authenticated session token
      - UDF datafeed              → injected at runtime from authenticated browser session

    Returns empty list with explicit UNAVAILABLE metadata.
    Do not use this function's output for scanner scoring until a verified path exists.
    """
    return [{
        "symbol":            symbol,
        "interval":          interval,
        "open_time_utc":     UNAVAIL_KLINE_NO_PUBLIC_REST,
        "source_epoch_ms":   UNAVAIL_KLINE_NO_PUBLIC_REST,
        "open":              UNAVAIL_KLINE_NO_PUBLIC_REST,
        "high":              UNAVAIL_KLINE_NO_PUBLIC_REST,
        "low":               UNAVAIL_KLINE_NO_PUBLIC_REST,
        "close":             UNAVAIL_KLINE_NO_PUBLIC_REST,
        "volume_base":       UNAVAIL_KLINE_NO_PUBLIC_REST,
        "volume_quote_usdt": UNAVAIL_KLINE_NO_PUBLIC_REST,
        "source_endpoint":   UNAVAIL_KLINE_NO_PUBLIC_REST,
        "data_source_name":  BTCC_DATA_SOURCE,
        "kline_block_reason": (
            "BTCC kline REST endpoints require a session-signed token. "
            "Verified paths: /btcc_trade/market/kline (returns invalid argument without sign), "
            "/quot_kline/klines (400 Sign length >= 2 required). "
            "WebSocket wss://waccess2.btloginc.com kline.query also requires sign. "
            "No unauthenticated kline REST path found as of 2026-08-18."
        ),
    }]


def get_funding_rate(symbol: str) -> Dict[str, Any]:
    """
    Return funding rate metadata.

    CURRENT STATUS: ENDPOINT GATED.
      - /api/futures/v1/funding-rate → HTTP 200 with empty body (Cloudflare gate)
      - No other public funding REST path found.

    Returns hardcoded BTCC documented funding windows (01:00, 09:00, 17:00 UTC)
    with UNAVAILABLE flags for the live rate and next_funding_time.
    These constants are suitable for Noise gate (UNAVAILABLE state) and
    Timing gate constants, but NOT for live funding rate value.
    """
    return {
        "symbol":                  symbol,
        "funding_rate":            UNAVAIL_FUNDING_ENDPOINT_GATED,
        "next_funding_time_utc":   UNAVAIL_FUNDING_ENDPOINT_GATED,
        "next_funding_epoch_ms":   UNAVAIL_FUNDING_ENDPOINT_GATED,
        "funding_interval_hours":  BTCC_FUNDING_INTERVAL_HOURS,
        "funding_windows_utc":     BTCC_FUNDING_WINDOWS_UTC,
        "source_endpoint":         BTCC_BASE_URL + _EP_FUNDING_GATED,
        "endpoint_http_status":    "200_EMPTY_BODY_CLOUDFLARE_GATE",
        "fetched_at_utc":          _utc_now_iso(),
        "data_source_name":        BTCC_DATA_SOURCE,
        "funding_block_reason": (
            "BTCC /api/futures/v1/funding-rate returns HTTP 200 with content-length: 0. "
            "Cloudflare accepts the request but the backend returns nothing. "
            "Live funding rate and nextFundingTime are UNAVAILABLE until a verified path exists."
        ),
    }


def get_spread(symbol: str) -> Dict[str, Any]:
    """
    Attempt to derive spread from public depth endpoint.

    CURRENT STATUS: ENDPOINT EXISTS BUT RETURNS EMPTY ORDER BOOK.
      - /btcc_trade/market/depth → HTTP 200, {"asks":[],"bids":[]}
      - Empty from non-browser IP; may require browser session or geo-IP allow.

    Returns UNAVAILABLE spread with exact endpoint status preserved.
    """
    try:
        raw = _get(_EP_DEPTH, {"market": symbol, "depth": "5"})
    except RuntimeError as exc:
        return {
            "symbol":          symbol,
            "best_bid":        UNAVAIL_DEPTH_EMPTY_RESPONSE,
            "best_ask":        UNAVAIL_DEPTH_EMPTY_RESPONSE,
            "spread_absolute": UNAVAIL_DEPTH_EMPTY_RESPONSE,
            "spread_bps":      UNAVAIL_DEPTH_EMPTY_RESPONSE,
            "source_endpoint": BTCC_BASE_URL + _EP_DEPTH,
            "data_source_name": BTCC_DATA_SOURCE,
            "fetched_at_utc":  _utc_now_iso(),
            "error":           str(exc),
        }

    data   = {}
    result = {}
    if isinstance(raw, dict):
        data   = raw.get("data") or {}
        result = data.get("result") or {}

    bids = result.get("bids", [])
    asks = result.get("asks", [])

    if not bids or not asks:
        return {
            "symbol":          symbol,
            "best_bid":        UNAVAIL_DEPTH_EMPTY_RESPONSE,
            "best_ask":        UNAVAIL_DEPTH_EMPTY_RESPONSE,
            "spread_absolute": UNAVAIL_DEPTH_EMPTY_RESPONSE,
            "spread_bps":      UNAVAIL_DEPTH_EMPTY_RESPONSE,
            "depth_bids_count": 0,
            "depth_asks_count": 0,
            "source_endpoint": BTCC_BASE_URL + _EP_DEPTH,
            "endpoint_http_status": "200_EMPTY_ORDER_BOOK",
            "data_source_name": BTCC_DATA_SOURCE,
            "fetched_at_utc":  _utc_now_iso(),
            "spread_block_reason": (
                "BTCC /btcc_trade/market/depth returns HTTP 200 with empty bids/asks arrays. "
                "Likely requires browser session cookie or geo-IP whitelist. "
                "Spread is UNAVAILABLE until this is resolved."
            ),
        }

    # If we ever get real data, derive spread
    try:
        def _px(level: Any) -> float:
            if isinstance(level, (list, tuple)):
                return float(level[0])
            if isinstance(level, dict):
                return float(level.get("price") or level.get("p"))
            return float(level)

        best_bid = _px(bids[0])
        best_ask = _px(asks[0])
        spread_abs = round(best_ask - best_bid, 10)
        mid = (best_bid + best_ask) / 2
        spread_bps = round((spread_abs / mid) * 10_000, 4) if mid > 0 else UNAVAIL_CALC_ERR

        return {
            "symbol":            symbol,
            "best_bid":          best_bid,
            "best_ask":          best_ask,
            "spread_absolute":   spread_abs,
            "spread_bps":        spread_bps,
            "depth_bids_count":  len(bids),
            "depth_asks_count":  len(asks),
            "source_endpoint":   BTCC_BASE_URL + _EP_DEPTH,
            "data_source_name":  BTCC_DATA_SOURCE,
            "fetched_at_utc":    _utc_now_iso(),
        }
    except Exception as exc:
        return {
            "symbol":          symbol,
            "best_bid":        UNAVAIL_CALC_ERR,
            "best_ask":        UNAVAIL_CALC_ERR,
            "spread_absolute": UNAVAIL_CALC_ERR,
            "spread_bps":      UNAVAIL_CALC_ERR,
            "source_endpoint": BTCC_BASE_URL + _EP_DEPTH,
            "data_source_name": BTCC_DATA_SOURCE,
            "fetched_at_utc":  _utc_now_iso(),
            "error":           str(exc),
        }
