import json
import random
import time
import os
import threading
from datetime import datetime, timezone
from flask import Flask

app = Flask(__name__)

class HostileActivitySentinel:
    def __init__(self, hostility_threshold=0.80):
        self.hostility_threshold = hostility_threshold
        self.prism_map_primed = False

    def evaluate_speed_gate(self, candidate_telemetry):
        speed_phase = candidate_telemetry.get("speed_phase")
        cvd_slope = candidate_telemetry.get("cvd_slope_state")
        anti_delta = candidate_telemetry.get("anti_delta_score", 0)
        
        if speed_phase == "SHOCK_EXPANSION":
            self.prism_map_primed = True
            return True, 0.99, "PRISM_AWAKENING: Raw shock ignored, map primed for emerging speed."
            
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
        is_hostile, score, reason = self.evaluate_speed_gate(offensive)
        if is_hostile:
            return True, score, reason
            
        anti_delta = offensive.get("anti_delta_score", 0)
        if anti_delta > 80:
            return True, 0.88, "Anti-Delta Pressure Overload"
            
        return False, 0.25, "CLEAN"

def run_continuous_orchestration():
    print("🚀 Initializing Continuous Master Orchestration Loop (Background Thread)...")
    sentinel = HostileActivitySentinel(hostility_threshold=0.80)
    pairs = ["OPUSD", "TRXUSD", "JUPUSD", "INJUSD"]
    
    while True:
        try:
            current_time = datetime.now(timezone.utc).isoformat()
            target_pair = random.choice(pairs)
            speed_phases = ["SHOCK_EXPANSION", "EMERGING_TEMPO", "DEAD_CHOP", "DECAY"]
            cvd_states = ["DIVERGENT", "FLAT", "EXPANDING"]
            
            sample_candidate = {
                "pair": target_pair,
                "offensive_review": {
                    "speed_phase": random.choice(speed_phases),
                    "cvd_slope_state": random.choice(cvd_states),
                    "anti_delta_score": random.randint(20, 85)
                }
            }
            
            is_hostile, score, reason = sentinel.evaluate_hostility(sample_candidate)
            status = "⛔ BLOCKED (VETO)" if is_hostile else "🟢 APPROVED (ALLOCATED)"
            
            print(f"[{current_time}] Pair: {target_pair} | Phase: {sample_candidate['offensive_review']['speed_phase']} | Status: {status} | Hostility: {score:.3f} | Reason: {reason}")
            time.sleep(10)
            
        except Exception as e:
            print(f"⚠️ Error in orchestration loop: {e}")
            time.sleep(5)

@app.route("/")
def health_check():
    return "Sniper Execution Engine & Prism Speed-Gate Active", 200

if __name__ == "__main__":
    # Start the continuous engine in a background thread so it doesn't block the web server
    engine_thread = threading.Thread(target=run_continuous_orchestration, daemon=True)
    engine_thread.start()
    
    # Bind to Render's required port
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
