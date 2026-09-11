"""
pair_universe.py — JHL Eight Gates Pair Universe
=================================================
49-pair Kraken ticker fetcher with batch loading, alias resolution,
hard sanity checks, and 5m OHLC fetch for gate feature computation.

Ported from battlefield/pairuniverse.py + sentinals/pair_universe.py.
XYZ100 and S&P500 removed (no Kraken spot ticker).
ADA included but flagged for quarantine by scanner.

No orders. No execution. Read-only market data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
import json
import time
import urllib.parse
import urllib.request

# ── 49-pair universe (prop platform list, indices removed) ────────────────────
PROP_SYMBOLS = [
    "AAVE", "ADA", "AIXBT", "ALGO", "APT", "ARB", "ASTER", "ATOM", "AVAX",
    "BCH", "BNB", "BTC", "CRV", "DOGE", "DOT", "ETC", "ETH", "FARTCOIN",
    "FIL", "GRASS", "HBAR", "HYPE", "INJ", "JTO", "JUP", "NEAR", "ONDO",
    "OP", "PENGU", "PNUT", "POL", "POPCAT", "PUMP", "RENDER", "S", "SOL",
    "STX", "SUI", "TAO", "TIA", "TRUMP", "TRX", "UNI", "VIRTUAL", "WIF",
    "WLD", "XPL", "XRP", "ZEC",
]

# ADA quarantined from EXECUTION_ELIGIBLE until outcomes prove otherwise
ADA_QUARANTINE = {"ADA"}

# Explicit Kraken USD ticker map (confirmed live)
KRAKEN_USD_TICKERS: Dict[str, str] = {
    "AAVE": "AAVEUSD",
    "ADA": "ADAUSD",
    "AIXBT": "AIXBTUSD",
    "ALGO": "ALGOUSD",
    "APT": "APTUSD",
    "ARB": "ARBUSD",
    "ASTER": "ASTERUSD",
    "ATOM": "ATOMUSD",
    "AVAX": "AVAXUSD",
    "BCH": "BCHUSD",
    "BNB": "BNBUSD",
    "BTC": "XBTUSD",
    "CRV": "CRVUSD",
    "DOGE": "XDGUSD",
    "DOT": "DOTUSD",
    "ETC": "ETCUSD",
    "ETH": "ETHUSD",
    "FARTCOIN": "FARTCOINUSD",
    "FIL": "FILUSD",
    "GRASS": "GRASSUSD",
    "HBAR": "HBARUSD",
    "HYPE": "HYPEUSD",
    "INJ": "INJUSD",
    "JTO": "JTOUSD",
    "JUP": "JUPUSD",
    "NEAR": "NEARUSD",
    "ONDO": "ONDOUSD",
    "OP": "OPUSD",
    "PENGU": "PENGUUSD",
    "PNUT": "PNUTUSD",
    "POL": "POLUSD",
    "POPCAT": "POPCATUSD",
    "PUMP": "PUMPUSD",
    "RENDER": "RENDERUSD",
    "S": "SUSD",
    "SOL": "SOLUSD",
    "STX": "STXUSD",
    "SUI": "SUIUSD",
    "TAO": "TAOUSD",
    "TIA": "TIAUSD",
    "TRUMP": "TRUMPUSD",
    "TRX": "TRXUSD",
    "UNI": "UNIUSD",
    "VIRTUAL": "VIRTUALUSD",
    "WIF": "WIFUSD",
    "WLD": "WLDUSD",
    "XPL": "XPLUSD",
    "XRP": "XRPUSD",
    "ZEC": "ZECUSD",
}

KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"
KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
REQUEST_TIMEOUT_SECONDS = 15
QUOTE_MAX_AGE_SECONDS = 90
BATCH_SIZE = 18

# 5m OHLC cache — refreshes every ~250s inside a 300s cycle
OHLC_5M_CACHE: Dict[str, Dict[str, Any]] = {}
OHLC_5M_CACHE_SECONDS = 250.0

# 15m OHLC cache for gate feature computation
OHLC_15M_CACHE: Dict[str, Dict[str, Any]] = {}
OHLC_15M_CACHE_SECONDS = 250.0


@dataclass
class PairContext:
    symbol: str
    base: str = ""
    quote: str = "USD"
    kraken_ticker: str = ""
    last_price: Optional[float] = None
    is_tradeable: bool = True
    market_active: bool = False
    data_fresh: bool = False
    quarantined: bool = False          # ADA quarantine flag
    candles_5m: Optional[List[Dict[str, float]]] = None
    candles_15m: Optional[List[Dict[str, float]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class MarketDataSource:
    def __init__(
        self,
        timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
        quote_max_age_seconds: int = QUOTE_MAX_AGE_SECONDS,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.quote_max_age_seconds = quote_max_age_seconds

    def _get_json(self, url: str) -> Dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "JHL-EightGates/1.0"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        errors = payload.get("error") or []
        if errors:
            raise RuntimeError("Kraken API error: " + "; ".join(str(e) for e in errors))
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Kraken API returned no result object")
        return result

    def _ticker_batch(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        if not tickers:
            return {}
        query = urllib.parse.urlencode({"pair": ",".join(tickers)})
        result = self._get_json(f"{KRAKEN_TICKER_URL}?{query}")
        fetched_at = datetime.now(timezone.utc).isoformat()
        quotes: Dict[str, Dict[str, Any]] = {}
        for kraken_pair, ticker in result.items():
            if not isinstance(ticker, dict):
                continue
            close = ticker.get("c") or []
            try:
                price = float(close[0])
            except (IndexError, TypeError, ValueError):
                continue
            if price <= 0:
                continue
            quotes[str(kraken_pair).upper()] = {
                "last_price": price,
                "kraken_pair": str(kraken_pair),
                "quote_timestamp": fetched_at,
                "quote_age_seconds": 0.0,
                "source": "kraken_public_ticker",
            }
        return quotes

    def fetch_ohlc(self, symbol: str, interval_minutes: int = 15, min_candles: int = 30) -> Optional[List[Dict[str, float]]]:
        """Fetch completed OHLCV candles for a symbol. Skips the live incomplete bar."""
        cache = OHLC_15M_CACHE if interval_minutes == 15 else OHLC_5M_CACHE
        cache_ttl = OHLC_15M_CACHE_SECONDS if interval_minutes == 15 else OHLC_5M_CACHE_SECONDS
        cache_key = f"{symbol}_{interval_minutes}"
        now_epoch = time.time()
        cached = cache.get(cache_key)
        if cached and (now_epoch - float(cached.get("_cached_at", 0.0)) < cache_ttl):
            return cached.get("candles")

        kraken_ticker = KRAKEN_USD_TICKERS.get(symbol)
        if not kraken_ticker:
            return None

        candidates = [kraken_ticker]
        # Try fallback symbol directly if ticker map entry fails
        candidates.append(symbol + "USD")

        for candidate in candidates:
            url = f"{KRAKEN_OHLC_URL}?pair={urllib.parse.quote(candidate, safe='')}&interval={interval_minutes}"
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "JHL-EightGates/1.0"})
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("error"):
                    continue
                result = payload.get("result") or {}
                candle_key = next((k for k in result.keys() if k != "last"), None)
                raw_candles = result.get(candle_key) if candle_key else None
                if not raw_candles or len(raw_candles) < min_candles + 1:
                    continue
                # Skip last (incomplete) bar
                parsed = []
                for candle in raw_candles[-101:-1]:
                    try:
                        parsed.append({
                            "ts": int(float(candle[0])),
                            "open": float(candle[1]),
                            "high": float(candle[2]),
                            "low": float(candle[3]),
                            "close": float(candle[4]),
                            "volume": float(candle[6]),
                        })
                    except (TypeError, ValueError, IndexError):
                        continue
                if len(parsed) < min_candles:
                    continue
                cache[cache_key] = {"candles": parsed, "_cached_at": now_epoch}
                return parsed
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return None

    def fetch_pairs(self) -> List[Dict[str, Any]]:
        requested = {
            symbol: ticker
            for symbol, ticker in KRAKEN_USD_TICKERS.items()
            if symbol in PROP_SYMBOLS
        }
        quotes_by_ticker: Dict[str, Dict[str, Any]] = {}
        ticker_names = list(requested.values())

        # Batched fetch
        for start in range(0, len(ticker_names), BATCH_SIZE):
            batch = ticker_names[start: start + BATCH_SIZE]
            try:
                response_quotes = self._ticker_batch(batch)
            except Exception as exc:
                print(f"KRAKEN_TICKER_BATCH_ERROR {type(exc).__name__}: {exc}")
                response_quotes = {}
            for ticker_name in batch:
                if ticker_name.upper() in response_quotes:
                    quotes_by_ticker[ticker_name.upper()] = response_quotes[ticker_name.upper()]
            if start + BATCH_SIZE < len(ticker_names):
                time.sleep(0.25)

        # Individual fallback for any missed
        for ticker_name in ticker_names:
            if ticker_name.upper() in quotes_by_ticker:
                continue
            try:
                response_quotes = self._ticker_batch([ticker_name])
                if response_quotes:
                    quote = next(iter(response_quotes.values()))
                    quotes_by_ticker[ticker_name.upper()] = quote
            except Exception:
                pass
            time.sleep(0.08)

        rows: List[Dict[str, Any]] = []
        unavailable: List[str] = []
        for symbol in PROP_SYMBOLS:
            ticker_name = requested.get(symbol)
            if not ticker_name:
                unavailable.append(symbol)
                continue
            quote = quotes_by_ticker.get(ticker_name.upper())
            if quote is None:
                unavailable.append(symbol)
                continue
            rows.append({
                "symbol": symbol,
                "kraken_ticker": ticker_name,
                "last_price": quote["last_price"],
                "is_tradeable": True,
                "market_active": True,
                "data_fresh": quote["quote_age_seconds"] <= self.quote_max_age_seconds,
                "source": quote["source"],
                "quote_timestamp": quote["quote_timestamp"],
                "quote_age_seconds": quote["quote_age_seconds"],
                "kraken_pair": quote["kraken_pair"],
            })
        print(f"KRAKEN_PRICE_ROWS {len(rows)}")
        if unavailable:
            print(f"KRAKEN_PRICE_UNAVAILABLE {','.join(unavailable)}")
        return rows


class PairUniverse:
    def __init__(self, market_data_source: Optional[MarketDataSource] = None) -> None:
        self.market_data_source = market_data_source or MarketDataSource()
        self.whitelist = set(PROP_SYMBOLS)

    def get_active_pairs(self) -> List[PairContext]:
        rows = self.market_data_source.fetch_pairs()
        active_pairs: List[PairContext] = []
        for row in rows:
            pair = self._build_pair_context(row)
            if pair is None:
                continue
            if not self._passes_hard_sanity(pair):
                print(f"REJECTED_NONLIVE_PAIR {pair.symbol}")
                continue
            # Enrich with OHLC candles
            pair.candles_15m = self.market_data_source.fetch_ohlc(pair.symbol, interval_minutes=15)
            pair.candles_5m = self.market_data_source.fetch_ohlc(pair.symbol, interval_minutes=5)
            time.sleep(0.08)
            active_pairs.append(pair)
        print(f"ACTIVE_PAIRS {len(active_pairs)}")
        return active_pairs

    def _build_pair_context(self, row: Dict[str, Any]) -> Optional[PairContext]:
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol or symbol not in self.whitelist:
            return None
        try:
            last_price = float(row.get("last_price"))
        except (TypeError, ValueError):
            last_price = None
        try:
            quote_age_seconds = float(row.get("quote_age_seconds", 0))
        except (TypeError, ValueError):
            quote_age_seconds = None

        metadata = {
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            "source": str(row.get("source") or "unknown"),
            "quote_timestamp": row.get("quote_timestamp"),
            "quote_age_seconds": quote_age_seconds,
            "kraken_pair": row.get("kraken_pair"),
            "data_fresh": bool(row.get("data_fresh", False)),
        }
        return PairContext(
            symbol=symbol,
            base=symbol,
            quote="USD",
            kraken_ticker=str(row.get("kraken_ticker") or ""),
            last_price=last_price,
            is_tradeable=bool(row.get("is_tradeable", True)),
            market_active=bool(row.get("market_active", False)),
            data_fresh=bool(row.get("data_fresh", False)),
            quarantined=(symbol in ADA_QUARANTINE),
            metadata=metadata,
        )

    @staticmethod
    def _passes_hard_sanity(pair: PairContext) -> bool:
        try:
            quote_age = float(pair.metadata.get("quote_age_seconds", 999))
        except (TypeError, ValueError):
            return False
        return bool(
            pair.is_tradeable
            and pair.market_active
            and pair.data_fresh
            and quote_age <= QUOTE_MAX_AGE_SECONDS
            and pair.last_price is not None
            and pair.last_price > 0
        )
