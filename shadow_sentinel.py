from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ShadowSentinelDecision:
    verdict: str
    score: int
    reasons: List[str]
    evidence: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": "shadow",
            "verdict": self.verdict,
            "score": self.score,
            "reasons": list(self.reasons),
            "evidence": dict(self.evidence),
        }


class ShadowSentinel:
    """
    Observation-only context assessor.

    This module has no authority to change Oracle action state, entries,
    stop losses, targets, signal routing, or any outward-facing payload.
    """

    def evaluate(
        self,
        *,
        metadata: Dict[str, Any],
        action_state: str,
        side: str,
        execution: Optional[Dict[str, Any]] = None,
    ) -> ShadowSentinelDecision:
        execution = execution or {}
        reasons: List[str] = []
        score = 0

        live_quote_valid = bool(metadata.get("live_quote_valid"))
        ohlc_ready = bool(metadata.get("ohlc_ready"))

        relative_volume = self._as_float(
            metadata.get("relative_volume_25")
        )
        volume_state = str(
            metadata.get("volume_state_15m") or "unknown"
        ).lower()
        impulse_state = str(
            metadata.get("impulse_state") or "quiet"
        ).lower()
        momentum_bias = str(
            metadata.get("momentum_bias") or "neutral"
        ).lower()
        trap_risk = str(
            metadata.get("trap_risk") or "normal"
        ).lower()
        volatility_state = str(
            metadata.get("volatility_state") or "normal"
        ).lower()

        if not live_quote_valid:
            score -= 100
            reasons.append("invalid_live_quote")

        if not ohlc_ready:
            score -= 35
            reasons.append("ohlc_context_unavailable")

        if relative_volume is not None:
            if relative_volume < 0.35:
                score -= 35
                reasons.append("very_thin_relative_volume")
            elif relative_volume < 0.65:
                score -= 15
                reasons.append("thin_relative_volume")
            elif relative_volume >= 1.25:
                score += 10
                reasons.append("above_average_relative_volume")

        if volume_state in {"very_low", "low", "thin"}:
            score -= 15
            reasons.append("weak_volume_state:" + volume_state)
        elif volume_state in {"high", "very_high"}:
            score += 8
            reasons.append("strong_volume_state:" + volume_state)

        if trap_risk == "high":
            score -= 35
            reasons.append("high_trap_risk")
        elif trap_risk == "elevated":
            score -= 15
            reasons.append("elevated_trap_risk")

        adverse_impulses = {
            "rotation_chop",
            "failed_impulse_reclaim",
            "acceleration_exhausted",
        }

        if impulse_state in adverse_impulses:
            score -= 20
            reasons.append("adverse_impulse:" + impulse_state)
        elif side == "BUY" and impulse_state == "impulse_up":
            score += 10
            reasons.append("buy_impulse_alignment")
        elif side == "SELL" and impulse_state == "impulse_down":
            score += 10
            reasons.append("sell_impulse_alignment")

        if momentum_bias == "fade":
            score -= 15
            reasons.append("momentum_fade")
        elif momentum_bias == "trend":
            score += 8
            reasons.append("momentum_trend_alignment")

        if volatility_state == "explosive":
            score -= 8
            reasons.append("explosive_volatility")

        if not reasons:
            reasons.append("no_shadow_objection")

        if score <= -50:
            verdict = "shadow_veto"
        elif score <= -15:
            verdict = "shadow_watch"
        elif action_state == "actionable" and score >= 10:
            verdict = "shadow_claim"
        else:
            verdict = "shadow_neutral"

        evidence = {
            "action_state": action_state,
            "side": side,
            "live_quote_valid": live_quote_valid,
            "ohlc_ready": ohlc_ready,
            "relative_volume_25": relative_volume,
            "volume_state_15m": volume_state,
            "impulse_state": impulse_state,
            "momentum_bias": momentum_bias,
            "trap_risk": trap_risk,
            "volatility_state": volatility_state,
            "execution_management_state": execution.get(
                "management_state"
            ),
        }

        return ShadowSentinelDecision(
            verdict=verdict,
            score=score,
            reasons=reasons,
            evidence=evidence,
        )

    @staticmethod
    def _as_float(value: Any) -> Optional[float]:
        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def summarize_shadow_decisions(decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
    verdict_counts = {
        "shadow_claim": 0,
        "shadow_watch": 0,
        "shadow_veto": 0,
        "shadow_neutral": 0,
        "unavailable": 0,
    }

    for decision in decisions:
        verdict = str(decision.get("verdict") or "unavailable")

        if verdict not in verdict_counts:
            verdict = "unavailable"

        verdict_counts[verdict] += 1

    return {
        "mode": "shadow",
        "enabled": True,
        "enforcement": "none",
        "rows_evaluated": len(decisions),
        "claim_count": verdict_counts["shadow_claim"],
        "watch_count": verdict_counts["shadow_watch"],
        "veto_count": verdict_counts["shadow_veto"],
        "neutral_count": verdict_counts["shadow_neutral"],
        "unavailable_count": verdict_counts["unavailable"],
        "verdict_counts": verdict_counts,
    }