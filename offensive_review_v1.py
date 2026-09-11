"""
Offensive Review Module v1
--------------------------
Calculates high-conviction candidate postures based on PRISM state,
Oracle structure, Speed/Tempo phases, and Delta/CVD slope alignment.

Design Rules:
- Enforces strict read-only, non-executable safety flags.
- Purely descriptive; contains no entry signals or order authority.
- Enforces strict statistical gates for PRIORITY_REVIEW posture.
"""

from typing import Any, Dict, List, Optional, TypedDict

# Pre-allocated immutable sets for high-throughput execution
EXPECTED_CONTRACT_KEYS = frozenset(
    {
        "state",
        "pair",
        "prism_state",
        "structural_location",
        "structure_state",
        "flow_state",
        "tempo_state",
        "speed_phase",
        "delta_cvd_state",
        "cvd_slope_state",
        "reclaim_confirmed",
        "freshness_state",
        "offensive_posture",
        "summary",
        "manual_review_only",
        "does_not_authorize_trade",
        "does_not_simulate_order",
    }
)

PROHIBITED_KEYS = frozenset(
    {
        "directional_context",
        "direction",
        "review_state",
        "context_claim",
        "context_score",
        "tier",
        "correlation_group",
        "correlation_role",
        "micro_watchlist",
        "micro_state",
        "m5_speed_display",
        "routes_ranked",
        "risk",
        "entry_authority",
        "trade_authority",
        "raw_source",
        "score",
        "rank",
        "route",
        "signal",
        "side",
        "entry",
        "stop",
        "target",
        "order",
        "position",
        "buy",
        "sell",
        "long",
        "short",
        "recommendation",
        "confidence",
        "trade_setup",
    }
)


class OffensiveReviewContract(TypedDict):
    state: str
    pair: str
    prism_state: str
    structural_location: str
    structure_state: str
    flow_state: str
    tempo_state: str
    speed_phase: str
    delta_cvd_state: str
    cvd_slope_state: str
    reclaim_confirmed: bool
    freshness_state: str
    offensive_posture: str
    summary: str
    manual_review_only: bool
    does_not_authorize_trade: bool
    does_not_simulate_order: bool


def evaluate_delta_cvd(
    delta_value: Optional[float],
    cvd_series: Optional[List[float]],
    directional_bias: str = "LONG",
) -> Dict[str, Any]:
    """
    Evaluates immediate Delta alignment and multi-bar CVD slope trajectory.
    """
    if delta_value is None or not cvd_series or len(cvd_series) < 3:
        return {
            "state": "UNAVAILABLE",
            "delta_aligned": False,
            "cvd_slope_state": "FLAT",
            "confirmed": False,
            "reason": "INSUFFICIENT_DATA",
        }

    # Directional Delta Check
    if directional_bias == "LONG":
        delta_aligned = delta_value > 0
    else:
        delta_aligned = delta_value < 0

    # Endpoint Linear Trajectory over recent bars
    cvd_recent_change = cvd_series[-1] - cvd_series[-3]

    if cvd_recent_change > 0 and delta_aligned:
        slope_state = "EXPANDING"
    elif cvd_recent_change < 0 and not delta_aligned:
        slope_state = "DIVERGENT"
    else:
        slope_state = "NEUTRAL"

    is_confirmed = delta_aligned and (slope_state == "EXPANDING")

    return {
        "state": "AVAILABLE",
        "delta_value": delta_value,
        "delta_aligned": delta_aligned,
        "cvd_slope_state": slope_state,
        "confirmed": is_confirmed,
        "reason": "OK" if is_confirmed else "DISCORDANT_FLOW",
    }


def build_offensive_review(
    card: Dict[str, Any],
    now_utc_str: str,
    delta_cvd_input: Optional[Dict[str, Any]] = None,
    expectancy_report: Optional[Dict[str, Dict[str, Any]]] = None,
) -> OffensiveReviewContract:
    """
    Builds the 17-key Offensive Review contract for a given candidate card.
    Optionally cross-references a live Expectancy Report to enforce statistical posture gates.
    """
    pair = card.get("pair", "UNKNOWN")

    # Oracle Structural Data Extraction
    oracle_ctx = card.get("oracle_context", {})
    structural_loc = oracle_ctx.get("location", "UNKNOWN")
    structure_st = oracle_ctx.get("structure", "UNKNOWN")
    flow_st = oracle_ctx.get("flow", "UNKNOWN")
    tempo_st = oracle_ctx.get("tempo", "UNKNOWN")

    # PRISM State
    prism_data = card.get("prism", {})
    prism_st = prism_data.get("state", "UNAVAILABLE")

    # Delta / Tempo Timing & Speed Phase
    timing_data = card.get("delta_tempo_timing", {})
    speed_phase = timing_data.get("lifecycle_state", "UNKNOWN")
    reclaim_conf = bool(timing_data.get("reclaim_confirmed", False))

    # Delta CVD Flow Evaluation
    if delta_cvd_input is None:
        delta_cvd_input = card.get("delta_cvd", {})

    delta_val = delta_cvd_input.get("delta_value")
    cvd_series = delta_cvd_input.get("cvd_series")
    directional_bias = timing_data.get("direction", "LONG")

    cvd_eval = evaluate_delta_cvd(
        delta_value=delta_val,
        cvd_series=cvd_series,
        directional_bias=directional_bias,
    )

    delta_cvd_st = cvd_eval["state"]
    cvd_slope_st = cvd_eval["cvd_slope_state"]

    # Structural Criteria
    is_prism_valid = prism_st == "AVAILABLE"
    is_speed_aligned = speed_phase in {"REACCELERATION", "EXPANDING"}
    is_flow_confirmed = cvd_eval["confirmed"] and (flow_st == "CONFIRMS")

    # Construct Quant Feature Key
    feature_key = f"PRISM:{prism_st}|SPEED:{speed_phase}|RECLAIM:{reclaim_conf}|CVD_SLOPE:{cvd_slope_st}"

    # Evaluate Posture with Quant Overrides if Available
    if expectancy_report and feature_key in expectancy_report:
        quant_metrics = expectancy_report[feature_key]
        posture = quant_metrics["recommended_posture"]
        summary = (
            f"{pair} evaluated via Quant Engine: Status={quant_metrics['confidence_status']}, "
            f"EV={quant_metrics['expected_value_r']}R, WinRate={quant_metrics['win_rate_pct']}%."
        )
    elif is_prism_valid and is_speed_aligned and reclaim_conf and is_flow_confirmed:
        posture = "PRIORITY_REVIEW"
        summary = f"{pair} shows aligned structural location and expanding CVD slope."
    elif is_prism_valid and is_speed_aligned:
        posture = "OBSERVE"
        summary = f"{pair} speed is expanding but awaiting full Delta/CVD slope confirmation."
    else:
        posture = "STAND_DOWN"
        summary = f"{pair} conditions do not meet offensive review criteria."

    freshness_st = "CURRENT" if now_utc_str else "UNKNOWN"

    review: OffensiveReviewContract = {
        "state": "AVAILABLE",
        "pair": pair,
        "prism_state": prism_st,
        "structural_location": structural_loc,
        "structure_state": structure_st,
        "flow_state": flow_st,
        "tempo_state": tempo_st,
        "speed_phase": speed_phase,
        "delta_cvd_state": delta_cvd_st,
        "cvd_slope_state": cvd_slope_st,
        "reclaim_confirmed": reclaim_conf,
        "freshness_state": freshness_st,
        "offensive_posture": posture,
        "summary": summary,
        "manual_review_only": True,
        "does_not_authorize_trade": True,
        "does_not_simulate_order": True,
    }

    return review
