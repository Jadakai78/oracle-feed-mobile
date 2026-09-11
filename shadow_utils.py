"""shadow_utils.py — Shared OHLCV helpers for shadow candidate specialists.

Used by shadow_gimba_volatile.py and shadow_trend_recovery.py.
These are pure, self-contained functions with no external dependencies beyond numpy.
"""
from __future__ import annotations

import numpy as np


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> float:
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )
    if len(tr) == 0:
        return 0.0
    return float(np.mean(tr[-period:])) if len(tr) >= period else float(np.mean(tr))


def rsi(c: np.ndarray, period: int = 14) -> float:
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
    return round(100.0 - 100.0 / (1.0 + avg_g / avg_l), 2)


def relative_volume(v: np.ndarray, lookback: int = 20) -> float:
    if len(v) < lookback + 1:
        return 1.0
    avg = v[-lookback - 1:-1].mean()
    if avg == 0:
        return 1.0
    return round(float(v[-1] / avg), 2)
