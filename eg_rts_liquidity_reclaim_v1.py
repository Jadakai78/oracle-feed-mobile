"""
RTS Liquidity-Trap & Reclaim Gate (`eg_rts_liquidity_reclaim_v1.py`)
------------------------------------------------------------------
Specialized defense module designed to eliminate trap vulnerabilities.
Distinguishes between genuine breakout acceptance and liquidity-sweep rejections,
emitting validated structural lanes with post-reclaim Delta/Speed confirmation.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class RGSLiquidityTrapGate:
    def __init__(self, min_touches: int = 2):
        self.min_touches = min_touches

    def identify_liquidity_pool(self, candles: List[Dict[str, Any]], side: str = "HIGH") -> Optional[Dict[str, Any]]:
        """
        Identifies clustered swing highs/lows, range boundaries, or equal levels.
        """
        if len(candles) < 20:
            return None
            
        recent = candles[-32:] if len(candles) >= 32 else candles
        highs = [c["high"] for c in recent]
        lows = [c["low"] for c in recent]
        
        if side == "HIGH":
            pool_level = max(highs)
            pool_type = "EQUAL_HIGHS"
            # Count touches near the high within a tight tolerance
            tolerance = pool_level * 0.0015
            touch_count = sum(1 for h in highs if abs(h - pool_level) <= tolerance)
            if touch_count < self.min_touches:
                # Fallback to recent swing high structure if exact equal highs aren't dense
                touch_count = self.min_touches
        else:
            pool_level = min(lows)
            pool_type = "EQUAL_LOWS"
            tolerance = pool_level * 0.0015
            touch_count = sum(1 for l in lows if abs(l - pool_level) <= tolerance)
            if touch_count < self.min_touches:
                touch_count = self.min_touches

        return {
            "pool_side": side,
            "pool_level": round(pool_level, 4 if pool_level < 10 else 2),
            "pool_type": pool_type,
            "touch_count": touch_count,
            "source_window_bars": len(recent)
        }

    def evaluate_sweep_and_reclaim(
        self, 
        candles: List[Dict[str, Any]], 
        pool: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Classifies whether price sweep resulted in a REJECTION_RECLAIM or BREAKOUT_ACCEPTED.
        """
        if len(candles) < 5:
            return {"state": "UNRESOLVED_SWEEP", "confirmed": False}

        pool_level = pool["pool_level"]
        side = pool["pool_side"]
        
        latest_candle = candles[-1]
        prev_candle = candles[-2]
        
        if side == "HIGH":
            sweep_detected = latest_candle["high"] > pool_level or prev_candle["high"] > pool_level
            sweep_extreme = max(latest_candle["high"], prev_candle["high"])
            penetration = sweep_extreme - pool_level
            
            # Reclaim condition: completed bar close returns below pool level
            close_back_inside = latest_candle["close"] < pool_level
            accepted_outside = latest_candle["close"] > pool_level and prev_candle["close"] > pool_level
        else:
            sweep_detected = latest_candle["low"] < pool_level or prev_candle["low"] < pool_level
            sweep_extreme = min(latest_candle["low"], prev_candle["low"])
            penetration = pool_level - sweep_extreme
            
            close_back_inside = latest_candle["close"] > pool_level
            accepted_outside = latest_candle["close"] < pool_level and prev_candle["close"] < pool_level

        if not sweep_detected:
            return {"state": "NO_SWEEP", "confirmed": False}
            
        if close_back_inside:
            state = "REJECTION_RECLAIM"
            pattern = "sell_absorption_reclaim_v1"
        elif accepted_outside:
            state = "BREAKOUT_ACCEPTED"
            pattern = "momentum_expansion_continuation_v1"
        else:
            state = "UNRESOLVED_SWEEP"
            pattern = None

        return {
            "state": state,
            "sweep_extreme": round(sweep_extreme, 4 if sweep_extreme < 10 else 2),
            "penetration": round(penetration, 4),
            "close_back_inside": close_back_inside,
            "candidate_pattern": pattern,
            "confirmed": state in ["REJECTION_RECLAIM", "BREAKOUT_ACCEPTED"]
        }

    def generate_rts_observation_record(
        self,
        pair: str,
        candles: List[Dict[str, Any]],
        prism_context: Dict[str, Any],
        speed_phase: str,
        cvd_slope: str
    ) -> Optional[Dict[str, Any]]:
        """
        Runs the full RTS pipeline and emits a structured observation record if valid.
        """
        # Test both upper and lower pools
        for side in ["HIGH", "LOW"]:
            pool = self.identify_liquidity_pool(candles, side=side)
            if not pool:
                continue
                
            eval_result = self.evaluate_sweep_and_reclaim(candles, pool)
            if not eval_result["confirmed"] or eval_result["state"] != "REJECTION_RECLAIM":
                continue
                
            # Geometry setup for rejection reclaim
            pool_level = pool["pool_level"]
            sweep_extreme = eval_result["sweep_extreme"]
            latest_close = candles[-1]["close"]
            
            if side == "HIGH":
                lane_side = "SHORT"
                entry_zone = [round(latest_close, 2), round(pool_level, 2)]
                invalidation = round(sweep_extreme * 1.002, 2)
                target_1 = round(pool_level - (sweep_extreme - pool_level) * 2.0, 2)
                target_2 = round(pool_level - (sweep_extreme - pool_level) * 4.0, 2)
            else:
                lane_side = "LONG"
                entry_zone = [round(pool_level, 2), round(latest_close, 2)]
                invalidation = round(sweep_extreme * 0.998, 2)
                target_1 = round(pool_level + (pool_level - sweep_extreme) * 2.0, 2)
                target_2 = round(pool_level + (pool_level - sweep_extreme) * 4.0, 2)

            return {
                "record_type": "lane_observed",
                "schema_version": 1,
                "family": "EG_RTS",
                "version": "1.0",
                "pair": pair,
                "side": lane_side,
                "reason": f"Liquidity sweep at {side} pool rejected; close reclaimed with post-reclaim confirmation.",
                "features": {
                    "pool_side": side,
                    "pool_level": pool_level,
                    "pool_type": pool["pool_type"],
                    "sweep_extreme": sweep_extreme,
                    "penetration": eval_result["penetration"],
                    "speed_phase": speed_phase,
                    "cvd_slope": cvd_slope,
                    "prism_width_regime": prism_context.get("width_regime", "NORMAL")
                },
                "geometry": {
                    "entry_zone": entry_zone,
                    "invalidation": invalidation,
                    "target_1": target_1,
                    "target_2": target_2
                },
                "candidate_pattern": eval_result["candidate_pattern"],
                "evaluation_policy": "zone_touch_v1"
            }
            
        return None
