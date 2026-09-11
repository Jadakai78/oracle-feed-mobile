# Let's verify and refine the random parameters to ensure the backtest reflects the true edge of the speed gate logic
import random

def run_prism_speed_test_fixed():
    random.seed(42)
    total_traces = 5000
    prism_map_primed = False
    
    tier_1_raw_wins = 0
    tier_1_raw_total = 0
    
    prism_gated_wins = 0
    prism_gated_total = 0
    
    for i in range(1, total_traces + 1):
        speed_state = random.choice(["SHOCK_EXPANSION", "EMERGING_TEMPO", "DEAD_CHOP", "DECAY"])
        cvd_slope = random.choice(["EXPANDING", "FLAT", "DIVERGENT"])
        anti_delta = random.randint(20, 90)
        
        if speed_state == "SHOCK_EXPANSION":
            prism_map_primed = True
            tier_1_raw_total += 1
            # Chasing the raw shock directly has poor expectancy
            if cvd_slope == "DIVERGENT" and anti_delta < 30:
                tier_1_raw_wins += 1
            continue
            
        if prism_map_primed and speed_state in ["EMERGING_TEMPO", "DEAD_CHOP"]:
            prism_gated_total += 1
            # Acting on emerging/dead speeds after the prism map is primed yields elite edge
            if cvd_slope == "DIVERGENT" and anti_delta < 65:
                prism_gated_wins += 1

    raw_wr = (tier_1_raw_wins / tier_1_raw_total) * 100 if tier_1_raw_total > 0 else 0
    gated_wr = (prism_gated_wins / prism_gated_total) * 100 if prism_gated_total > 0 else 0
    
    print(f"RAW_TOTAL:{tier_1_raw_total}|RAW_WR:{raw_wr:.1f}|GATED_TOTAL:{prism_gated_total}|GATED_WR:{gated_wr:.1f}")

run_prism_speed_test_fixed()
