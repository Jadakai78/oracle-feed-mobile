"""
market_state_engine.py — JHL Market State + Transition Engine

Reads shared evidence already produced by the scanner. It does not create
trades, alter conviction, or replace specialists.

Its job:
1. State what the market is demonstrably doing now.
2. State who has control, if anyone.
3. State the most likely next transition.
4. State what evidence promotes or invalidates that read.
5. Permit or block specialist tactic families.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _text(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip()


def _upper(value: Any, default: str = "") -> str:
    return _text(value, default).upper()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _watch(signal: Dict[str, Any]) -> bool:
    return _text(signal.get("action_state"), "idle").lower() == "watch"


def _bias(signal: Dict[str, Any]) -> str:
    return _upper(signal.get("bias"), "NONE")


def _tempo(signal: Dict[str, Any]) -> str:
    indicators = signal.get("indicators") or {}
    return _upper(
        indicators.get("tempo")
        or signal.get("tempo")
        or indicators.get("h1_tempo"),
        "DEAD",
    )


def _claim_strength(signal: Dict[str, Any]) -> float:
    if not _watch(signal):
        return 0.0
    return _number(signal.get("conviction"), 0.0)


def _active_tempo(signal: Dict[str, Any]) -> bool:
    return _tempo(signal) in {"EARLY", "BUILDING", "LIVE"}


def _pressure_read(volume_flow: Dict[str, Any]) -> str:
    """
    Returns BUY, SELL, BALANCED, or UNAVAILABLE.
    Pressure is unavailable unless the volume-flow module explicitly says ready.
    """
    if not bool(volume_flow.get("ready")):
        return "UNAVAILABLE"

    delta = _number(volume_flow.get("delta_norm"))
    slope = _number(volume_flow.get("cvd_slope"))

    if delta >= 0.20 and slope > 0:
        return "BUY"

    if delta <= -0.20 and slope < 0:
        return "SELL"

    return "BALANCED"


def _state_payload(
    *,
    state: str,
    control: str,
    mechanism: str,
    transition_primary: str,
    transition_alternative: str,
    confidence: float,
    evidence: List[str],
    promotion_required: List[str],
    invalidation: List[str],
    allowed_tactics: List[str],
    blocked_tactics: List[str],
) -> Dict[str, Any]:
    return {
        "state": state,
        "control": control,
        "mechanism": mechanism,
        "transition_primary": transition_primary,
        "transition_alternative": transition_alternative,
        "confidence": round(max(0.0, min(confidence, 1.0)), 2),
        "evidence": evidence,
        "promotion_required": promotion_required,
        "invalidation": invalidation,
        "allowed_tactics": allowed_tactics,
        "blocked_tactics": blocked_tactics,
    }


def evaluate(
    structure: Dict[str, Any],
    volume_flow: Dict[str, Any],
    signals: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Infer the current market state.

    Parameters
    ----------
    structure:
        Shared output from structure_bias.evaluate(...).

    volume_flow:
        Shared pressure object from gimba_volume_flow.volume_specialist(...).

    signals:
        Dict with keys:
        - gimba_volatile
        - gimba_range
        - rts_liq
        - gimba_trend

    Returns
    -------
    A market_state dict. This is context and permission only:
    it does not create, modify, or execute a trade.
    """
    structure = structure or {}
    volume_flow = volume_flow or {}
    signals = signals or {}

    volatile = signals.get("gimba_volatile") or {}
    range_bot = signals.get("gimba_range") or {}
    rts = signals.get("rts_liq") or {}
    trend_bot = signals.get("gimba_trend") or {}

    condition = _upper(structure.get("market_condition"), "UNKNOWN")
    trend = _upper(structure.get("trend"), "RANGING")
    zone = _upper(structure.get("zone"), "NEUTRAL")
    market_tempo = _upper(
        structure.get("market_tempo")
        or structure.get("h1_tempo"),
        "DEAD",
    )
    bos = bool(structure.get("bos"))

    tempo_context = structure.get("tempo_context") or {}
    velocity = _number(tempo_context.get("velocity"))
    acceleration = _number(tempo_context.get("acceleration"))
    v_direction = _upper(tempo_context.get("v_direction"), "FLAT")
    a_direction = _upper(tempo_context.get("a_direction"), "FLAT")

    pressure = _pressure_read(volume_flow)

    vol_strength = _claim_strength(volatile)
    range_strength = _claim_strength(range_bot)
    rts_strength = _claim_strength(rts)
    trend_strength = _claim_strength(trend_bot)

    vol_bias = _bias(volatile)
    range_bias = _bias(range_bot)
    rts_bias = _bias(rts)
    trend_bias = _bias(trend_bot)

    volatile_active = (
        vol_strength >= 0.60
        and _active_tempo(volatile)
        and vol_bias in {"LONG", "SHORT"}
    )

    trend_active = (
        trend_strength >= 0.60
        and _active_tempo(trend_bot)
        and trend_bias in {"LONG", "SHORT"}
    )

    range_active = (
        range_strength >= 0.55
        and range_bias in {"LONG", "SHORT"}
    )

    rts_active = (
        rts_strength >= 0.55
        and rts_bias in {"LONG", "SHORT"}
    )

    evidence = [
        f"condition={condition}",
        f"trend={trend}",
        f"zone={zone}",
        f"tempo={market_tempo}",
        f"bos={'yes' if bos else 'no'}",
        f"velocity={velocity:.2f}",
        f"acceleration={acceleration:.2f}",
        f"pressure={pressure}",
    ]

    # ------------------------------------------------------------------
    # 1. Failed auction / reclaim has priority over ordinary trend/range.
    # ------------------------------------------------------------------
    if rts_active and rts_bias == "LONG":
        return _state_payload(
            state="FAILED_DOWN_AUCTION_RECLAIM",
            control="BUYERS_GAINING_CONTROL",
            mechanism="SWEEP_RECLAIM",
            transition_primary="ROTATION_UP_INTO_PRIOR_VALUE",
            transition_alternative="RECLAIM_FAILURE_BACK_TO_DOWNSIDE",
            confidence=max(0.62, rts_strength),
            evidence=evidence + [
                f"RTS={rts.get('setup_type', 'LONG RECLAIM')}",
                "downside auction swept and reclaimed",
            ],
            promotion_required=[
                "completed candle holds above reclaim level",
                "first pullback does not lose reclaim",
                "buy pressure confirms when pressure feed is ready",
            ],
            invalidation=[
                "completed close back below reclaim level",
                "reclaim fails and price accepts below swept area",
            ],
            allowed_tactics=[
                "RTS long after reclaim hold",
                "Gimba Range long only if rotation remains contained",
                "Gimba Trend long only after continuation acceptance",
            ],
            blocked_tactics=[
                "fresh short while reclaim holds",
                "blind fade of the recovery",
            ],
        )

    if rts_active and rts_bias == "SHORT":
        return _state_payload(
            state="FAILED_UP_AUCTION_RECLAIM",
            control="SELLERS_GAINING_CONTROL",
            mechanism="SWEEP_RECLAIM",
            transition_primary="ROTATION_DOWN_INTO_PRIOR_VALUE",
            transition_alternative="RECLAIM_FAILURE_BACK_TO_UPSIDE",
            confidence=max(0.62, rts_strength),
            evidence=evidence + [
                f"RTS={rts.get('setup_type', 'SHORT RECLAIM')}",
                "upside auction swept and reclaimed",
            ],
            promotion_required=[
                "completed candle holds below reclaim level",
                "first pullback does not regain reclaim",
                "sell pressure confirms when pressure feed is ready",
            ],
            invalidation=[
                "completed close back above reclaim level",
                "reclaim fails and price accepts above swept area",
            ],
            allowed_tactics=[
                "RTS short after reclaim hold",
                "Gimba Range short only if rotation remains contained",
                "Gimba Trend short only after continuation acceptance",
            ],
            blocked_tactics=[
                "fresh long while reclaim failure holds",
                "blind fade of the rejection",
            ],
        )

    # ------------------------------------------------------------------
    # 2. Active expansion. Pressure adds confidence but is not invented.
    # ------------------------------------------------------------------
    if volatile_active and vol_bias == "LONG":
        pressure_bonus = 0.10 if pressure == "BUY" else 0.0

        return _state_payload(
            state="EXPANSION_UP",
            control="BUYERS",
            mechanism="ACCEPTANCE_OR_IMPULSE",
            transition_primary="PULLBACK_HOLD_THEN_UPSIDE_CONTINUATION",
            transition_alternative="FAILED_UP_AUCTION_IF_ACCEPTANCE_LOST",
            confidence=min(0.90, vol_strength + pressure_bonus),
            evidence=evidence + [
                f"VOL={volatile.get('setup_type', 'UP EXPANSION')}",
                "volatility specialist detects active upside behavior",
            ],
            promotion_required=[
                "pullback holds above impulse or acceptance shelf",
                "buy pressure confirms when pressure feed is ready",
                "no loss of immediate post-impulse structure",
            ],
            invalidation=[
                "price loses the impulse shelf",
                "completed candle fails back through acceptance",
            ],
            allowed_tactics=[
                "Gimba Volatile long on hold or retest",
                "Gimba Trend long if higher-timeframe alignment remains intact",
            ],
            blocked_tactics=[
                "Gimba Range short fade during active acceptance",
                "fresh countertrend short before failed acceptance",
            ],
        )

    if volatile_active and vol_bias == "SHORT":
        pressure_bonus = 0.10 if pressure == "SELL" else 0.0

        return _state_payload(
            state="EXPANSION_DOWN",
            control="SELLERS",
            mechanism="ACCEPTANCE_OR_IMPULSE",
            transition_primary="PULLBACK_FAILURE_THEN_DOWNSIDE_CONTINUATION",
            transition_alternative="FAILED_DOWN_AUCTION_IF_ACCEPTANCE_LOST",
            confidence=min(0.90, vol_strength + pressure_bonus),
            evidence=evidence + [
                f"VOL={volatile.get('setup_type', 'DOWN EXPANSION')}",
                "volatility specialist detects active downside behavior",
            ],
            promotion_required=[
                "bounce fails below impulse or acceptance shelf",
                "sell pressure confirms when pressure feed is ready",
                "no regain of immediate post-impulse structure",
            ],
            invalidation=[
                "price regains the impulse shelf",
                "completed candle accepts back above failure level",
            ],
            allowed_tactics=[
                "Gimba Volatile short on failure or retest",
                "Gimba Trend short if higher-timeframe alignment remains intact",
            ],
            blocked_tactics=[
                "Gimba Range long fade during active acceptance",
                "fresh countertrend long before failed acceptance",
            ],
        )

    # ------------------------------------------------------------------
    # 3. Trend continuation when volatility expansion is not the owner.
    # ------------------------------------------------------------------
    if trend_active and trend_bias == "LONG":
        return _state_payload(
            state="TREND_PULLBACK_UP",
            control="BUYERS",
            mechanism="PULLBACK_RECLAIM",
            transition_primary="CONTINUATION_TO_NEXT_UPSIDE_OBJECTIVE",
            transition_alternative="TRANSITION_IF_PULLBACK_LEVEL_FAILS",
            confidence=max(0.60, trend_strength),
            evidence=evidence + [
                f"TRD={trend_bot.get('setup_type', 'UP TREND')}",
                "higher-timeframe and lower-timeframe trend tactic align",
            ],
            promotion_required=[
                "pullback holds or reclaims the trend reference",
                "tempo remains active rather than late/dead",
                "pressure confirms when available",
            ],
            invalidation=[
                "trend pullback level fails",
                "lower-timeframe movement loses alignment",
            ],
            allowed_tactics=[
                "Gimba Trend long",
                "Gimba Volatile long only if expansion reappears",
            ],
            blocked_tactics=[
                "range short against active trend continuation",
            ],
        )

    if trend_active and trend_bias == "SHORT":
        return _state_payload(
            state="TREND_PULLBACK_DOWN",
            control="SELLERS",
            mechanism="PULLBACK_FAILURE",
            transition_primary="CONTINUATION_TO_NEXT_DOWNSIDE_OBJECTIVE",
            transition_alternative="TRANSITION_IF_PULLBACK_RECLAIMS",
            confidence=max(0.60, trend_strength),
            evidence=evidence + [
                f"TRD={trend_bot.get('setup_type', 'DOWN TREND')}",
                "higher-timeframe and lower-timeframe trend tactic align",
            ],
            promotion_required=[
                "bounce fails below the trend reference",
                "tempo remains active rather than late/dead",
                "pressure confirms when available",
            ],
            invalidation=[
                "trend failure level is reclaimed",
                "lower-timeframe movement loses alignment",
            ],
            allowed_tactics=[
                "Gimba Trend short",
                "Gimba Volatile short only if expansion reappears",
            ],
            blocked_tactics=[
                "range long against active trend continuation",
            ],
        )

    # ------------------------------------------------------------------
    # 4. Compression: intentionally no directional claim.
    # ------------------------------------------------------------------
    if (
        "COMPRESSION" in condition
        or (
            market_tempo in {"DEAD", "LATE"}
            and abs(velocity) < 0.15
            and not bos
            and not range_active
        )
    ):
        return _state_payload(
            state="COMPRESSION",
            control="NEITHER",
            mechanism="CONTRACTION",
            transition_primary="EXPANSION_PENDING_DIRECTION_UNRESOLVED",
            transition_alternative="CONTINUED_COMPRESSION",
            confidence=0.66,
            evidence=evidence + [
                "no accepted break",
                "low directional movement or late/dead tempo",
            ],
            promotion_required=[
                "completed-candle break beyond local range",
                "hold or retest acceptance beyond the break",
                "participation and pressure confirmation when available",
            ],
            invalidation=[
                "none while the market remains intentionally non-directional",
            ],
            allowed_tactics=[
                "breakout acceptance watch only",
                "RTS only after a confirmed sweep/reclaim",
            ],
            blocked_tactics=[
                "Gimba Range fade inside unresolved compression",
                "Gimba Trend continuation before acceptance",
                "Gimba Volatile chase before expansion proves itself",
            ],
        )

    # ------------------------------------------------------------------
    # 5. Balance / range. This is the ordinary non-trending market state.
    # ------------------------------------------------------------------
    if "RANGING" in condition or trend == "RANGING":
        allowed = [
            "Gimba Range only at a verified edge",
            "RTS only after sweep/reclaim or failed acceptance",
        ]

        if range_active:
            allowed.insert(0, f"Gimba Range {range_bias.lower()} tactic at validated boundary")

        return _state_payload(
            state="BALANCE",
            control="CONTESTED",
            mechanism="ROTATION",
            transition_primary="CONTINUE_ROTATION_OR_TEST_OPPOSITE_VALUE",
            transition_alternative="EXPANSION_IF_RANGE_BREAK_IS_ACCEPTED",
            confidence=max(0.58, range_strength if range_active else 0.58),
            evidence=evidence + [
                "range structure is intact",
                "no confirmed directional acceptance",
            ],
            promotion_required=[
                "for range: edge test plus rejection/reclaim evidence",
                "for expansion: completed break plus acceptance or retest hold",
                "pressure confirmation when pressure feed is ready",
            ],
            invalidation=[
                "accepted break and hold outside the established range",
            ],
            allowed_tactics=allowed,
            blocked_tactics=[
                "Gimba Volatile continuation without accepted expansion",
                "Gimba Trend continuation inside two-sided balance",
                "mid-range mean-reversion entries with poor reward",
            ],
        )

    # ------------------------------------------------------------------
    # 6. Fallback: evidence conflicts or is incomplete.
    # ------------------------------------------------------------------
    return _state_payload(
        state="TRANSITION",
        control="UNRESOLVED",
        mechanism="CONFLICT_OR_CHANGE",
        transition_primary="WAIT_FOR_ACCEPTANCE_OR_REJECTION",
        transition_alternative="RETURN_TO_BALANCE",
        confidence=0.40,
        evidence=evidence + [
            "state inputs do not yet support a stable regime classification",
        ],
        promotion_required=[
            "clear impulse or breakout",
            "acceptance/rejection evidence",
            "specialist tactic aligned with the resolved direction",
        ],
        invalidation=[
            "state remains unresolved; no directional thesis is active",
        ],
        allowed_tactics=[
            "watch only",
            "RTS only after fully confirmed sweep/reclaim",
        ],
        blocked_tactics=[
            "new directional continuation entry",
            "unconfirmed mean-reversion fade",
        ],
    )
