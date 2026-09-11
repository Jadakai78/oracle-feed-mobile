import json
import random
from datetime import datetime, timezone

class HostileActivitySentinel:
    def __init__(self, hostility_threshold=0.80):
        self.hostility_threshold = hostility_threshold
        self.prism_map_primed = False

    def evaluate_speed_gate(self, candidate_telemetry):
        """
        Enforces the two-stage Prism-Awakened Speed Gate:
        1. Raw SHOCK_EXPANSION primes the map but triggers an immediate VETO (no chasing).
        2. EMERGING_TEMPO or DEAD_CHOP subsequent states unlock execution.
        """
        speed_phase = candidate_telemetry.get("speed_phase")
        cvd_slope = candidate_telemetry.get("cvd_slope_state")
        anti_delta = candidate_telemetry.get("anti_delta_score", 0)
        
        # Stage 1: Raw Shock Awakening
        if speed_phase == "SHOCK_EXPANSION":
            self.prism_map_primed = True
            return True, 0.99, "PRISM_AWAKENING: Raw shock ignored, map primed for emerging speed."
            
        # Stage 2: Checking if we have a primed map for emerging/dead tempo
        if not self.prism_map_primed:
            return True, 0.95, "VETO: Prism map unprimed. Awaiting initial high-speed shock."
            
        if speed_phase in ["EMERGING_TEMPO", "DEAD_CHOP", "REACCELERATION"]:
            if cvd_slope == "DIVERGENT" and anti_delta < 60:
                return False, 0.30, "CLEAN: Prism-primed emerging speed aligned with CVD divergence."
            else:
                return True, 0.85, "VETO: Emerging speed detected but lacking CVD divergence / low anti-delta."
                
        return True, 0.90, "VETO: Speed phase out of optimal alignment."

    def evaluate_hostility(self, candidate):
        offensive = candidate.get("offensive_review", {})
        
        # Run the two-stage speed gate check first
        is_hostile, score, reason = self.evaluate_speed_gate(offensive)
        if is_hostile:
            return True, score, reason
            
        # Fallback anti-delta check
        anti_delta = offensive.get("anti_delta_score", 0)
        if anti_delta > 80:
            return True, 0.88, "Anti-Delta Pressure Overload"
            
        return False, 0.25, "CLEAN"

def run_master_orchestration():
    print("🚀 Initializing Master Orchestration Loop with Prism Speed Gate & Sentinel...")
    sentinel = HostileActivitySentinel(hostility_threshold=0.80)
    
    # Simulate a live evaluation cycle
    sample_candidate = {
        "pair": "OPUSD",
        "offensive_review": {
            "speed_phase": "EMERGING_TEMPO",
            "cvd_slope_state": "DIVERGENT",
            "anti_delta_score": 35
        }
    }
    
    # Force prism priming for test simulation
    sentinel.prism_map_primed = True
    
    is_hostile, score, reason = sentinel.evaluate_hostility(sample_candidate)
    print(f"\n📊 ORCHESTRATION CYCLE TEST:")
    print(f" - Candidate: {sample_candidate['pair']}")
    print(f" - Veto Status: {'BLOCKED' if is_hostile else 'APPROVED (ALLOCATED)'}")
    print(f" - Hostility Score: {score}")
    print(f" - Reason: {reason}\n")

if __name__ == "__main__":
    run_master_orchestration()
