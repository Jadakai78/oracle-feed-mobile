"""
gimba_range.py — Gimba Range Specialist

Edge to center. Hunt rotation. Kill false fades.

Identity:
- rotational and mean-reversion specialist

Event families:
- LOWER_BAND_BOUNCE_LONG
- UPPER_BAND_FADE_SHORT
- RANGE_FAILED_BREAK_LONG
- RANGE_FAILED_BREAK_SHORT
- NO_FADE_EXPANSION_ACTIVE

Self-contained:
- fetches own 1h OHLC from Kraken
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("gimba_range")

try:
    import tempo as _tempo_mod
    _TEMPO_AVAILABLE = True
except ImportError:
    _TEMPO_AVAILABLE = False


def _fetch_ohlc(kraken_pair: str, interval: int = 60, limit: int = 60) -> Optional[List]:
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


def _bollinger(c: np.ndarray, period: int = 20, std_mult: float = 2.0) -> Tuple[float, float, float, float]:
    """
    Returns:
        upper, mid, lower, bb_pct
    where:
        bb_pct = 0.0 at lower band
        bb_pct = 1.0 at upper band
    """
    if len(c) < period:
        mid = float(c[-1])
        return mid, mid, mid, 0.5

    window = c[-period:]
    mid = float(window.mean())
    std = float(window.std())
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    rng = upper - lower
    bb_pct = (float(c[-1]) - lower) / rng if rng > 0 else 0.5
    return upper, mid, lower, round(bb_pct, 3)


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


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> float:
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1]))
    )
    if len(tr) < period:
        return float(np.mean(tr)) if len(tr) > 0 else 0.0
    return float(np.mean(tr[-period:]))


def _is_expansion_active(
    c: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    atr_val: float,
    lookback: int = 5,
) -> bool:
    """
    Real expansion checks:
    1. Last candle body > 1.5x average recent body
    2. Recent displacement > 0.8 ATR
    """
    if len(c) < lookback + 1 or atr_val <= 0:
        return False

    bodies = np.abs(c[1:] - c[:-1])
    avg_body = float(bodies[-lookback - 1:-1].mean()) if len(bodies) > lookback else 0.001
    last_body = float(abs(c[-1] - c[-2]))
    if last_body > 1.5 * avg_body:
        return True

    price_move = abs(float(c[-1]) - float(c[-lookback - 1]))
    if price_move > 0.8 * atr_val:
        return True

    return False


def _range_integrity(h: np.ndarray, l: np.ndarray, lookback: int = 20) -> Tuple[float, float]:
    return float(h[-lookback:].max()), float(l[-lookback:].min())


def _failed_break_reclaim(
    c: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    rng_high: float,
    rng_low: float,
    atr_val: float,
    lookback: int = 5,
) -> Tuple[bool, bool]:
    """
    Detect recent false break and reclaim.

    Returns:
        failed_high_short, failed_low_long
    """
    if len(c) < lookback + 1 or atr_val <= 0:
        return False, False

    buf = atr_val * 0.3

    recent_high_break = float(np.max(h[-lookback:])) > (rng_high + buf)
    recent_low_break = float(np.min(l[-lookback:])) < (rng_low - buf)

    now_back_inside_from_high = float(c[-1]) < rng_high
    now_back_inside_from_low = float(c[-1]) > rng_low

    failed_high_short = recent_high_break and now_back_inside_from_high
    failed_low_long = recent_low_break and now_back_inside_from_low

    return failed_high_short, failed_low_long


def evaluate(
    pair: str,
    kraken_pair: str,
    current_price: float,
    fg_score: int = 50,
) -> Dict[str, Any]:
    null_result = {
        "pair": pair,
        "bias": "NONE",
        "engine": "GimbaRange",
        "setup_type": "NO_FADE_EXPANSION_ACTIVE",
        "conviction": 0.0,
        "entry": None,
        "sl": None,
        "tp": None,
        "why": "insufficient_data",
        "action_state": "idle",
        "indicators": {
            "rsi": 50.0,
            "bb_pct": 0.5,
            "bb_upper": 0.0,
            "bb_mid": 0.0,
            "bb_lower": 0.0,
            "atr": 0.0,
            "expansion_active": False,
            "range_high": 0.0,
            "range_low": 0.0,
            "tempo": "DEAD",
            "speed_score": 0.0,
            "velocity": 0.0,
            "acceleration": 0.0,
        },
        "tempo": "DEAD",
    }

    rows = _fetch_ohlc(kraken_pair, interval=60, limit=60)
    if not rows or len(rows) < 25:
        return null_result

    o, h, l, c, v = _to_arrays(rows)
    price = float(c[-1])
    atr_val = _atr(h, l, c, 14)
    rsi_val = _rsi(c, 14)
    bb_upper, bb_mid, bb_lower, bb_pct = _bollinger(c, 20, 2.0)
    rng_high, rng_low = _range_integrity(h, l, 20)

    expansion = _is_expansion_active(c, h, l, atr_val, 5)

    if _TEMPO_AVAILABLE and atr_val > 0:
        tempo_ctx = _tempo_mod.compute(c, atr_val)
    else:
        tempo_ctx = {
            "tempo": "DEAD",
            "speed_score": 0.0,
            "velocity": 0.0,
            "acceleration": 0.0,
        }

    tempo_state = tempo_ctx["tempo"]
    speed_score = tempo_ctx["speed_score"]

    if tempo_state == "LIVE" and not expansion:
        expansion = True

    failed_high_short, failed_low_long = _failed_break_reclaim(
        c, h, l, rng_high, rng_low, atr_val, lookback=5
    )

    bias = "NONE"
    setup_type = "NO_FADE_EXPANSION_ACTIVE"
    conviction = 0.0
    action = "idle"
    why_parts: List[str] = []

    if expansion:
        setup_type = "NO_FADE_EXPANSION_ACTIVE"
        why_parts = [
            "expansion_active_displacement_detected",
            f"tempo={tempo_state}",
            f"bb_pct={bb_pct:.2f}",
            f"rsi={rsi_val:.0f}",
        ]
        action = "idle"

    elif failed_high_short:
        bias = "SHORT"
        setup_type = "RANGE_FAILED_BREAK_SHORT"
        conviction = 0.70
        conviction += min(speed_score * 0.05, 0.05)
        why_parts = [
            "price_left_range_high",
            "returned_inside",
            f"rng_high={rng_high:.4f}",
            f"bb_pct={bb_pct:.2f}",
        ]
        action = "watch"

    elif failed_low_long:
        bias = "LONG"
        setup_type = "RANGE_FAILED_BREAK_LONG"
        conviction = 0.70
        conviction += min(speed_score * 0.05, 0.05)
        why_parts = [
            "price_left_range_low",
            "returned_inside",
            f"rng_low={rng_low:.4f}",
            f"bb_pct={bb_pct:.2f}",
        ]
        action = "watch"

    elif bb_pct <= 0.15 and rsi_val < 40 and not expansion:
        bias = "LONG"
        setup_type = "LOWER_BAND_BOUNCE_LONG"
        conviction = 0.55
        if rsi_val < 30:
            conviction += 0.08
        if bb_pct <= 0.05:
            conviction += 0.05
        if tempo_state in ("EARLY", "BUILDING"):
            conviction += 0.03
        elif tempo_state == "LATE":
            conviction -= 0.05
        why_parts = [
            "at_lower_bb_edge",
            f"bb_pct={bb_pct:.2f}",
            f"rsi={rsi_val:.0f}",
            "exhaustion_posture",
            "range_integrity_alive",
        ]
        action = "watch"

    elif bb_pct >= 0.85 and rsi_val > 60 and not expansion:
        bias = "SHORT"
        setup_type = "UPPER_BAND_FADE_SHORT"
        conviction = 0.55
        if rsi_val > 70:
            conviction += 0.08
        if bb_pct >= 0.95:
            conviction += 0.05
        if tempo_state in ("EARLY", "BUILDING"):
            conviction += 0.03
        elif tempo_state == "LATE":
            conviction -= 0.05
        why_parts = [
            "at_upper_bb_edge",
            f"bb_pct={bb_pct:.2f}",
            f"rsi={rsi_val:.0f}",
            "rejection_posture",
            "range_integrity_alive",
        ]
        action = "watch"

    else:
        setup_type = "NO_FADE_EXPANSION_ACTIVE"
        why_parts = [
            f"bb_pct={bb_pct:.2f}",
            f"rsi={rsi_val:.0f}",
            "mid_range_no_edge",
        ]
        action = "idle"

    if fg_score <= 25 and bias == "SHORT":
        conviction = min(conviction + 0.05, 1.0)
        why_parts.append(f"fg_fear_boost(fg={fg_score})")

    entry = sl = tp = None
    if action == "watch" and atr_val > 0:
        if bias == "LONG":
            entry = round(price, 4)
            sl = round(min(price - atr_val * 1.2, bb_lower - atr_val * 0.3), 4)
            tp = round(bb_mid, 4)
        elif bias == "SHORT":
            entry = round(price, 4)
            sl = round(max(price + atr_val * 1.2, bb_upper + atr_val * 0.3), 4)
            tp = round(bb_mid, 4)

    return {
        "pair": pair,
        "bias": bias,
        "engine": "GimbaRange",
        "setup_type": setup_type,
        "conviction": round(min(max(conviction, 0.0), 1.0), 3),
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "why": " | ".join(why_parts),
        "action_state": action,
        "indicators": {
            "rsi": rsi_val,
            "bb_pct": bb_pct,
            "bb_upper": round(bb_upper, 4),
            "bb_mid": round(bb_mid, 4),
            "bb_lower": round(bb_lower, 4),
            "atr": round(atr_val, 4),
            "expansion_active": expansion,
            "range_high": round(rng_high, 4),
            "range_low": round(rng_low, 4),
            "tempo": tempo_state,
            "speed_score": speed_score,
            "velocity": tempo_ctx.get("velocity", 0.0),
            "acceleration": tempo_ctx.get("acceleration", 0.0),
        },
        "tempo": tempo_state,
    }


def evaluate_with_knn(
    pair: str,
    kraken_pair: str,
    current_price: float,
    fg_score: int = 50,
    log_dir=None,
) -> dict:
    from pathlib import Path as _Path
    from knn_engine import KNNEngine as _KNN

    result = evaluate(pair, kraken_pair, current_price, fg_score)

    _log = log_dir or (_Path(__file__).parent / "training_logs")
    try:
        engine = _KNN("gimba_range", _log, min_samples=30)
        adj, n = engine.adjust(result)

        if n >= 30:
            raw = result["conviction"]
            result["conviction"] = round(min(max(raw + adj, 0.0), 1.0), 3)
            result["knn_adj"] = round(adj, 3)
            result["knn_samples"] = n
        else:
            result["knn_adj"] = 0.0
            result["knn_samples"] = n

    except Exception:
        result["knn_adj"] = 0.0
        result["knn_samples"] = 0

    return result
