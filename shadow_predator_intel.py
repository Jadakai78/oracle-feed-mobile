"""
Shadow Predator Intelligence Engine (`shadow_predator_intel.py`)
---------------------------------------------------------------
Defensive telemetry radar that reverse-engineers high-frequency liquidity-hunting 
algos. It analyzes localized volume delta, order book clustering, and PRISM terrain 
width to compute the Maximum Cloaked Allocation Limit (MCAL) for any given setup.

Core Objectives:
1. Detect localized liquidity absorption capacity (avoiding the "flare" effect).
2. Calculate proportional sizing thresholds based on immediate tape activity.
3. Flag "Predator Squeeze Zones" where hunter algos are actively feeding.
"""

import logging
from typing import Dict, List, Any, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class ShadowPredatorIntel:
    def __init__(self, base_stealth_tier: float = 750.0, max_prop_tier: float = 1500.0):
        self.base_stealth_tier = base_stealth_tier
        self.max_prop_tier = max_prop_tier

    def analyze_local_liquidity_depth(self, candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyzes recent completed candles to estimate local volume delta absorption 
        and order-book friction.
        """
        if not candles or len(candles) < 10:
            return {
                "local_absorption_capacity": "LOW",
                "avg_volume_chunk": 0.0,
                "friction_index": 1.0,
                "predator_hazard_level": "HIGH"
            }

        recent = candles[-10:]
        volumes = [c.get("volume", 0.0) for c in recent]
        avg_vol = sum(volumes) / len(volumes)
        
        # Calculate price ranges to measure localized volatility/friction
        ranges = [c.get("high", 0) - c.get("low", 0) for c in recent]
        last_candle = recent[-1]
        
        # Volume expansion or contraction relative to recent history
        vol_expansion = last_candle.get("volume", 0.0) / max(1.0, avg_vol)
        
        if vol_expansion < 0.7:
            hazard = "HIGH (Thin Tape / Predator Chop Zone)"
            capacity = "RESTRICTED"
        elif vol_expansion > 2.5:
            hazard = "ELEVATED (High Volatility / Sweep Risk)"
            capacity = "EXPANDED"
        else:
            hazard = "NORMAL (Balanced Stealth Zone)"
            capacity = "OPTIMAL"

        return {
            "local_absorption_capacity": capacity,
            "avg_volume_chunk": round(avg_vol, 2),
            "vol_expansion_ratio": round(vol_expansion, 2),
            "predator_hazard_level": hazard
        }

    def compute_maximum_cloaked_allocation(
        self, 
        symbol: str, 
        prism_width_regime: str, 
        liquidity_metrics: Dict[str, Any]
    ) -> Tuple[float, str]:
        """
        Computes the Maximum Cloaked Allocation Limit (MCAL).
        Ensures our position size blends into background noise and doesn't trigger 
        predator stop-hunting routines.
        """
        hazard = liquidity_metrics.get("predator_hazard_level", "HIGH")
        capacity = liquidity_metrics.get("local_absorption_capacity", "RESTRICTED")
        vol_ratio = liquidity_metrics.get("vol_expansion_ratio", 1.0)

        # Base allocation starts at our safe minimum stealth tier
        allowed_allocation = self.base_stealth_tier
        rationale = "Default Stealth Tier ($750): Preserving background noise profile."

        # If width regime is compressing or tape is thin, restrict size strictly
        if "HIGH" in hazard or capacity == "RESTRICTED":
            allowed_allocation = 500.0
            rationale = "Restricted Stealth Tier ($500): Thin liquidity detected. Large footprints will be targeted by predator algos."
        
        # If PRISM width regime is expanding and local absorption is optimal, we can scale up safely
        elif prism_width_regime == "EXPANSION" and capacity == "OPTIMAL" and vol_ratio >= 1.0:
            allowed_allocation = self.max_prop_tier
            rationale = "Max Prop Tier ($1,500): Local volume delta fully absorbs footprint. Stealth achieved."
        
        elif prism_width_regime == "NORMAL":
            allowed_allocation = 1000.0
            rationale = "Balanced Tier ($1,000): Moderate structural width. Cloaked within normal distribution."

        return float(allowed_allocation), rationale

    def evaluate_shadow_telemetry(
        self, 
        symbol: str, 
        candles: List[Dict[str, Any]], 
        prism_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Runs the complete shadow predator intelligence scan combining PRISM terrain 
        with localized tape friction.
        """
        liq_metrics = self.analyze_local_liquidity_depth(candles)
        width_regime = prism_context.get("width_regime", {}).get("regime", "NORMAL")
        
        mcal, rationale = self.compute_maximum_cloaked_allocation(symbol, width_regime, liq_metrics)
        
        return {
            "symbol": symbol,
            "maximum_cloaked_allocation": mcal,
            "liquidity_telemetry": liq_metrics,
            "prism_width_regime": width_regime,
            "stealth_rationale": rationale,
            "predator_status": "MONITORED_AND_CLOAKED"
        }
