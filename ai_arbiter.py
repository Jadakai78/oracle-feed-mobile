"""
Contextual AI Arbiter Module for JHL Confluence Engine.
Sits on top of the deterministic feature pipeline (PRISM, Speed Phase, Sentinel)
to evaluate macro context, session anomalies (e.g., Saturday decay), and nuanced
setup quality before making a final execution verdict.
"""

from __future__ import annotations
import json
import logging
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class AIArbiter:
    """
    Contextual AI Arbiter Module.
    Evaluates candidate trade cards against structural features and macro context.
    """
    def __init__(self, mode: str = "SHADOW"):
        self.mode = mode.upper()  # SHADOW or ACTIVE
        logging.info(f"AI Arbiter initialized in {self.mode} mode.")

    def evaluate_candidate(self, candidate_card: Dict[str, Any], market_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Evaluates a candidate trade card against structural features and macro context.
        Returns an AI decision payload: { decision, confidence, reasoning, override_rule }
        """
        pair = candidate_card.get("pair", "UNKNOWN")
        speed_phase = candidate_card.get("speed_phase", "NONE")
        cvd_slope = candidate_card.get("cvd_slope", "FLAT")
        anti_delta = candidate_card.get("anti_delta_score", 50)
        hostility_score = candidate_card.get("hostility_score", 0.0)
        rule_status = candidate_card.get("status", "WAIT")
        
        reasoning_steps = []
        confidence = 0.85
        decision = "PASS"
        override_rule = False

        # 1. Macro Regime Check (e.g., Weekend / Low Liquidity Chop)
        is_weekend_session = market_context and market_context.get("is_weekend", True)
        if is_weekend_session:
            reasoning_steps.append("Weekend macro regime detected (higher noise/decay risk).")
            if speed_phase != "REACCELERATION":
                confidence -= 0.25
                reasoning_steps.append(f"Speed phase '{speed_phase}' insufficient for weekend deployment. Recommendation: ABSTAIN.")
                return {
                    "pair": pair,
                    "decision": "ABSTAIN",
                    "confidence": round(confidence, 2),
                    "reasoning": " | ".join(reasoning_steps),
                    "override_rule": False
                }

        # 2. Sentinel & Hostility Check
        if hostility_score >= 0.80 or "VETOED" in rule_status:
            reasoning_steps.append(f"Rule engine / Sentinel flagged hostility score {hostility_score}. Upholding veto.")
            return {
                "pair": pair,
                "decision": "ABSTAIN",
                "confidence": 0.95,
                "reasoning": " | ".join(reasoning_steps),
                "override_rule": False
            }

        # 3. Unicorn Qualification Check
        is_unicorn = (speed_phase == "REACCELERATION" and cvd_slope == "DIVERGENT" and anti_delta < 60)
        if is_unicorn:
            decision = "TAKE"
            confidence = 0.92
            reasoning_steps.append("Unicorn signature verified: Clean Reacceleration + Divergent CVD + Low Anti-Delta.")
        elif speed_phase == "CONTROLLED_PULLBACK" and anti_delta < 50:
            decision = "TAKE"
            confidence = 0.78
            reasoning_steps.append("Controlled pullback setup accepted under moderate risk parameters.")
        else:
            decision = "PASS"
            confidence = 0.70
            reasoning_steps.append(f"Setup structure '{speed_phase}' with CVD '{cvd_slope}' does not meet high-conviction threshold.")

        return {
            "pair": pair,
            "decision": decision,
            "confidence": round(confidence, 2),
            "reasoning": " | ".join(reasoning_steps),
            "override_rule": override_rule
        }
