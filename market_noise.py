"""Shared market-noise analytics from completed 15m OHLCV bars only.

This module is observation-only. It does not change execution eligibility,
OFFENSE/PERMISSION, routing, orders, sizing, risk, conviction, or KNN inputs.

Calculations use the most recent completed bars in a fixed window:

- wick_body_noise:
    mean(min((upper_wick + lower_wick) / max(real_body, 1e-6), 6.0))
- alternation_ratio:
    direction flips / (non-zero candle bodies - 1)
- directional_efficiency:
    abs(last_close - first_close) / sum(abs(close[i] - close[i-1]))
- directional_run_length:
    longest consecutive non-zero candle-body direction run

The normalized noise_score is a weighted blend of:
- wick noise       : 35%
- candle alternation: 30%
- directional inefficiency (1 - efficiency): 20%
- run fragmentation (1 - run_length / window_bars): 15%

Regime thresholds are deterministic:
- CLEAN  : noise_score < 0.34
- MIXED  : 0.34 <= noise_score < 0.67
- CHOPPY : noise_score >= 0.67
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

TIMEFRAME = "15m"
WINDOW_BARS = 6
MIN_BARS_REQUIRED = 6
CLEAN_MAX = 0.34
MIXED_MAX = 0.67


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _mean(values: Sequence[float]) -> float:
    return sum(values) / max(len(values), 1)


def _body_dir(open_: float, close: float) -> int:
    if close > open_:
        return 1
    if close < open_:
        return -1
    return 0


def alternation_ratio(directions: Sequence[int]) -> float:
    non_zero = [direction for direction in directions if direction]
    if len(non_zero) < 2:
        return 0.0
    flips = sum(1 for left, right in zip(non_zero, non_zero[1:]) if left != right)
    return flips / (len(non_zero) - 1)


def directional_run_length(directions: Sequence[int]) -> int:
    best = current = 0
    last = 0
    for direction in directions:
        if not direction:
            current = 0
            last = 0
            continue
        if direction == last:
            current += 1
        else:
            current = 1
            last = direction
        best = max(best, current)
    return best


def directional_efficiency(closes: Sequence[float]) -> float:
    if len(closes) < 2:
        return 0.0
    path = sum(abs(right - left) for left, right in zip(closes, closes[1:]))
    if path <= 0:
        return 0.0
    return abs(closes[-1] - closes[0]) / path


def wick_body_noise(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> float:
    ratios = []
    for open_, high, low, close in zip(opens, highs, lows, closes):
        body = abs(close - open_)
        upper = max(0.0, high - max(open_, close))
        lower = max(0.0, min(open_, close) - low)
        ratios.append(min((upper + lower) / max(body, 1e-6), 6.0))
    return _mean(ratios)


def classify_noise_score(noise_score: float) -> str:
    if noise_score < CLEAN_MAX:
        return "CLEAN"
    if noise_score < MIXED_MAX:
        return "MIXED"
    return "CHOPPY"


def unavailable(reason: str, *, reference_bar_start: Optional[int] = None) -> Dict[str, Any]:
    return {
        "available": False,
        "timeframe": TIMEFRAME,
        "window_bars": WINDOW_BARS,
        "completed_bars": 0,
        "reference_bar_start": reference_bar_start,
        "reference_bar_end": reference_bar_start + 900 if reference_bar_start is not None else None,
        "wick_body_noise": None,
        "alternation_ratio": None,
        "directional_efficiency": None,
        "directional_run_length": 0,
        "noise_score": None,
        "regime": None,
        "reason": reason,
    }


def observe(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float] | None = None,
    *,
    reference_bar_start: Optional[int] = None,
    window_bars: int = WINDOW_BARS,
) -> Dict[str, Any]:
    del volumes
    if window_bars < MIN_BARS_REQUIRED:
        return unavailable(
            "window_bars_below_minimum",
            reference_bar_start=reference_bar_start,
        )
    if min(len(opens), len(highs), len(lows), len(closes)) < window_bars:
        return unavailable(
            "insufficient_completed_15m_bars",
            reference_bar_start=reference_bar_start,
        )

    recent_opens = [float(value) for value in opens[-window_bars:]]
    recent_highs = [float(value) for value in highs[-window_bars:]]
    recent_lows = [float(value) for value in lows[-window_bars:]]
    recent_closes = [float(value) for value in closes[-window_bars:]]
    directions = [_body_dir(open_, close) for open_, close in zip(recent_opens, recent_closes)]

    wick_noise = wick_body_noise(recent_opens, recent_highs, recent_lows, recent_closes)
    alternation = alternation_ratio(directions)
    efficiency = directional_efficiency(recent_closes)
    run_length = directional_run_length(directions)

    wick_component = _clamp(wick_noise / 2.5)
    alternation_component = _clamp(alternation)
    inefficiency_component = _clamp(1.0 - efficiency)
    fragmentation_component = _clamp(1.0 - min(run_length / max(window_bars, 1), 1.0))
    noise_score = round(
        _clamp(
            0.35 * wick_component
            + 0.30 * alternation_component
            + 0.20 * inefficiency_component
            + 0.15 * fragmentation_component
        ),
        3,
    )

    return {
        "available": True,
        "timeframe": TIMEFRAME,
        "window_bars": window_bars,
        "completed_bars": window_bars,
        "reference_bar_start": reference_bar_start,
        "reference_bar_end": reference_bar_start + 900 if reference_bar_start is not None else None,
        "wick_body_noise": round(wick_noise, 6),
        "alternation_ratio": round(alternation, 6),
        "directional_efficiency": round(efficiency, 6),
        "directional_run_length": int(run_length),
        "noise_score": noise_score,
        "regime": classify_noise_score(noise_score),
        "reason": "completed_15m_ohlcv_window",
    }
