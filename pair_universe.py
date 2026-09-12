"""
sentinel/pair_universe.py
=========================
Lifted from battlefield's pair universe. Two additions on top of the original:

1. XYZ100 removed (delisted per user)
2. fetch_5m_candles() method added — sentinels need 5-min OHLC for features

Everything else is unchanged from the working battlefield version.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
import json
import time
import urllib.parse
import urllib.request


PROP_SYMBOLS = [
    "AAVE", "ADA", "AIXBT", "ALGO", "APT", "ARB", "ASTER", "ATOM", "AVAX",
    "BCH", "BNB", "BTC", "CRV", "DOGE", "DOT", "ETC", "ETH", "FARTCOIN",
    "FIL", "GRASS", "HBAR", "HYPE", "INJ", "JTO", "JUP", "NEAR", "ONDO",
    "OP", "PENGU", "PNUT", "POL", "POPCAT", "PUMP", "RENDER", "S", "SOL",
    "STX", "SUI", "TAO", "TIA", "TRUMP", "TRX", "UNI", "VIRTUAL", "WIF",
    "WLD", "XPL", "XRP", "ZEC",
]

KRAKEN_ALIASES = {
    "BTC": ["XBTUSD", "XXBTZUSD"],
    "DOGE": ["XDGUSD", "XXDGZUSD"],
    "XRP": ["XRPUSD", "XXRPZUSD"],
}

KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker?pair="
KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
OHLC_CONTEXT_CACHE: Dict[str, Dict[str, Any]] = {}
OHLC_CONTEXT_CACHE_SECONDS = 300.0

OHLC_5M_CACHE: Dict[str, Dict[str, Any]] = {}
OHLC_5M_CACHE_SECONDS = 250.0


@dataclass
class PairContext:
    symbol: str
    base: str = ""
    quote: str = "USD"
    timeframe: str = "5m"
    exchange: str = "kraken"
    last_price: Optional[float] = None
    is_tradeable: bool = True
    market_active: bool = False
    data_fresh: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    candles_5m: Optional[List[Dict[str, float]]] = None


class MarketDataSource:
    def _ticker_candidates(self, base: str) -> List[str]:
        candidates = list(KRAKEN_ALIASES.get(base, []))
        candidates.append(base + "USD")
        candidates.append(base + "/USD")
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _ticker_price(ticker: Dict[str, Any], key: str) -> Optional[float]:
        values = ticker.get(key) or []
        if not values:
            return None
        try:
            value = float(values[0])
            return value if value > 0 else None
        except (TypeError, ValueError):
            return None

    def fetch_5m_candles(self, base: str, min_candles: int = 30) -> Optional[List[Dict[str, float]]]:
        cache_key = str(base).upper()
        now_epoch = time.time()
        cached = OHLC_5M_CACHE.get(cache_key)
        if cached and (now_epoch - float(cached.get("_cached_at", 0.0)) < OHLC_5M_CACHE_SECONDS):
            return cached.get("candles")

        for candidate in self._ticker_candidates(base):
            url = KRAKEN_OHLC_URL + "?pair=" + urllib.parse.quote(candidate, safe="") + "&interval=5"
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "JHL-Oracle/1.0"})
                with urllib.request.urlopen(request, timeout=15) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("error"):
                    continue
                result = payload.get("result") or {}
                candle_key = next((key for key in result.keys() if key != "last"), None)
                candles = result.get(candle_key) if candle_key else None
                if not candles or len(candles) < min_candles:
                    continue
                parsed = []
                for candle in candles[-101:-1]:
                    try:
                        parsed.append({
                            "open":   float(candle[1]),
                            "high":   float(candle[2]),
                            "low":    float(candle[3]),
                            "close":  float(candle[4]),
                            "volume": float(candle[6]),
                        })
                    except (TypeError, ValueError, IndexError):
                        continue
                if len(parsed) < min_candles:
                    continue
                OHLC_5M_CACHE[cache_key] = {"candles": parsed, "_cached_at": now_epoch}
                return parsed
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return None
