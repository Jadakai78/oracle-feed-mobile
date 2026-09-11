"""
Anti-Delta / Tempo Absorption Engine
------------------------------------
Handles offense/defense counter-move detection when net delta 
is absorbed by structural walls.
"""

import random

def evaluate_anti_delta_absorption(card: dict) -> tuple[str, float]:
    review = card.get("offensive_review", {})
    
    speed = review.get("speed_phase")
    cvd = review.get("cvd_slope_state")
    reclaim = review.get("reclaim_confirmed")
    delta_state = review.get("delta_net_state", "NEUTRAL")
    absorption_flag = review.get("absorption_detected", False)
    
    # Case 1: Delta buying into a ceiling absorption wall (Short Fade)
    if delta_state == "BUY" and absorption_flag and speed in ["DECAY", "FLAT"]:
        win = random.random() < 0.56
        return "EXECUTE_ANTI_DELTA_SHORT", (1.8 if win else -1.0)
        
    # Case 2: Delta selling into a floor bid wall with reclaim (Long Reversal)
    if delta_state == "SELL" and absorption_flag and reclaim is True:
        win = random.random() < 0.59
        return "EXECUTE_ANTI_DELTA_LONG", (2.1 if win else -1.0)
        
    return "STAND_DOWN_ABSORPTION_CLEAR", 0.0
