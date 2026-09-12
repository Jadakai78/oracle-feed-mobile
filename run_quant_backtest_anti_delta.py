from __future__ import annotations
import os
import random
from quant_setup_analyzer import QuantSetupAnalyzer


def evaluate_rts_gate(card: dict) -> bool:
    """Phase 2: RTS Liquidation Gate. Hard vetoes high liquidation cascade zones."""
    review = card.get("offensive_review", {})
    rts_state = review.get("rts_state", "NEUTRAL")
    if rts_state == "LIQUIDATION_WARNING":
        return False
    return True


def evaluate_phase1_veto(card: dict) -> bool:
    """Phase 1: Decay + Divergent Hard Veto Gate."""
    review = card.get("offensive_review", {})
    speed = review.get("speed_phase")
    cvd = review.get("cvd_slope_state")
    if speed == "DECAY" and cvd == "DIVERGENT":
        return True # True means it IS a toxic trap
    return False


def evaluate_anti_delta_inversion(card: dict) -> tuple[str, float]:
    """Anti-Delta / Tempo Role Reversal Engine."""
    review = card.get("offensive_review", {})
    anti_delta_score = review.get("anti_delta_score", 50)
    speed = review.get("speed_phase")
    cvd = review.get("cvd_slope_state")
    reclaim = review.get("reclaim_confirmed")
    delta_state = review.get("delta_net_state", "NEUTRAL")
    absorption_flag = review.get("absorption_detected", False)
    
    if anti_delta_score >= 80:
        win = random.random() < 0.42
        return "STAND_DOWN_ANTI_DELTA_FRICTION", (-1.0 if not win else 1.5)

    if delta_state == "BUY" and absorption_flag and speed in ["DECAY", "FLAT"]:
        win = random.random() < 0.56
        return "EXECUTE_ABSORPTION_SELL", (1.8 if win else -1.0)
        
    if delta_state == "SELL" and absorption_flag and reclaim is True:
        win = random.random() < 0.59
        return "EXECUTE_ABSORPTION_BUY", (2.1 if win else -1.0)
        
    return "STAND_DOWN_ABSORPTION_CLEAR", 0.0


def evaluate_sequential_pipeline(card: dict) -> tuple[str, float]:
    review = card.get("offensive_review", {})
    
    # Checkpoint 1: PRISM Structural Availability
    if review.get("prism_state") != "AVAILABLE":
        return "STAND_DOWN", 0.0
        
    # Checkpoint 2: Eight Gates + KNN Confluence Gate
    gates_score = review.get("eight_gates_score", 0)
    knn_confidence = review.get("knn_confidence", 0.0)
    if gates_score < 55 or knn_confidence < 0.70:
        return "STAND_DOWN", 0.0

    # Checkpoint 2.5: Phase 2 RTS Liquidation Gate
    if not evaluate_rts_gate(card):
        return "STAND_DOWN_RTS_LIQUIDATION_RISK", 0.0

    # Checkpoint 2.7: Phase 1 Decay + Divergent Hard Veto Gate
    if evaluate_phase1_veto(card):
        return "STAND_DOWN_TOXIC_DECAY_TRAP", 0.0
        
    # Checkpoint 3A: Anti-Delta Dual Inversion & Absorption Check
    inversion_posture, inversion_r = evaluate_anti_delta_inversion(card)
    if "EXECUTE" in inversion_posture or "STAND_DOWN_ANTI_DELTA" in inversion_posture:
        return inversion_posture, inversion_r
        
    # Checkpoint 3B: Core Momentum & Unicorn Clusters
    speed = review.get("speed_phase")
    cvd = review.get("cvd_slope_state")
    reclaim = review.get("reclaim_confirmed")
    
    is_cluster_a = (speed == "EXPANDING" and reclaim is False and cvd == "EXPANDING")
    is_cluster_b = (speed == "REACCELERATION" and reclaim is True and cvd == "EXPANDING")
    is_unicorn_c = (speed == "REACCELERATION" and reclaim is True and cvd == "DIVERGENT") # Our 61.6% Win Rate Unicorn
    
    if is_unicorn_c:
        win = random.random() < 0.6163
        return "EXECUTE_UNICORN_REACCEL_DIVERGENT", (3.37 if win else -1.0)
    elif is_cluster_a or is_cluster_b:
        win = random.random() < (0.5876 if is_cluster_a else 0.5357)
        r_return = 2.0 if win else -1.0
        return "EXECUTE_MOMENTUM", r_return
        
    return "OBSERVE", 0.0


def run_sequential_simulation():
    analyzer = QuantSetupAnalyzer(
        min_sample_size=30, min_ev_r=0.30, min_win_rate_pct=50.0
    )

    speed_phases = ["REACCELERATION", "EXPANDING", "DECAY"]
    cvd_slopes = ["EXPANDING", "FLAT", "DIVERGENT"]
    reclaim_states = [True, False]
    prism_states = ["AVAILABLE", "LOCKED", "SYNCING"]
    delta_states = ["BUY", "SELL", "NEUTRAL"]
    rts_states = ["ALIGNED", "NEUTRAL", "LIQUIDATION_WARNING"]

    print("Running 25,000 snapshots with Phase 1 Veto, Phase 2 RTS, and Unicorn Clustering...")

    for _ in range(25000):
        prism_state = random.choices(prism_states, weights=[0.90, 0.07, 0.03])[0]
        speed_phase = random.choices(speed_phases, weights=[0.40, 0.40, 0.20])[0]
        cvd_slope_state = random.choices(cvd_slopes, weights=[0.50, 0.30, 0.20])[0]
        delta_net_state = random.choices(delta_states, weights=[0.40, 0.40, 0.20])[0]
        absorption_detected = random.choices([True, False], weights=[0.35, 0.65])[0]
        rts_state = random.choices(rts_states, weights=[0.65, 0.25, 0.10])[0]
        anti_delta_score = random.randint(35, 95)

        card = {
            "pair": f"PAIR_{random.randint(1, 49)}/USD",
            "offensive_review": {
                "prism_state": prism_state,
                "speed_phase": speed_phase,
                "reclaim_confirmed": random.choice(reclaim_states),
                "cvd_slope_state": cvd_slope_state,
                "eight_gates_score": random.randint(55, 95),
                "knn_confidence": random.uniform(0.70, 0.95),
                "delta_net_state": delta_net_state,
                "absorption_detected": absorption_detected,
                "rts_state": rts_state,
                "anti_delta_score": anti_delta_score,
            },
        }

        posture, r_return = evaluate_sequential_pipeline(card)
        card["offensive_review"]["offensive_posture"] = posture

        if "EXECUTE" in posture:
            analyzer.record_snapshot_outcome(card, r_return)

    report = analyzer.generate_expectancy_report()

    print("\n" + "=" * 80)
    print("        UPDATED QUANT EXPECTANCY REPORT — FULL DEFENSE SUITE        ")
    print("=" * 80)

    for setup, metrics in report.items():
        print(f"\nSetup Cluster: {setup}")
        print(f"  Sample Size (N)     : {metrics['sample_size']}")
        print(f"  Win Rate            : {metrics['win_rate_pct']}%")
        print(f"  Profit Factor       : {metrics['profit_factor']}")
        print(f"  Expected Value (EV) : {metrics['expected_value_r']} R")
        print(f"  Confidence Status   : {metrics['confidence_status']}")
        print(f"  Final Posture       : {metrics['recommended_posture']}")

    json_path = "full_defense_quant_report.json"
    csv_path = "full_defense_quant_report.csv"

    analyzer.export_report_to_json(json_path)
    analyzer.export_report_to_csv(csv_path)

    print("\n" + "-" * 80)
    print(f"Report saved to JSON: {os.path.abspath(json_path)}")
    print(f"Report saved to CSV:  {os.path.abspath(csv_path)}")
    print("-" * 80)


if __name__ == "__main__":
    run_sequential_simulation()
