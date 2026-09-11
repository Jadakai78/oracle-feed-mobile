"""
tempo.py — Market Speed, Velocity, Acceleration, and Tempo State

Shared utility consumed by Volatile, Range, Trend, and Structure.

Formulas:
vt = Pt - Pt-1   (price velocity — candle-to-candle displacement)
at = vt - vt-1   (price acceleration — change in velocity)

Tempo states:
LIVE      — velocity strong, acceleration positive, move in progress NOW
BUILDING  — velocity moderate, acceleration positive, setting up
EARLY     — first signs of movement, acceleration just turned positive
LATE      — velocity positive but acceleration fading/negative (move aging)
DEAD      — velocity flat/negative, acceleration negative (exhausted)

These map directly to the Oracle / Gimba tempo field.
LIVE / BUILDING / EARLY = worth acting
LATE = manage only / no chase
DEAD = stand aside
"""

from __future__ import annotations

from typing import Dict
import numpy as np


def _velocity_series(c: np.ndarray) -> np.ndarray:
    """vt = Pt - Pt-1 for all candles."""
    return np.diff(c)


def _acceleration_series(v: np.ndarray) -> np.ndarray:
    """at = vt - vt-1 for all velocity values."""
    return np.diff(v)


def _null_tempo() -> Dict:
    return {
        "velocity": 0.0,
        "acceleration": 0.0,
        "velocity_norm": 0.0,
        "accel_norm": 0.0,
        "velocity_avg": 0.0,
        "v_direction": "flat",
        "a_direction": "flat",
        "tempo": "DEAD",
        "speed_score": 0.0,
    }


def compute(
    c: np.ndarray,
    atr_val: float,
    v_lookback: int = 5,
    a_lookback: int = 3,
) -> Dict:
    """
    Given close array and ATR, return full tempo context dict.

    Returns:
        velocity        — latest single candle velocity (raw)
        acceleration    — latest acceleration value
        velocity_norm   — |velocity| normalized by ATR
        accel_norm      — signed acceleration normalized by ATR
        velocity_avg    — avg velocity over v_lookback candles
        v_direction     — 'up', 'down', 'flat'
        a_direction     — 'expanding', 'fading', 'flat'
        tempo           — LIVE / BUILDING / EARLY / LATE / DEAD
        speed_score     — 0.0-1.0 composite speed score for conviction weighting
    """
    if len(c) < 4 or atr_val <= 0:
        return _null_tempo()

    c = np.asarray(c, dtype=float)
    vel = _velocity_series(c)
    accel = _acceleration_series(vel)

    v_now = float(vel[-1])
    a_now = float(accel[-1]) if len(accel) > 0 else 0.0

    v_avg = float(vel[-v_lookback:].mean()) if len(vel) >= v_lookback else float(vel.mean())

    v_norm = abs(v_now) / atr_val
    a_norm = a_now / atr_val

    v_dir = "up" if v_now > atr_val * 0.05 else ("down" if v_now < -atr_val * 0.05 else "flat")
    a_dir = "expanding" if a_norm > 0.02 else ("fading" if a_norm < -0.02 else "flat")

    if v_norm >= 0.60 and a_dir == "expanding":
        tempo = "LIVE"
        speed_score = min(0.90 + (v_norm - 0.60) * 0.20, 1.0)

    elif (v_norm >= 0.30 and a_dir == "expanding") or (v_norm >= 0.55 and a_dir == "flat"):
        tempo = "BUILDING"
        speed_score = min(0.65 + v_norm * 0.15, 0.89)

    elif v_norm < 0.30 and a_dir == "expanding" and a_norm > 0.0:
        tempo = "EARLY"
        speed_score = min(0.40 + a_norm * 10, 0.64)

    elif v_norm >= 0.25 and a_dir == "fading":
        tempo = "LATE"
        speed_score = max(0.25, 0.50 - abs(a_norm) * 5)

    else:
        tempo = "DEAD"
        speed_score = max(0.0, min(v_norm * 0.30, 0.24))

    return {
        "velocity": round(v_now, 6),
        "acceleration": round(a_now, 6),
        "velocity_norm": round(v_norm, 3),
        "accel_norm": round(a_norm, 4),
        "velocity_avg": round(v_avg, 6),
        "v_direction": v_dir,
        "a_direction": a_dir,
        "tempo": tempo,
        "speed_score": round(min(max(speed_score, 0.0), 1.0), 3),
    }


def displacement_quality(
    c: np.ndarray,
    o: np.ndarray,
    h: np.ndarray | None = None,
    l: np.ndarray | None = None,
    lookback: int = 5,
) -> float:
    """
    Body dominance score used by Volatile / Range / Trend.

    Measures impulse quality after a move:
    0.0 = all wick / weak participation
    1.0 = strong body candles / real participation

    If high/low arrays are present, use true candle range.
    Otherwise fall back to a close-to-close approximation.
    """
    if len(c) < lookback + 1 or len(o) < lookback:
        return 0.5

    c = np.asarray(c, dtype=float)
    o = np.asarray(o, dtype=float)
    use_hl = h is not None and l is not None and len(h) >= lookback and len(l) >= lookback

    if use_hl:
        h = np.asarray(h, dtype=float)
        l = np.asarray(l, dtype=float)

    scores = []
    for i in range(-lookback, 0):
        body = abs(float(c[i]) - float(o[i]))

        if use_hl:
            total = max(float(h[i]) - float(l[i]), body)
        else:
            total = max(abs(float(c[i]) - float(c[i - 1])) * 1.5, body)

        if total <= 0:
            scores.append(0.5)
        else:
            scores.append(min(body / total, 1.0))

    return round(float(np.mean(scores)), 3)
