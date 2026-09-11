"""PRISM Runtime Snapshot v1 — read-only, non-fixture market-map source.

Fetches Kraken public 15-minute OHLC data for the fixed 49-pair universe,
uses completed candles only, and writes a separate runtime snapshot.
It has no orders, trade authority, entry authority, alerts, queue mutation,
GitHub publishing, or execution behavior.
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = ROOT / "prism_runtime_snapshot_v1.json"

RECORDTYPE = "PRISMRUNTIMESNAPSHOT"
SCHEMA_VERSION = "prism.runtime-snapshot.v1"
VENUE = "KRAKEN_SPOT"
UNIVERSE = "APRIL_12_FIXED"
TIMEFRAME = "15m"
INTERVAL_MINUTES = 15
INTERVAL_SECONDS = INTERVAL_MINUTES * 60
MIN_HISTORY_BARS = 390
SHORT_WINDOW_BARS = 20
MEDIUM_WINDOW_BARS = 60
LONG_WINDOW_BARS = 200

APRIL_12_FIXED_PAIRS: Tuple[str, ...] = (
    "AAVE/USD", "ADA/USD", "ALGO/USD", "ARB/USD", "ATOM/USD", "AVAX/USD",
    "BTC/USD", "BCH/USD", "BONK/USD", "DOGE/USD", "DOT/USD", "ETH/USD",
    "ETC/USD", "FET/USD", "FIL/USD", "INJ/USD", "LINK/USD", "LTC/USD",
    "MATIC/USD", "NEAR/USD", "OP/USD", "PEPE/USD", "POL/USD", "RNDR/USD",
    "SEI/USD", "SHIB/USD", "SOL/USD", "SUI/USD", "TIA/USD", "TON/USD",
    "TRX/USD", "UNI/USD", "WIF/USD", "XLM/USD", "XRP/USD", "XTZ/USD",
    "APT/USD", "CRV/USD", "DYDX/USD", "EGLD/USD", "ICP/USD", "IMX/USD",
    "KAS/USD", "LDO/USD", "RUNE/USD", "STX/USD", "TAO/USD", "WLD/USD",
    "ZRX/USD",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _kraken_pair_name(pair: str) -> str:
    base, quote = pair.split("/")
    aliases = {"BTC": "XBT", "DOGE": "XDG"}
    return f"{aliases.get(base, base)}{aliases.get(quote, quote)}"


def _unavailable_card(pair: str, state: str, reason: str, *, bar_count: int = 0,
                      last_completed_candle_utc: Optional[str] = None) -> Dict[str, Any]:
    return {
        "pair": pair,
        "source_health": {
            "state": state,
            "source": "kraken_spot_ohlc",
            "timeframe": TIMEFRAME,
            "last_completed_candle_utc": last_completed_candle_utc,
            "bar_count": bar_count,
            "required_bar_count": MIN_HISTORY_BARS,
            "reason_codes": [reason],
        },
        "context": {
            "direction": "UNAVAILABLE",
            "regime": "UNAVAILABLE",
            "location": "UNAVAILABLE",
            "activity_state": "UNAVAILABLE",
            "volatility_state": "UNAVAILABLE",
            "available_distance": "UNAVAILABLE",
        },
        "construction": {
            "state": "UNAVAILABLE",
            "previous": {"label": "UNAVAILABLE", "direction": "UNAVAILABLE", "confidence": "UNAVAILABLE"},
            "current": {"label": "UNAVAILABLE", "direction": "UNAVAILABLE", "confidence": "UNAVAILABLE"},
            "transition": {"label": "UNAVAILABLE", "status": "UNAVAILABLE"},
        },
        "fair_price": {"state": "UNAVAILABLE", "reason": reason},
        "band_travel": {"state": "UNAVAILABLE", "reason": reason},
        "routes_ranked": [],
        "risk": {"state": "UNAVAILABLE", "risk_reasons": [reason]},
        "display": {
            "attention_state": "UNAVAILABLE",
            "manual_review_only": True,
            "entry_authority": False,
            "summary": "PRISM runtime map unavailable; no replacement map, route, or risk field was inferred.",
        },
    }


def _fetch_ohlc(pair: str) -> List[Dict[str, float]]:
    query = urllib.parse.urlencode({"pair": _kraken_pair_name(pair), "interval": INTERVAL_MINUTES})
    request = urllib.request.Request(
        f"https://api.kraken.com/0/public/OHLC?{query}",
        headers={"User-Agent": "prism-runtime-snapshot/1.0"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError("KRAKEN_ERROR")
    result = payload.get("result") or {}
    series_key = next((key for key in result if key != "last"), None)
    rows = result.get(series_key or "", [])
    candles: List[Dict[str, float]] = []
    for row in rows[:-1]:
        candles.append({
            "ts": float(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[6]),
        })
    return candles


def _valid_candles(candles: Sequence[Dict[str, float]]) -> Tuple[bool, str]:
    if len(candles) < MIN_HISTORY_BARS:
        return False, "PRISM.DATA.INSUFFICIENT_HISTORY"
    prior_ts: Optional[float] = None
    for candle in candles:
        try:
            ts = float(candle["ts"])
            open_ = float(candle["open"])
            high = float(candle["high"])
            low = float(candle["low"])
            close = float(candle["close"])
            volume = float(candle["volume"])
        except (KeyError, TypeError, ValueError):
            return False, "PRISM.DATA.INVALID_OHLCV"
        values = (ts, open_, high, low, close, volume)
        if not all(math.isfinite(value) for value in values):
            return False, "PRISM.DATA.INVALID_OHLCV"
        if min(open_, high, low, close) <= 0 or volume < 0:
            return False, "PRISM.DATA.INVALID_OHLCV"
        if low > min(open_, close) or high < max(open_, close):
            return False, "PRISM.DATA.INVALID_OHLCV"
        if prior_ts is not None and ts - prior_ts != INTERVAL_SECONDS:
            return False, "PRISM.DATA.MISSING_BARS"
        prior_ts = ts
    if sum(float(candle["volume"]) for candle in candles) <= 0:
        return False, "PRISM.DATA.ZERO_TOTAL_VOLUME"
    return True, ""


def _ema(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = fmean(values[:period])
    for item in values[period:]:
        value = alpha * item + (1.0 - alpha) * value
    return value


def _atr(candles: Sequence[Dict[str, float]], period: int = 14) -> Optional[float]:
    if len(candles) < period + 1:
        return None
    values: List[float] = []
    for index in range(1, len(candles)):
        current, previous = candles[index], candles[index - 1]
        values.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        ))
    return fmean(values[-period:]) if values else None


def _direction(return_value: float, threshold: float = 0.0015) -> str:
    if return_value > threshold:
        return "UP"
    if return_value < -threshold:
        return "DOWN"
    return "NEUTRAL"


def _confidence(value: float) -> str:
    absolute = abs(value)
    if absolute >= 0.012:
        return "HIGH"
    if absolute >= 0.004:
        return "MODERATE"
    return "LOW"


def _segment(candles: Sequence[Dict[str, float]]) -> Dict[str, Any]:
    closes = [float(candle["close"]) for candle in candles]
    highs = [float(candle["high"]) for candle in candles]
    lows = [float(candle["low"]) for candle in candles]
    volumes = [float(candle["volume"]) for candle in candles]
    start, end = closes[0], closes[-1]
    return_value = (end - start) / start if start > 0 else 0.0
    average_range = fmean(max(high - low, 1e-12) for high, low in zip(highs, lows))
    average_volume = fmean(volumes)
    direction = _direction(return_value)
    range_pct = average_range / max(fmean(closes), 1e-12)

    if direction == "NEUTRAL":
        label = "BALANCE"
    elif abs(return_value) >= 0.018 and range_pct >= 0.003:
        label = "IMPULSE_EXPANSION"
    elif abs(return_value) >= 0.006:
        label = "STAIRSTEP_TREND"
    else:
        label = "DIRECTIONAL_DRIFT"

    return {
        "label": label,
        "direction": direction,
        "confidence": _confidence(return_value),
        "return_pct": round(return_value * 100.0, 4),
        "average_range_pct": round(range_pct * 100.0, 4),
        "average_volume": round(average_volume, 8),
    }


def _transition(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, str]:
    label = f"{previous['label']}_TO_{current['label']}"
    if previous["direction"] == current["direction"] and current["direction"] != "NEUTRAL":
        status = "CONFIRMED"
    elif current["direction"] == "NEUTRAL":
        status = "AMBIGUOUS"
    else:
        status = "TRANSITIONING"
    return {"label": label, "status": status}


def _classify(candles: Sequence[Dict[str, float]]) -> Dict[str, Any]:
    closes = [float(candle["close"]) for candle in candles]
    price = closes[-1]
    atr = _atr(candles)
    ema20 = _ema(closes, SHORT_WINDOW_BARS)
    ema60 = _ema(closes, MEDIUM_WINDOW_BARS)
    ema200 = _ema(closes, LONG_WINDOW_BARS)
    if atr is None or ema20 is None or ema60 is None or ema200 is None:
        raise ValueError("PRISM.DATA.INDICATORS_UNAVAILABLE")

    current = _segment(candles[-SHORT_WINDOW_BARS:])
    previous = _segment(candles[-2 * SHORT_WINDOW_BARS:-SHORT_WINDOW_BARS])
    transition = _transition(previous, current)

    direction = "UP" if ema20 > ema60 > ema200 and price >= ema20 else (
        "DOWN" if ema20 < ema60 < ema200 and price <= ema20 else "NEUTRAL"
    )
    atr_pct = atr / price
    recent_return = (price - closes[-5]) / closes[-5] if closes[-5] else 0.0

    if atr_pct >= 0.05:
        regime = "DISORDERLY"
    elif direction == "UP":
        regime = "TREND_UP"
    elif direction == "DOWN":
        regime = "TREND_DOWN"
    elif abs(recent_return) >= max(atr_pct, 1e-12):
        regime = "EXPANSION"
    else:
        regime = "BALANCE"

    distance_from_ema = abs(price - ema20) / max(atr, 1e-12)
    if distance_from_ema <= 0.6:
        location = "FAIR_VALUE_PROXIMATE"
    elif direction == "UP" and price > ema20:
        location = "EXTENDED_UP"
    elif direction == "DOWN" and price < ema20:
        location = "EXTENDED_DOWN"
    else:
        location = "DISLOCATED"

    recent_volumes = [float(candle["volume"]) for candle in candles[-SHORT_WINDOW_BARS:]]
    prior_volumes = [float(candle["volume"]) for candle in candles[-2 * SHORT_WINDOW_BARS:-SHORT_WINDOW_BARS]]
    volume_ratio = fmean(recent_volumes) / max(fmean(prior_volumes), 1e-12)
    activity_state = "EXPANDING" if volume_ratio >= 1.2 else "CONTRACTING" if volume_ratio <= 0.8 else "NORMAL"
    volatility_state = "DISORDERLY" if atr_pct >= 0.05 else "EXPANDING" if atr_pct >= 0.025 else "NORMAL"

    return {
        "context": {
            "direction": direction,
            "regime": regime,
            "location": location,
            "activity_state": activity_state,
            "volatility_state": volatility_state,
            "available_distance": "UNAVAILABLE",
        },
        "construction": {
            "state": "AVAILABLE",
            "previous": previous,
            "current": current,
            "transition": transition,
        },
        "fair_price": {
            "state": "UNAVAILABLE",
            "reason": "PRISM.RUNTIME.V1.FAIR_PRICE_NOT_IMPLEMENTED",
        },
        "band_travel": {
            "state": "UNAVAILABLE",
            "reason": "PRISM.RUNTIME.V1.BAND_TRAVEL_NOT_IMPLEMENTED",
        },
        "routes_ranked": [],
        "risk": {
            "state": "UNAVAILABLE",
            "risk_reasons": [
                "PRISM.RUNTIME.V1.NO_FAIR_PRICE_ROUTE",
                "PRISM.RUNTIME.V1.NO_BAND_TRAVEL_ROUTE",
            ],
        },
    }


def build_card(pair: str, candles: Sequence[Dict[str, float]]) -> Dict[str, Any]:
    last_completed = _utc_from_epoch(float(candles[-1]["ts"])) if candles else None
    valid, reason = _valid_candles(candles)
    if not valid:
        state = "INSUFFICIENT_HISTORY" if reason == "PRISM.DATA.INSUFFICIENT_HISTORY" else (
            "MISSING_BARS" if reason == "PRISM.DATA.MISSING_BARS" else "INVALID"
        )
        return _unavailable_card(pair, state, reason, bar_count=len(candles), last_completed_candle_utc=last_completed)

    try:
        classified = _classify(candles)
    except Exception:
        return _unavailable_card(
            pair, "INVALID", "PRISM.DATA.CLASSIFICATION_UNAVAILABLE",
            bar_count=len(candles), last_completed_candle_utc=last_completed,
        )

    return {
        "pair": pair,
        "source_health": {
            "state": "AVAILABLE",
            "source": "kraken_spot_ohlc",
            "timeframe": TIMEFRAME,
            "last_completed_candle_utc": last_completed,
            "bar_count": len(candles),
            "required_bar_count": MIN_HISTORY_BARS,
            "reason_codes": [],
        },
        **classified,
        "display": {
            "attention_state": "OBSERVE",
            "manual_review_only": True,
            "entry_authority": False,
            "summary": "Runtime PRISM map is descriptive only; no trade authority or combined score.",
        },
    }


def build_snapshot(fetcher=_fetch_ohlc) -> Dict[str, Any]:
    cards: List[Dict[str, Any]] = []
    for pair in APRIL_12_FIXED_PAIRS:
        try:
            cards.append(build_card(pair, fetcher(pair)))
        except Exception:
            cards.append(_unavailable_card(pair, "MARKET_DATA_UNAVAILABLE", "PRISM.DATA.MARKET_DATA_UNAVAILABLE"))

    if len(cards) != 49 or [card["pair"] for card in cards] != list(APRIL_12_FIXED_PAIRS):
        raise RuntimeError("PRISM.RUNTIME.FIXED_UNIVERSE_CONTRACT_FAILED")

    states = [card["source_health"]["state"] for card in cards]
    return {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "venue": VENUE,
        "universe": UNIVERSE,
        "source_kind": "runtime_market_data",
        "fixture_market_source": False,
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
        "configuration": {
            "timeframe": TIMEFRAME,
            "interval_seconds": INTERVAL_SECONDS,
            "minimum_history_bars": MIN_HISTORY_BARS,
            "source": "kraken_spot_ohlc",
            "calculation_scope": "runtime_prism_context_construction_v1",
        },
        "health": {
            "expected_pair_count": 49,
            "observed_pair_count": len(cards),
            "available_count": states.count("AVAILABLE"),
            "insufficient_history_count": states.count("INSUFFICIENT_HISTORY"),
            "missing_bars_count": states.count("MISSING_BARS"),
            "invalid_count": states.count("INVALID"),
            "market_data_unavailable_count": states.count("MARKET_DATA_UNAVAILABLE"),
        },
        "cards": cards,
    }


def write_snapshot(payload: Dict[str, Any], output_path: Path = OUTPUT_PATH) -> None:
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output_path)


def main() -> None:
    payload = build_snapshot()
    write_snapshot(payload)
    health = payload["health"]
    print(f"PRISM runtime snapshot written: {OUTPUT_PATH}")
    print(
        f"Cards: {health['observed_pair_count']} | Available: {health['available_count']} | "
        f"Insufficient history: {health['insufficient_history_count']} | "
        f"Missing bars: {health['missing_bars_count']} | "
        f"Market unavailable: {health['market_data_unavailable_count']}"
    )


if __name__ == "__main__":
    main()