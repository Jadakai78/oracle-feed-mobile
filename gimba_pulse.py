"""gimba_pulse.py — Gimba Pulse micro-regime observer (training only).

Pulse classifies short-horizon, structure-light market behavior from public
OHLCV only. It is diagnostic/training-only in v1: no trade claims, execution
eligibility, order placement, sizing, live risk changes, or KNN adjustments.

OHLCV limitations:
- Uses completed Kraken OHLC bars only; no order-book, tape sequencing, or
  proprietary liquidity data are available.
- Breakout hold/fail is approximated from candle closes/wicks; true intrabar
  event ordering cannot be known from OHLC alone.
- Wick/body rejection noise is a proxy for two-sided rejection, not a direct
  measure of passive absorption or hidden liquidity.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple

KRAKEN_API = "https://api.kraken.com/0/public"
INTERVAL_MINUTES = 15
LOOKBACK_BARS = 12
MIN_BARS_REQUIRED = 10
STATE_DEAD = "PULSE_DEAD"
STATE_CHOPPY = "PULSE_CHOPPY"
STATE_IMPULSIVE = "PULSE_IMPULSIVE"
STATE_EXHAUSTED = "PULSE_EXHAUSTED"
DEAD_REALIZED_RANGE_MAX = 0.004
DEAD_RANGE_EXPANSION_MAX = 1.05
IMPULSIVE_EFFICIENCY_MIN = 0.62
IMPULSIVE_RANGE_EXPANSION_MIN = 1.15
IMPULSIVE_ALTERNATION_MAX = 0.45
IMPULSIVE_RUN_LENGTH_MIN = 3
EXHAUSTED_RANGE_EXPANSION_MIN = 1.1
EXHAUSTED_WICK_NOISE_MIN = 1.6
EXHAUSTED_ALT_WICK_NOISE_MIN = 1.25
EXHAUSTED_EFFICIENCY_MAX = 0.45
EXHAUSTED_ALTERNATION_MIN = 0.55
EXHAUSTED_RUN_LENGTH_MIN = 3
OHLCV_LIMITATIONS = [
    "completed_ohlcv_only",
    "no_order_book_or_trade_sequence",
    "breakout_retention_is_close_and_wick_proxy",
]


def _request(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{KRAKEN_API}{path}?{query}", timeout=12) as response:
        payload = json.loads(response.read())
    if payload.get("error"):
        raise RuntimeError("; ".join(payload["error"]))
    return payload.get("result") or {}


def _fetch_ohlc(kraken_pair: str, interval: int = INTERVAL_MINUTES, limit: int = LOOKBACK_BARS + 2) -> Optional[List[List[Any]]]:
    result = _request("/OHLC", {"pair": kraken_pair, "interval": interval})
    key = next((name for name in result if name != "last"), None)
    rows = list(result.get(key) or []) if key else []
    if len(rows) < 2:
        return None
    return rows[-limit:-1]


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


def _alternation_ratio(directions: Sequence[int]) -> float:
    non_zero = [direction for direction in directions if direction]
    if len(non_zero) < 2:
        return 0.0
    flips = sum(1 for left, right in zip(non_zero, non_zero[1:]) if left != right)
    return flips / (len(non_zero) - 1)


def _longest_run(directions: Sequence[int]) -> int:
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


def _directional_efficiency(closes: Sequence[float]) -> float:
    if len(closes) < 2:
        return 0.0
    path = sum(abs(right - left) for left, right in zip(closes, closes[1:]))
    if path <= 0:
        return 0.0
    return abs(closes[-1] - closes[0]) / path


def _wick_noise(opens: Sequence[float], highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> float:
    ratios: List[float] = []
    for open_, high, low, close in zip(opens, highs, lows, closes):
        body = abs(close - open_)
        upper = max(0.0, high - max(open_, close))
        lower = max(0.0, min(open_, close) - low)
        ratios.append(min((upper + lower) / max(body, 1e-6), 6.0))
    return _mean(ratios)


def _breakout_status(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> Tuple[str, Optional[float], str]:
    if len(highs) < 6:
        return "NEUTRAL", None, "NONE"
    prev_high = max(highs[-6:-1])
    prev_low = min(lows[-6:-1])
    last_high = highs[-1]
    last_low = lows[-1]
    last_close = closes[-1]
    if last_close > prev_high:
        return "UP", prev_high, "HELD"
    if last_close < prev_low:
        return "DOWN", prev_low, "HELD"
    up_excess = last_high - prev_high
    down_excess = prev_low - last_low
    if up_excess > 0 and up_excess >= down_excess:
        return "UP", prev_high, "FAILED"
    if down_excess > 0:
        return "DOWN", prev_low, "FAILED"
    return "NEUTRAL", None, "NONE"


def _metrics(rows: Sequence[Sequence[Any]]) -> Dict[str, Any]:
    opens = [float(row[1]) for row in rows]
    highs = [float(row[2]) for row in rows]
    lows = [float(row[3]) for row in rows]
    closes = [float(row[4]) for row in rows]
    volumes = [float(row[6]) for row in rows]
    recent_slice = slice(-6, None)
    prior_slice = slice(-10, -6)
    recent_highs = highs[recent_slice]
    recent_lows = lows[recent_slice]
    recent_closes = closes[recent_slice]
    recent_opens = opens[recent_slice]
    recent_ranges = [high - low for high, low in zip(recent_highs, recent_lows)]
    prior_ranges = [high - low for high, low in zip(highs[prior_slice], lows[prior_slice])] or recent_ranges
    recent_avg_range = _mean(recent_ranges)
    prior_avg_range = max(_mean(prior_ranges), 1e-6)
    reference_close = max(abs(recent_closes[-1]), 1e-6)
    realized_range = (max(recent_highs) - min(recent_lows)) / reference_close
    range_expansion = recent_avg_range / prior_avg_range
    directions = [_body_dir(open_, close) for open_, close in zip(recent_opens, recent_closes)]
    alternation = _alternation_ratio(directions)
    run_length = _longest_run(directions)
    efficiency = _directional_efficiency(recent_closes)
    wick_noise = _wick_noise(recent_opens, recent_highs, recent_lows, recent_closes)
    breakout_side, breakout_level, breakout_status = _breakout_status(recent_highs, recent_lows, recent_closes)
    net_change = recent_closes[-1] - recent_closes[0]
    observer_direction = breakout_side if breakout_side != "NEUTRAL" else ("UP" if net_change > 0 else "DOWN" if net_change < 0 else "NEUTRAL")
    return {
        "reference_close": recent_closes[-1],
        "reference_high": recent_highs[-1],
        "reference_low": recent_lows[-1],
        "reference_volume": volumes[-1],
        "reference_bar_start": int(float(rows[-1][0])),
        "reference_bar_end": int(float(rows[-1][0])) + INTERVAL_MINUTES * 60,
        "realized_range": round(realized_range, 6),
        "range_expansion": round(range_expansion, 6),
        "directional_efficiency": round(efficiency, 6),
        "alternation_ratio": round(alternation, 6),
        "directional_run_length": run_length,
        "wick_body_noise": round(wick_noise, 6),
        "breakout_side": breakout_side,
        "breakout_level": round(breakout_level, 10) if breakout_level is not None else None,
        "breakout_status": breakout_status,
        "observer_direction": observer_direction,
    }


def _state(metrics: Dict[str, Any]) -> Tuple[str, float, str]:
    realized_range = float(metrics["realized_range"])
    range_expansion = float(metrics["range_expansion"])
    efficiency = float(metrics["directional_efficiency"])
    alternation = float(metrics["alternation_ratio"])
    wick_noise = float(metrics["wick_body_noise"])
    run_length = int(metrics["directional_run_length"])
    breakout_status = str(metrics["breakout_status"])

    range_score = _clamp(realized_range / 0.02)
    expansion_score = _clamp((range_expansion - 0.8) / 0.8)
    efficiency_score = _clamp(efficiency)
    stability_score = _clamp(1.0 - alternation)
    run_score = _clamp(run_length / 5.0)
    rejection_penalty = _clamp(wick_noise / 3.0)
    pulse_score = round(
        _clamp(
            0.22 * range_score
            + 0.18 * expansion_score
            + 0.22 * efficiency_score
            + 0.14 * stability_score
            + 0.12 * run_score
            + 0.12 * (1.0 - rejection_penalty)
        ),
        3,
    )

    if realized_range < DEAD_REALIZED_RANGE_MAX and range_expansion < DEAD_RANGE_EXPANSION_MAX:
        return STATE_DEAD, pulse_score, "Short-window range is muted and expansion is absent, leaving little observable pulse."
    if (
        breakout_status == "HELD"
        and efficiency >= IMPULSIVE_EFFICIENCY_MIN
        and range_expansion >= IMPULSIVE_RANGE_EXPANSION_MIN
        and alternation <= IMPULSIVE_ALTERNATION_MAX
        and run_length >= IMPULSIVE_RUN_LENGTH_MIN
    ):
        return STATE_IMPULSIVE, pulse_score, "Range is expanding with efficient directional travel, low alternation, and a local break that is holding."
    if (
        breakout_status == "FAILED"
        or (range_expansion >= EXHAUSTED_RANGE_EXPANSION_MIN and wick_noise >= EXHAUSTED_WICK_NOISE_MIN and run_length >= EXHAUSTED_RUN_LENGTH_MIN)
        or (
            (range_expansion >= EXHAUSTED_RANGE_EXPANSION_MIN or run_length >= EXHAUSTED_RUN_LENGTH_MIN)
            and efficiency < EXHAUSTED_EFFICIENCY_MAX
            and alternation >= EXHAUSTED_ALTERNATION_MIN
            and wick_noise >= EXHAUSTED_ALT_WICK_NOISE_MIN
        )
    ):
        return STATE_EXHAUSTED, pulse_score, "Expansion is being rejected: breakout retention failed or directional runs are ending in noisy rejection."
    return STATE_CHOPPY, pulse_score, "Two-sided candle alternation and rejection noise dominate the short window; any local break lacks sufficient directional efficiency or expansion to qualify as impulsive."


def evaluate(pair: str, kraken_pair: str, _current_price: float, _fg_score: int = 50) -> Dict[str, Any]:
    try:
        rows = _fetch_ohlc(kraken_pair, INTERVAL_MINUTES, LOOKBACK_BARS + 2)
    except Exception as exc:
        rows = None
        fetch_error = f"pulse_fetch_error:{type(exc).__name__}"
    else:
        fetch_error = ""

    if not rows or len(rows) < MIN_BARS_REQUIRED:
        pulse_state = STATE_DEAD
        pulse_score = 0.0
        why = "Pulse fell back to DEAD because there was not enough completed 15m OHLCV context to measure the micro-regime."
        indicators = {
            "realized_range": 0.0,
            "range_expansion": 0.0,
            "directional_efficiency": 0.0,
            "alternation_ratio": 0.0,
            "directional_run_length": 0,
            "wick_body_noise": 0.0,
            "breakout_side": "NEUTRAL",
            "breakout_level": None,
            "breakout_status": "NONE",
        }
        diagnostics = {
            "observer_direction": "NEUTRAL",
            "reference_close": None,
            "reference_high": None,
            "reference_low": None,
            "reference_bar_start": None,
            "reference_bar_end": None,
            "fetch_error": fetch_error or "insufficient_ohlcv_context",
            "ohlcv_limitations": OHLCV_LIMITATIONS,
        }
    else:
        raw_metrics = _metrics(rows)
        indicators = {
            key: raw_metrics[key]
            for key in (
                "realized_range",
                "range_expansion",
                "directional_efficiency",
                "alternation_ratio",
                "directional_run_length",
                "wick_body_noise",
                "breakout_side",
                "breakout_level",
                "breakout_status",
            )
        }
        pulse_state, pulse_score, why = _state(raw_metrics)
        diagnostics = {
            "observer_direction": raw_metrics["observer_direction"],
            "breakout_side": raw_metrics["breakout_side"],
            "breakout_level": raw_metrics["breakout_level"],
            "breakout_status": raw_metrics["breakout_status"],
            "reference_close": raw_metrics["reference_close"],
            "reference_high": raw_metrics["reference_high"],
            "reference_low": raw_metrics["reference_low"],
            "reference_bar_start": raw_metrics["reference_bar_start"],
            "reference_bar_end": raw_metrics["reference_bar_end"],
            "ohlcv_limitations": OHLCV_LIMITATIONS,
        }

    return {
        "pair": pair,
        "bias": "NONE",
        "engine": "GimbaPulse",
        "setup_type": pulse_state,
        "pulse_state": pulse_state,
        "pulse_score": pulse_score,
        "conviction": pulse_score,
        "entry": None,
        "sl": None,
        "tp": None,
        "why": why,
        "action_state": "observe",
        "indicators": indicators,
        "diagnostics": diagnostics,
        "training_only": True,
        "diagnostic_only": True,
    }
