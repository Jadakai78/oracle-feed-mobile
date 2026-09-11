"""
gimba_volatile.py — Gimba Volatile Specialist

Pulse locked. Hunt live volatility. Kill bad chase.

Identity:
- volatility and expansion specialist

Event families:
- SURGE_CONTINUATION_LONG / SHORT
- CASCADE_RECOVERY_LONG / SHORT
- MOVE_MATURED_NO_CHASE_LONG / SHORT
- WEAK_EXPANSION_NO_CLAIM

Self-contained:
- fetches own 15m OHLC from Kraken public API
- output matches TAK scanner signal shape
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("gimba_volatile")

try:
    import tempo as _tempo_mod
    _TEMPO_AVAILABLE = True
except ImportError:
    _TEMPO_AVAILABLE = False


def _fetch_ohlc(kraken_pair: str, interval: int = 15, limit: int = 60) -> Optional[List]:
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
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1]))
    )
    if len(tr) < period:
        return float(np.mean(tr)) if len(tr) > 0 else 0.0
    return float(np.mean(tr[-period:]))


def _supertrend(
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    period: int = 10,
    mult: float = 3.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Lightweight supertrend approximation.

    Returns:
        direction array: 1 = up, -1 = down
        supertrend line
    """
    if len(c) < 3:
        base = float(c[-1]) if len(c) else 0.0
        return np.array([1]), np.array([base])

    tr = []
    for i in range(1, len(c)):
        tr_i = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        tr.append(tr_i)
    tr = np.array(tr, dtype=float)

    atr_arr = np.zeros_like(tr)
    for i in range(len(tr)):
        start = max(0, i - period + 1)
        atr_arr[i] = np.mean(tr[start:i + 1])

    hl2 = (h[1:] + l[1:]) / 2.0
    upper_band = hl2 + mult * atr_arr
    lower_band = hl2 - mult * atr_arr

    st = np.zeros(len(c) - 1, dtype=float)
    direction = np.ones(len(c) - 1, dtype=int)

    for i in range(len(st)):
        if i == 0:
            st[i] = lower_band[i]
            direction[i] = 1
            continue

        if c[i] > st[i - 1]:
            st[i] = max(lower_band[i], st[i - 1]) if direction[i - 1] == 1 else lower_band[i]
            direction[i] = 1
        else:
            st[i] = min(upper_band[i], st[i - 1]) if direction[i - 1] == -1 else upper_band[i]
            direction[i] = -1

    return direction, st


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


def _relative_volume(v: np.ndarray, lookback: int = 20) -> float:
    if len(v) < lookback + 1:
        return 1.0
    avg = v[-lookback - 1:-1].mean()
    if avg == 0:
        return 1.0
    return round(float(v[-1] / avg), 2)


def _impulse_speed(c: np.ndarray, lookback: int = 25) -> float:
    if len(c) < lookback + 1:
        return 0.0
    start = c[-lookback - 1]
    end = c[-1]
    if start == 0:
        return 0.0
    return round(abs((end - start) / start) * 100, 2)


def _move_maturity(
    c: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    atr_val: float,
    lookback: int = 25,
) -> float:
    """
    How extended is the current move vs ATR.
    0.0 = fresh
    1.0 = fully extended
    """
    if atr_val <= 0 or len(c) < lookback:
        return 0.5

    swing_low = float(l[-lookback:].min())
    swing_high = float(h[-lookback:].max())
    total_range = swing_high - swing_low
    if total_range <= 0:
        return 0.5

    atr_multiples = total_range / atr_val
    return round(min(atr_multiples / 4.0, 1.0), 2)


def evaluate(
    pair: str,
    kraken_pair: str,
    current_price: float,
    fg_score: int = 50,
) -> Dict[str, Any]:
    """
    Gimba Volatile evaluation.
    Returns signal dict matching TAK scanner format.
    """
    null_result = {
        "pair": pair,
        "bias": "NONE",
        "engine": "GimbaVolatile",
        "setup_type": "WEAK_EXPANSION_NO_CLAIM",
        "conviction": 0.0,
        "entry": None,
        "sl": None,
        "tp": None,
        "why": "insufficient_data",
        "action_state": "idle",
        "indicators": {
            "rsi": 50.0,
            "rvol": 1.0,
            "atr": 0.0,
            "speed_pct": 0.0,
            "maturity": 0.5,
            "st_direction": 0,
            "st_flipped": False,
            "tempo": "DEAD",
            "speed_score": 0.0,
            "velocity": 0.0,
            "acceleration": 0.0,
            "disp_quality": 0.5,
            "st_dist_pct": 0.0,
        },
        "tempo": "DEAD",
    }

    rows = _fetch_ohlc(kraken_pair, interval=15, limit=60)
    if not rows or len(rows) < 30:
        return null_result

    o, h, l, c, v = _to_arrays(rows)
    atr_val = _atr(h, l, c, 14)
    rsi_val = _rsi(c, 14)
    rvol = _relative_volume(v, 20)
    speed = _impulse_speed(c, 25)
    maturity = _move_maturity(c, h, l, atr_val, 25)
    price = float(c[-1])

    direction, st = _supertrend(h, l, c, 10, 3.0)
    st_dir = int(direction[-1]) if len(direction) else 1
    st_flipped = bool(len(direction) > 1 and int(direction[-1]) != int(direction[-2]))
    st_dist_pct = abs(price - float(st[-1])) / price * 100 if price > 0 and len(st) else 0.0

    if _TEMPO_AVAILABLE and atr_val > 0:
        tempo_ctx = _tempo_mod.compute(c, atr_val)
        disp_q = _tempo_mod.displacement_quality(c, o, h, l)
    else:
        tempo_ctx = {
            "tempo": "DEAD",
            "speed_score": 0.0,
            "v_direction": "flat",
            "a_direction": "flat",
            "velocity": 0.0,
            "acceleration": 0.0,
        }
        disp_q = 0.5

    tempo_state = tempo_ctx["tempo"]
    speed_score = tempo_ctx["speed_score"]

    bias = "LONG" if st_dir == 1 else "SHORT"
    setup_type = "WEAK_EXPANSION_NO_CLAIM"
    conviction = 0.0
    action = "idle"
    why_parts: List[str] = []

    if tempo_state == "DEAD":
        setup_type = "WEAK_EXPANSION_NO_CLAIM"
        why_parts = ["tempo_dead", f"speed_score={speed_score:.2f}"]
        action = "idle"
        bias = "NONE"

    elif (
        st_dir == 1
        and rsi_val > 50
        and rvol >= 1.4
        and maturity < 0.65
        and speed > 0.5
        and tempo_state in ("LIVE", "BUILDING", "EARLY")
    ):
        setup_type = "SURGE_CONTINUATION_LONG"
        conviction = 0.60
        conviction += min(rvol - 1.4, 0.6) * 0.15
        conviction += (1.0 - maturity) * 0.10
        conviction += speed_score * 0.08
        conviction += (disp_q - 0.5) * 0.06
        why_parts = [
            "supertrend_up",
            f"rvol={rvol:.2f}",
            f"rsi={rsi_val:.0f}",
            f"maturity={maturity:.2f}",
            f"tempo={tempo_state}",
            f"disp_q={disp_q:.2f}",
            "room_available",
        ]
        action = "watch"

    elif (
        st_dir == -1
        and rsi_val < 50
        and rvol >= 1.4
        and maturity < 0.65
        and speed > 0.5
        and tempo_state in ("LIVE", "BUILDING", "EARLY")
    ):
        setup_type = "SURGE_CONTINUATION_SHORT"
        conviction = 0.60
        conviction += min(rvol - 1.4, 0.6) * 0.15
        conviction += (1.0 - maturity) * 0.10
        conviction += speed_score * 0.08
        conviction += (disp_q - 0.5) * 0.06
        why_parts = [
            "supertrend_down",
            f"rvol={rvol:.2f}",
            f"rsi={rsi_val:.0f}",
            f"maturity={maturity:.2f}",
            f"tempo={tempo_state}",
            f"disp_q={disp_q:.2f}",
            "room_available",
        ]
        action = "watch"

    elif (
        st_dir == 1
        and rsi_val > 50
        and rvol >= 1.4
        and maturity < 0.65
        and tempo_state == "LATE"
    ):
        setup_type = "MOVE_MATURED_NO_CHASE_LONG"
        conviction = 0.0
        why_parts = [
            "surge_conditions_met_but_tempo_late",
            f"tempo={tempo_state}",
            f"speed_score={speed_score:.2f}",
        ]
        action = "idle"
        bias = "NONE"

    elif (
        st_dir == -1
        and rsi_val < 50
        and rvol >= 1.4
        and maturity < 0.65
        and tempo_state == "LATE"
    ):
        setup_type = "MOVE_MATURED_NO_CHASE_SHORT"
        conviction = 0.0
        why_parts = [
            "surge_conditions_met_but_tempo_late",
            f"tempo={tempo_state}",
            f"speed_score={speed_score:.2f}",
        ]
        action = "idle"
        bias = "NONE"

    elif (
        st_flipped
        and rvol >= 1.2
        and atr_val > 0
        and st_dist_pct < 2.0
        and tempo_state in ("LIVE", "BUILDING", "EARLY")
    ):
        if st_dir == 1:
            setup_type = "CASCADE_RECOVERY_LONG"
            bias = "LONG"
            why_parts = [
                "supertrend_flip_up",
                f"rvol={rvol:.2f}",
                f"st_dist={st_dist_pct:.2f}%",
                f"tempo={tempo_state}",
                "recovery_expansion",
            ]
        else:
            setup_type = "CASCADE_RECOVERY_SHORT"
            bias = "SHORT"
            why_parts = [
                "supertrend_flip_down",
                f"rvol={rvol:.2f}",
                f"st_dist={st_dist_pct:.2f}%",
                f"tempo={tempo_state}",
                "recovery_expansion",
            ]
        conviction = 0.72 + speed_score * 0.06
        action = "watch"

    elif maturity >= 0.75 and speed > 1.0:
        setup_type = f"MOVE_MATURED_NO_CHASE_{'LONG' if st_dir == 1 else 'SHORT'}"
        conviction = 0.0
        why_parts = [
            f"maturity={maturity:.2f}",
            f"speed={speed:.2f}",
            "entry_window_passed_chase_fee_too_high",
        ]
        action = "idle"
        bias = "NONE"

    else:
        setup_type = "WEAK_EXPANSION_NO_CLAIM"
        conviction = 0.0
        why_parts = [
            f"rvol={rvol:.2f}",
            f"speed={speed:.2f}",
            f"rsi={rsi_val:.0f}",
            "participation_not_confirmed",
        ]
        action = "idle"
        bias = "NONE"

    if fg_score <= 25 and setup_type.startswith("SURGE"):
        conviction *= 0.85
        why_parts.append(f"fg_fear_penalty(fg={fg_score})")

    entry = sl = tp = None
    if action == "watch" and atr_val > 0:
        if bias == "LONG":
            entry = round(price, 4)
            sl = round(price - atr_val * 1.5, 4)
            tp = round(price + atr_val * 2.5, 4)
        elif bias == "SHORT":
            entry = round(price, 4)
            sl = round(price + atr_val * 1.5, 4)
            tp = round(price - atr_val * 2.5, 4)

    return {
        "pair": pair,
        "bias": bias,
        "engine": "GimbaVolatile",
        "setup_type": setup_type,
        "conviction": round(min(max(conviction, 0.0), 1.0), 3),
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "why": " | ".join(why_parts),
        "action_state": action,
        "indicators": {
            "rsi": rsi_val,
            "rvol": rvol,
            "atr": round(atr_val, 4),
            "speed_pct": speed,
            "maturity": maturity,
            "st_direction": st_dir,
            "st_flipped": st_flipped,
            "tempo": tempo_state,
            "speed_score": speed_score,
            "velocity": tempo_ctx.get("velocity", 0.0),
            "acceleration": tempo_ctx.get("acceleration", 0.0),
            "disp_quality": disp_q,
            "st_dist_pct": round(st_dist_pct, 3),
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
    """
    Drop-in replacement for evaluate() that also applies KNN conviction adjustment.
    Falls back to raw evaluate() output until min_samples (30) are collected.
    """
    from pathlib import Path as _Path
    from knn_engine import KNNEngine as _KNN

    result = evaluate(pair, kraken_pair, current_price, fg_score)

    _log = log_dir or (_Path(__file__).parent / "training_logs")
    try:
        engine = _KNN("gimba_volatile", _log, min_samples=30)
        adj, n = engine.adjust(result)

        if n >= 30:
            raw = result["conviction"]
            adjusted = round(min(max(raw + adj, 0.0), 1.0), 3)

            is_cascade = result.get("setup_type", "") in (
                "CASCADE_RECOVERY_LONG",
                "CASCADE_RECOVERY_SHORT",
            )
            ind = result.get("indicators", {})
            confirmed_flip = (
                is_cascade
                and ind.get("st_flipped", False)
                and ind.get("rvol", 0.0) >= 1.2
            )

            if confirmed_flip:
                adjusted = max(adjusted, 0.65)

            result["conviction"] = adjusted
            result["knn_adj"] = round(adj, 3)
            result["knn_samples"] = n
            result["floor_applied"] = confirmed_flip
        else:
            result["knn_adj"] = 0.0
            result["knn_samples"] = n
            result["floor_applied"] = False

    except Exception:
        result["knn_adj"] = 0.0
        result["knn_samples"] = 0
        result["floor_applied"] = False

    return result
