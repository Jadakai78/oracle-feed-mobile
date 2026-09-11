"""
gimba_trend.py — Gimba Trend Specialist (with KNN wrapper)

Flow with structure. Hunt continuation when lower-timeframe movement
is aligned with higher-timeframe structure.

Identity:
- directional continuation specialist
- trades with HTF current, never against it
- requires active tempo in the same direction
- avoids late/dead moves and overextended chase

Event families:
- HTF_CONTINUATION_LONG
- HTF_CONTINUATION_SHORT
- HTF_PULLBACK_RESUMPTION_LONG
- HTF_PULLBACK_RESUMPTION_SHORT
- TREND_LATE_NO_CHASE_LONG
- TREND_LATE_NO_CHASE_SHORT
- NO_TREND_ALIGNMENT

Self-contained:
- fetches its own D1 / 4H / 1H / 15m OHLC from Kraken
- uses shared tempo.py if available
- outputs TAK scanner-compatible signal shape
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("gimba_trend")

try:
    import tempo as _tempo_mod

    _TEMPO_AVAILABLE = True
except ImportError:
    _TEMPO_AVAILABLE = False


def _fetch_ohlc(kraken_pair: str, interval: int, limit: int = 80) -> Optional[List]:
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


def _to_arrays(rows: List) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    o = np.array([float(r[1]) for r in rows], dtype=float)
    h = np.array([float(r[2]) for r in rows], dtype=float)
    l = np.array([float(r[3]) for r in rows], dtype=float)
    c = np.array([float(r[4]) for r in rows], dtype=float)
    v = np.array([float(r[6]) for r in rows], dtype=float)
    return o, h, l, c, v


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> float:
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )
    if len(tr) < period:
        return float(np.mean(tr)) if len(tr) > 0 else 0.0
    return float(np.mean(tr[-period:]))


def _ema(c: np.ndarray, period: int) -> float:
    if len(c) < period:
        return float(c[-1])
    k = 2.0 / (period + 1)
    val = float(c[0])
    for price in c[1:]:
        val = float(price) * k + val * (1 - k)
    return val


def _relative_volume(v: np.ndarray, lookback: int = 20) -> float:
    if len(v) < lookback + 1:
        return 1.0
    avg = v[-lookback - 1:-1].mean()
    if avg == 0:
        return 1.0
    return round(float(v[-1] / avg), 2)


def _rsi(c: np.ndarray, period: int = 14) -> float:
    if len(c) < period + 1:
        return 50.0
    d = np.diff(c)
    gains = np.where(d > 0, d, 0.0)
    losses = np.where(d < 0, -d, 0.0)
    avg_g = gains[:period].mean()
    avg_l = losses[:period].mean()
    for gi, li in zip(gains[period:], losses[period:]):
        avg_g = (avg_g * (period - 1) + gi) / period
        avg_l = (avg_l * (period - 1) + li) / period
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 2)


def _swing_structure(h: np.ndarray, l: np.ndarray, lookback: int = 20) -> Tuple[str, float, float]:
    if len(h) < lookback or len(l) < lookback:
        return "ranging", float(h[-1]), float(l[-1])

    window_h = h[-lookback:]
    window_l = l[-lookback:]
    n = len(window_h)
    pivot_highs = []
    pivot_lows = []

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
    rng = swing_high - swing_low
    if rng <= 0:
        return "neutral", 0.5
    pct = (price - swing_low) / rng
    if pct >= 0.70:
        return "premium", round(pct, 3)
    if pct <= 0.30:
        return "discount", round(pct, 3)
    return "neutral", round(pct, 3)


def _pullback_depth(price: float, ema_fast: float, ema_slow: float, atr_val: float, trend: str) -> float:
    if atr_val <= 0:
        return 0.5
    if trend == "up":
        ref = min(ema_fast, ema_slow)
        return max(0.0, min((ref - price) / atr_val, 2.0))
    if trend == "down":
        ref = max(ema_fast, ema_slow)
        return max(0.0, min((price - ref) / atr_val, 2.0))
    return 0.5


def evaluate(pair: str, kraken_pair: str, current_price: float, fg_score: int = 50) -> Dict[str, Any]:
    null_result: Dict[str, Any] = {
        "pair": pair,
        "bias": "NONE",
        "engine": "GimbaTrend",
        "setup_type": "NO_TREND_ALIGNMENT",
        "conviction": 0.0,
        "entry": None,
        "sl": None,
        "tp": None,
        "why": "insufficient_data",
        "action_state": "idle",
        "indicators": {
            "d1_trend": "unknown",
            "h4_trend": "unknown",
            "h1_tempo": "DEAD",
            "m15_tempo": "DEAD",
            "zone": "neutral",
            "eq_pct": 0.5,
            "rsi_h1": 50.0,
            "rvol_m15": 1.0,
            "pullback_depth": 0.5,
            "ema20_h1": 0.0,
            "ema50_h1": 0.0,
            "speed_score_h1": 0.0,
            "speed_score_m15": 0.0,
        },
        "tempo": "DEAD",
    }

    d1_rows = _fetch_ohlc(kraken_pair, 1440, 40)
    h4_rows = _fetch_ohlc(kraken_pair, 240, 50)
    h1_rows = _fetch_ohlc(kraken_pair, 60, 80)
    m15_rows = _fetch_ohlc(kraken_pair, 15, 80)

    if not d1_rows or len(d1_rows) < 20:
        return null_result
    if not h4_rows or len(h4_rows) < 20:
        return null_result
    if not h1_rows or len(h1_rows) < 30:
        return null_result
    if not m15_rows or len(m15_rows) < 30:
        return null_result

    o1, h1, l1, c1, v1 = _to_arrays(h1_rows)
    o4, h4, l4, c4, v4 = _to_arrays(h4_rows)
    od, hd, ld, cd, vd = _to_arrays(d1_rows)
    om, hm, lm, cm, vm = _to_arrays(m15_rows)

    price = float(c1[-1])
    atr_h1 = _atr(h1, l1, c1, 14)
    ema20_h1 = _ema(c1, 20)
    ema50_h1 = _ema(c1, 50)
    rsi_h1 = _rsi(c1, 14)
    rvol_m15 = _relative_volume(vm, 20)

    d1_trend, d1_hi, d1_lo = _swing_structure(hd, ld, 20)
    h4_trend, h4_hi, h4_lo = _swing_structure(h4, l4, 20)

    zone, eq_pct = _premium_discount(price, d1_hi, d1_lo)

    combined_trend = "ranging"
    whyparts = [f"d1={d1_trend}", f"h4={h4_trend}", f"zone={zone}", f"eq={eq_pct:.2f}"]

    if d1_trend == "up" and h4_trend == "up":
        combined_trend = "up"
        whyparts.append("d1_h4_aligned_up")
    elif d1_trend == "down" and h4_trend == "down":
        combined_trend = "down"
        whyparts.append("d1_h4_aligned_down")
    elif d1_trend == "up" and h4_trend in ("down", "ranging"):
        combined_trend = "up"
        whyparts.append("d1_up_h4_pullback")
    elif d1_trend == "down" and h4_trend in ("up", "ranging"):
        combined_trend = "down"
        whyparts.append("d1_down_h4_pullback")
    else:
        combined_trend = "ranging"
        whyparts.append("no_clear_trend")

    pullback = _pullback_depth(price, ema20_h1, ema50_h1, atr_h1, combined_trend)
    whyparts.append(f"pullback={pullback:.2f}")

    # Tempo from m15 / h1
    if _TEMPO_AVAILABLE:
        tempo_ctx_h1 = _tempo_mod.compute(c1, atr_h1)
        tempo_ctx_m15 = _tempo_mod.compute(cm, _atr(hm, lm, cm, 14))
        h1_tempo = tempo_ctx_h1.get("tempo", "DEAD")
        m15_tempo = tempo_ctx_m15.get("tempo", "DEAD")
        speed_score_h1 = tempo_ctx_h1.get("speed_score", 0.0)
        speed_score_m15 = tempo_ctx_m15.get("speed_score", 0.0)
    else:
        h1_tempo = "DEAD"
        m15_tempo = "DEAD"
        speed_score_h1 = 0.0
        speed_score_m15 = 0.0

    # Bias and setup
    bias = "NONE"
    setup_type = "NO_TREND_ALIGNMENT"
    conviction = 0.0
    action_state = "idle"

    if combined_trend == "up":
        if zone == "discount" and h1_tempo in ("LIVE", "BUILDING", "EARLY"):
            bias = "LONG"
            setup_type = "HTF_PULLBACK_RESUMPTION_LONG"
            conviction = 0.65
            action_state = "watch"
            whyparts.append("uptrend_pullback_resumption")
        elif zone == "neutral" and h1_tempo in ("LIVE", "BUILDING"):
            bias = "LONG"
            setup_type = "HTF_CONTINUATION_LONG"
            conviction = 0.55
            action_state = "watch"
            whyparts.append("uptrend_continuation")
        elif zone == "premium" and h1_tempo == "LATE":
            bias = "NONE"
            setup_type = "TREND_LATE_NO_CHASE_LONG"
            conviction = 0.0
            action_state = "idle"
            whyparts.append("late_trend_no_chase")
    elif combined_trend == "down":
        if zone == "premium" and h1_tempo in ("LIVE", "BUILDING", "EARLY"):
            bias = "SHORT"
            setup_type = "HTF_PULLBACK_RESUMPTION_SHORT"
            conviction = 0.65
            action_state = "watch"
            whyparts.append("downtrend_pullback_resumption")
        elif zone == "neutral" and h1_tempo in ("LIVE", "BUILDING"):
            bias = "SHORT"
            setup_type = "HTF_CONTINUATION_SHORT"
            conviction = 0.55
            action_state = "watch"
            whyparts.append("downtrend_continuation")
        elif zone == "discount" and h1_tempo == "LATE":
            bias = "NONE"
            setup_type = "TREND_LATE_NO_CHASE_SHORT"
            conviction = 0.0
            action_state = "idle"
            whyparts.append("late_trend_no_chase")

    if bias == "NONE":
        setup_type = "NO_TREND_ALIGNMENT"
        conviction = 0.0
        action_state = "idle"
        whyparts.append("no_trend_entry_conditions")

    indicators: Dict[str, Any] = {
        "d1_trend": d1_trend,
        "h4_trend": h4_trend,
        "htf_trend": combined_trend,
        "h1_tempo": h1_tempo,
        "m15_tempo": m15_tempo,
        "zone": zone,
        "eq_pct": eq_pct,
        "rsi_h1": rsi_h1,
        "rvol_m15": rvol_m15,
        "pullback_depth": pullback,
        "ema20_h1": round(ema20_h1, 4),
        "ema50_h1": round(ema50_h1, 4),
        "speed_score_h1": speed_score_h1,
        "speed_score_m15": speed_score_m15,
        "h1_v_direction": "down" if c1[-1] < c1[-2] else "up",
        "m15_v_direction": "down" if cm[-1] < cm[-2] else "up",
        "atr_h1": round(atr_h1, 4),
    }

    result: Dict[str, Any] = {
        "pair": pair,
        "bias": bias,
        "engine": "GimbaTrend",
        "setup_type": setup_type,
        "conviction": round(conviction, 3),
        "entry": None,
        "sl": None,
        "tp": None,
        "why": ";".join(whyparts),
        "action_state": action_state,
        "indicators": indicators,
        "tempo": h1_tempo,
    }

    return result


# ── KNN wrapper for Trend ─────────────────────────────────────────────────
from pathlib import Path as _Path
from knn_engine import KNNEngine as KNN


def evaluate_with_knn(
    pair: str,
    kraken_pair: str,
    current_price: float,
    fg_score: int = 50,
    log_dir: Any = None,
) -> Dict[str, Any]:
    """Drop-in replacement for evaluate that also applies KNN conviction adjustment.

    Falls back to raw evaluate output until minsamples are collected.
    """
    # Raw trend evaluation
    result = evaluate(pair, kraken_pair, current_price, fg_score)

    log_dir_path = _Path(log_dir) if log_dir is not None else _Path(__file__).parent / "training_logs"

    try:
        engine = KNN("gimba_trend", log_dir_path, min_samples=30)
        adj, n = engine.adjust(result)

        if n >= 30:
            raw = float(result.get("conviction", 0.0))
            adjusted = raw + adj
            result["conviction"] = round(max(0.0, min(adjusted, 1.0)), 3)
            result["knn_adj"] = round(adj, 3)
            result["knn_samples"] = n
        else:
            result["knn_adj"] = 0.0
            result["knn_samples"] = n
    except Exception:
        result["knn_adj"] = 0.0
        result["knn_samples"] = 0

    return result
