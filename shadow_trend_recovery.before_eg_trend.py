"""shadow_trend_recovery.py — Shadow-Only Trend Recovery Candidate Specialist

SHADOW MODE — evidence collection only.

This module emits inert candidate claims that are:
  - logged to training_logs/shadow_trend_recovery.jsonl
  - always annotated with shadow_mode=True, diagnostic_only=True,
    training_only=True, action_state='observe'
  - entry/sl/tp always set to None
  - never forwarded to the execution router, KNN, or OFFENSE/PERMISSION

Mandate: classify continuation setups after pullback, liquidation, or
reclaim events.  Valid setup families are limited to:
  RECLAIM_*, PULLBACK_CONTINUATION_*, PULLBACK_HOLD_*

Generic trend-direction calls (no reclaim/pullback semantics) are NOT emitted.
This is a hard contract requirement.

Setup families emitted:
  SHADOW_TRD_RECLAIM_LONG
  SHADOW_TRD_RECLAIM_SHORT
  SHADOW_TRD_PULLBACK_CONTINUATION_LONG
  SHADOW_TRD_PULLBACK_CONTINUATION_SHORT
  SHADOW_TRD_PULLBACK_HOLD_LONG
  SHADOW_TRD_PULLBACK_HOLD_SHORT
  SHADOW_TRD_NO_SIGNAL

Reclaim semantics:
  - price was below a key level (EMA or swing low) and has closed back above it
    (or above for short side: back below swing high)

Pullback-continuation semantics:
  - price has retraced into a pullback zone (discount for long, premium for short)
    and is resuming in the trend direction with momentum confirmation

Pullback-hold semantics:
  - price is at the pullback zone boundary, not yet breaking; hold/watch

Required inputs (OHLCV + structure context from scanner):
  - 15m OHLCV bars (RSI, RVOL, ATR, EMA20/50, swing structure)
  - D1/H4 trend from structure context (passed in or inferred from 4H/D1 OHLCV)

No order-book, no proprietary data.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import shadow_utils as _su

# ── SHADOW-MODE CONSTANTS — MUST NOT CHANGE ────────────────────────────────

SHADOW_MODE = True
DIAGNOSTIC_ONLY = True
TRAINING_ONLY = True
ACTION_STATE = "observe"
ENGINE_LABEL = "ShadowTrendRecovery"
LOG_BOT_NAME = "shadow_trend_recovery"

# Namespace prefix that all non-NO_SIGNAL families must carry
TREND_RECOVERY_NS = "SHADOW_TRD_"

# Valid semantic family prefixes (the portion after TREND_RECOVERY_NS)
# Contract restriction: only these three are permitted.
VALID_PREFIXES = ("RECLAIM_", "PULLBACK_CONTINUATION_", "PULLBACK_HOLD_")

# Setup family tokens
SF_RECLAIM_LONG              = "SHADOW_TRD_RECLAIM_LONG"
SF_RECLAIM_SHORT             = "SHADOW_TRD_RECLAIM_SHORT"
SF_PB_CONTINUATION_LONG      = "SHADOW_TRD_PULLBACK_CONTINUATION_LONG"
SF_PB_CONTINUATION_SHORT     = "SHADOW_TRD_PULLBACK_CONTINUATION_SHORT"
SF_PB_HOLD_LONG              = "SHADOW_TRD_PULLBACK_HOLD_LONG"
SF_PB_HOLD_SHORT             = "SHADOW_TRD_PULLBACK_HOLD_SHORT"
SF_NO_SIGNAL                 = "SHADOW_TRD_NO_SIGNAL"

# Thresholds
PULLBACK_DISCOUNT_MAX        = 0.40   # below this fraction of range = discount zone
PULLBACK_PREMIUM_MIN         = 0.60   # above this fraction of range = premium zone
PULLBACK_HOLD_BAND           = 0.10   # ±10% around zone boundary = hold band
RVOL_MIN                     = 1.15
RSI_LONG_MIN                 = 48.0
RSI_SHORT_MAX                = 52.0
EMA_RECLAIM_ATR_BUFFER       = 0.10   # price must be EMA + buffer*ATR above EMA


# ── OHLCV helpers (delegated to shadow_utils) ─────────────────────────────

def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> float:
    return _su.atr(h, l, c, period)


def _rsi(c: np.ndarray, period: int = 14) -> float:
    return _su.rsi(c, period)


def _relative_volume(v: np.ndarray, lookback: int = 20) -> float:
    return _su.relative_volume(v, lookback)


def _ema(c: np.ndarray, period: int) -> float:
    if len(c) < period:
        return float(c[-1]) if len(c) else 0.0
    k = 2.0 / (period + 1)
    val = float(c[0])
    for price in c[1:]:
        val = float(price) * k + val * (1.0 - k)
    return val


def _swing_structure(
    h: np.ndarray, l: np.ndarray, lookback: int = 20,
) -> Tuple[str, float, float]:
    """Return (trend, swing_high, swing_low) from pivot analysis."""
    if len(h) < lookback or len(l) < lookback:
        return "ranging", float(h[-1]) if len(h) else 0.0, float(l[-1]) if len(l) else 0.0

    wh = h[-lookback:]
    wl = l[-lookback:]
    n = len(wh)
    pivot_highs: List[float] = []
    pivot_lows: List[float] = []

    for i in range(2, n - 2):
        if wh[i] > wh[i - 1] and wh[i] > wh[i - 2] and wh[i] > wh[i + 1] and wh[i] > wh[i + 2]:
            pivot_highs.append(float(wh[i]))
        if wl[i] < wl[i - 1] and wl[i] < wl[i - 2] and wl[i] < wl[i + 1] and wl[i] < wl[i + 2]:
            pivot_lows.append(float(wl[i]))

    sh = float(wh.max())
    sl = float(wl.min())

    if len(pivot_highs) >= 2 and len(pivot_lows) >= 2:
        hh = pivot_highs[-1] > pivot_highs[-2]
        hl = pivot_lows[-1] > pivot_lows[-2]
        lh = pivot_highs[-1] < pivot_highs[-2]
        ll = pivot_lows[-1] < pivot_lows[-2]
        if hh and hl:
            return "up", pivot_highs[-1], pivot_lows[-1]
        if lh and ll:
            return "down", pivot_highs[-1], pivot_lows[-1]

    return "ranging", sh, sl


def _premium_discount(price: float, swing_high: float, swing_low: float) -> Tuple[str, float]:
    rng = swing_high - swing_low
    if rng <= 0:
        return "neutral", 0.5
    pct = (price - swing_low) / rng
    return ("discount" if pct <= PULLBACK_DISCOUNT_MAX
            else "premium" if pct >= PULLBACK_PREMIUM_MIN
            else "neutral"), round(pct, 3)


# ── Contract validator ────────────────────────────────────────────────────

def _is_valid_trend_recovery_family(setup_family: str) -> bool:
    """Return True only when *setup_family* satisfies the TREND_RECOVERY contract.

    Valid families are either:
    - ``SF_NO_SIGNAL`` (``SHADOW_TRD_NO_SIGNAL``) — always permitted, or
    - a name that carries the ``SHADOW_TRD_`` namespace prefix **and** whose
      semantic portion (the text after the prefix) starts with exactly one of
      ``RECLAIM_``, ``PULLBACK_CONTINUATION_``, or ``PULLBACK_HOLD_``.

    Generic trend-direction families (e.g. ``SHADOW_TRD_BULLISH``) that lack
    a recognised semantic prefix are explicitly rejected.
    """
    if setup_family == SF_NO_SIGNAL:
        return True
    if not setup_family.startswith(TREND_RECOVERY_NS):
        return False
    semantic = setup_family[len(TREND_RECOVERY_NS):]
    return any(semantic.startswith(pfx) for pfx in VALID_PREFIXES)


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
        "required_inputs": ["ohlcv_15m", "structure_context"],
        "invalidation_level": None,
        "maturity_context": None,
        "reference_price": None,
        "reference_bar_ts": None,
        "entry": None,
        "sl": None,
        "tp": None,
    }


# ── Core evaluate ──────────────────────────────────────────────────────────

def evaluate_arrays(
    pair: str,
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    v: np.ndarray,
    structure_context: Optional[Dict[str, Any]] = None,
    reference_bar_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Evaluate the shadow trend recovery candidate from pre-built OHLCV arrays.

    Parameters
    ----------
    pair             : display pair name, e.g. 'SOL/USD'
    o, h, l, c, v   : numpy float64 arrays, length ≥ 30
    structure_context: optional dict with keys 'trend', 'zone', etc.
                       If omitted, trend is inferred from local OHLCV.
    reference_bar_ts : Unix timestamp of the reference bar (optional)

    Returns
    -------
    Inert shadow candidate dict.  entry/sl/tp are always None.
    """
    if len(c) < 30:
        return _null_result(pair, "insufficient_bars")

    price   = float(c[-1])
    atr_val = _atr(h, l, c, 14)
    rsi_val = _rsi(c, 14)
    rvol    = _relative_volume(v, 20)
    ema20   = _ema(c, 20)
    ema50   = _ema(c, 50)

    # Infer local swing structure for pullback zone
    local_trend, swing_high, swing_low = _swing_structure(h, l, 20)
    zone, eq_pct = _premium_discount(price, swing_high, swing_low)

    # Prefer structure context trend when available
    htf_trend = local_trend
    if structure_context:
        htf_trend = str(structure_context.get("trend") or local_trend)

    # ── Reclaim detection ─────────────────────────────────────────────────
    # Long reclaim: price now above EMA20 by a buffer (was recent below)
    # Short reclaim: price now below EMA20 by a buffer (was recent above)
    atr_buf = atr_val * EMA_RECLAIM_ATR_BUFFER if atr_val > 0 else 0.0

    # Previous close relative to EMA20 (use second-to-last close)
    prev_close = float(c[-2]) if len(c) >= 2 else price

    long_reclaim  = (prev_close < ema20) and (price > ema20 + atr_buf)
    short_reclaim = (prev_close > ema20) and (price < ema20 - atr_buf)

    # ── Setup classification ───────────────────────────────────────────────

    setup_family = SF_NO_SIGNAL
    side = "NONE"
    score = 0.0
    reasons: List[str] = []

    if htf_trend == "up":

        if long_reclaim and rvol >= RVOL_MIN and rsi_val >= RSI_LONG_MIN:
            # Reclaim of EMA20 in uptrend
            setup_family = SF_RECLAIM_LONG
            side = "LONG"
            score = round(0.60 + min(rvol - 1.15, 0.5) * 0.20, 3)
            reasons = [
                "ema20_reclaim",
                f"prev_below_ema20={prev_close:.4f}",
                f"price_above_ema20={price:.4f}",
                f"rvol={rvol:.2f}",
                f"rsi={rsi_val:.0f}",
            ]

        elif zone == "discount" and rvol >= RVOL_MIN and rsi_val >= RSI_LONG_MIN:
            # Pullback continuation in uptrend — price in discount zone, bouncing
            setup_family = SF_PB_CONTINUATION_LONG
            side = "LONG"
            score = round(0.50 + (PULLBACK_DISCOUNT_MAX - eq_pct) * 0.30, 3)
            reasons = [
                "uptrend_pullback_continuation",
                f"zone=discount",
                f"eq_pct={eq_pct:.2f}",
                f"rvol={rvol:.2f}",
                f"rsi={rsi_val:.0f}",
            ]

        elif zone == "neutral" and eq_pct <= PULLBACK_DISCOUNT_MAX + PULLBACK_HOLD_BAND:
            # Price just entering discount zone — pullback hold
            setup_family = SF_PB_HOLD_LONG
            side = "LONG"
            score = round(0.35, 3)
            reasons = [
                "uptrend_pullback_hold",
                f"eq_pct={eq_pct:.2f}",
                f"approaching_discount_zone",
            ]

        else:
            reasons = [
                f"htf_up_no_reclaim_or_pullback",
                f"zone={zone}",
                f"long_reclaim={long_reclaim}",
                f"rvol={rvol:.2f}",
            ]

    elif htf_trend == "down":

        if short_reclaim and rvol >= RVOL_MIN and rsi_val <= RSI_SHORT_MAX:
            # Reclaim of EMA20 to downside in downtrend
            setup_family = SF_RECLAIM_SHORT
            side = "SHORT"
            score = round(0.60 + min(rvol - 1.15, 0.5) * 0.20, 3)
            reasons = [
                "ema20_reclaim_short",
                f"prev_above_ema20={prev_close:.4f}",
                f"price_below_ema20={price:.4f}",
                f"rvol={rvol:.2f}",
                f"rsi={rsi_val:.0f}",
            ]

        elif zone == "premium" and rvol >= RVOL_MIN and rsi_val <= RSI_SHORT_MAX:
            # Pullback continuation in downtrend — price in premium zone, resuming down
            setup_family = SF_PB_CONTINUATION_SHORT
            side = "SHORT"
            score = round(0.50 + (eq_pct - PULLBACK_PREMIUM_MIN) * 0.30, 3)
            reasons = [
                "downtrend_pullback_continuation",
                f"zone=premium",
                f"eq_pct={eq_pct:.2f}",
                f"rvol={rvol:.2f}",
                f"rsi={rsi_val:.0f}",
            ]

        elif zone == "neutral" and eq_pct >= PULLBACK_PREMIUM_MIN - PULLBACK_HOLD_BAND:
            # Approaching premium — pullback hold
            setup_family = SF_PB_HOLD_SHORT
            side = "SHORT"
            score = round(0.35, 3)
            reasons = [
                "downtrend_pullback_hold",
                f"eq_pct={eq_pct:.2f}",
                f"approaching_premium_zone",
            ]

        else:
            reasons = [
                f"htf_down_no_reclaim_or_pullback",
                f"zone={zone}",
                f"short_reclaim={short_reclaim}",
                f"rvol={rvol:.2f}",
            ]

    else:
        # Ranging — no trend-recovery claim
        reasons = [
            f"htf_trend={htf_trend}",
            "no_trend_alignment_for_recovery",
        ]

    # ── Invalidation / maturity context ───────────────────────────────────

    if side == "LONG" and atr_val > 0:
        invalidation_level = round(min(ema20, price) - atr_val, 6)
        maturity_ctx = f"reclaim_hold_above_ema20={round(ema20, 6)}"
    elif side == "SHORT" and atr_val > 0:
        invalidation_level = round(max(ema20, price) + atr_val, 6)
        maturity_ctx = f"reclaim_hold_below_ema20={round(ema20, 6)}"
    else:
        invalidation_level = None
        maturity_ctx = f"zone={zone}_trend={htf_trend}"

    # ── Contract enforcement: validate before return ──────────────────────

    assert _is_valid_trend_recovery_family(setup_family), (
        f"Contract violation: {setup_family!r} is not a valid TREND_RECOVERY "
        f"setup family — must carry the '{TREND_RECOVERY_NS}' namespace and have "
        f"a semantic portion starting with one of {VALID_PREFIXES}"
    )

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
        "required_inputs": ["ohlcv_15m", "structure_context"],
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
            "ema20": round(ema20, 6),
            "ema50": round(ema50, 6),
            "htf_trend": htf_trend,
            "local_trend": local_trend,
            "zone": zone,
            "eq_pct": eq_pct,
            "long_reclaim": long_reclaim,
            "short_reclaim": short_reclaim,
        },
    }
