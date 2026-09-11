"""
Delta Tempo Speed Companion Module
----------------------------------
Calculates speed/tempo metrics from bar price sequences and evaluates
lifecycle episode state transitions for market candidates.
"""

from typing import Any, Dict, List, Optional
import numpy as np

_STATE: Dict[str, Any] = {}


def reset_state() -> None:
    """Clears internal state dictionary."""
    _STATE.clear()


def _to_scalar(val: Any) -> float:
    """Safely converts dict, scalar, numpy array, or pandas series to float scalar."""
    if isinstance(val, dict):
        val = val.get("close", 0.0)
    arr = np.asarray(val)
    if arr.size == 1:
        return float(arr.item())
    elif arr.size > 1:
        return float(arr.flat[-1])
    return 0.0


def calculate_speed_metrics(bars: Any) -> Dict[str, Any]:
    """Calculates price velocity and acceleration from recent bars."""
    if bars is None:
        return {"velocity": 0.0, "acceleration": 0.0, "speed_phase": "STABLE"}

    # Extract price array if bars is passed as tuple (times, highs, lows, closes, ...)
    if isinstance(bars, tuple) and len(bars) >= 4:
        closes = bars[3]
    elif isinstance(bars, (list, tuple)):
        closes = [_to_scalar(b) for b in bars]
    else:
        closes = [_to_scalar(bars)]

    closes = np.asarray(closes, dtype=float)
    if len(closes) < 2:
        return {"velocity": 0.0, "acceleration": 0.0, "speed_phase": "STABLE"}

    recent_changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    latest_delta = recent_changes[-1]
    prev_delta = recent_changes[-2] if len(recent_changes) > 1 else 0.0
    accel = latest_delta - prev_delta

    if latest_delta > prev_delta and latest_delta > 0:
        speed_phase = "EXPANDING"
    elif latest_delta < prev_delta:
        speed_phase = "DECAY"
    elif accel > 0 and latest_delta > 0:
        speed_phase = "REACCELERATION"
    else:
        speed_phase = "IMPULSE"

    return {
        "velocity": round(latest_delta, 4),
        "acceleration": round(accel, 4),
        "speed_phase": speed_phase,
    }


def evaluate(
    pair: str,
    direction: str = "LONG",
    prism_available: bool = True,
    location_confluence: float = 0.8,
    flow_ratio: float = 0.8,
    reclaim_confirmed: bool = False,
    structure: Optional[Dict[str, Any]] = None,
    state: Optional[Dict[str, Any]] = None,
    bars: Any = None,
) -> Dict[str, Any]:
    """Evaluates lifecycle episode state transitions."""
    if structure is None:
        structure = {"market_condition": "TRENDING_UP"}

    prev_episode = None
    if state and "episode_state" in state:
        prev_episode = state["episode_state"]
    elif pair in _STATE:
        prev_episode = _STATE[pair].get("episode_state")

    metrics = calculate_speed_metrics(bars)
    speed_phase = metrics["speed_phase"]
    market_cond = str(structure.get("market_condition", "")).upper()

    # Episode State Transition Logic
    if speed_phase == "DECAY" and prev_episode is not None and not reclaim_confirmed:
        episode_state = "DROPPED"
    elif reclaim_confirmed:
        episode_state = "CONFIRMED_RECLAIM_ACCELERATION"
    elif prev_episode is not None:
        if "PULLBACK" in market_cond:
            episode_state = "CONFIRMED_PULLBACK_REACCELERATION"
        elif "BREAKOUT" in market_cond or structure.get("bos"):
            episode_state = "CONFIRMED_BREAKOUT_ACCEPTANCE"
        else:
            episode_state = "WATCH_PULLBACK" if speed_phase == "DECAY" else "CONFIRMED_PULLBACK_REACCELERATION"
    else:
        episode_state = "WATCH_INITIAL_IMPULSE"

    entry_authority = episode_state.startswith("CONFIRMED_")
    active_feed_visibility = episode_state != "DROPPED"

    res = {
        "pair": pair,
        "direction": direction,
        "prism_available": prism_available,
        "location_confluence": location_confluence,
        "flow_ratio": flow_ratio,
        "reclaim_confirmed": reclaim_confirmed,
        "episode_state": episode_state,
        "speed_phase": speed_phase,
        "active_feed_visibility": active_feed_visibility,
        "entry_authority": entry_authority,
        "metrics": metrics,
    }

    _STATE[pair] = res
    return res
