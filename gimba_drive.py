"""
gimba_drive.py — Gimba Drive Specialist (training-only, event-driven continuation)

TRAINING ONLY — this module does not place orders, enable execution, or
alter any live risk configuration.  All output is observation/logging only.

Identity:
  - event-driven continuation specialist
  - issues DRIVE_LONG or DRIVE_SHORT claims only when all five conditions
    are simultaneously present; emits no claim otherwise
  - designed to capture the "drive" phase: pullback ends, structure breaks,
    speed/efficiency expands in the aligned direction

Five conditions required for a claim:
  (1) HTF directional alignment — D1/H4 trend aligned (from structure_bias context)
  (2) Valid pullback location — price has retraced into a pullback zone (not chasing)
  (3) Pullback compression / countertrend efficiency weakened — local ATR contracts
      or recent range has compressed relative to the prior swing
  (4) Local structure break in the aligned direction — a short-horizon swing
      level (M15/H1) is broken cleanly in the trend direction
  (5) Break holds and speed/efficiency expands — at least one of: RVOL ≥ 1.2,
      speed_score rises, or RSI momentum confirms direction

Missing conditions are reported as human-readable reasons in the output.

Claim schema (training log compatible with outcome_evaluator):
  - setup_type: DRIVE_LONG | DRIVE_SHORT | NO_DRIVE_CONDITION
  - action_state: "watch" (all 5 met) | "idle" (one or more absent)
  - bias: "LONG" | "SHORT" | "NONE"
  - entry, sl, tp: price levels when watch; None otherwise
  - sl is set at the local pullback structure break level (hard invalidation)
  - tp is set at the prior swing extreme (HTF target)
  - traction_expectation: human-readable time/traction window
  - invalidation_note: describes the hard invalidation condition
  - thesis_decay_note: describes conditions that would signal thesis decay

Data used:
  - Kraken public OHLC (D1, H4, H1, M15) — no proprietary data required
  - shared structure context is accepted as an optional argument so the
    scanner can pass its pre-computed structure dict and avoid a duplicate
    fetch; the module fetches its own data if not provided

Limitations (documented per problem statement):
  - no tick/order-book data; execution precision is approximate
  - M15 structure break detection uses close-based pivot logic only;
    wick-based breaks are not detected
  - speed/efficiency expansion uses RVOL and RSI momentum as proxies;
    a full tempo module is used if available, otherwise falls back
  - traction expectation is a fixed configurable default, not adaptive
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("gimba_drive")

try:
    import tempo as _tempo_mod

    _TEMPO_AVAILABLE = True
except ImportError:
    _TEMPO_AVAILABLE = False

# ── Configurable defaults ─────────────────────────────────────────────────
TRACTION_BARS_DEFAULT = 8          # 15m bars before traction is expected
TRACTION_LABEL = "8 bars (~2 hours) expected traction window"
COMPRESSION_RATIO_THRESHOLD = 0.80  # local range must be ≤ 80 % of prior range
RVOL_EXPANSION_MIN = 1.2           # minimum relative volume for expansion
RSI_LONG_MIN = 52.0                # RSI floor for long break confirmation
RSI_SHORT_MAX = 48.0               # RSI ceiling for short break confirmation
PULLBACK_ZONE_MAX = 0.70           # price must be ≤ 70 % of HTF range for long
PULLBACK_ZONE_MIN = 0.30           # price must be ≥ 30 % of HTF range for short


# ── OHLC helpers (self-contained, same pattern as siblings) ───────────────

def _fetch_ohlc(kraken_pair: str, interval: int, limit: int = 80) -> Optional[List]:
    url = (
        f"https://api.kraken.com/0/public/OHLC"
        f"?pair={kraken_pair}&interval={interval}"
    )
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
    except Exception as exc:
        logger.debug("OHLC fetch %s %s: %s", kraken_pair, interval, exc)
        return None


def _to_arrays(
    rows: List,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    o = np.array([float(r[1]) for r in rows], dtype=float)
    h = np.array([float(r[2]) for r in rows], dtype=float)
    l = np.array([float(r[3]) for r in rows], dtype=float)
    c = np.array([float(r[4]) for r in rows], dtype=float)
    v = np.array([float(r[6]) for r in rows], dtype=float)
    return o, h, l, c, v


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> float:
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )
    if len(tr) < period:
        return float(np.mean(tr)) if len(tr) > 0 else 0.0
    return float(np.mean(tr[-period:]))


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


def _ema(c: np.ndarray, period: int) -> float:
    if len(c) < period:
        return float(c[-1])
    k = 2.0 / (period + 1)
    val = float(c[0])
    for price in c[1:]:
        val = float(price) * k + val * (1 - k)
    return val


# ── Analysis helpers ──────────────────────────────────────────────────────

def _swing_structure(
    h: np.ndarray, l: np.ndarray, lookback: int = 20
) -> Tuple[str, float, float]:
    """Derive swing trend from pivot highs/lows."""
    if len(h) < lookback or len(l) < lookback:
        return "ranging", float(h[-1]), float(l[-1])
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
    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return "ranging", float(wh.max()), float(wl.min())
    hh = pivot_highs[-1] > pivot_highs[-2]
    hl = pivot_lows[-1] > pivot_lows[-2]
    lh = pivot_highs[-1] < pivot_highs[-2]
    ll = pivot_lows[-1] < pivot_lows[-2]
    last_swing_high = pivot_highs[-1]
    last_swing_low = pivot_lows[-1]
    if hh and hl:
        return "up", last_swing_high, last_swing_low
    if lh and ll:
        return "down", last_swing_high, last_swing_low
    return "ranging", last_swing_high, last_swing_low


def _htf_alignment(structure: Dict[str, Any]) -> Tuple[str, List[str]]:
    """
    Condition 1: Higher-timeframe directional alignment.

    Returns (direction, reasons_if_absent).
    direction is 'up', 'down', or '' (no alignment).
    """
    d1 = str(structure.get("d1_trend") or "").lower()
    h4 = str(structure.get("h4_trend") or "").lower()
    trend = str(structure.get("trend") or "").lower()

    # Accept the pre-computed combined trend from structure_bias if available
    if trend in ("up", "down"):
        return trend, []
    # Or derive from D1/H4 individually
    if d1 == "up" and h4 in ("up", "ranging"):
        return "up", []
    if d1 == "down" and h4 in ("down", "ranging"):
        return "down", []
    reasons = [f"no_htf_alignment(d1={d1},h4={h4})"]
    return "", reasons


def _pullback_location(
    price: float,
    swing_high: float,
    swing_low: float,
    direction: str,
) -> Tuple[bool, float, List[str]]:
    """
    Condition 2: Price is in a valid pullback zone, not an extended chase.

    eq_pct = (price - swing_low) / (swing_high - swing_low)
    Long: price must be in discount-to-neutral zone (eq_pct ≤ PULLBACK_ZONE_MAX)
    Short: price must be in premium-to-neutral zone (eq_pct ≥ PULLBACK_ZONE_MIN)
    """
    rng = swing_high - swing_low
    if rng <= 0:
        return False, 0.5, ["pullback_check_skipped:zero_range"]
    eq_pct = (price - swing_low) / rng
    if direction == "up":
        ok = eq_pct <= PULLBACK_ZONE_MAX
        reason = [] if ok else [f"price_extended:eq_pct={eq_pct:.2f}>={PULLBACK_ZONE_MAX}"]
        return ok, round(eq_pct, 3), reason
    if direction == "down":
        ok = eq_pct >= PULLBACK_ZONE_MIN
        reason = [] if ok else [f"price_extended:eq_pct={eq_pct:.2f}<={PULLBACK_ZONE_MIN}"]
        return ok, round(eq_pct, 3), reason
    return False, round(eq_pct, 3), ["pullback_check_skipped:no_direction"]


def _pullback_compression(
    hm: np.ndarray, lm: np.ndarray, cm: np.ndarray, atr_m15: float,
    lookback_recent: int = 6, lookback_prior: int = 14,
) -> Tuple[bool, float, List[str]]:
    """
    Condition 3: Pullback/local consolidation has compressed or countertrend
    efficiency has weakened.

    Uses two windows of M15 candles:
      - prior_range  = range of the last (lookback_prior) bars before the recent window
      - recent_range = range of the last (lookback_recent) bars

    Compression is detected when recent_range ≤ COMPRESSION_RATIO_THRESHOLD × prior_range.
    Fallback: if ATR is shrinking relative to recent range this is also accepted.
    """
    needed = lookback_recent + lookback_prior
    if len(hm) < needed or atr_m15 <= 0:
        return False, 0.0, ["compression_check_skipped:insufficient_bars"]

    recent_h = hm[-lookback_recent:]
    recent_l = lm[-lookback_recent:]
    prior_h = hm[-needed:-lookback_recent]
    prior_l = lm[-needed:-lookback_recent]

    recent_range = float(recent_h.max() - recent_l.min())
    prior_range = float(prior_h.max() - prior_l.min())

    if prior_range <= 0:
        return False, 0.0, ["compression_check_skipped:zero_prior_range"]

    ratio = recent_range / prior_range
    compressed = ratio <= COMPRESSION_RATIO_THRESHOLD
    reason = [] if compressed else [f"no_compression:range_ratio={ratio:.2f}>{COMPRESSION_RATIO_THRESHOLD}"]
    return compressed, round(ratio, 3), reason


def _local_structure_break(
    hm: np.ndarray, lm: np.ndarray, cm: np.ndarray,
    direction: str, lookback: int = 10,
) -> Tuple[bool, float, List[str]]:
    """
    Condition 4: Local M15 structure breaks in the aligned direction.

    Long  → current close breaks above the recent local swing high.
    Short → current close breaks below the recent local swing low.

    Returns (broke, break_level, reasons_if_absent).
    Limitation: close-based detection only; wick breaks are not detected.
    """
    if len(cm) < lookback + 1:
        return False, 0.0, ["break_check_skipped:insufficient_bars"]

    prior = cm[-(lookback + 1):-1]  # exclude current bar
    if direction == "up":
        level = float(hm[-(lookback + 1):-1].max())
        broke = float(cm[-1]) > level
        reason = [] if broke else [f"no_structure_break:price={cm[-1]:.4f}<=local_high={level:.4f}(limitation:close_based)"]
        return broke, round(level, 6), reason
    if direction == "down":
        level = float(lm[-(lookback + 1):-1].min())
        broke = float(cm[-1]) < level
        reason = [] if broke else [f"no_structure_break:price={cm[-1]:.4f}>=local_low={level:.4f}(limitation:close_based)"]
        return broke, round(level, 6), reason
    return False, 0.0, ["break_check_skipped:no_direction"]


def _break_holds_and_expands(
    cm: np.ndarray, vm: np.ndarray, direction: str,
    break_level: float, atr_m15: float, speed_score: float,
) -> Tuple[bool, float, float, List[str]]:
    """
    Condition 5: Break holds and short-horizon speed/directional efficiency expands.

    Three proxy signals (at least one must be true):
      a) RVOL ≥ RVOL_EXPANSION_MIN
      b) RSI momentum confirms direction (long: RSI ≥ RSI_LONG_MIN, short: RSI ≤ RSI_SHORT_MAX)
      c) speed_score > 0 (from tempo module if available)

    Additionally: price must not have closed back inside the break level.
    """
    rvol = _relative_volume(vm, 20)
    rsi_val = _rsi(cm, 14)
    price = float(cm[-1])

    # Check break is holding (price has not returned through the break level)
    if direction == "up" and price < break_level:
        return False, rvol, rsi_val, [f"break_failed:price={price:.4f}<break_level={break_level:.4f}"]
    if direction == "down" and price > break_level:
        return False, rvol, rsi_val, [f"break_failed:price={price:.4f}>break_level={break_level:.4f}"]

    expansion_signals: List[str] = []
    if rvol >= RVOL_EXPANSION_MIN:
        expansion_signals.append(f"rvol={rvol:.2f}")
    if direction == "up" and rsi_val >= RSI_LONG_MIN:
        expansion_signals.append(f"rsi_long={rsi_val:.1f}")
    if direction == "down" and rsi_val <= RSI_SHORT_MAX:
        expansion_signals.append(f"rsi_short={rsi_val:.1f}")
    if speed_score > 0:
        expansion_signals.append(f"speed_score={speed_score:.2f}")

    if expansion_signals:
        return True, rvol, rsi_val, []
    return False, rvol, rsi_val, [
        f"no_expansion:rvol={rvol:.2f},rsi={rsi_val:.1f},speed={speed_score:.2f}"
    ]


# ── Public evaluate function ──────────────────────────────────────────────

def evaluate(
    pair: str,
    kraken_pair: str,
    current_price: float,
    fg_score: int = 50,
    structure: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Gimba Drive evaluation — training/observation only.

    Parameters
    ----------
    pair : str
        Human-readable pair name, e.g. "SOL/USD".
    kraken_pair : str
        Kraken API pair key, e.g. "SOLUSD".
    current_price : float
        Not used for signal generation (prices are read from OHLC);
        kept for API compatibility with sibling specialists.
    fg_score : int
        Fear-and-greed score (0–100).  Not used to gate the claim but
        is logged as a feature.
    structure : dict, optional
        Pre-computed structure context from structure_bias.evaluate().
        If not provided the module uses its own D1/H4 fetch — this means
        a second API call when called from scanner.py; pass structure to
        avoid the duplicate fetch.

    Returns
    -------
    dict matching the TAK scanner signal shape, plus Drive-specific keys:
        traction_expectation, invalidation_note, thesis_decay_note,
        drive_conditions (diagnostic dict of which conditions passed/failed).
    """
    null_result: Dict[str, Any] = {
        "pair": pair,
        "bias": "NONE",
        "engine": "GimbaDrive",
        "setup_type": "NO_DRIVE_CONDITION",
        "conviction": 0.0,
        "entry": None,
        "sl": None,
        "tp": None,
        "why": "insufficient_data",
        "action_state": "idle",
        "indicators": {
            "d1_trend": "unknown",
            "h4_trend": "unknown",
            "eq_pct": 0.5,
            "compression_ratio": 0.0,
            "rvol_m15": 1.0,
            "rsi_m15": 50.0,
            "atr_m15": 0.0,
            "speed_score": 0.0,
            "break_level": 0.0,
            "swing_high": 0.0,
            "swing_low": 0.0,
        },
        "traction_expectation": TRACTION_LABEL,
        "invalidation_note": (
            "Hard invalidation: price closes back through the local structure "
            "break level / pullback zone entry."
        ),
        "thesis_decay_note": (
            "Thesis decay: speed/efficiency collapses or price returns inside "
            "the trigger range without follow-through."
        ),
        "drive_conditions": {
            "htf_alignment": False,
            "pullback_location": False,
            "compression": False,
            "structure_break": False,
            "expansion": False,
        },
        "training_only": True,
    }

    # ── Fetch OHLC ────────────────────────────────────────────────────────
    d1_rows = _fetch_ohlc(kraken_pair, 1440, 40)
    h4_rows = _fetch_ohlc(kraken_pair, 240, 50)
    h1_rows = _fetch_ohlc(kraken_pair, 60, 80)
    m15_rows = _fetch_ohlc(kraken_pair, 15, 80)

    if not d1_rows or len(d1_rows) < 20:
        null_result["why"] = "d1_data_unavailable"
        return null_result
    if not h4_rows or len(h4_rows) < 20:
        null_result["why"] = "h4_data_unavailable"
        return null_result
    if not h1_rows or len(h1_rows) < 30:
        null_result["why"] = "h1_data_unavailable"
        return null_result
    if not m15_rows or len(m15_rows) < 30:
        null_result["why"] = "m15_data_unavailable"
        return null_result

    od, hd, ld, cd, vd = _to_arrays(d1_rows)
    o4, h4, l4, c4, v4 = _to_arrays(h4_rows)
    o1, h1, l1, c1, v1 = _to_arrays(h1_rows)
    om, hm, lm, cm, vm = _to_arrays(m15_rows)

    price = float(cm[-1])
    atr_m15 = _atr(hm, lm, cm, 14)

    # ── Build structure context ───────────────────────────────────────────
    if structure and isinstance(structure, dict) and structure.get("d1_trend"):
        ctx = structure
        d1_trend = str(ctx.get("d1_trend") or "ranging").lower()
        h4_trend = str(ctx.get("h4_trend") or "ranging").lower()
        swing_high = float(ctx.get("swing_high") or hd[-20:].max())
        swing_low = float(ctx.get("swing_low") or ld[-20:].min())
    else:
        d1_trend_str, d1_sh, d1_sl = _swing_structure(hd, ld, 20)
        h4_trend_str, _, _ = _swing_structure(h4, l4, 20)
        d1_trend = d1_trend_str
        h4_trend = h4_trend_str
        swing_high = d1_sh
        swing_low = d1_sl
        ctx = {
            "d1_trend": d1_trend,
            "h4_trend": h4_trend,
            "trend": d1_trend,
            "swing_high": swing_high,
            "swing_low": swing_low,
        }

    # ── Tempo (optional) ─────────────────────────────────────────────────
    if _TEMPO_AVAILABLE and atr_m15 > 0:
        tempo_ctx = _tempo_mod.compute(cm, atr_m15)
        speed_score = float(tempo_ctx.get("speed_score", 0.0))
        m15_tempo = str(tempo_ctx.get("tempo", "DEAD"))
    else:
        speed_score = 0.0
        m15_tempo = "DEAD"

    # ── Five-condition evaluation ─────────────────────────────────────────
    missing_reasons: List[str] = []

    # Condition 1
    direction, r1 = _htf_alignment(ctx)
    cond_1 = direction != ""
    missing_reasons.extend(r1)

    # Condition 2
    cond_2, eq_pct, r2 = _pullback_location(price, swing_high, swing_low, direction)
    missing_reasons.extend(r2)

    # Condition 3
    cond_3, compression_ratio, r3 = _pullback_compression(hm, lm, cm, atr_m15)
    missing_reasons.extend(r3)

    # Condition 4
    cond_4, break_level, r4 = _local_structure_break(hm, lm, cm, direction)
    missing_reasons.extend(r4)

    # Condition 5 (only meaningful if condition 4 is met)
    if cond_4:
        cond_5, rvol_m15, rsi_m15, r5 = _break_holds_and_expands(
            cm, vm, direction, break_level, atr_m15, speed_score,
        )
        missing_reasons.extend(r5)
    else:
        cond_5, rvol_m15, rsi_m15 = False, _relative_volume(vm, 20), _rsi(cm, 14)
        # No additional reason added; condition 4 reason already covers this

    drive_conditions = {
        "htf_alignment": cond_1,
        "pullback_location": cond_2,
        "compression": cond_3,
        "structure_break": cond_4,
        "expansion": cond_5,
    }

    # ── Build output ─────────────────────────────────────────────────────
    all_met = cond_1 and cond_2 and cond_3 and cond_4 and cond_5

    if all_met and direction == "up":
        setup_type = "DRIVE_LONG"
        bias = "LONG"
    elif all_met and direction == "down":
        setup_type = "DRIVE_SHORT"
        bias = "SHORT"
    else:
        setup_type = "NO_DRIVE_CONDITION"
        bias = "NONE"

    action_state = "watch" if all_met else "idle"

    # Conviction reflects how many conditions are met (diagnostic, not for routing)
    conditions_met = sum([cond_1, cond_2, cond_3, cond_4, cond_5])
    conviction = round(conditions_met / 5.0 * 0.70, 3) if all_met else round(conditions_met / 5.0 * 0.30, 3)

    entry = sl = tp = None
    invalidation_note = (
        "Hard invalidation: price closes back through the local structure "
        "break level / pullback zone entry."
    )
    if all_met and atr_m15 > 0:
        if bias == "LONG":
            entry = round(price, 6)
            # Hard stop: below the break level with one ATR buffer
            sl = round(break_level - atr_m15 * 0.5, 6)
            # Target: prior D1 swing extreme
            tp = round(swing_high, 6)
            invalidation_note = (
                f"Hard invalidation: close below local structure break level "
                f"{break_level:.4f} (sl={sl:.4f}). "
                f"Thesis decay: speed/efficiency collapses or price returns "
                f"below {round(break_level - atr_m15 * 0.25, 4):.4f}."
            )
        elif bias == "SHORT":
            entry = round(price, 6)
            sl = round(break_level + atr_m15 * 0.5, 6)
            tp = round(swing_low, 6)
            invalidation_note = (
                f"Hard invalidation: close above local structure break level "
                f"{break_level:.4f} (sl={sl:.4f}). "
                f"Thesis decay: speed/efficiency collapses or price returns "
                f"above {round(break_level + atr_m15 * 0.25, 4):.4f}."
            )

    why = (
        "; ".join(missing_reasons)
        if missing_reasons
        else f"all_conditions_met:direction={direction}"
    )

    indicators: Dict[str, Any] = {
        "d1_trend": d1_trend,
        "h4_trend": h4_trend,
        "eq_pct": eq_pct,
        "compression_ratio": compression_ratio,
        "rvol_m15": rvol_m15,
        "rsi_m15": rsi_m15,
        "atr_m15": round(atr_m15, 6),
        "speed_score": speed_score,
        "break_level": break_level,
        "swing_high": round(swing_high, 6),
        "swing_low": round(swing_low, 6),
        "m15_tempo": m15_tempo,
        "fg_score": fg_score,
        "conditions_met": conditions_met,
    }

    return {
        "pair": pair,
        "bias": bias,
        "engine": "GimbaDrive",
        "setup_type": setup_type,
        "conviction": conviction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "why": why,
        "action_state": action_state,
        "indicators": indicators,
        "traction_expectation": TRACTION_LABEL,
        "invalidation_note": invalidation_note,
        "thesis_decay_note": (
            "Thesis decay: speed/efficiency collapses (speed_score → 0, "
            "RVOL drops below 1.0) or price returns inside the trigger range "
            f"without follow-through within {TRACTION_BARS_DEFAULT} bars."
        ),
        "drive_conditions": drive_conditions,
        "training_only": True,
    }


# ── KNN wrapper ───────────────────────────────────────────────────────────

from pathlib import Path as _Path
from knn_engine import KNNEngine as _KNN


def evaluate_with_knn(
    pair: str,
    kraken_pair: str,
    current_price: float,
    fg_score: int = 50,
    log_dir: Any = None,
    structure: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Drop-in wrapper that applies KNN conviction adjustment after raw evaluation.
    Falls back to raw evaluate output until min_samples (30) are collected.
    Training-only — does not enable execution.
    """
    result = evaluate(pair, kraken_pair, current_price, fg_score, structure=structure)

    log_dir_path = (
        _Path(log_dir) if log_dir is not None else _Path(__file__).parent / "training_logs"
    )

    try:
        engine = _KNN("gimba_drive", log_dir_path, min_samples=30)
        adj, n = engine.adjust(result)
        if n >= 30:
            raw = float(result.get("conviction", 0.0))
            result["conviction"] = round(max(0.0, min(raw + adj, 1.0)), 3)
            result["knn_adj"] = round(adj, 3)
            result["knn_samples"] = n
        else:
            result["knn_adj"] = 0.0
            result["knn_samples"] = n
    except Exception:
        result["knn_adj"] = 0.0
        result["knn_samples"] = 0

    return result
