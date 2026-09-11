"""
Retail Theft Sniper (RTS) Engine
--------------------------------
Tracks institutional liquidation cascades and trades the 
post-cluster vacuum / volume vacuum aftermath.
"""

import random

def evaluate_rts_liquidation_sniper(card: dict) -> tuple[str, float]:
    review = card.get("offensive_review", {})
    
    liquidation_spike = review.get("liquidation_spike_detected", False)
    vacuum_state = review.get("post_cluster_vacuum", False)
    delta_imbalance = review.get("rts_delta_shift", "NEUTRAL") # "FLUSH_LONG" or "FLUSH_SHORT"
    
    # Case 1: Longs flushed out violently, price sweeps lows, vacuum forms (Long Sniper)
    if liquidation_spike and vacuum_state and delta_imbalance == "FLUSH_LONG":
        win = random.random() < 0.61
        return "EXECUTE_RTS_LONG_SNIPE", (2.2 if win else -1.0)
        
    # Case 2: Shorts squeezed/flushed out, price sweeps highs, vacuum forms (Short Sniper)
    if liquidation_spike and vacuum_state and delta_imbalance == "FLUSH_SHORT":
        win = random.random() < 0.58
        return "EXECUTE_RTS_SHORT_SNIPE", (1.9 if win else -1.0)
        
    return "STAND_DOWN_RTS_CLEAR", 0.0
