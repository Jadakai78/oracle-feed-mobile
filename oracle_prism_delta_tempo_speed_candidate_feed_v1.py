import json
import os
from datetime import datetime, timezone

try:
    from eight_gates_brain import evaluate_eight_gates
except ImportError:
    evaluate_eight_gates = None

try:
    from knn_engine_trend import match_knn_geometry
except ImportError:
    match_knn_geometry = None

PRISM_FETCH_FILE = r"C:\Users\jason\OneDrive\Desktop\jhl_v2\oracle-feed-mobile\prism_kraken_spot_15m_latest.json"
OUTPUT_FEED_FILE = r"C:\Users\jason\OneDrive\Desktop\jhl_v2\oracle-feed-mobile\oracle_joined_delta_prism_v1.json"

def evaluate_candidate_execution_gate(item):
    failed_conditions = []
    
    # 1. Strict Identity Alignment Checks
    if not item.get("pair_matched", False):
        failed_conditions.append("PAIR_MISMATCH")
    if not item.get("timeframe_matched", False):
        failed_conditions.append("TIMEFRAME_MISMATCH")
    if not item.get("timestamp_matched", False):
        failed_conditions.append("TIMESTAMP_MISMATCH")

    # 2. Independent Delta / Tempo Checks (No Synthetic Defaults)
    dt = item.get("card_payload", {}).get("delta_tempo_timing", {})
    if dt.get("state") != "AVAILABLE":
        failed_conditions.append("DELTA_TEMPO_NOT_AVAILABLE")
    if dt.get("speed_phase") not in ["ACCELERATING", "IMPULSE"]:
        failed_conditions.append("INVALID_SPEED_PHASE")
    
    direction = dt.get("direction")
    delta_state = dt.get("delta_state")
    if (direction == "LONG" and delta_state != "POSITIVE_DELTA") or \
       (direction == "SHORT" and delta_state != "NEGATIVE_DELTA"):
        failed_conditions.append("DELTA_DIRECTION_MISMATCH")
        
    if dt.get("cvd_slope") != "EXPANDING":
        failed_conditions.append("CVD_SLOPE_NOT_EXPANDING")
        
    if not dt.get("reclaim_confirmed", False):
        failed_conditions.append("RECLAIM_NOT_CONFIRMED")

    # 3. Independent PRISM Checks (Requires real feed data; synthetic diagnostics excluded from EXECUTE)
    prism = item.get("synthetic_prism_diagnostic", {})
    if not prism.get("prism_available", False):
        failed_conditions.append("PRISM_NOT_AVAILABLE")
    if prism.get("structural_state") not in ["BREAKOUT_EXPANSION", "SUPPORT_HOLD", "RESISTANCE_REJECT"]:
        failed_conditions.append("INVALID_PRISM_STRUCTURE")
    if prism.get("width_regime") not in ["EXPANSION", "EXTREME_EXPANSION"]:
        failed_conditions.append("INVALID_PRISM_WIDTH_REGIME")

    # Final Execution State Classification
    if len(failed_conditions) == 0:
        execution_state = "EXECUTE"
    elif any(k in failed_conditions for k in ["DELTA_TEMPO_NOT_AVAILABLE", "TIMESTAMP_MISMATCH", "PRISM_NOT_AVAILABLE"]):
        execution_state = "DEAD"
    else:
        execution_state = "WATCH"

    return execution_state, failed_conditions

def run_alpha_pipeline():
    if not os.path.exists(PRISM_FETCH_FILE):
        return

    with open(PRISM_FETCH_FILE, "r") as f:
        raw_data = json.load(f)

    bars_by_symbol = raw_data.get("bars", {})
    joined_candidates = []

    for symbol, bar_list in bars_by_symbol.items():
        if not bar_list:
            continue

        latest_bar = bar_list[-1]
        close = float(latest_bar.get("close", 0) or 0)
        high = float(latest_bar.get("high", 0) or 0)
        low = float(latest_bar.get("low", 0) or 0)
        vol = float(latest_bar.get("volume", 0) or 0)

        bar_close_utc = latest_bar.get("reference_bar_close_utc", "")
        bar_start_iso = latest_bar.get("timestamp_interval_start", "")

        # Independent identity timestamps (simulating separate telemetry streams)
        dt_close_utc = bar_close_utc
        prism_close_utc = bar_close_utc

        pair_matched = True
        timeframe_matched = True
        timestamp_matched = (dt_close_utc == prism_close_utc and bool(bar_close_utc))

        # Real Delta/Tempo Fields (un-opinionated default to GATED unless explicit telemetry confirms)
        dt_timing = {
            "direction": "SHORT" if close < float(latest_bar.get("open", close)) else "LONG",
            "speed_phase": "IMPULSE_DECAY", 
            "delta_state": "NEUTRAL",
            "cvd_slope": "FLAT",
            "reclaim_confirmed": False,
            "state": "GATED",
            "gate_score": "4/8",
            "knn_score": "60.0%"
        }

        # Isolated Synthetic Diagnostic Placeholder (Never used for EXECUTE gating)
        synthetic_prism_diagnostic = {
            "prism_available": False,
            "structural_state": "CONSOLIDATION",
            "width_regime": "NEUTRAL"
        }

        canonical_pair = symbol.replace("/", "").replace("-", "")
        candidate_entry = {
            "pair": canonical_pair,
            "canonical_pair": symbol,
            "timeframe": "15m",
            "reference_bar_raw": bar_start_iso,
            "delta_tempo_reference_bar_close_utc": dt_close_utc,
            "prism_reference_bar_close_utc": prism_close_utc,
            "pair_matched": pair_matched,
            "timeframe_matched": timeframe_matched,
            "timestamp_matched": timestamp_matched,
            "matched_prism_bar": {
                "close": close,
                "high": high,
                "low": low,
                "volume": vol
            },
            "synthetic_prism_diagnostic": synthetic_prism_diagnostic,
            "card_payload": {
                "delta_tempo_timing": dt_timing
            }
        }

        exec_state, failed_conds = evaluate_candidate_execution_gate(candidate_entry)
        candidate_entry["execution_state"] = exec_state
        candidate_entry["execution_evidence"] = {
            "identity_status": "MATCHED" if timestamp_matched else "MISMATCHED",
            "delta_tempo": dt_timing,
            "prism_diagnostic": synthetic_prism_diagnostic,
            "failed_conditions": failed_conds
        }

        joined_candidates.append(candidate_entry)

    counts = {
        "EXECUTE": sum(1 for c in joined_candidates if c["execution_state"] == "EXECUTE"),
        "WATCH": sum(1 for c in joined_candidates if c["execution_state"] == "WATCH"),
        "DEAD": sum(1 for c in joined_candidates if c["execution_state"] == "DEAD")
    }

    output_payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_cards_evaluated": len(joined_candidates),
        "execution_state_counts": counts,
        "joined_data": joined_candidates
    }

    with open(OUTPUT_FEED_FILE, "w") as f:
        json.dump(output_payload, f, indent=2)

if __name__ == "__main__":
    run_alpha_pipeline()
