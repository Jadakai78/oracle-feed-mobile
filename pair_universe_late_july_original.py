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
    "WLD", "XPL", "XRP", "XYZ100", "ZEC",
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


@dataclass
class PairContext:
    symbol: str
    base: str = ""
    quote: str = "USD"
    timeframe: str = "15m"
    exchange: str = "kraken"
    last_price: Optional[float] = None
    is_tradeable: bool = True
    market_active: bool = False
    data_fresh: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


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

    def _live_quote(self, base: str) -> Optional[Dict[str, Any]]:
        for candidate in self._ticker_candidates(base):
            url = KRAKEN_TICKER_URL + urllib.parse.quote(candidate, safe="")

            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "JHL-Oracle/1.0"},
                )

                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))

                if payload.get("error"):
                    continue

                result = payload.get("result") or {}

                for pair_name, ticker in result.items():
                    last_price = self._ticker_price(ticker, "c")
                    bid = self._ticker_price(ticker, "b")
                    ask = self._ticker_price(ticker, "a")

                    if (
                        last_price is None
                        or bid is None
                        or ask is None
                        or ask < bid
                    ):
                        continue

                    mid = (bid + ask) / 2.0
                    spread = ask - bid
                    spread_bps = (
                        (spread / mid) * 10000.0
                        if mid > 0
                        else None
                    )

                    return {
                        "last_price": last_price,
                        "bid": bid,
                        "ask": ask,
                        "mid_price": mid,
                        "spread": spread,
                        "spread_bps": spread_bps,
                        "kraken_pair": pair_name,
                        "quote_timestamp": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    }

            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue

        return None

    def _enrich_oracle_context(
        self,
        base: str,
        quote: Dict[str, Any],
    ) -> Dict[str, Any]:
        cache_key = str(base).upper()
        now_epoch = time.time()
        cached = OHLC_CONTEXT_CACHE.get(cache_key)

        if cached and (
            now_epoch - float(cached.get("_cached_at", 0.0))
            < OHLC_CONTEXT_CACHE_SECONDS
        ):
            return {
                key: value
                for key, value in cached.items()
                if key != "_cached_at"
            }

        for candidate in self._ticker_candidates(base):
            url = (
                KRAKEN_OHLC_URL
                + "?pair="
                + urllib.parse.quote(candidate, safe="")
                + "&interval=60"
            )

            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "JHL-Oracle/1.0"},
                )

                with urllib.request.urlopen(request, timeout=15) as response:
                    payload = json.loads(response.read().decode("utf-8"))

                if payload.get("error"):
                    continue

                result = payload.get("result") or {}
                candle_key = next(
                    (key for key in result.keys() if key != "last"),
                    None,
                )
                candles = result.get(candle_key) if candle_key else None

                if not candles or len(candles) < 25:
                    continue

                parsed = []
                for candle in candles[-100:-1]:
                    try:
                        parsed.append(
                            {
                                "high": float(candle[2]),
                                "low": float(candle[3]),
                                "close": float(candle[4]),
                            }
                        )
                    except (TypeError, ValueError, IndexError):
                        continue

                if len(parsed) < 25:
                    continue

                closes = [item["close"] for item in parsed]
                highs = [item["high"] for item in parsed]
                lows = [item["low"] for item in parsed]

                # EMA(20): v1 fair value, responsive enough for 1h context.
                ema_period = 20
                alpha = 2.0 / (ema_period + 1.0)
                fair_price = sum(closes[:ema_period]) / ema_period

                for close in closes[ema_period:]:
                    fair_price = (
                        close * alpha
                        + fair_price * (1.0 - alpha)
                    )

                # Wilder ATR(14) on completed 1h candles.
                tr_values = []
                previous_close = closes[0]

                for index in range(1, len(closes)):
                    true_range = max(
                        highs[index] - lows[index],
                        abs(highs[index] - previous_close),
                        abs(lows[index] - previous_close),
                    )
                    tr_values.append(true_range)
                    previous_close = closes[index]

                atr = None
                if len(tr_values) >= 14:
                    atr = sum(tr_values[:14]) / 14.0
                    for true_range in tr_values[14:]:
                        atr = ((atr * 13.0) + true_range) / 14.0

                momentum_bias = "neutral"
                if len(closes) >= 7 and fair_price > 0:
                    recent_move_pct = (
                        (closes[-1] - closes[-7]) / fair_price
                    )

                    if recent_move_pct >= 0.010:
                        momentum_bias = "trend"
                    elif recent_move_pct <= -0.010:
                        momentum_bias = "reversion"
                    elif abs(recent_move_pct) <= 0.0025:
                        momentum_bias = "stall"

                live_price = float(quote.get("last_price") or 0.0)
                fair_gap_bps = None

                if live_price > 0 and fair_price > 0:
                    fair_gap_bps = (
                        (live_price - fair_price) / fair_price
                    ) * 10000.0

                atr_pct = (
                    (atr / fair_price)
                    if atr is not None and fair_price > 0
                    else None
                )

                if atr_pct is None:
                    volatility_state = "normal"
                elif atr_pct >= 0.030:
                    volatility_state = "volatile"
                elif atr_pct <= 0.008:
                    volatility_state = "compression"
                else:
                    volatility_state = "normal"

                output = {
                    "fair_price": round(fair_price, 10),
                    "fair_gap_bps": (
                        round(fair_gap_bps, 4)
                        if fair_gap_bps is not None
                        else None
                    ),
                    "atr": (
                        round(atr, 10)
                        if atr is not None
                        else None
                    ),
                    "momentum_bias": momentum_bias,
                    "volatility_state": volatility_state,
                    "ohlc_context_source": "kraken_public_ohlc_1h",
                    "ohlc_context_pair": candle_key,
                    "ohlc_context_candles": len(parsed),
                }

                OHLC_CONTEXT_CACHE[cache_key] = {
                    **output,
                    "_cached_at": now_epoch,
                }

                return output

            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ):
                continue

        return {
            "fair_price": None,
            "fair_gap_bps": None,
            "atr": None,
            "momentum_bias": "neutral",
            "volatility_state": "normal",
            "ohlc_context_source": "unavailable",
            "ohlc_context_pair": None,
            "ohlc_context_candles": 0,
        }

    def fetch_pairs(self) -> Iterable[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []

        for base in PROP_SYMBOLS:
            quote = self._live_quote(base)

            if quote is None:
                print("NO_LIVE_KRAKEN_QUOTE", base)
                continue

            oracle_context = self._enrich_oracle_context(base, quote)

            rows.append(
                {
                    "symbol": base,
                    "base": base,
                    "quote": "USD",
                    "timeframe": "15m",
                    "exchange": "kraken",
                    "last_price": quote["last_price"],
                    "bid": quote["bid"],
                    "ask": quote["ask"],
                    "mid_price": quote["mid_price"],
                    "spread": quote["spread"],
                    "spread_bps": quote["spread_bps"],
                    "is_tradeable": True,
                    "market_active": True,
                    "data_fresh": True,
                    "source": "kraken_public_ticker",
                    "quote_timestamp": quote["quote_timestamp"],
                    "kraken_pair": quote["kraken_pair"],
                    **oracle_context,
                }
            )

            time.sleep(0.08)

        print("LIVE_KRAKEN_ROWS", len(rows))
        return rows


class PairUniverse:
    def __init__(
        self,
        market_data_source: Optional[MarketDataSource] = None,
    ) -> None:
        self.market_data_source = market_data_source or MarketDataSource()
        self.whitelist = set(PROP_SYMBOLS)

    def get_active_pairs(self) -> List[PairContext]:
        rows = list(self.market_data_source.fetch_pairs())
        print("PAIR_ROWS", len(rows))

        active_pairs: List[PairContext] = []

        for row in rows:
            pair = self._build_pair_context(row)

            if pair is None:
                continue

            if not self._passes_hard_sanity(pair):
                continue

            active_pairs.append(pair)

        print("ACTIVE_PAIRS", len(active_pairs))
        return active_pairs

    def _build_pair_context(
        self,
        row: Dict[str, Any],
    ) -> Optional[PairContext]:
        symbol = str(
            row.get("symbol") or row.get("base") or ""
        ).strip().upper()

        if not symbol or symbol not in self.whitelist:
            return None

        try:
            last_price = float(row.get("last_price"))
        except (TypeError, ValueError):
            last_price = None

        metadata = {
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            "source": row.get("source", "unknown"),
            "quote_timestamp": row.get("quote_timestamp"),
            "kraken_pair": row.get("kraken_pair"),
            "bid": row.get("bid"),
            "ask": row.get("ask"),
            "mid_price": row.get("mid_price"),
            "spread": row.get("spread"),
            "spread_bps": row.get("spread_bps"),
            "fair_price": row.get("fair_price"),
            "fair_gap_bps": row.get("fair_gap_bps"),
            "atr": row.get("atr"),
            "momentum_bias": row.get("momentum_bias"),
            "volatility_state": row.get("volatility_state"),
            "ohlc_context_source": row.get("ohlc_context_source"),
            "ohlc_context_pair": row.get("ohlc_context_pair"),
            "ohlc_context_candles": row.get("ohlc_context_candles"),
        }

        return PairContext(
            symbol=symbol,
            base=symbol,
            quote="USD",
            timeframe=str(row.get("timeframe") or "15m"),
            exchange=str(row.get("exchange") or "kraken"),
            last_price=last_price,
            is_tradeable=bool(row.get("is_tradeable", True)),
            market_active=bool(row.get("market_active", False)),
            data_fresh=bool(row.get("data_fresh", False)),
            metadata=metadata,
        )

    @staticmethod
    def _passes_hard_sanity(pair: PairContext) -> bool:
        metadata = pair.metadata or {}

        try:
            bid = float(metadata.get("bid"))
            ask = float(metadata.get("ask"))
        except (TypeError, ValueError):
            return False

        return bool(
            pair.is_tradeable
            and pair.market_active
            and pair.data_fresh
            and pair.last_price is not None
            and pair.last_price > 0
            and bid > 0
            and ask > 0
            and ask >= bid
        )

