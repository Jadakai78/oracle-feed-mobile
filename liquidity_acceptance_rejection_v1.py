"""
Liquidity Acceptance / Rejection Gate (LAR-Gate v1)
----------------------------------------------------
Inspects completed 5m candles to detect structural liquidity pools,
evaluates sweep penetrations, and classifies rejections vs breakouts.
"""

def analyze_liquidity_acceptance_rejection(candles, atr_multiplier=0.15):
    if len(candles) < 40:
        return {
            "liquidity_gate": {
                "state": "INSUFFICIENT_CANDLES",
                "pool_side": "NONE",
                "pool_level": 0.0,
                "pool_type": "NONE",
                "touch_count": 0,
                "sweep_extreme": 0.0,
                "penetration_pct": 0.0,
                "reclaim_close": 0.0,
                "reclaim_confirmed": False,
                "acceptance_confirmed": False,
                "entry_permission": "BLOCK",
                "reason": "Less than 40 candles available."
            }
        }
        
    recent = candles[-50:]
    current_candle = recent[-1]
    prev_candles = recent[:-1]
    
    ranges = [c["high"] - c["low"] for c in recent]
    median_range = sorted(ranges)[len(ranges) // 2]
    penetration_buffer = max(0.15 * median_range, current_candle["close"] * 0.0005)
    
    highs = [c["high"] for c in prev_candles[-30:]]
    lows = [c["low"] for c in prev_candles[-30:]]
    
    upper_pool = max(highs)
    lower_pool = min(lows)
    
    high_touches = sum(1 for h in highs if abs(h - upper_pool) <= (median_range * 0.2))
    low_touches = sum(1 for l in lows if abs(l - lower_pool) <= (median_range * 0.2))
    
    pool_side = "NONE"
    pool_level = 0.0
    pool_type = "NONE"
    touch_count = 0
    sweep_extreme = 0.0
    penetration_pct = 0.0
    reclaim_confirmed = False
    acceptance_confirmed = False
    state = "NO_SWEEP"
    entry_permission = "PASS_ALL"
    reason = "No meaningful structural breach detected."
    
    if current_candle["high"] > upper_pool + penetration_buffer:
        pool_side = "HIGH"
        pool_level = upper_pool
        pool_type = "EQUAL_HIGHS" if high_touches >= 2 else "RANGE_HIGH"
        touch_count = max(2, high_touches)
        sweep_extreme = current_candle["high"]
        penetration_pct = round((sweep_extreme - upper_pool) / upper_pool * 100, 3)
        
        if current_candle["close"] < upper_pool:
            state = "REJECTION_RECLAIM"
            reclaim_confirmed = True
            entry_permission = "SHORT_RECLAIM_ONLY"
            reason = "Upper liquidity sweep closed back below validated pool."
        elif current_candle["close"] >= upper_pool and recent[-2]["close"] >= upper_pool:
            state = "BREAKOUT_ACCEPTED"
            acceptance_confirmed = True
            entry_permission = "LONG_CONTINUATION_ONLY"
            reason = "Upper break accepted with consecutive closes above pool."
        else:
            state = "UNRESOLVED_SWEEP"
            entry_permission = "BLOCK"
            reason = "Upper pool swept; acceptance/rejection unresolved."
            
    elif current_candle["low"] < lower_pool - penetration_buffer:
        pool_side = "LOW"
        pool_level = lower_pool
        pool_type = "EQUAL_LOWS" if low_touches >= 2 else "RANGE_LOW"
        touch_count = max(2, low_touches)
        sweep_extreme = current_candle["low"]
        penetration_pct = round((lower_pool - sweep_extreme) / lower_pool * 100, 3)
        
        if current_candle["close"] > lower_pool:
            state = "REJECTION_RECLAIM"
            reclaim_confirmed = True
            entry_permission = "LONG_RECLAIM_ONLY"
            reason = "Lower liquidity sweep closed back above validated pool."
        elif current_candle["close"] <= lower_pool and recent[-2]["close"] <= lower_pool:
            state = "BREAKOUT_ACCEPTED"
            acceptance_confirmed = True
            entry_permission = "SHORT_CONTINUATION_ONLY"
            reason = "Lower break accepted with consecutive closes below pool."
        else:
            state = "UNRESOLVED_SWEEP"
            entry_permission = "BLOCK"
            reason = "Lower pool swept; acceptance/rejection unresolved."
            
    return {
        "liquidity_gate": {
            "state": state,
            "pool_side": pool_side,
            "pool_level": round(pool_level, 4 if pool_level < 10 else 2),
            "pool_type": pool_type,
            "touch_count": touch_count,
            "sweep_extreme": round(sweep_extreme, 4 if sweep_extreme < 10 else 2),
            "penetration_pct": penetration_pct,
            "reclaim_close": round(current_candle["close"], 4 if current_candle["close"] < 10 else 2),
            "reclaim_confirmed": reclaim_confirmed,
            "acceptance_confirmed": acceptance_confirmed,
            "entry_permission": entry_permission,
            "reason": reason
        }
    }
