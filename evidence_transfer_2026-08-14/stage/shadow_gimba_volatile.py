"""shadow_gimba_volatile.py — Shadow-Only Volatile Candidate Specialist

SHADOW MODE — evidence collection only.

This module emits inert candidate claims that are:
  - logged to training_logs/shadow_volatile.jsonl
  - always annotated with shadow_mode=True, diagnostic_only=True,
    training_only=True, action_state='observe'
  - entry/sl/tp always set to None
  - never forwarded to the execution router, KNN, or OFFENSE/PERMISSION

Mandate: classify each scan as expansion/continuation versus
maturity/exhaustion using only currently available OHLCV/structure fields.
No proprietary or order-book inputs are used.

Setup families emitted:
  SHADOW_VOL_EXPANSION_LONG
  SHADOW_VOL_EXPANSION_SHORT
  SHADOW_VOL_CONTINUATION_LONG
  SHADOW_VOL_CONTINUATION_SHORT
  SHADOW_VOL_MATURITY_LONG
  SHADOW_VOL_MATURITY_SHORT
  SHADOW_VOL_EXHAUSTION
  SHADOW_VOL_NO_SIGNAL

Invalidation/maturity context fields:
  invalidation_level: price level that would negate the claim
  maturity_context: human-readable description of current move maturity
  reference_price: close of the reference bar

Required inputs (OHLCV only):
  - 15m OHLCV bars (ATR, RSI, RVOL, supertrend, move maturity, impulse speed)
  - No order-book, no proprietary data
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import shadow_utils as _su


# ── SHADOW-MODE CONSTANTS — MUST NOT CHANGE ────────────────────────────────

SHADOW_MODE = True
DIAGNOSTIC_ONLY = True
TRAINING_ONLY = True
ACTION_STATE = "observe"
ENGINE_LABEL = "ShadowGimbaVolatile"
LOG_BOT_NAME = "shadow_volatile"

# Setup family tokens
SF_EXPANSION_LONG      = "SHADOW_VOL_EXPANSION_LONG"
SF_EXPANSION_SHORT     = "SHADOW_VOL_EXPANSION_SHORT"
SF_CONTINUATION_LONG   = "SHADOW_VOL_CONTINUATION_LONG"
SF_CONTINUATION_SHORT  = "SHADOW_VOL_CONTINUATION_SHORT"
SF_MATURITY_LONG       = "SHADOW_VOL_MATURITY_LONG"
SF_MATURITY_SHORT      = "SHADOW_VOL_MATURITY_SHORT"
SF_EXHAUSTION          = "SHADOW_VOL_EXHAUSTION"
SF_NO_SIGNAL           = "SHADOW_VOL_NO_SIGNAL"

# Thresholds (OHLCV-based only)
RVOL_EXPANSION_MIN     = 1.40
RVOL_CONTINUATION_MIN  = 1.20
MATURITY_MATURE        = 0.65   # move considered mature when ≥ this
MATURITY_EXHAUSTED     = 0.80   # move considered exhausted when ≥ this
RSI_LONG_MIN           = 50.0
RSI_SHORT_MAX          = 50.0
SPEED_MIN              = 0.30


# ── OHLCV helpers (delegated to shadow_utils) ──────────────────────────────

def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> float:
    return _su.atr(h, l, c, period)


def _rsi(c: np.ndarray, period: int = 14) -> float:
    return _su.rsi(c, period)


def _relative_volume(v: np.ndarray, lookback: int = 20) -> float:
    return _su.relative_volume(v, lookback)


def _impulse_speed(c: np.ndarray, lookback: int = 20) -> float:
    if len(c) < lookback + 1:
        return 0.0
    start = c[-lookback - 1]
    end = c[-1]
    if start == 0:
        return 0.0
    return round(abs((end - start) / start) * 100.0, 2)


def _move_maturity(
    c: np.ndarray, h: np.ndarray, l: np.ndarray,
    atr_val: float, lookback: int = 20,
) -> float:
    if atr_val <= 0 or len(c) < lookback:
        return 0.5
    swing_low = float(l[-lookback:].min())
    swing_high = float(h[-lookback:].max())
    total_range = swing_high - swing_low
    if total_range <= 0:
        return 0.5
    return round(min(total_range / atr_val / 4.0, 1.0), 2)


def _supertrend_dir(
    h: np.ndarray, l: np.ndarray, c: np.ndarray,
    period: int = 10, mult: float = 3.0,
) -> tuple[int, float, bool]:
    """Return (direction, st_level, flipped). direction: 1=up, -1=down."""
    if len(c) < 3:
        return 1, float(c[-1]) if len(c) else 0.0, False

    tr_vals = [
        max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        for i in range(1, len(c))
    ]
    tr_arr = np.array(tr_vals, dtype=float)
    atr_arr = np.zeros_like(tr_arr)
    for i in range(len(tr_arr)):
        start = max(0, i - period + 1)
        atr_arr[i] = float(np.mean(tr_arr[start:i + 1]))

    hl2 = (h[1:] + l[1:]) / 2.0
    upper_band = hl2 + mult * atr_arr
    lower_band = hl2 - mult * atr_arr

    st = np.zeros(len(c) - 1, dtype=float)
    direction = np.ones(len(c) - 1, dtype=int)

    for i in range(len(st)):
        if i == 0:
            st[i] = lower_band[i]
            continue
        if c[i] > st[i - 1]:
            st[i] = max(lower_band[i], st[i - 1]) if direction[i - 1] == 1 else lower_band[i]
            direction[i] = 1
        else:
            st[i] = min(upper_band[i], st[i - 1]) if direction[i - 1] == -1 else upper_band[i]
            direction[i] = -1

    cur_dir = int(direction[-1])
    cur_st = float(st[-1])
    flipped = bool(len(direction) > 1 and int(direction[-1]) != int(direction[-2]))
    return cur_dir, cur_st, flipped


# ── Null result ────────────────────────────────────────────────────────────

def _null_result(pair: str, reason: str) -> Dict[str, Any]:
    return {
        "pair": pair,
        "engine": ENGINE_LABEL,
        "shadow_mode": SHADOW_MODE,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "training_only": TRAINING_ONLY,
        "action_state": ACTION_STATE,
        "setup_family": SF_NO_SIGNAL,
        "side": "NONE",
        "score": 0.0,
        "state": "no_signal",
        "reasons": [reason],
        "required_inputs": ["ohlcv_15m"],
        "invalidation_level": None,
        "maturity_context": None,
        "reference_price": None,
        "reference_bar_ts": None,
        "entry": None,
        "sl": None,
        "tp": None,
    }


# ── Core evaluate (accepts pre-built arrays, no live fetch) ────────────────

def evaluate_arrays(
    pair: str,
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    v: np.ndarray,
    reference_bar_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Evaluate the shadow volatile candidate from pre-built OHLCV arrays.

    Parameters
    ----------
    pair             : display pair name, e.g. 'SOL/USD'
    o, h, l, c, v   : numpy float64 arrays, length ≥ 30
    reference_bar_ts : Unix timestamp of the reference bar (optional)

    Returns
    -------
    Inert shadow candidate dict.  entry/sl/tp are always None.
    """
    if len(c) < 30:
        return _null_result(pair, "insufficient_bars")

    atr_val  = _atr(h, l, c, 14)
    rsi_val  = _rsi(c, 14)
    rvol     = _relative_volume(v, 20)
    speed    = _impulse_speed(c, 20)
    maturity = _move_maturity(c, h, l, atr_val, 20)
    price    = float(c[-1])

    st_dir, st_level, st_flipped = _supertrend_dir(h, l, c, 10, 3.0)

    # ── Classify ───────────────────────────────────────────────────────────

    setup_family = SF_NO_SIGNAL
    side = "NONE"
    score = 0.0
    reasons: List[str] = []

    # Exhaustion confirmation: low/declining RVOL or weak impulse tempo.
    # A move that is still actively expanding (high RVOL + strong speed)
    # is NOT exhausted regardless of maturity; it falls to the maturity branch.
    exhaustion_confirmed = (rvol < RVOL_CONTINUATION_MIN) or (speed < SPEED_MIN)

    # Exhaustion: high maturity AND confirmed exhaustion signal
    if maturity >= MATURITY_EXHAUSTED and exhaustion_confirmed:
        setup_family = SF_EXHAUSTION
        side = "LONG" if st_dir == 1 else "SHORT"
        score = round(maturity * 0.6, 3)
        reasons = [
            f"maturity={maturity:.2f}",
            f"st_dir={'up' if st_dir == 1 else 'down'}",
            "exhaustion_threshold_reached",
            f"rvol={rvol:.2f}",
            f"speed={speed:.2f}",
        ]

    # Maturity (moderately extended, or high-maturity without exhaustion confirmation).
    # Score = (1-maturity)*0.5 + 0.2:  ranges from ~0.375 at MATURITY_MATURE (0.65)
    # down to 0.2 at maturity=1.0.  The 0.2 floor is intentional for the
    # exhausted-but-still-expanding case — low confidence, observe only.
    elif maturity >= MATURITY_MATURE:
        setup_family = SF_MATURITY_LONG if st_dir == 1 else SF_MATURITY_SHORT
        side = "LONG" if st_dir == 1 else "SHORT"
        score = round((1.0 - maturity) * 0.5 + 0.2, 3)
        reasons = [
            f"maturity={maturity:.2f}",
            f"rvol={rvol:.2f}",
            "move_mature_no_new_entry",
        ]

    # Expansion: supertrend flip + rvol spike + speed
    elif (
        st_flipped
        and rvol >= RVOL_EXPANSION_MIN
        and speed >= SPEED_MIN
        and maturity < MATURITY_MATURE
    ):
        if st_dir == 1:
            setup_family = SF_EXPANSION_LONG
            side = "LONG"
        else:
            setup_family = SF_EXPANSION_SHORT
            side = "SHORT"
        score = round(0.55 + min(rvol - 1.4, 0.5) * 0.2, 3)
        reasons = [
            f"st_flip={'up' if st_dir == 1 else 'down'}",
            f"rvol={rvol:.2f}",
            f"speed={speed:.2f}",
            f"maturity={maturity:.2f}",
        ]

    # Continuation: aligned RSI + rvol + low maturity
    elif (
        rvol >= RVOL_CONTINUATION_MIN
        and maturity < MATURITY_MATURE
        and speed >= SPEED_MIN
    ):
        if st_dir == 1 and rsi_val >= RSI_LONG_MIN:
            setup_family = SF_CONTINUATION_LONG
            side = "LONG"
            score = round(0.40 + min(rvol - 1.2, 0.6) * 0.15, 3)
            reasons = [
                f"st_up",
                f"rsi={rsi_val:.0f}",
                f"rvol={rvol:.2f}",
                f"maturity={maturity:.2f}",
            ]
        elif st_dir == -1 and rsi_val <= RSI_SHORT_MAX:
            setup_family = SF_CONTINUATION_SHORT
            side = "SHORT"
            score = round(0.40 + min(rvol - 1.2, 0.6) * 0.15, 3)
            reasons = [
                "st_down",
                f"rsi={rsi_val:.0f}",
                f"rvol={rvol:.2f}",
                f"maturity={maturity:.2f}",
            ]
        else:
            reasons = [
                f"rvol={rvol:.2f}_ok_but_no_rsi_or_dir_confirm",
                f"st_dir={'up' if st_dir == 1 else 'down'}",
                f"rsi={rsi_val:.0f}",
            ]

    else:
        reasons = [
            f"rvol={rvol:.2f}",
            f"speed={speed:.2f}",
            f"maturity={maturity:.2f}",
            "participation_below_threshold",
        ]

    # ── Invalidation / maturity context ───────────────────────────────────

    if side == "LONG" and atr_val > 0:
        invalidation_level = round(price - atr_val * 1.5, 6)
    elif side == "SHORT" and atr_val > 0:
        invalidation_level = round(price + atr_val * 1.5, 6)
    else:
        invalidation_level = None

    if maturity < 0.3:
        maturity_ctx = "fresh_move"
    elif maturity < MATURITY_MATURE:
        maturity_ctx = "room_remaining"
    elif maturity < MATURITY_EXHAUSTED:
        maturity_ctx = "mature_extended"
    else:
        maturity_ctx = "exhausted"

    return {
        "pair": pair,
        "engine": ENGINE_LABEL,
        "shadow_mode": SHADOW_MODE,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "training_only": TRAINING_ONLY,
        "action_state": ACTION_STATE,
        "setup_family": setup_family,
        "side": side,
        "score": round(min(score, 1.0), 3),
        "state": setup_family.lower(),
        "reasons": reasons,
        "required_inputs": ["ohlcv_15m"],
        "invalidation_level": invalidation_level,
        "maturity_context": maturity_ctx,
        "reference_price": round(price, 6),
        "reference_bar_ts": reference_bar_ts,
        "entry": None,
        "sl": None,
        "tp": None,
        "indicators": {
            "atr": round(atr_val, 6),
            "rsi": rsi_val,
            "rvol": rvol,
            "speed_pct": speed,
            "maturity": maturity,
            "st_direction": st_dir,
            "st_flipped": st_flipped,
            "st_level": round(st_level, 6),
        },
    }
