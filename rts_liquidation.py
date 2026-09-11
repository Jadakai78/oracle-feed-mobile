"""
rts_liquidation.py — RTS Liquidation Specialist

RetailCraft Sniper. Liquidity and trap specialist.

Identity:
- seek the resting liquidity
- detect the raid
- determine whether acceptance or reclaim won
- veto bad aggression while trap is unresolved
- capture the move once trapped inventory is exposed

Event families:
- LIQUIDITY_SWEEP_RECLAIM_LONG / SHORT
- FAILED_BREAKOUT_SHORT
- FAILED_BREAKDOWN_LONG
- EXTENSION_RISK_NO_SHORT / LONG
- LIQUIDATION_TO_CONTINUATION_LONG / SHORT
- STAND_ASIDE_AMBIGUOUS_SWEEP

Precedence:
- confirmed RTS veto outranks all other specialists

Self-contained:
- fetches 15m OHLC from Kraken
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("rts_liquidation")


PRIOR_WINDOW = 25
RECLAIM_ATR_FACTOR = 0.05
STOP_ATR_FACTOR = 0.20
ENTRY_ATR_FACTOR = 0.15


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


def _liquidity_pool(rows: List, prior_window: int = PRIOR_WINDOW) -> Tuple[float, float]:
    """
    Prior completed candles before the last one define the pool.
    """
    if len(rows) < prior_window + 2:
        prior = rows[:-1]
    else:
        prior = rows[-(prior_window + 1):-1]

    pool_high = max(float(r[2]) for r in prior)
    pool_low = min(float(r[3]) for r in prior)
    return pool_high, pool_low


def _relative_volume(v: np.ndarray, lookback: int = 20) -> float:
    if len(v) < lookback + 1:
        return 1.0
    avg = v[-lookback - 1:-1].mean()
    return round(float(v[-1] / avg), 2) if avg > 0 else 1.0


def _is_strong_rejection(o: float, h: float, l: float, c: float) -> bool:
    """
    Strong rejection wick on either side.
    """
    total = h - l
    if total <= 0:
        return False

    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return (upper_wick / total > 0.55) or (lower_wick / total > 0.55)


def _trap_score(
    swept_high: bool,
    swept_low: bool,
    reclaim_high: bool,
    reclaim_low: bool,
    rvol: float,
    strong_wick: bool,
    atr_val: float,
    sweep_size: float,
) -> float:
    """
    Trap-risk score:
    0.0 = very clean / little residual risk
    1.0 = unresolved / dangerous
    """
    score = 0.5

    if reclaim_high or reclaim_low:
        score -= 0.30
    elif swept_high or swept_low:
        score += 0.20

    if rvol >= 1.5:
        score -= 0.10
    if strong_wick:
        score -= 0.10
    if atr_val > 0 and sweep_size > atr_val * 0.5:
        score -= 0.05

    return round(max(0.0, min(1.0, score)), 2)


def _continuation_after_reclaim(
    rows: List,
    pool_high: float,
    pool_low: float,
    reclaim_buffer: float,
) -> Tuple[bool, bool]:
    """
    Previous candle reclaimed, current candle continues in reclaim direction.
    Returns:
        continuation_short, continuation_long
    """
    if len(rows) < 28:
        return False, False

    prev_h = float(rows[-2][2])
    prev_l = float(rows[-2][3])
    prev_c = float(rows[-2][4])
    last_c = float(rows[-1][4])

    prev_swept_high = prev_h > pool_high
    prev_swept_low = prev_l < pool_low
    prev_reclaim_high = prev_swept_high and prev_c < (pool_high - reclaim_buffer)
    prev_reclaim_low = prev_swept_low and prev_c > (pool_low + reclaim_buffer)

    continuation_short = prev_reclaim_high and last_c < pool_high
    continuation_long = prev_reclaim_low and last_c > pool_low

    return continuation_short, continuation_long


def evaluate(
    pair: str,
    kraken_pair: str,
    current_price: float,
    fg_score: int = 50,
) -> Dict[str, Any]:
    null_result = {
        "pair": pair,
        "bias": "NONE",
        "engine": "RTSLiquidation",
        "setup_type": "NO_TRAP",
        "conviction": 0.0,
        "entry": None,
        "sl": None,
        "tp": None,
        "why": "insufficient_data",
        "action_state": "idle",
        "trap_score": 0.5,
        "veto": False,
        "veto_direction": "none",
        "indicators": {
            "pool_high": 0.0,
            "pool_low": 0.0,
            "midpoint": 0.0,
            "atr": 0.0,
            "swept_high": False,
            "swept_low": False,
            "reclaim_high": False,
            "reclaim_low": False,
            "rvol": 1.0,
            "strong_wick": False,
            "sweep_size": 0.0,
        },
    }

    rows = _fetch_ohlc(kraken_pair, interval=15, limit=60)
    if not rows or len(rows) < 27:
        return null_result

    o, h, l, c, v = _to_arrays(rows)
    atr_val = _atr(h, l, c, 14)
    if atr_val <= 0:
        null_result["why"] = "atr_unavailable"
        return null_result

    pool_high, pool_low = _liquidity_pool(rows)
    midpoint = (pool_high + pool_low) / 2.0

    last_o = float(o[-1])
    last_h = float(h[-1])
    last_l = float(l[-1])
    last_c = float(c[-1])
    price = float(c[-1])

    reclaim_buffer = atr_val * RECLAIM_ATR_FACTOR
    stop_buffer = atr_val * STOP_ATR_FACTOR
    entry_buffer = atr_val * ENTRY_ATR_FACTOR

    swept_high = last_h > pool_high
    swept_low = last_l < pool_low
    reclaim_high = swept_high and last_c < (pool_high - reclaim_buffer)
    reclaim_low = swept_low and last_c > (pool_low + reclaim_buffer)

    rvol = _relative_volume(v, 20)
    strong_wick = _is_strong_rejection(last_o, last_h, last_l, last_c)

    sweep_size = max(
        (last_h - pool_high) if swept_high else 0.0,
        (pool_low - last_l) if swept_low else 0.0,
    )

    trap_score_val = _trap_score(
        swept_high,
        swept_low,
        reclaim_high,
        reclaim_low,
        rvol,
        strong_wick,
        atr_val,
        sweep_size,
    )

    continuation_short, continuation_long = _continuation_after_reclaim(
        rows, pool_high, pool_low, reclaim_buffer
    )

    bias = "NONE"
    setup_type = "NO_TRAP"
    conviction = 0.0
    action = "idle"
    why_parts: List[str] = []
    veto = False
    veto_dir = "none"

    if reclaim_high and reclaim_low:
        setup_type = "STAND_ASIDE_AMBIGUOUS_SWEEP"
        why_parts = ["two_sided_sweep_same_candle"]
        veto = True
        veto_dir = "both"
        action = "idle"

    elif reclaim_high:
        bias = "SHORT"
        setup_type = "LIQUIDITY_SWEEP_RECLAIM_SHORT"
        conviction = 0.75
        conviction += max(0.0, (0.5 - trap_score_val)) * 0.10
        if rvol >= 1.5:
            conviction += 0.05
        if strong_wick:
            conviction += 0.05
        why_parts = [
            "buy_side_liquidity_swept",
            "reclaimed_below_pool_high",
            f"pool_high={pool_high:.4f}",
            f"trap_score={trap_score_val:.2f}",
            f"rvol={rvol:.2f}",
        ]
        action = "watch"
        veto_dir = "long"

    elif reclaim_low:
        bias = "LONG"
        setup_type = "LIQUIDITY_SWEEP_RECLAIM_LONG"
        conviction = 0.75
        conviction += max(0.0, (0.5 - trap_score_val)) * 0.10
        if rvol >= 1.5:
            conviction += 0.05
        if strong_wick:
            conviction += 0.05
        why_parts = [
            "sell_side_liquidity_swept",
            "reclaimed_above_pool_low",
            f"pool_low={pool_low:.4f}",
            f"trap_score={trap_score_val:.2f}",
            f"rvol={rvol:.2f}",
        ]
        action = "watch"
        veto_dir = "short"

    elif swept_high and not reclaim_high and strong_wick:
        bias = "SHORT"
        setup_type = "FAILED_BREAKOUT_SHORT"
        conviction = 0.55
        why_parts = [
            "above_pool_high",
            "strong_rejection_wick",
            "breakout_acceptance_failing",
            f"pool_high={pool_high:.4f}",
            f"rvol={rvol:.2f}",
        ]
        action = "watch"
        veto_dir = "long"

    elif swept_low and not reclaim_low and strong_wick:
        bias = "LONG"
        setup_type = "FAILED_BREAKDOWN_LONG"
        conviction = 0.55
        why_parts = [
            "below_pool_low",
            "strong_rejection_wick",
            "breakdown_acceptance_failing",
            f"pool_low={pool_low:.4f}",
            f"rvol={rvol:.2f}",
        ]
        action = "watch"
        veto_dir = "short"

    elif swept_high and not reclaim_high:
        setup_type = "EXTENSION_RISK_NO_SHORT"
        why_parts = [
            "buy_side_liquidity_being_raided",
            "no_reclaim_yet",
            "do_not_short_into_active_extension",
            f"pool_high={pool_high:.4f}",
        ]
        veto = True
        veto_dir = "short"
        action = "idle"

    elif swept_low and not reclaim_low:
        setup_type = "EXTENSION_RISK_NO_LONG"
        why_parts = [
            "sell_side_liquidity_being_raided",
            "no_reclaim_yet",
            "do_not_long_into_active_extension",
            f"pool_low={pool_low:.4f}",
        ]
        veto = True
        veto_dir = "long"
        action = "idle"

    elif continuation_short:
        bias = "SHORT"
        setup_type = "LIQUIDATION_TO_CONTINUATION_SHORT"
        conviction = 0.68
        why_parts = [
            "prior_reclaim_high_confirmed",
            "continuation_below_pool_high",
            f"pool_high={pool_high:.4f}",
        ]
        action = "watch"
        veto_dir = "long"

    elif continuation_long:
        bias = "LONG"
        setup_type = "LIQUIDATION_TO_CONTINUATION_LONG"
        conviction = 0.68
        why_parts = [
            "prior_reclaim_low_confirmed",
            "continuation_above_pool_low",
            f"pool_low={pool_low:.4f}",
        ]
        action = "watch"
        veto_dir = "short"

    else:
        why_parts = ["no_sweep_condition_detected"]

    if action == "watch" and conviction >= 0.65:
        veto = True

    entry = sl = tp = None
    if action == "watch" and atr_val > 0:
        if bias == "LONG":
            entry = round(price, 4)
            sl = round(min(price - atr_val * 2.0, last_l - stop_buffer), 4)
            tp = round(midpoint, 4)
        elif bias == "SHORT":
            entry = round(price, 4)
            sl = round(max(price + atr_val * 2.0, last_h + stop_buffer), 4)
            tp = round(midpoint, 4)

    return {
        "pair": pair,
        "bias": bias,
        "engine": "RTSLiquidation",
        "setup_type": setup_type,
        "conviction": round(min(max(conviction, 0.0), 1.0), 3),
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "why": " | ".join(why_parts),
        "action_state": action,
        "trap_score": trap_score_val,
        "veto": veto,
        "veto_direction": veto_dir,
        "indicators": {
            "pool_high": round(pool_high, 4),
            "pool_low": round(pool_low, 4),
            "midpoint": round(midpoint, 4),
            "atr": round(atr_val, 4),
            "swept_high": swept_high,
            "swept_low": swept_low,
            "reclaim_high": reclaim_high,
            "reclaim_low": reclaim_low,
            "rvol": rvol,
            "strong_wick": strong_wick,
            "sweep_size": round(sweep_size, 4),
            "entry_buffer": round(entry_buffer, 4),
        },
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
        engine = _KNN("rts_liquidation", _log, min_samples=30)
        adj, n = engine.adjust(result)

        if n >= 30:
            raw = result["conviction"]
            adjusted = round(min(max(raw + adj, 0.0), 1.0), 3)

            is_confirmed_reclaim = result.get("setup_type", "") in (
                "LIQUIDITY_SWEEP_RECLAIM_LONG",
                "LIQUIDITY_SWEEP_RECLAIM_SHORT",
            )

            ind = result.get("indicators", {})
            fully_confirmed = (
                is_confirmed_reclaim
                and (ind.get("reclaim_high", False) or ind.get("reclaim_low", False))
                and ind.get("strong_wick", False)
                and ind.get("rvol", 0.0) >= 1.5
            )

            if fully_confirmed:
                adjusted = max(adjusted, 0.62)

            result["conviction"] = adjusted
            result["knn_adj"] = round(adj, 3)
            result["knn_samples"] = n
            result["floor_applied"] = fully_confirmed
        else:
            result["knn_adj"] = 0.0
            result["knn_samples"] = n
            result["floor_applied"] = False

    except Exception:
        result["knn_adj"] = 0.0
        result["knn_samples"] = 0
        result["floor_applied"] = False

    return result
