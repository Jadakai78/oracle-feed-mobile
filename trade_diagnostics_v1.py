from __future__ import annotations

from typing import Any, Dict, Optional


def _n(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify(outcome: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic post-outcome diagnostic tag.
    It does not claim causality; it labels the next engineering question.
    """
    fill_status = str(outcome.get("fill_status") or "").upper()
    exit_status = str(outcome.get("exit_status") or "").upper()
    reason = str(outcome.get("reason") or "")
    gross_r = _n(outcome.get("gross_r"))
    mfe_r = _n(outcome.get("mfe_r"))
    mae_r = _n(outcome.get("mae_r"))

    if fill_status == "UNFILLED":
        return {
            "failure_mode": "ENTRY_NOT_FILLED",
            "review_question": "Was the entry zone too selective or did price run without a valid retest?",
        }

    if exit_status == "AMBIGUOUS" or "ambiguous" in reason.lower():
        return {
            "failure_mode": "OHLC_AMBIGUOUS",
            "review_question": "Did both target and invalidation trade in one candle?",
        }

    if exit_status == "TARGET" or gross_r is not None and gross_r > 0:
        return {
            "failure_mode": "TARGET_REACHED",
            "review_question": "Keep measuring this family and entry-policy combination.",
        }

    if exit_status == "INVALIDATION" or gross_r == -1:
        if mfe_r is None or mfe_r < 0.25:
            return {
                "failure_mode": "TRIGGER_OR_LOCATION_FAILURE",
                "review_question": "Was the setup at the wrong level, or was the trigger not genuine?",
            }
        if mfe_r >= 1.0:
            return {
                "failure_mode": "ENTRY_OR_STOP_PLACEMENT_FAILURE",
                "review_question": "Was the fill late, or was invalidation inside normal adverse movement?",
            }
        return {
            "failure_mode": "ENTRY_OR_TRIGGER_WEAKNESS",
            "review_question": "Did price show enough favorable movement before invalidation?",
        }

    if exit_status == "TIMEOUT":
        if mfe_r is not None and mfe_r >= 1.5:
            return {
                "failure_mode": "TARGET_UNREALISTIC_OR_EXIT_POLICY",
                "review_question": "Did price offer meaningful profit but fail to reach the planned objective?",
            }
        return {
            "failure_mode": "TIMEOUT_OR_TARGET_DISTANCE",
            "review_question": "Was the objective too distant, or did the setup lack follow-through?",
        }

    return {
        "failure_mode": "UNCLASSIFIED",
        "review_question": "Inspect raw fill, MFE, MAE, and OHLC path.",
    }
