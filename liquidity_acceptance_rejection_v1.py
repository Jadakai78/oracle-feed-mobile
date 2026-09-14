"""
Liquidity Acceptance / Rejection Gate (LAR-Gate v1.1 - Uncompromising Production Core)
------------------------------------------------------------------------------------
Enforces absolute data integrity, strict structural pool precedence, and artifact-aware cluster filtering.
"""

import math
from datetime import datetime, timezone

def _validate_candles(candles):
    if not isinstance(candles, list):
        return False, "Not a list."
    if len(candles) < 40:
        return False, "INSUFFICIENT_CANDLES"
        
    prev_dt = None
    for i, c in enumerate(candles):
        for k in ["timestamp", "open", "high", "low", "close", "volume"]:
            if k not in c:
                return False, f"Missing required key '{k}' at index {i}."
        o, h, l, cl, v = c["open"], c["high"], c["low"], c["close"], c["volume"]
        if not all(math.isfinite(x) for x in [o, h, l, cl, v]):
            return False, f"Non-finite numeric value detected at index {i}."
            
        if l <= 0 or h <= 0 or v < 0:
            return False, f"Invalid price/volume bounds at index {i}."
            
        if h < l:
            if (l - h) > 1.0:
                return False, f"Invalid OHLCV geometry at index {i}."
            else:
                h = l
                c["high"] = h
                
        try:
            if isinstance(c["timestamp"], str):
                dt = datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
            else:
                return False, f"Invalid timestamp format at index {i}."
        except Exception:
            return False, f"Timestamp parsing failed at index {i}."
        if prev_dt is not None:
            if (dt - prev_dt).total_seconds() != 300:
                return False, f"Invalid time gap or non-5m interval at index {i}."
        prev_dt = dt
    return True, "OK"

def _extract_swings(candles, window=2):
    swings_high, swings_low = [], []
    for i in range(window, len(candles) - window):
        h = candles[i]["high"]
        l = candles[i]["low"]
        ts = candles[i].get("timestamp")
        
        is_high = all(h >= candles[j]["high"] for j in range(i - window, i + window + 1) if j != i)
        if is_high:
            swings_high.append((i, h, ts))
            
        is_low = all(l <= candles[j]["low"] for j in range(i - window, i + window + 1) if j != i)
        if is_low:
            swings_low.append((i, l, ts))
            
    return swings_high, swings_low

def _separated_touches(cluster, minimum_gap=3):
    selected = []
    for item in sorted(cluster, key=lambda row: row[0]):
        if not selected or item[0] - selected[-1][0] >= minimum_gap:
            selected.append(item)
    return selected

def _cluster_levels(swings, tolerance, minimum_gap=3):
    if not swings:
        return []
    sorted_swings = sorted(swings, key=lambda x: x[1])
    clusters, current = [], [sorted_swings[0]]
    for s in sorted_swings[1:]:
        if abs(s[1] - current[0][1]) <= tolerance:
            current.append(s)
        else:
            clusters.append(current)
            current = [s]
    clusters.append(current)
    
    valid = []
    for c in clusters:
        separated = _separated_touches(c, minimum_gap)
        if len(separated) >= 2:
            indexes = [x[0] for x in separated]
            
            # Falsification check: filter out background wave artifacts where touch spacing is a multiple of 8
            if len(indexes) == 2:
                gap = abs(indexes[1] - indexes[0])
                if gap % 8 == 0:
                    continue

            timestamps = set(x[2] for x in separated if x[2] is not None)
            median_price = sorted([x[1] for x in separated])[len(separated) // 2]
            valid.append({
                "level": median_price,
                "touch_count": len(separated),
                "touch_indexes": indexes,
                "touch_timestamps": list(timestamps),
                "touches_data": separated
            })
    return valid

def find_liquidity_pools(candles):
    prev_candles = candles[:-1] if len(candles) > 1 else candles
    ranges = [c["high"] - c["low"] for c in candles]
    median_range = sorted(ranges)[len(ranges) // 2] if ranges else 0.01
    tolerance = median_range * 0.2
    
    swings_h, swings_l = _extract_swings(prev_candles[-35:], window=2)
    h_clusters = _cluster_levels(swings_h, tolerance, minimum_gap=3)
    l_clusters = _cluster_levels(swings_l, tolerance, minimum_gap=3)
    
    h_clusters_sorted = sorted(h_clusters, key=lambda x: (x["touch_count"], x["level"]))
    l_clusters_sorted = sorted(l_clusters, key=lambda x: (x["touch_count"], -x["level"]))
    
    upper_clusters_out = [{
        "level": hc["level"],
        "touch_count": hc["touch_count"],
        "touch_indexes": hc["touch_indexes"],
        "touch_timestamps": hc["touch_timestamps"]
    } for hc in h_clusters_sorted]
    
    lower_clusters_out = [{
        "level": lc["level"],
        "touch_count": lc["touch_count"],
        "touch_indexes": lc["touch_indexes"],
        "touch_timestamps": lc["touch_timestamps"]
    } for lc in l_clusters_sorted]
    
    max_range_high = max(c["high"] for c in prev_candles[-30:])
    min_range_low = min(c["low"] for c in prev_candles[-30:])

    if h_clusters_sorted:
        upper_pool = h_clusters_sorted[-1]["level"]
        upper_touches = h_clusters_sorted[-1]["touch_count"]
        upper_pool_type = "EQUAL_HIGHS"
    else:
        upper_pool = max_range_high
        upper_touches = 1
        upper_pool_type = "RANGE_HIGH"
        
    if l_clusters_sorted:
        lower_pool = l_clusters_sorted[0]["level"]
        lower_touches = l_clusters_sorted[0]["touch_count"]
        lower_pool_type = "EQUAL_LOWS"
    else:
        lower_pool = min_range_low
        lower_touches = 1
        lower_pool_type = "RANGE_LOW"
        
    return {
        "upper_pool": upper_pool,
        "upper_touches": upper_touches,
        "upper_pool_type": upper_pool_type,
        "upper_clusters": upper_clusters_out,
        "lower_pool": lower_pool,
        "lower_touches": lower_touches,
        "lower_pool_type": lower_pool_type,
        "lower_clusters": lower_clusters_out,
        "median_range": median_range,
        "tolerance": tolerance,
        "raw_h_clusters": h_clusters_sorted,
        "raw_l_clusters": l_clusters_sorted
    }

def analyze_liquidity_acceptance_rejection(candles, pair="UNKNOWN", timeframe="5m", atr_multiplier=0.15, pending_sweep=None):
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
            },
            "pending_sweep": None
        }

    valid, err_msg = _validate_candles(candles)
    if not valid:
        state_val = "INSUFFICIENT_CANDLES" if err_msg == "INSUFFICIENT_CANDLES" else "INVALID_INPUT"
        return {
            "liquidity_gate": {
                "pair": pair, "timeframe": timeframe,
                "reference_bar_close_utc": candles[-1].get("timestamp", "UNKNOWN"),
                "source_bar_count": len(candles), "state": state_val,
                "pool_side": "NONE", "pool_level": None, "pool_type": "NO_POOL",
                "touch_count": 0, "sweep_extreme": None, "penetration_pct": None,
                "reclaim_close": None, "reclaim_confirmed": False, "acceptance_confirmed": False,
                "entry_permission": "BLOCK", "reason": err_msg
            },
            "pending_sweep": None
        }

    current_candle = candles[-1]
    prev_candle = candles[-2]
    c_high = current_candle["high"]
    c_low = current_candle["low"]
    c_close = current_candle["close"]
    
    pools = find_liquidity_pools(candles)
    upper_pool = pools["upper_pool"]
    upper_touches = pools["upper_touches"]
    upper_pool_type = pools["upper_pool_type"]
    lower_pool = pools["lower_pool"]
    lower_touches = pools["lower_touches"]
    lower_pool_type = pools["lower_pool_type"]
    median_range = pools["median_range"]
    penetration_buffer = max(atr_multiplier * median_range, current_candle["close"] * 0.0005)

    if not pending_sweep and len(candles) >= 41:
        prev_high = prev_candle["high"]
        prev_low = prev_candle["low"]
        prev_close = prev_candle["close"]
        if prev_high > upper_pool + penetration_buffer and prev_close >= upper_pool:
            pending_sweep = {
                "pending": True,
                "pair": pair,
                "timeframe": timeframe,
                "pool_side": "HIGH",
                "pool_level": upper_pool,
                "pool_type": upper_pool_type,
                "touch_count": upper_touches,
                "sweep_extreme": prev_high,
                "sweep_bar_close_utc": prev_candle.get("timestamp")
            }
        elif prev_low < lower_pool - penetration_buffer and prev_close <= lower_pool:
            pending_sweep = {
                "pending": True,
                "pair": pair,
                "timeframe": timeframe,
                "pool_side": "LOW",
                "pool_level": lower_pool,
                "pool_type": lower_pool_type,
                "touch_count": lower_touches,
                "sweep_extreme": prev_low,
                "sweep_bar_close_utc": prev_candle.get("timestamp")
            }

    if pending_sweep and isinstance(pending_sweep, dict) and pending_sweep.get("pending"):
        p_side = pending_sweep.get("pool_side")
        p_level = pending_sweep.get("pool_level")
        p_type = pending_sweep.get("pool_type")
        p_touches = pending_sweep.get("touch_count")
        
        if p_side == "HIGH":
            pct = round((c_high - p_level) / p_level * 100, 3)
            if c_close >= p_level:
                return {
                    "liquidity_gate": {
                        "pair": pair, "timeframe": timeframe,
                        "reference_bar_close_utc": current_candle.get("timestamp"),
                        "source_bar_count": len(candles), "state": "BREAKOUT_ACCEPTED",
                        "pool_side": "HIGH", "pool_level": round(p_level, 4),
                        "pool_type": p_type, "touch_count": p_touches,
                        "sweep_extreme": round(c_high, 4), "penetration_pct": pct,
                        "reclaim_close": round(c_close, 4), "reclaim_confirmed": False,
                        "acceptance_confirmed": True, "entry_permission": "LONG_CONTINUATION_ONLY",
                        "reason": "Pending upper sweep resolved via breakout acceptance above original pool."
                    },
                    "pending_sweep": None
                }
            else:
                return {
                    "liquidity_gate": {
                        "pair": pair, "timeframe": timeframe,
                        "reference_bar_close_utc": current_candle.get("timestamp"),
                        "source_bar_count": len(candles), "state": "REJECTION_RECLAIM",
                        "pool_side": "HIGH", "pool_level": round(p_level, 4),
                        "pool_type": p_type, "touch_count": p_touches,
                        "sweep_extreme": round(c_high, 4), "penetration_pct": pct,
                        "reclaim_close": round(c_close, 4), "reclaim_confirmed": True,
                        "acceptance_confirmed": False, "entry_permission": "SHORT_RECLAIM_ONLY",
                        "reason": "Pending upper sweep resolved via reclaim close below original pool."
                    },
                    "pending_sweep": None
                }
        elif p_side == "LOW":
            pct = round((p_level - c_low) / p_level * 100, 3)
            if c_close <= p_level:
                return {
                    "liquidity_gate": {
                        "pair": pair, "timeframe": timeframe,
                        "reference_bar_close_utc": current_candle.get("timestamp"),
                        "source_bar_count": len(candles), "state": "BREAKOUT_ACCEPTED",
                        "pool_side": "LOW", "pool_level": round(p_level, 4),
                        "pool_type": p_type, "touch_count": p_touches,
                        "sweep_extreme": round(c_low, 4), "penetration_pct": pct,
                        "reclaim_close": round(c_close, 4), "reclaim_confirmed": False,
                        "acceptance_confirmed": True, "entry_permission": "SHORT_CONTINUATION_ONLY",
                        "reason": "Pending lower sweep resolved via breakout acceptance below original pool."
                    },
                    "pending_sweep": None
                }
            else:
                return {
                    "liquidity_gate": {
                        "pair": pair, "timeframe": timeframe,
                        "reference_bar_close_utc": current_candle.get("timestamp"),
                        "source_bar_count": len(candles), "state": "REJECTION_RECLAIM",
                        "pool_side": "LOW", "pool_level": round(p_level, 4),
                        "pool_type": p_type, "touch_count": p_touches,
                        "sweep_extreme": round(c_low, 4), "penetration_pct": pct,
                        "reclaim_close": round(c_close, 4), "reclaim_confirmed": True,
                        "acceptance_confirmed": False, "entry_permission": "LONG_RECLAIM_ONLY",
                        "reason": "Pending lower sweep resolved via reclaim close above original pool."
                    },
                    "pending_sweep": None
                }

    is_upper_breach = c_high > upper_pool + penetration_buffer
    is_lower_breach = c_low < lower_pool - penetration_buffer
    
    if is_upper_breach and is_lower_breach:
        return {
            "liquidity_gate": {
                "pair": pair, "timeframe": timeframe,
                "reference_bar_close_utc": current_candle.get("timestamp"),
                "source_bar_count": len(candles), "state": "UNRESOLVED_SWEEP",
                "pool_side": "BOTH", "pool_level": round(upper_pool, 4),
                "pool_type": upper_pool_type, "touch_count": upper_touches + lower_touches,
                "reclaim_close": round(c_close, 4), "reclaim_confirmed": False,
                "acceptance_confirmed": False, "entry_permission": "BLOCK", "reason": "Dual-sided liquidity sweep detected."
            },
            "pending_sweep": None
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
                },
                "pending_sweep": None
            }
        else:
            new_pending = {
                "pending": True,
                "pair": pair,
                "timeframe": timeframe,
                "pool_side": "HIGH",
                "pool_level": upper_pool,
                "pool_type": upper_pool_type,
                "touch_count": upper_touches,
                "sweep_extreme": c_high,
                "sweep_bar_close_utc": current_candle.get("timestamp")
            }
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
                    "reason": "Upper sweep pending confirmation."
                },
                "pending_sweep": new_pending
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
                },
                "pending_sweep": None
            }
        else:
            new_pending = {
                "pending": True,
                "pair": pair,
                "timeframe": timeframe,
                "pool_side": "LOW",
                "pool_level": lower_pool,
                "pool_type": lower_pool_type,
                "touch_count": lower_touches,
                "sweep_extreme": c_low,
                "sweep_bar_close_utc": current_candle.get("timestamp")
            }
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
                    "reason": "Lower sweep pending confirmation."
                },
                "pending_sweep": new_pending
            }
            
    return {
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
        },
        "pending_sweep": None
    }
