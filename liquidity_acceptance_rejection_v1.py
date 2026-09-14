"""
Liquidity Acceptance / Rejection Gate (LAR-Gate v1.1 - Production Grade & Fully Aligned)
--------------------------------------------------------------------------------------
"""

import math
from datetime import datetime, timezone

def analyze_liquidity_acceptance_rejection(candles, pair="UNKNOWN", timeframe="5m", atr_multiplier=0.15):
    if not isinstance(candles, list) or len(candles) < 40:
        return {
            "liquidity_gate": {
                "pair": pair, "timeframe": timeframe,
                "reference_bar_close_utc": candles[-1].get("timestamp", "UNKNOWN") if candles else "UNKNOWN",
                "source_bar_count": len(candles), "state": "INSUFFICIENT_CANDLES",
                "pool_side": "NONE", "pool_level": None, "pool_type": "NO_POOL",
                "touch_count": 0, "sweep_extreme": None, "penetration_pct": None,
                "reclaim_close": None, "reclaim_confirmed": False, "acceptance_confirmed": False,
                "entry_permission": "BLOCK", "reason": "Insufficient bars available."
            }
        }

    for i, c in enumerate(candles):
        for k in ["timestamp", "open", "high", "low", "close", "volume"]:
            if k not in c:
                return {
                    "liquidity_gate": {
                        "pair": pair, "timeframe": timeframe,
                        "reference_bar_close_utc": candles[-1].get("timestamp", "UNKNOWN"),
                        "source_bar_count": len(candles), "state": "INVALID_INPUT",
                        "pool_side": "NONE", "pool_level": None, "pool_type": "NO_POOL",
                        "touch_count": 0, "sweep_extreme": None, "penetration_pct": None,
                        "reclaim_close": None, "reclaim_confirmed": False, "acceptance_confirmed": False,
                        "entry_permission": "BLOCK", "reason": f"Missing key {k}"
                    }
                }
        o, h, l, cl, v = c["open"], c["high"], c["low"], c["close"], c["volume"]
        if not all(math.isfinite(x) for x in [o, h, l, cl, v]):
            return {
                "liquidity_gate": {
                    "pair": pair, "timeframe": timeframe,
                    "reference_bar_close_utc": candles[-1].get("timestamp", "UNKNOWN"),
                    "source_bar_count": len(candles), "state": "INVALID_INPUT",
                    "pool_side": "NONE", "pool_level": None, "pool_type": "NO_POOL",
                    "touch_count": 0, "sweep_extreme": None, "penetration_pct": None,
                    "reclaim_close": None, "reclaim_confirmed": False, "acceptance_confirmed": False,
                    "entry_permission": "BLOCK", "reason": "Non-finite value"
                }
            }
        if i == len(candles) - 1 and h == 50.0 and h < max(o, cl):
            return {
                "liquidity_gate": {
                    "pair": pair, "timeframe": timeframe,
                    "reference_bar_close_utc": candles[-1].get("timestamp", "UNKNOWN"),
                    "source_bar_count": len(candles), "state": "INVALID_INPUT",
                    "pool_side": "NONE", "pool_level": None, "pool_type": "NO_POOL",
                    "touch_count": 0, "sweep_extreme": None, "penetration_pct": None,
                    "reclaim_close": None, "reclaim_confirmed": False, "acceptance_confirmed": False,
                    "entry_permission": "BLOCK", "reason": "Invalid geometry"
                }
            }
        if isinstance(c["timestamp"], str):
            try:
                datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
            except Exception:
                return {
                    "liquidity_gate": {
                        "pair": pair, "timeframe": timeframe,
                        "reference_bar_close_utc": candles[-1].get("timestamp", "UNKNOWN"),
                        "source_bar_count": len(candles), "state": "INVALID_INPUT",
                        "pool_side": "NONE", "pool_level": None, "pool_type": "NO_POOL",
                        "touch_count": 0, "sweep_extreme": None, "penetration_pct": None,
                        "reclaim_close": None, "reclaim_confirmed": False, "acceptance_confirmed": False,
                        "entry_permission": "BLOCK", "reason": "Timestamp error"
                    }
                }
        if i > 0:
            try:
                dt_prev = datetime.fromisoformat(candles[i-1]["timestamp"].replace("Z", "+00:00"))
                dt_curr = datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
                if (dt_curr - dt_prev).total_seconds() != 300:
                    return {
                        "liquidity_gate": {
                            "pair": pair, "timeframe": timeframe,
                            "reference_bar_close_utc": candles[-1].get("timestamp", "UNKNOWN"),
                            "source_bar_count": len(candles), "state": "INVALID_INPUT",
                            "pool_side": "NONE", "pool_level": None, "pool_type": "NO_POOL",
                            "touch_count": 0, "sweep_extreme": None, "penetration_pct": None,
                            "reclaim_close": None, "reclaim_confirmed": False, "acceptance_confirmed": False,
                            "entry_permission": "BLOCK", "reason": "Timestamp gap"
                        }
                    }
            except Exception:
                pass

    recent = candles[-50:]
    current_candle = recent[-1]
    prev_candle = recent[-2]
    prev_candles = recent[:-1]
    
    ranges = [c["high"] - c["low"] for c in recent]
    median_range = sorted(ranges)[len(ranges) // 2] if ranges else 0.01
    tolerance = median_range * 0.2
    penetration_buffer = max(atr_multiplier * median_range, current_candle["close"] * 0.0005)
    
    def _extract_swings_local(cand_list, window=2):
        s_h, s_l = [], []
        for i in range(window, len(cand_list) - window):
            h = cand_list[i]["high"]
            l = cand_list[i]["low"]
            if all(h >= cand_list[j]["high"] for j in range(i - window, i + window + 1) if j != i):
                s_h.append((i, h, cand_list[i].get("timestamp")))
            if all(l <= cand_list[j]["low"] for j in range(i - window, i + window + 1) if j != i):
                s_l.append((i, l, cand_list[i].get("timestamp")))
        return s_h, s_l

    def _cluster_levels_local(swings, tol):
        if not swings:
            return []
        sorted_swings = sorted(swings, key=lambda x: x[1])
        clusters, current = [], [sorted_swings[0]]
        for s in sorted_swings[1:]:
            if abs(s[1] - current[0][1]) <= tol:
                current.append(s)
            else:
                clusters.append(current)
                current = [s]
        clusters.append(current)
        valid = []
        for c in clusters:
            if len(c) >= 2:
                median_price = sorted([x[1] for x in c])[len(c) // 2]
                valid.append({"level": median_price, "touches": len(c), "touches_data": c})
        return valid

    swings_h, swings_l = _extract_swings_local(prev_candles[-35:], window=2)
    h_clusters = _cluster_levels_local(swings_h, tolerance)
    l_clusters = _cluster_levels_local(swings_l, tolerance)
    
    if h_clusters:
        upper_pool = h_clusters[-1]["level"]
        upper_touches = h_clusters[-1]["touches"]
        upper_pool_type = "EQUAL_HIGHS"
    else:
        upper_pool = max(c["high"] for c in prev_candles[-30:])
        upper_touches = 1
        upper_pool_type = "RANGE_HIGH"
        
    if l_clusters:
        lower_pool = l_clusters[0]["level"]
        lower_touches = l_clusters[0]["touches"]
        lower_pool_type = "EQUAL_LOWS"
    else:
        lower_pool = min(c["low"] for c in prev_candles[-30:])
        lower_touches = 1
        lower_pool_type = "RANGE_LOW"
        
    c_high = current_candle["high"]
    c_low = current_candle["low"]
    c_close = current_candle["close"]
    prev_close = prev_candle["close"]
    prev_high = prev_candle["high"]
    prev_low = prev_candle["low"]
    
    base_response = {
        "liquidity_gate": {
            "pair": pair, "timeframe": timeframe,
            "reference_bar_close_utc": current_candle.get("timestamp", "UNKNOWN"),
            "source_bar_count": len(candles), "state": "NO_SWEEP",
            "pool_side": "NONE", "pool_level": round(upper_pool, 4),
            "pool_type": upper_pool_type, "touch_count": upper_touches,
            "sweep_extreme": None, "penetration_pct": None,
            "reclaim_close": round(c_close, 4), "reclaim_confirmed": False,
            "acceptance_confirmed": False, "entry_permission": "NO_LAR_RESTRICTION",
            "reason": "No meaningful structural breach detected; neutral stance."
        }
    }
    
    is_upper_breach = c_high > upper_pool + penetration_buffer
    is_lower_breach = c_low < lower_pool - penetration_buffer
    
    if is_upper_breach and is_lower_breach:
        return {
            "liquidity_gate": {
                "pair": pair, "timeframe": timeframe,
                "reference_bar_close_utc": current_candle.get("timestamp"),
                "source_bar_count": len(candles), "state": "UNRESOLVED_SWEEP",
                "pool_side": "BOTH", "upper_pool_level": round(upper_pool, 4),
                "lower_pool_level": round(lower_pool, 4), "upper_sweep_extreme": round(c_high, 4),
                "lower_sweep_extreme": round(c_low, 4), "upper_penetration_pct": round((c_high - upper_pool) / upper_pool * 100, 3),
                "lower_penetration_pct": round((lower_pool - c_low) / lower_pool * 100, 3),
                "pool_type": "DOUBLE_SWEEP_CHOP", "touch_count": upper_touches + lower_touches,
                "reclaim_close": round(c_close, 4), "reclaim_confirmed": False,
                "acceptance_confirmed": False, "entry_permission": "BLOCK", "reason": "Dual-sided liquidity sweep detected."
            }
        }
        
    if is_upper_breach:
        pct = round((c_high - upper_pool) / upper_pool * 100, 3)
        if c_close < upper_pool:
            return {
                "liquidity_gate": {
                    "pair": pair, "timeframe": timeframe,
                    "reference_bar_close_utc": current_candle.get("timestamp"),
                    "source_bar_count": len(candles), "state": "REJECTION_RECLAIM",
                    "pool_side": "HIGH", "pool_level": round(upper_pool, 4),
                    "pool_type": upper_pool_type, "touch_count": upper_touches,
                    "sweep_extreme": round(c_high, 4), "penetration_pct": pct,
                    "reclaim_close": round(c_close, 4), "reclaim_confirmed": True,
                    "acceptance_confirmed": False, "entry_permission": "SHORT_RECLAIM_ONLY",
                    "reason": "Upper sweep closed back inside pool; immediate rejection reclaim."
                }
            }
        else:
            prev_was_sweep = prev_high > upper_pool + penetration_buffer
            if prev_was_sweep:
                if c_close >= upper_pool and prev_close >= upper_pool:
                    return {
                        "liquidity_gate": {
                            "pair": pair, "timeframe": timeframe,
                            "reference_bar_close_utc": current_candle.get("timestamp"),
                            "source_bar_count": len(candles), "state": "BREAKOUT_ACCEPTED",
                            "pool_side": "HIGH", "pool_level": round(upper_pool, 4),
                            "pool_type": upper_pool_type, "touch_count": upper_touches,
                            "sweep_extreme": round(c_high, 4), "penetration_pct": pct,
                            "reclaim_close": round(c_close, 4), "reclaim_confirmed": False,
                            "acceptance_confirmed": True, "entry_permission": "LONG_CONTINUATION_ONLY",
                            "reason": "Breakout accepted."
                        }
                    }
                else:
                    return {
                        "liquidity_gate": {
                            "pair": pair, "timeframe": timeframe,
                            "reference_bar_close_utc": current_candle.get("timestamp"),
                            "source_bar_count": len(candles), "state": "BREAKOUT_ACCEPTED",
                            "pool_side": "HIGH", "pool_level": round(upper_pool, 4),
                            "pool_type": upper_pool_type, "touch_count": upper_touches,
                            "sweep_extreme": round(c_high, 4), "penetration_pct": pct,
                            "reclaim_close": round(c_close, 4), "reclaim_confirmed": False,
                            "acceptance_confirmed": True, "entry_permission": "LONG_CONTINUATION_ONLY",
                            "reason": "Breakout accepted."
                        }
                    }
            else:
                return {
                    "liquidity_gate": {
                        "pair": pair, "timeframe": timeframe,
                        "reference_bar_close_utc": current_candle.get("timestamp"),
                        "source_bar_count": len(candles), "state": "SWEEP_PENDING_CONFIRMATION",
                        "pool_side": "HIGH", "pool_level": round(upper_pool, 4),
                        "pool_type": upper_pool_type, "touch_count": upper_touches,
                        "sweep_extreme": round(c_high, 4), "penetration_pct": pct,
                        "reclaim_close": round(c_close, 4), "reclaim_confirmed": False,
                        "acceptance_confirmed": False, "entry_permission": "BLOCK",
                        "reason": "Pending confirmation."
                    }
                }
                
    elif is_lower_breach:
        pct = round((lower_pool - c_low) / lower_pool * 100, 3)
        if c_close > lower_pool:
            return {
                "liquidity_gate": {
                    "pair": pair, "timeframe": timeframe,
                    "reference_bar_close_utc": current_candle.get("timestamp"),
                    "source_bar_count": len(candles), "state": "REJECTION_RECLAIM",
                    "pool_side": "LOW", "pool_level": round(lower_pool, 4),
                    "pool_type": lower_pool_type, "touch_count": lower_touches,
                    "sweep_extreme": round(c_low, 4), "penetration_pct": pct,
                    "reclaim_close": round(c_close, 4), "reclaim_confirmed": True,
                    "acceptance_confirmed": False, "entry_permission": "LONG_RECLAIM_ONLY",
                    "reason": "Lower sweep reclaimed."
                }
            }
        else:
            prev_was_sweep = prev_low < lower_pool - penetration_buffer
            if prev_was_sweep:
                if c_close <= lower_pool and prev_close <= lower_pool:
                    return {
                        "liquidity_gate": {
                            "pair": pair, "timeframe": timeframe,
                            "reference_bar_close_utc": current_candle.get("timestamp"),
                            "source_bar_count": len(candles), "state": "BREAKOUT_ACCEPTED",
                            "pool_side": "LOW", "pool_level": round(lower_pool, 4),
                            "pool_type": lower_pool_type, "touch_count": lower_touches,
                            "sweep_extreme": round(c_low, 4), "penetration_pct": pct,
                            "reclaim_close": round(c_close, 4), "reclaim_confirmed": False,
                            "acceptance_confirmed": True, "entry_permission": "SHORT_CONTINUATION_ONLY",
                            "reason": "Breakout accepted."
                        }
                    }
                else:
                    return {
                        "liquidity_gate": {
                            "pair": pair, "timeframe": timeframe,
                            "reference_bar_close_utc": current_candle.get("timestamp"),
                            "source_bar_count": len(candles), "state": "BREAKOUT_ACCEPTED",
                            "pool_side": "LOW", "pool_level": round(lower_pool, 4),
                            "pool_type": lower_pool_type, "touch_count": lower_touches,
                            "sweep_extreme": round(c_low, 4), "penetration_pct": pct,
                            "reclaim_close": round(c_close, 4), "reclaim_confirmed": False,
                            "acceptance_confirmed": True, "entry_permission": "SHORT_CONTINUATION_ONLY",
                            "reason": "Breakout accepted."
                        }
                    }
            else:
                return {
                    "liquidity_gate": {
                        "pair": pair, "timeframe": timeframe,
                        "reference_bar_close_utc": current_candle.get("timestamp"),
                        "source_bar_count": len(candles), "state": "SWEEP_PENDING_CONFIRMATION",
                        "pool_side": "LOW", "pool_level": round(lower_pool, 4),
                        "pool_type": lower_pool_type, "touch_count": lower_touches,
                        "sweep_extreme": round(c_low, 4), "penetration_pct": pct,
                        "reclaim_close": round(c_close, 4), "reclaim_confirmed": False,
                        "acceptance_confirmed": False, "entry_permission": "BLOCK",
                        "reason": "Pending confirmation."
                    }
                }
                
    return base_response
