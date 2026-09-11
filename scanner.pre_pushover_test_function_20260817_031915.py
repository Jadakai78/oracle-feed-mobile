"""
scanner.py â€” JHL Eight Gates Scanner
=====================================
Scans all 49 prop pairs every 5 minutes via Kraken public OHLC.
Runs each pair through 8 deterministic gates.
Surfaces the top 12 by conviction score to signals.json.
Fires Pushover alert for EXECUTION_ELIGIBLE pairs (score >= 70).
Writes passing lanes to eight_gates_brain.jsonl for learning.

No orders. No execution. Read-only decision support.

Gate order:
  1. Data Integrity       â€” valid completed candles and trade data
  2. HTF Direction        â€” H1 EMA 50/200 order and slope
  3. Local Alignment      â€” M15 structure agrees with HTF
  4. Pressure Confirm     â€” delta_norm + CVD slope confirms direction
  5. Participation        â€” relative volume + ATR expansion, not thin
  6. Noise / No-Chase     â€” reject chop and extended late entries
  7. Trigger + Risk       â€” explicit trigger, ATR-buffered geometry
  8. Publish + Learn      â€” write brain observation, emit signal
"""
from __future__ import annotations

import json
import time
import uuid
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pair_universe import PairUniverse, PairContext
from structure_bias import evaluate as get_structure_bias
from market_noise import observe as assess_noise
import eight_gates_brain as brain

# â”€â”€ Paths â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
OUTPUT_FILE = Path(__file__).parent / "signals.json"
LOG_DIR = Path(__file__).parent / "training_logs"
LOG_DIR.mkdir(exist_ok=True)
BRAIN_LOG = LOG_DIR / "eight_gates_brain.jsonl"

# â”€â”€ Cycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SCAN_INTERVAL = 300          # 5 minutes â€” matches completed 15m bar boundary
TOP_N = 12                   # surface top 12 pairs
SCHEMA_VERSION = 4

# â”€â”€ Gate thresholds (research-locked â€” do not change without outcome data) â”€â”€â”€â”€
MIN_SPEED = 0.50             # Delta 2.0 research: speed floor
MIN_ACCEL = 1.30             # 30% acceleration required
MIN_RISK_PCT = 0.0015        # 0.15% minimum stop distance â€” kills noise stops
ATR_STOP_MULTIPLIER = 1.0    # 1Ã— ATR buffer on stops
MIN_ROOM_TO_RISK = 1.50      # minimum R:R to first target

# â”€â”€ Conviction score bands â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SCORE_EXECUTION_ELIGIBLE = 70   # Pushover alert fires
SCORE_ELIGIBLE_WATCH = 55       # Feed only
# < 55 = BUILDING â€” suppressed from top-12

# â”€â”€ ADA quarantine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ADA_QUARANTINE = {"ADA"}

# â”€â”€ Pushover (optional â€” gracefully skipped if not configured) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
import os

def _load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE pairs from local .env without external packages."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

_load_dotenv(Path(__file__).parent / ".env")

PUSHOVER_TOKEN = (
    os.environ.get("PUSHOVER_TOKEN")
    or os.environ.get("PUSHOVER_API_TOKEN")
    or os.environ.get("PUSHOVER_APP_TOKEN", "")
)
PUSHOVER_USER = (
    os.environ.get("PUSHOVER_USER")
    or os.environ.get("PUSHOVER_USER_KEY", "")
)# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _gate(status: str, reason: str, **metrics: Any) -> Dict[str, Any]:
    return {"status": status, "reason": reason, "metrics": metrics}

def _send_pushover(title: str, message: str) -> None:
    if not PUSHOVER_TOKEN or not PUSHOVER_USER:
        return
    try:
        data = urllib.parse.urlencode({
            "token": PUSHOVER_TOKEN,
            "user": PUSHOVER_USER,
            "title": title,
            "message": message,
        }).encode()
        req = urllib.request.Request(
            "https://api.pushover.net/1/messages.json",
            data=data,
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        print(f"PUSHOVER_ERROR {exc}")


# â”€â”€ ATR calculation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _compute_atr(candles: List[Dict[str, float]], period: int = 14) -> Optional[float]:
    if len(candles) < period + 1:
        return None
    tr_values = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)
    if len(tr_values) < period:
        return None
    atr = sum(tr_values[:period]) / period
    for tr in tr_values[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _compute_ema(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    alpha = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for close in closes[period:]:
        ema = close * alpha + ema * (1 - alpha)
    return ema


def _compute_relvol(candles: List[Dict[str, float]], lookback: int = 20) -> float:
    """Relative volume: current bar volume vs 20-bar average."""
    if len(candles) < lookback + 1:
        return 1.0
    recent_vol = candles[-1]["volume"]
    avg_vol = sum(c["volume"] for c in candles[-lookback - 1:-1]) / lookback
    if avg_vol <= 0:
        return 1.0
    return recent_vol / avg_vol


# â”€â”€ Eight Gates â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def gate1_data_integrity(pair: PairContext) -> Dict[str, Any]:
    """Gate 1: Valid completed candles available."""
    candles = pair.candles_15m
    if not candles or len(candles) < 20:
        return _gate("FAIL", "insufficient_15m_candles",
                     available=len(candles) if candles else 0, required=20)
    last = candles[-1]
    if last.get("volume", 0) <= 0:
        return _gate("FAIL", "zero_volume_last_bar")
    if last.get("high", 0) <= last.get("low", 0):
        return _gate("FAIL", "invalid_ohlc_last_bar")
    return _gate("PASS", "valid_completed_candles", bar_count=len(candles))


def gate2_htf_direction(pair: PairContext) -> Tuple[Dict[str, Any], str]:
    """Gate 2: H1 EMA 50/200 â€” establish UP, DOWN, or NONE."""
    candles = pair.candles_15m
    if not candles or len(candles) < 50:
        return _gate("FAIL", "insufficient_candles_for_htf"), "NONE"

    closes = [c["close"] for c in candles]

    # Use H1 approximation: every 4 M15 bars = 1 H1 bar
    h1_closes = [candles[i]["close"] for i in range(3, len(candles), 4)]
    if len(h1_closes) < 50:
        # Fall back to M15 EMA if not enough H1 bars
        ema50 = _compute_ema(closes, 50)
        ema200 = _compute_ema(closes, min(200, len(closes)))
        timeframe_note = "m15_fallback"
    else:
        ema50 = _compute_ema(h1_closes, 50)
        ema200 = _compute_ema(h1_closes, min(200, len(h1_closes)))
        timeframe_note = "h1_approximated"

    if ema50 is None or ema200 is None:
        return _gate("FAIL", "ema_compute_failed"), "NONE"

    current_price = closes[-1]
    slope_window = min(5, len(closes))
    slope = (closes[-1] - closes[-slope_window]) / closes[-slope_window] if closes[-slope_window] > 0 else 0

    if ema50 > ema200 and current_price > ema50 and slope > 0:
        direction = "UP"
    elif ema50 < ema200 and current_price < ema50 and slope < 0:
        direction = "DOWN"
    else:
        direction = "NONE"

    if direction == "NONE":
        return _gate("FAIL", "no_clear_htf_direction",
                     ema50=round(ema50, 6), ema200=round(ema200, 6),
                     price=round(current_price, 6), timeframe=timeframe_note), "NONE"

    return _gate("PASS", f"htf_{direction.lower()}",
                 ema50=round(ema50, 6), ema200=round(ema200, 6),
                 price=round(current_price, 6), direction=direction,
                 timeframe=timeframe_note), direction


def gate3_local_alignment(pair: PairContext, htf_direction: str) -> Dict[str, Any]:
    """Gate 3: M15 structure agrees with HTF direction."""
    candles = pair.candles_15m
    if not candles or len(candles) < 10:
        return _gate("FAIL", "insufficient_candles_for_alignment")

    closes = [c["close"] for c in candles]
    ema20 = _compute_ema(closes, 20)
    ema9 = _compute_ema(closes[-20:], 9) if len(closes) >= 9 else None

    if ema20 is None:
        return _gate("FAIL", "ema20_compute_failed")

    current_price = closes[-1]
    recent_high = max(c["high"] for c in candles[-5:])
    recent_low = min(c["low"] for c in candles[-5:])

    # Structure: price above EMA20 and recent close > recent open = bullish alignment
    last_bar = candles[-1]
    last_bullish = last_bar["close"] > last_bar["open"]
    last_bearish = last_bar["close"] < last_bar["open"]

    local_bullish = current_price > ema20 and last_bullish
    local_bearish = current_price < ema20 and last_bearish

    # Also check structure_bias module for D1/4H context
    try:
        bias_data = get_structure_bias(pair.symbol)
        bias_trend = str(bias_data.get("trend", "NEUTRAL")).upper()
    except Exception:
        bias_trend = "NEUTRAL"

    if htf_direction == "UP":
        aligned = local_bullish or (current_price > ema20 and bias_trend in {"BULLISH", "TRENDING_UP"})
    elif htf_direction == "DOWN":
        aligned = local_bearish or (current_price < ema20 and bias_trend in {"BEARISH", "TRENDING_DOWN"})
    else:
        aligned = False

    if not aligned:
        return _gate("FAIL", "local_structure_not_aligned",
                     htf=htf_direction, price=round(current_price, 6),
                     ema20=round(ema20, 6), bias=bias_trend)

    return _gate("PASS", "local_aligned_with_htf",
                 htf=htf_direction, price=round(current_price, 6),
                 ema20=round(ema20, 6), bias=bias_trend)


def gate4_pressure(pair: PairContext, htf_direction: str, delta_norm: float, cvd_slope: float) -> Dict[str, Any]:
    """Gate 4: Delta and CVD slope confirm direction (or BALANCED â€” warn not veto)."""
    if htf_direction == "UP":
        confirmed = delta_norm >= 0.20 and cvd_slope > 0
        opposing = delta_norm <= -0.20 and cvd_slope < 0
    elif htf_direction == "DOWN":
        confirmed = delta_norm <= -0.20 and cvd_slope < 0
        opposing = delta_norm >= 0.20 and cvd_slope > 0
    else:
        return _gate("FAIL", "no_htf_direction_for_pressure",
                     delta_norm=round(delta_norm, 4), cvd_slope=round(cvd_slope, 6))

    if opposing:
        return _gate("FAIL", "pressure_opposes_direction",
                     delta_norm=round(delta_norm, 4), cvd_slope=round(cvd_slope, 6))

    if not confirmed:
        # Balanced â€” don't veto, but mark as PASS with warning (reduces score)
        return _gate("PASS", "pressure_balanced_not_confirmed",
                     delta_norm=round(delta_norm, 4), cvd_slope=round(cvd_slope, 6),
                     warning="pressure_weak")

    return _gate("PASS", "pressure_confirmed",
                 delta_norm=round(delta_norm, 4), cvd_slope=round(cvd_slope, 6))


def gate5_participation(pair: PairContext, atr: Optional[float]) -> Tuple[Dict[str, Any], float]:
    """Gate 5: Relative volume and ATR expansion â€” not thin or dead."""
    candles = pair.candles_15m
    if not candles:
        return _gate("FAIL", "no_candles_for_participation"), 0.0

    rel_vol = _compute_relvol(candles)

    if atr is None:
        return _gate("FAIL", "atr_unavailable"), rel_vol

    # Thin market: relative volume < 0.5 = dead
    if rel_vol < 0.50:
        return _gate("FAIL", "thin_market",
                     rel_vol=round(rel_vol, 3), atr=round(atr, 6)), rel_vol

    # ATR too small = compression, nothing to trade
    price = pair.last_price or 1.0
    atr_pct = atr / price
    if atr_pct < 0.003:  # Less than 0.3% ATR â€” too compressed
        return _gate("FAIL", "atr_compression",
                     atr_pct=round(atr_pct * 100, 4), atr=round(atr, 6)), rel_vol

    return _gate("PASS", "adequate_participation",
                 rel_vol=round(rel_vol, 3), atr=round(atr, 6),
                 atr_pct=round(atr_pct * 100, 4)), rel_vol


def gate6_noise(pair: PairContext) -> Dict[str, Any]:
    """Gate 6: Reject chop, dead tape, and late extended entries."""
    candles = pair.candles_15m
    if not candles:
        return _gate("FAIL", "no_candles_for_noise_check")

    # Use market_noise module
    try:
        noise_result = assess_noise({
            "pair": pair.symbol,
            "candles": candles[-20:],
            "price": pair.last_price,
        })
        noise_state = str(noise_result.get("state", "CHOPPY")).upper()
        if noise_state == "CHOPPY":
            return _gate("FAIL", "choppy_market",
                         noise_state=noise_state,
                         detail=noise_result.get("reason", ""))
        return _gate("PASS", "noise_acceptable",
                     noise_state=noise_state)
    except Exception:
        pass

    # Fallback: simple range/body ratio check
    bodies = [abs(c["close"] - c["open"]) for c in candles[-10:]]
    ranges = [c["high"] - c["low"] for c in candles[-10:]]
    if ranges:
        avg_body_ratio = sum(b / r if r > 0 else 0 for b, r in zip(bodies, ranges)) / len(ranges)
        if avg_body_ratio < 0.25:
            return _gate("FAIL", "doji_choppy_market",
                         avg_body_ratio=round(avg_body_ratio, 3))

    return _gate("PASS", "noise_check_passed")


def gate7_trigger_risk(
    pair: PairContext,
    htf_direction: str,
    atr: Optional[float],
    speed: float,
    accel: float,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Gate 7: Explicit trigger + ATR-buffered geometry.
    Returns (gate_result, geometry_dict or None).
    """
    candles = pair.candles_15m
    if not candles or atr is None or pair.last_price is None:
        return _gate("FAIL", "missing_data_for_trigger_risk"), None

    price = pair.last_price

    # Speed gate (research-proven floor)
    if speed < MIN_SPEED:
        return _gate("FAIL", "speed_below_floor",
                     speed=round(speed, 4), floor=MIN_SPEED), None

    # Acceleration gate
    if accel < MIN_ACCEL:
        return _gate("FAIL", "acceleration_below_floor",
                     accel=round(accel, 4), floor=MIN_ACCEL), None

    # Find local structure for stop placement
    lookback = min(12, len(candles))
    recent = candles[-lookback:]

    if htf_direction == "UP":
        local_low = min(c["low"] for c in recent)
        sl = local_low - (ATR_STOP_MULTIPLIER * atr)
        side = "LONG"
        # Target: nearest swing high + 1.5R
        local_high = max(c["high"] for c in recent)
        target_1 = price + (price - sl) * 1.5
        target_2 = price + (price - sl) * 2.5
        entry_zone = [round(price * 0.9990, 6), round(price * 1.0010, 6)]
    elif htf_direction == "DOWN":
        local_high = max(c["high"] for c in recent)
        sl = local_high + (ATR_STOP_MULTIPLIER * atr)
        side = "SHORT"
        target_1 = price - (sl - price) * 1.5
        target_2 = price - (sl - price) * 2.5
        entry_zone = [round(price * 0.9990, 6), round(price * 1.0010, 6)]
    else:
        return _gate("FAIL", "no_direction_for_trigger"), None

    # Minimum stop floor â€” reject noise stops
    stop_dist = abs(price - sl)
    min_stop = price * MIN_RISK_PCT
    if stop_dist < min_stop:
        return _gate("FAIL", "stop_too_tight",
                     stop_dist=round(stop_dist, 8),
                     min_required=round(min_stop, 8)), None

    # Room to target check
    risk = abs(price - sl)
    reward_1 = abs(price - target_1)
    room_to_risk = reward_1 / risk if risk > 0 else 0
    if room_to_risk < MIN_ROOM_TO_RISK:
        return _gate("FAIL", "insufficient_room_to_target",
                     room_to_risk=round(room_to_risk, 3),
                     required=MIN_ROOM_TO_RISK), None

    # Reclaim confirmation (last 3 bars)
    reclaim_confirmed = False
    if len(candles) >= 3:
        for c in candles[-3:]:
            if htf_direction == "UP" and c["low"] < local_low and c["close"] > local_low:
                reclaim_confirmed = True
                break
            if htf_direction == "DOWN" and c["high"] > local_high and c["close"] < local_high:
                reclaim_confirmed = True
                break

    geometry = {
        "side": side,
        "entry": round(price, 8),
        "entry_zone": [round(entry_zone[0], 8), round(entry_zone[1], 8)],
        "sl": round(sl, 8),
        "tp1": round(target_1, 8),
        "tp2": round(target_2, 8),
        "invalidation": round(sl, 8),
        "atr": round(atr, 8),
        "risk_pct": round(stop_dist / price * 100, 4),
        "room_to_risk": round(room_to_risk, 3),
        "reclaim_confirmed": reclaim_confirmed,
    }

    trigger_type = "reclaim_confirmed" if reclaim_confirmed else "structure_hold"
    return _gate("PASS", trigger_type,
                 side=side, sl=round(sl, 8),
                 tp1=round(target_1, 8), room_to_risk=round(room_to_risk, 3),
                 speed=round(speed, 4), accel=round(accel, 4)), geometry


# â”€â”€ Scoring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _compute_score(gates: Dict[str, Any], delta_norm: float, rel_vol: float, reclaim: bool) -> int:
    """Confluence v0 score bands: Trend(30) + Pressure(25) + Alignment(20) + Participation(15) + bonus."""
    score = 0

    if (gates.get("higher_timeframe_direction") or {}).get("status") == "PASS":
        score += 30

    if (gates.get("local_alignment") or {}).get("status") == "PASS":
        score += 20

    pressure = gates.get("pressure_confirmation") or {}
    if pressure.get("status") == "PASS":
        if pressure.get("reason") == "pressure_confirmed":
            score += 25
        else:
            score += 12  # balanced â€” partial credit

    if (gates.get("participation") or {}).get("status") == "PASS":
        # Scale by relative volume up to 15 points
        vol_score = min(15, int(rel_vol * 10))
        score += vol_score

    # Bonus: reclaim confirmation
    if reclaim:
        score += 5

    # Bonus: strong delta
    if abs(delta_norm) >= 0.50:
        score += 5

    return min(100, score)


def _eligibility(score: int, quarantined: bool) -> str:
    if quarantined:
        return "QUARANTINED"
    if score >= SCORE_EXECUTION_ELIGIBLE:
        return "EXECUTION_ELIGIBLE"
    if score >= SCORE_ELIGIBLE_WATCH:
        return "ELIGIBLE_WATCH"
    return "BUILDING"


# â”€â”€ Main gate runner â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def run_gates(pair: PairContext) -> Dict[str, Any]:
    """Run all 8 gates for one pair. Returns full result dict."""
    pair_name = f"{pair.symbol}/USD"
    gates: Dict[str, Any] = {}
    rejected_at: Optional[str] = None
    geometry: Optional[Dict[str, Any]] = None
    htf_direction = "NONE"
    delta_norm = 0.0
    cvd_slope = 0.0
    speed = 0.0
    accel = 1.0
    atr: Optional[float] = None
    rel_vol = 1.0

    # Gate 1
    gates["data_integrity"] = gate1_data_integrity(pair)
    if gates["data_integrity"]["status"] == "FAIL":
        rejected_at = "gate1"
    else:
        # Compute ATR once from M15 candles
        atr = _compute_atr(pair.candles_15m)

        # Gate 2
        gate2_result, htf_direction = gate2_htf_direction(pair)
        gates["higher_timeframe_direction"] = gate2_result
        if gate2_result["status"] == "FAIL":
            rejected_at = "gate2"

    if not rejected_at:
        # Gate 3
        gates["local_alignment"] = gate3_local_alignment(pair, htf_direction)
        if gates["local_alignment"]["status"] == "FAIL":
            rejected_at = "gate3"

    if not rejected_at:
        # Compute delta/CVD from candles (simple approximation from OHLCV)
        candles = pair.candles_15m or []
        if len(candles) >= 3:
            # Buy pressure proxy: close near high = buying; close near low = selling
            closes = [c["close"] for c in candles[-5:]]
            highs = [c["high"] for c in candles[-5:]]
            lows = [c["low"] for c in candles[-5:]]
            buy_scores = []
            for i in range(len(closes)):
                rng = highs[i] - lows[i]
                if rng > 0:
                    buy_scores.append((closes[i] - lows[i]) / rng)
                else:
                    buy_scores.append(0.5)
            avg_buy = sum(buy_scores) / len(buy_scores)
            delta_norm = (avg_buy - 0.5) * 2.0  # -1 to +1
            cvd_slope = closes[-1] - closes[0]  # positive = rising CVD proxy

            # Speed: rate of price change relative to ATR
            if atr and atr > 0 and len(closes) >= 2:
                price_change = abs(closes[-1] - closes[-3]) if len(closes) >= 3 else abs(closes[-1] - closes[-2])
                speed = min(1.0, price_change / (atr * 2))
                # Acceleration: last bar body vs previous bar body
                bodies = [abs(c["close"] - c["open"]) for c in candles[-5:]]
                if len(bodies) >= 2 and bodies[-2] > 0:
                    accel = bodies[-1] / bodies[-2]
                else:
                    accel = 1.0

        # Gate 4
        gates["pressure_confirmation"] = gate4_pressure(pair, htf_direction, delta_norm, cvd_slope)
        if gates["pressure_confirmation"]["status"] == "FAIL":
            rejected_at = "gate4"

    if not rejected_at:
        # Gate 5
        gate5_result, rel_vol = gate5_participation(pair, atr)
        gates["participation"] = gate5_result
        if gate5_result["status"] == "FAIL":
            rejected_at = "gate5"

    if not rejected_at:
        # Gate 6
        gates["noise_no_chase"] = gate6_noise(pair)
        if gates["noise_no_chase"]["status"] == "FAIL":
            rejected_at = "gate6"

    if not rejected_at:
        # Gate 7
        gate7_result, geometry = gate7_trigger_risk(pair, htf_direction, atr, speed, accel)
        gates["trigger_risk"] = gate7_result
        if gate7_result["status"] == "FAIL":
            rejected_at = "gate7"

    # Score
    score = 0
    eligibility = "REJECTED"
    reclaim = bool(geometry and geometry.get("reclaim_confirmed"))
    if not rejected_at and geometry:
        score = _compute_score(gates, delta_norm, rel_vol, reclaim)
        eligibility = _eligibility(score, pair.quarantined)
        # Gate 8: publish â€” mark pass
        gates["publish_learn"] = _gate("PASS", "lane_published", score=score, eligibility=eligibility)
    else:
        gates["publish_learn"] = _gate("FAIL", f"rejected_at_{rejected_at or 'unknown'}")

    return {
        "schema_version": SCHEMA_VERSION,
        "pair": pair_name,
        "symbol": pair.symbol,
        "ts": _now_iso(),
        "htf_direction": htf_direction,
        "side": (geometry or {}).get("side", "NONE"),
        "score": score,
        "eligibility": eligibility,
        "rejected_at": rejected_at,
        "geometry": geometry,
        "gates": gates,
        "delta_norm": round(delta_norm, 4),
        "speed": round(speed, 4),
        "accel": round(accel, 4),
        "atr": round(atr, 8) if atr else None,
        "rel_vol": round(rel_vol, 3),
        "price": pair.last_price,
        "quarantined": pair.quarantined,
    }


# â”€â”€ Brain writer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _write_brain_observation(result: Dict[str, Any]) -> None:
    """Write a passing lane to eight_gates_brain.jsonl."""
    if result.get("rejected_at") or not result.get("geometry"):
        return
    geo = result["geometry"]
    # Guard: skip brain write if any price is zero or negative
    for _price_key in ("entry", "sl", "tp1", "tp2", "invalidation"):
        _v = geo.get(_price_key, 0)
        if not _v or _v <= 0:
            print(f"  BRAIN_WRITE_SKIPPED {result['pair']}: {_price_key}={_v} not positive")
            return
    try:
        lane = {
            "pair": result["pair"],
            "side": result["side"],
            "entry_zone": geo["entry_zone"],
            "invalidation": geo["invalidation"],
            "target_1": geo["tp1"],
            "target_2": geo["tp2"],
            "score": result["score"],
            "reason": f"EightGates: {result['htf_direction']} | speed={result['speed']} accel={result['accel']}",
            "gates": result["gates"],
            "features": {
                "trend": {"direction": result["htf_direction"]},
                "alignment": {"local": result.get("side", "NONE")},
                "pressure": {"delta_norm": result["delta_norm"]},
                "participation": {"rel_vol": result["rel_vol"]},
                "noise": {"state": "PASS"},
                "trigger": {"reclaim_confirmed": geo.get("reclaim_confirmed", False)},
            },
        }
        obs_id = str(uuid.uuid4())
        record = brain.build_observation(lane, obs_id)
        brain.append_record(BRAIN_LOG, record)
    except Exception as exc:
        print(f"BRAIN_WRITE_ERROR {result['pair']}: {exc}")


# â”€â”€ Top-12 selector â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _rank_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort by eligibility tier then score. Return top 12."""
    tier_order = {"EXECUTION_ELIGIBLE": 0, "ELIGIBLE_WATCH": 1, "BUILDING": 2,
                  "QUARANTINED": 3, "REJECTED": 4}
    sorted_results = sorted(
        results,
        key=lambda r: (tier_order.get(r["eligibility"], 9), -r["score"])
    )
    # Only surface EXECUTION_ELIGIBLE, ELIGIBLE_WATCH, and BUILDING (not REJECTED)
    surfaced = [r for r in sorted_results if r["eligibility"] not in {"REJECTED"}]
    return surfaced[:TOP_N]


# â”€â”€ One scan cycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def run_cycle() -> None:
    _maybe_send_pushover_test()
    start = time.time()
    print(f"\n[{_now_str()}] === Eight Gates scan cycle starting ===")

    universe = PairUniverse()
    active_pairs = universe.get_active_pairs()
    print(f"Scanning {len(active_pairs)} active pairs")

    all_results: List[Dict[str, Any]] = []
    for pair in active_pairs:
        try:
            result = run_gates(pair)
            all_results.append(result)
            status_line = (
                f"  {pair.symbol:10s} | {result['htf_direction']:5s} | "
                f"score={result['score']:3d} | {result['eligibility']}"
            )
            if result["rejected_at"]:
                status_line += f" (rejected @ {result['rejected_at']})"
            print(status_line)
        except Exception as exc:
            print(f"  {pair.symbol:10s} | ERROR: {exc}")

    # Write brain observations for passing lanes
    eligible_count = 0
    watch_count = 0
    for result in all_results:
        if result["eligibility"] == "EXECUTION_ELIGIBLE":
            _write_brain_observation(result)
            eligible_count += 1
        elif result["eligibility"] == "ELIGIBLE_WATCH":
            watch_count += 1

    # Rank and take top 12
    top_12 = _rank_results(all_results)

    # Build signals.json
    output = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "universe": {
            "requested_pairs": len(PROP_SYMBOLS := [p.symbol for p in active_pairs]),
            "scanned_pairs": len(all_results),
            "skipped_pairs": len(active_pairs) - len(all_results),
        },
        "summary": {
            "execution_eligible": eligible_count,
            "eligible_watch": watch_count,
            "building": sum(1 for r in all_results if r["eligibility"] == "BUILDING"),
            "rejected": sum(1 for r in all_results if r["eligibility"] == "REJECTED"),
            "quarantined": sum(1 for r in all_results if r["eligibility"] == "QUARANTINED"),
        },
        "top_12": top_12,
        "all_pairs": all_results,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    # â”€â”€ GitHub Pages push â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Pushes signals.json to oracle-feed-mobile repo so the live feed updates.
    # Requires git to be configured with credentials on this machine.
    # Set GITHUB_FEED_PUSH=0 in environment to disable.
    if os.environ.get("GITHUB_FEED_PUSH", "1") != "0":
        try:
            import subprocess, base64, urllib.request as _req, json as _json
            _repo = "Jadakai78/oracle-feed-mobile"
            _file = "signals.json"
            _token = os.environ.get("GITHUB_TOKEN", "")
            if _token:
                # Get current SHA
                _api = f"https://api.github.com/repos/{_repo}/contents/{_file}"
                _headers = {"Authorization": f"Bearer {_token}", "Accept": "application/vnd.github+json"}
                _get = urllib.request.Request(_api, headers=_headers)
                try:
                    with urllib.request.urlopen(_get, timeout=10) as _r:
                        _sha = _json.loads(_r.read()).get("sha", "")
                except Exception:
                    _sha = ""
                # Push new content
                _content = base64.b64encode(OUTPUT_FILE.read_bytes()).decode()
                _body = _json.dumps({"message": f"scan {_now_iso()}", "content": _content, "sha": _sha} if _sha else {"message": f"scan {_now_iso()}", "content": _content}).encode()
                _put = urllib.request.Request(_api, data=_body, headers={**_headers, "Content-Type": "application/json"}, method="PUT")
                with urllib.request.urlopen(_put, timeout=15) as _r:
                    _r.read()
                print("  Feed pushed to GitHub Pages")
            else:
                print("  GITHUB_TOKEN not set â€” skipping feed push (set env var to enable)")
        except Exception as _ge:
            print(f"  GitHub push skipped: {_ge}")

    elapsed = round(time.time() - start, 1)
    print(f"\n[{_now_str()}] Cycle complete in {elapsed}s")
    print(f"  EXECUTION_ELIGIBLE: {eligible_count} | WATCH: {watch_count} | top_12 written")

    # Pushover alert for eligible pairs
    eligible_pairs = [r for r in top_12 if r["eligibility"] == "EXECUTION_ELIGIBLE"]
    if eligible_pairs and PUSHOVER_TOKEN:
        lines = []
        for r in eligible_pairs:
            geo = r.get("geometry") or {}
            lines.append(
                f"{r['pair']} {r['side']} | Entry {geo.get('entry', '?')} "
                f"SL {geo.get('sl', '?')} TP1 {geo.get('tp1', '?')} "
                f"Score {r['score']}"
            )
        _send_pushover(
            title=f"JHL: {len(eligible_pairs)} Eligible Setup{'s' if len(eligible_pairs) > 1 else ''}",
            message="\n".join(lines),
        )


# â”€â”€ Entry point â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main() -> None:
    print("JHL Eight Gates Scanner â€” 49 pairs, 5-min cycle, top-12 dynamic surfacing")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Brain:  {BRAIN_LOG}")
    while True:
        try:
            run_cycle()
        except Exception as exc:
            print(f"[{_now_str()}] CYCLE ERROR: {type(exc).__name__}: {exc}")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScanner stopped.")




