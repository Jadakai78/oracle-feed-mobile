from __future__ import annotations

from typing import Any, Dict

MAX_EXTENSION_R = 0.25


def _number(value: Any):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _append_reason(candidate: Dict[str, Any], reason: str) -> None:
    reasons = [item for item in str(candidate.get("reason") or "").split(";") if item]
    if reason not in reasons:
        reasons.append(reason)
    candidate["reason"] = ";".join(reasons)


def apply(candidate: Dict[str, Any], market_noise: Dict[str, Any], structure: Dict[str, Any]) -> Dict[str, Any]:
    candidate = dict(candidate or {})
    noise = market_noise or {}
    structure = structure or {}
    side = str(candidate.get("delta_direction") or "NONE").upper()
    claims = candidate.get("setup_claims") or []
    sources = {str(item.get("source") if isinstance(item, dict) else item).upper() for item in claims}

    noise_available = bool(noise.get("available"))
    noise_regime = str(noise.get("regime") or "UNAVAILABLE").upper()
    zone = str(structure.get("zone") or "UNKNOWN").upper()
    location = "NEUTRAL"
    if side == "LONG" and zone == "PREMIUM":
        location = "EXTENDED"
    elif side == "SHORT" and zone == "DISCOUNT":
        location = "EXTENDED"
    elif (side == "LONG" and zone == "DISCOUNT") or (side == "SHORT" and zone == "PREMIUM"):
        location = "FAVORABLE"

    entry, stop, current = _number(candidate.get("entry")), _number(candidate.get("sl")), _number(candidate.get("close"))
    extension_r = None
    if entry is not None and stop is not None and current is not None and abs(entry - stop) > 0:
        extension_r = ((current - entry) if side == "LONG" else (entry - current)) / abs(entry - stop)

    candidate["noise_available"] = noise_available
    candidate["noise_regime"] = noise_regime
    candidate["noise_gate"] = "PASS" if noise_available else "NOISE_UNAVAILABLE_VETO"
    candidate["location_state"] = location
    candidate["location_gate"] = "LOCATION_EXTENDED_CAUTION" if location == "EXTENDED" else "PASS"
    candidate["entry_extension_r"] = extension_r
    candidate["max_entry_extension_r"] = MAX_EXTENSION_R

    vetoes = []
    if not noise_available:
        vetoes.append("NOISE_UNAVAILABLE_VETO")
    if sources == {"DRIVE"}:
        vetoes.append("DRIVE_ALONE_VETO")
    if extension_r is not None and extension_r > MAX_EXTENSION_R:
        vetoes.append("LATE_AFTER_TRIGGER")
    for veto in vetoes:
        _append_reason(candidate, veto)
    if vetoes:
        candidate["state"] = "WAITING"
    return candidate
