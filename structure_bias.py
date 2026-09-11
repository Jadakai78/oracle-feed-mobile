"""
structure_bias.py — JHL Market Context

The matrix. Reads D1 and 4H (and 1H tempo) to tell the other bots
whether they are swimming with or against the current.

This bot does NOT generate trade signals.
It generates CONTEXT that amplifies or discounts specialists.

Outputs:
- market_condition — HTF structure state
- market_tempo — current movement state
- trend — combined D1/H4 trend (up/down/ranging)
- zone — premium / discount / neutral within D1 range
- alignment — HTF vs LTF flow alignment
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("structure_bias")

try:
    import tempo as _tempo_mod
    _TEMPO_AVAILABLE = True
except ImportError:
    _TEMPO_AVAILABLE = False


def _fetch_ohlc(kraken_pair: str, interval: int, limit: int = 60) -> Optional[List]:
    url = f"https://api.kraken.com/0/public/OHLC?pair={kraken_pair}&interval={interval}"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
        if data.get("error"):
            return None
        result = data.get("result", {})
        key = [k for k in result if k != "last"]
        if not key:
            return None
        return result[key[0]][-limit:]
    except Exception as e:
        logger.debug("OHLC fetch %s %s: %s", kraken_pair, interval, e)
        return None


def _to_arrays(rows: List) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    h = np.array([float(r[2]) for r in rows], dtype=float)
    l = np.array([float(r[3]) for r in rows], dtype=float)
    c = np.array([float(r[4]) for r in rows], dtype=float)
    v = np.array([float(r[6]) for r in rows], dtype=float)
    return h, l, c, v


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> float:
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1]))
    )
    if len(tr) < period:
        return float(np.mean(tr)) if len(tr) > 0 else 0.0
    return float(np.mean(tr[-period:]))


def _swing_structure(
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    lookback: int = 20,
) -> Tuple[str, float, float]:
    """
    Identify swing trend from last N candles.

    Returns:
        trend: 'up' | 'down' | 'ranging'
        last_swing_high
        last_swing_low
    """
    if len(h) < lookback or len(l) < lookback:
        return "ranging", float(h[-1]), float(l[-1])

    window_h = h[-lookback:]
    window_l = l[-lookback:]
    n = len(window_h)

    pivot_highs: List[float] = []
    pivot_lows: List[float] = []

    for i in range(2, n - 2):
        if (
            window_h[i] > window_h[i - 1]
            and window_h[i] > window_h[i - 2]
            and window_h[i] > window_h[i + 1]
            and window_h[i] > window_h[i + 2]
        ):
            pivot_highs.append(float(window_h[i]))

        if (
            window_l[i] < window_l[i - 1]
            and window_l[i] < window_l[i - 2]
            and window_l[i] < window_l[i + 1]
            and window_l[i] < window_l[i + 2]
        ):
            pivot_lows.append(float(window_l[i]))

    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return "ranging", float(window_h.max()), float(window_l.min())

    last_swing_high = pivot_highs[-1]
    last_swing_low = pivot_lows[-1]

    hh = pivot_highs[-1] > pivot_highs[-2]
    hl = pivot_lows[-1] > pivot_lows[-2]
    lh = pivot_highs[-1] < pivot_highs[-2]
    ll = pivot_lows[-1] < pivot_lows[-2]

    if hh and hl:
        return "up", last_swing_high, last_swing_low
    if lh and ll:
        return "down", last_swing_high, last_swing_low
    return "ranging", last_swing_high, last_swing_low


def _premium_discount(price: float, swing_high: float, swing_low: float) -> Tuple[str, float]:
    """
    Where is price in the HTF range?

    premium = top 30% of range
    discount = bottom 30% of range
    neutral = middle 40%
    """
    rng = swing_high - swing_low
    if rng <= 0:
        return "neutral", 0.5

    pct = (price - swing_low) / rng
    if pct >= 0.70:
        zone = "premium"
    elif pct <= 0.30:
        zone = "discount"
    else:
        zone = "neutral"

    return zone, round(pct, 3)


def _ema(c: np.ndarray, period: int) -> float:
    if len(c) < period:
        return float(c[-1])

    k = 2.0 / (period + 1)
    val = float(c[0])
    for price in c[1:]:
        val = float(price) * k + val * (1 - k)
    return val


def _bos_detected(h: np.ndarray, l: np.ndarray, c: np.ndarray, trend: str, lookback: int = 10) -> bool:
    """
    Break of structure check on 4H.
    """
    if len(c) < lookback + 1:
        return False

    if trend == "up":
        prior_high = float(h[-lookback - 1:-1].max())
        return float(c[-1]) > prior_high
    elif trend == "down":
        prior_low = float(l[-lookback - 1:-1].min())
        return float(c[-1]) < prior_low

    return False


def _resolve_market_condition(d1_trend: str, h4_trend: str, zone: str) -> Tuple[str, str, float]:
    """
    Returns:
        market_condition,
        combined_trend,
        amplifier (for same-direction trades)
    """
    if d1_trend == "up" and h4_trend == "up":
        if zone == "discount":
            return "TRENDING_UP_DISCOUNT", "up", 1.20
        elif zone == "premium":
            return "TRENDING_UP_PREMIUM", "up", 0.85
        else:
            return "TRENDING_UP_NEUTRAL", "up", 1.05

    if d1_trend == "down" and h4_trend == "down":
        if zone == "premium":
            return "TRENDING_DOWN_PREMIUM", "down", 1.20
        elif zone == "discount":
            return "TRENDING_DOWN_DISCOUNT", "down", 0.85
        else:
            return "TRENDING_DOWN_NEUTRAL", "down", 1.05

    if d1_trend == "up" and h4_trend in ("down", "ranging"):
        return "TRENDING_UP_PULLBACK", "up", 0.95

    if d1_trend == "down" and h4_trend in ("up", "ranging"):
        return "TRENDING_DOWN_PULLBACK", "down", 0.95

    return "RANGING_NEUTRAL", "ranging", 1.00


def evaluate(pair: str, kraken_pair: str) -> Dict[str, Any]:
    """
    Returns pure context dict — no bias/entry/SL/TP.
    Used by scanner/router to amplify or discount specialists.
    """
    null = {
        "pair": pair,
        "market_condition": "STRUCTURE_UNCLEAR",
        "market_tempo": "DEAD",
        "trend": "unknown",
        "zone": "neutral",
        "eq_pct": 0.5,
        "d1_trend": "unknown",
        "h4_trend": "unknown",
        "h1_tempo": "DEAD",
        "amplifier": 1.0,
        "counter_amplifier": 0.70,
        "bos": False,
        "ema21_d1": 0.0,
        "swing_high": 0.0,
        "swing_low": 0.0,
        "alignment": "unclear",
        "tempo_context": {},
        "why": "insufficient_data",
    }

    d1_rows = _fetch_ohlc(kraken_pair, interval=1440, limit=30)
    h4_rows = _fetch_ohlc(kraken_pair, interval=240, limit=40)
    h1_rows = _fetch_ohlc(kraken_pair, interval=60, limit=60)

    if not d1_rows or len(d1_rows) < 10:
        null["why"] = "d1_data_unavailable"
        return null
    if not h4_rows or len(h4_rows) < 10:
        null["why"] = "h4_data_unavailable"
        return null
    if not h1_rows or len(h1_rows) < 20:
        null["why"] = "h1_data_unavailable"
        return null

    d1_h, d1_l, d1_c, _ = _to_arrays(d1_rows)
    h4_h, h4_l, h4_c, _ = _to_arrays(h4_rows)
    h1_h, h1_l, h1_c, _ = _to_arrays(h1_rows)

    price = float(h1_c[-1])

    d1_trend, d1_swing_high, d1_swing_low = _swing_structure(d1_h, d1_l, d1_c, lookback=20)
    h4_trend, _, _ = _swing_structure(h4_h, h4_l, h4_c, lookback=15)

    zone, eq_pct = _premium_discount(price, d1_swing_high, d1_swing_low)
    bos = _bos_detected(h4_h, h4_l, h4_c, h4_trend, lookback=8)
    ema21_d1 = _ema(d1_c, 21)
    ema_bias = "up" if price > ema21_d1 else "down"

    h1_atr = _atr(h1_h, h1_l, h1_c, 14)
    if _TEMPO_AVAILABLE and h1_atr > 0:
        tempo_ctx = _tempo_mod.compute(h1_c, h1_atr)
    else:
        tempo_ctx = {
            "tempo": "DEAD",
            "speed_score": 0.0,
            "velocity": 0.0,
            "acceleration": 0.0,
            "v_direction": "flat",
            "a_direction": "flat",
        }

    market_condition, combined_trend, amplifier = _resolve_market_condition(d1_trend, h4_trend, zone)
    market_tempo = tempo_ctx["tempo"]

    v_dir = tempo_ctx.get("v_direction", "flat")
    if combined_trend == "up" and v_dir == "up":
        alignment = "aligned_up"
    elif combined_trend == "down" and v_dir == "down":
        alignment = "aligned_down"
    elif combined_trend in ("up", "down"):
        alignment = "pullback_or_countermove"
    else:
        alignment = "range"

    why_parts = [
        f"d1={d1_trend}",
        f"h4={h4_trend}",
        f"zone={zone}",
        f"eq_pct={eq_pct:.2f}",
        f"ema_bias={ema_bias}",
        f"tempo={market_tempo}",
        f"v_dir={v_dir}",
        f"alignment={alignment}",
    ]

    if bos:
        why_parts.append("bos_detected_4h")

    return {
        "pair": pair,
        "market_condition": market_condition,
        "market_tempo": market_tempo,
        "trend": combined_trend,
        "zone": zone,
        "eq_pct": eq_pct,
        "d1_trend": d1_trend,
        "h4_trend": h4_trend,
        "h1_tempo": market_tempo,
        "amplifier": amplifier,
        "counter_amplifier": 0.70,
        "bos": bos,
        "ema21_d1": round(ema21_d1, 4),
        "swing_high": round(d1_swing_high, 4),
        "swing_low": round(d1_swing_low, 4),
        "alignment": alignment,
        "tempo_context": {
            "speed_score": tempo_ctx.get("speed_score", 0.0),
            "velocity": tempo_ctx.get("velocity", 0.0),
            "acceleration": tempo_ctx.get("acceleration", 0.0),
            "v_direction": tempo_ctx.get("v_direction", "flat"),
            "a_direction": tempo_ctx.get("a_direction", "flat"),
        },
        "why": " | ".join(why_parts),
    }
