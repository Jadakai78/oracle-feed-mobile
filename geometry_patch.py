# ── Geometry patch for delta_tempo_prop_router.py ─────────────────────────────
#
# REPLACE the entire _local_geometry function with this version.
# Changes:
#   1. Calculates ATR from the completed 15m bars (no external dependency).
#   2. Stop = local_low - (ATR * ATR_STOP_MULT) for LONG
#             local_high + (ATR * ATR_STOP_MULT) for SHORT
#   3. Minimum stop distance floor: rejects geometry if risk < MIN_RISK_PCT of entry.
#      Stops tighter than 0.15% are noise, not structure.
#   4. TP unchanged — still local_high / local_low.
#
# Constants to add near LOCAL_STRUCTURE_BARS at the top of the file:
#   ATR_STOP_MULT = 1.0        # ATR multiplier for stop buffer
#   MIN_RISK_PCT  = 0.0015     # 0.15% minimum stop distance (filters noise stops)

import numpy as np
import math
from typing import Any, Dict

LOCAL_STRUCTURE_BARS = 12   # already in the file — do not duplicate
ATR_STOP_MULT        = 1.0  # ADD this near LOCAL_STRUCTURE_BARS
MIN_RISK_PCT         = 0.0015  # ADD this near LOCAL_STRUCTURE_BARS
MIN_ROOM_TO_RISK     = 1.50    # already in the file — do not duplicate


def _local_geometry(side: str, ohlcv_arrays: tuple | None) -> Dict[str, Any]:
    result = {
        "geometry_status": "LOCAL_BARS_UNAVAILABLE",
        "entry":       None,
        "sl":          None,
        "tp":          None,
        "risk_pct":    None,
        "reward_pct":  None,
        "room_to_risk": None,
        "geometry_reason": "local_15m_bars_unavailable",
    }

    if not ohlcv_arrays or len(ohlcv_arrays) < 5:
        return result

    try:
        _, highs, lows, closes, _, _ = ohlcv_arrays
        highs  = np.asarray(highs,  dtype=float)
        lows   = np.asarray(lows,   dtype=float)
        closes = np.asarray(closes, dtype=float)
    except (TypeError, ValueError):
        result["geometry_reason"] = "invalid_local_15m_arrays"
        return result

    usable = min(LOCAL_STRUCTURE_BARS, len(highs), len(lows), len(closes))

    if usable < LOCAL_STRUCTURE_BARS:
        result["geometry_reason"] = f"need_{LOCAL_STRUCTURE_BARS}_local_bars_have_{usable}"
        return result

    # Exclude the live in-progress bar — use completed bars only.
    completed_highs  = highs[ -(usable + 1):-1]
    completed_lows   = lows[  -(usable + 1):-1]
    completed_closes = closes[-(usable + 1):-1]

    if len(completed_closes) < LOCAL_STRUCTURE_BARS:
        result["geometry_reason"] = "insufficient_completed_15m_bars"
        return result

    if not all(
        math.isfinite(v) and v > 0
        for v in np.concatenate([completed_highs, completed_lows, completed_closes])
    ):
        result["geometry_reason"] = "non_finite_local_structure"
        return result

    # ── ATR (True Range average over completed bars) ───────────────────────────
    # TR = max(high-low, |high-prev_close|, |low-prev_close|)
    prev_closes = completed_closes[:-1]
    curr_highs  = completed_highs[1:]
    curr_lows   = completed_lows[1:]
    tr = np.maximum(
        curr_highs - curr_lows,
        np.maximum(
            np.abs(curr_highs - prev_closes),
            np.abs(curr_lows  - prev_closes),
        ),
    )
    atr = float(np.mean(tr)) if len(tr) > 0 else 0.0

    # ── Entry / Stop / Target ──────────────────────────────────────────────────
    entry      = float(completed_closes[-1])
    local_high = float(np.max(completed_highs))
    local_low  = float(np.min(completed_lows))

    if side == "LONG":
        sl = local_low  - (atr * ATR_STOP_MULT)   # buffer below range floor
        tp = local_high
    elif side == "SHORT":
        sl = local_high + (atr * ATR_STOP_MULT)   # buffer above range ceiling
        tp = local_low
    else:
        result["geometry_reason"] = "delta_side_unavailable"
        return result

    # ── Sanity checks ──────────────────────────────────────────────────────────
    if side == "LONG":
        risk   = (entry - sl) / entry
        reward = (tp - entry) / entry
    else:
        risk   = (sl - entry) / entry
        reward = (entry - tp) / entry

    if risk <= 0:
        result["geometry_reason"] = "entry_not_inside_local_structure"
        return result

    if reward <= 0:
        result["geometry_reason"] = "no_room_to_local_target"
        return result

    # Reject noise stops — must be at least MIN_RISK_PCT of entry price.
    if risk < MIN_RISK_PCT:
        result["geometry_status"] = "GEOMETRY_REJECTED"
        result["geometry_reason"] = f"stop_too_tight_{risk*100:.4f}pct_min_{MIN_RISK_PCT*100:.2f}pct"
        return result

    room_to_risk = reward / risk

    result.update({
        "entry":        entry,
        "sl":           sl,
        "tp":           tp,
        "atr":          round(atr, 8),
        "risk_pct":     risk   * 100.0,
        "reward_pct":   reward * 100.0,
        "room_to_risk": room_to_risk,
        "geometry_status": "LOCAL_STRUCTURE_VALID",
        "geometry_reason": "ok",
    })

    if room_to_risk < MIN_ROOM_TO_RISK:
        result["geometry_status"] = "GEOMETRY_REJECTED"
        result["geometry_reason"] = f"room_to_risk_below_{MIN_ROOM_TO_RISK:.2f}"

    return result
