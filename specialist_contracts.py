"""
specialist_contracts.py — Canonical contract definitions for the JHL Gimba specialist architecture.

CONTRACT MODULE — NO EXECUTION CAPABILITY
==========================================
This module contains only:
- Enum definitions (state labels, side, family, action-state, ownership, reasons)
- NamedTuple field schemas for canonical claim/result records
- Named score-band constants (for documentation; no threshold changes to runtime)
- Ownership precedence helpers (pure deterministic logic; no side effects)
- Shadow-mode flag constants for recovered specialists

This file MUST NOT:
- Place orders, size positions, or touch live risk
- Import scanner.py or be imported by scanner.py
- Modify KNN conviction, OFFENSE/PERMISSION calculations, or existing specialist logic
- Provide any execution pathway, even an indirect one

All claim/result records produced by this module are inert data containers.
"""

from __future__ import annotations

from enum import Enum, unique
from typing import Any, Dict, FrozenSet, List, NamedTuple, Optional, Tuple


# ── 1. Canonical Specialist Families ─────────────────────────────────────────

@unique
class SpecialistFamily(str, Enum):
    """Canonical family identifier for each specialist role.

    Values match the labels used in scanner output and the README roster.
    Comparison is case-insensitive because these are str-Enum members.
    """
    RTS_LIQUIDITY    = "RTS_LIQUIDITY"     # Liquidity-sweep / trap specialist
    GIMBA_VOLATILE   = "GIMBA_VOLATILE"    # Volatility / expansion specialist
    GIMBA_RANGE      = "GIMBA_RANGE"       # Rotational / mean-reversion specialist
    TREND_RECOVERY   = "TREND_RECOVERY"    # Reclaim / pullback-continuation specialist
    STRUCTURE        = "STRUCTURE"         # Oracle / Structure — market truth and routing
    GIMBA_PULSE      = "GIMBA_PULSE"       # Training-only micro-regime observer


# ── 2. Explicit Roles ─────────────────────────────────────────────────────────

@unique
class SpecialistRole(str, Enum):
    """High-level role category for each specialist family.

    ORACLE_STRUCTURE  — supplies market truth and routing context; is the
                        final router; does NOT produce directional proposals.
    PROPOSAL          — produces execution-eligible claims (subject to veto).
    SHADOW            — recovered specialist in observation-only mode; produces
                        annotated proposals but they are NOT routed for execution
                        until explicitly promoted by the system owner.
    TRAINING_ONLY     — produces logged claims for ML/outcome evaluation only;
                        no execution, no risk, no OFFENSE/PERMISSION contribution.
    """
    ORACLE_STRUCTURE = "ORACLE_STRUCTURE"
    PROPOSAL         = "PROPOSAL"
    SHADOW           = "SHADOW"
    TRAINING_ONLY    = "TRAINING_ONLY"


# Role assignment by family — authoritative mapping
FAMILY_ROLE: Dict[SpecialistFamily, SpecialistRole] = {
    SpecialistFamily.STRUCTURE:      SpecialistRole.ORACLE_STRUCTURE,
    SpecialistFamily.RTS_LIQUIDITY:  SpecialistRole.PROPOSAL,
    SpecialistFamily.GIMBA_RANGE:    SpecialistRole.PROPOSAL,
    SpecialistFamily.GIMBA_VOLATILE: SpecialistRole.SHADOW,       # recovered — shadow mode
    SpecialistFamily.TREND_RECOVERY: SpecialistRole.SHADOW,       # recovered — shadow mode
    SpecialistFamily.GIMBA_PULSE:    SpecialistRole.TRAINING_ONLY,
}


# ── 3. Claim / Result Enums ───────────────────────────────────────────────────

@unique
class ClaimState(str, Enum):
    """Lifecycle state of a specialist claim."""
    PENDING       = "PENDING"        # Emitted; awaiting routing decision
    ACTIVE        = "ACTIVE"         # Accepted by router; in progress
    VETOED        = "VETOED"         # Blocked by a higher-precedence claim/veto
    INVALIDATED   = "INVALIDATED"    # Hard invalidation fired (price/structure)
    MATURE        = "MATURE"         # Claim reached maturity / full target
    DECAYED       = "DECAYED"        # Thesis decay without hard invalidation
    EXPIRED       = "EXPIRED"        # Time-window elapsed without resolution
    SHADOW_LOGGED = "SHADOW_LOGGED"  # Shadow-mode: logged, never routed


@unique
class ClaimSide(str, Enum):
    """Directional side of a claim."""
    LONG  = "LONG"
    SHORT = "SHORT"
    FLAT  = "FLAT"   # No directional bias (e.g. neutral context claims)


@unique
class ActionState(str, Enum):
    """Router-facing action state attached to an accepted claim."""
    WAITING    = "WAITING"    # Claim accepted; awaiting trigger condition
    TRIGGERED  = "TRIGGERED"  # Entry condition met
    EXITED     = "EXITED"     # Position exited (hit target or stop)
    ABANDONED  = "ABANDONED"  # Claim dropped by router without fill


@unique
class OwnershipFlag(str, Enum):
    """Which specialist currently holds directional ownership."""
    NONE            = "NONE"
    RTS             = "RTS"
    VOLATILE        = "VOLATILE"
    RANGE           = "RANGE"
    TREND_RECOVERY  = "TREND_RECOVERY"
    STRUCTURE       = "STRUCTURE"


@unique
class VetoReason(str, Enum):
    """Enumerated reasons a claim may be vetoed."""
    RTS_TRAP_CONFIRMED        = "RTS_TRAP_CONFIRMED"
    EXPANSION_ACTIVE_VOLATILE = "EXPANSION_ACTIVE_VOLATILE"
    RANGE_YIELDING_EXPANSION  = "RANGE_YIELDING_EXPANSION"
    STRUCTURE_ROUTER_BLOCK    = "STRUCTURE_ROUTER_BLOCK"
    SHADOW_MODE               = "SHADOW_MODE"


@unique
class InvalidationReason(str, Enum):
    """Hard invalidation triggers for a claim."""
    STRUCTURE_BREAK_THROUGH  = "STRUCTURE_BREAK_THROUGH"
    PRICE_RETURNS_TO_TRIGGER = "PRICE_RETURNS_TO_TRIGGER"
    STOP_HIT                 = "STOP_HIT"
    OPPOSITE_TRAP_CONFIRMED  = "OPPOSITE_TRAP_CONFIRMED"
    EXPANSION_REVERSED       = "EXPANSION_REVERSED"
    CUSTOM                   = "CUSTOM"


@unique
class MaturityReason(str, Enum):
    """Reasons a claim is considered mature / claim lifecycle complete."""
    TARGET_HIT          = "TARGET_HIT"
    FULL_EXPANSION_DONE = "FULL_EXPANSION_DONE"
    PRIOR_SWING_REACHED = "PRIOR_SWING_REACHED"
    TRACTION_COMPLETE   = "TRACTION_COMPLETE"


# ── 4. Canonical Claim / Result Field Schemas ─────────────────────────────────

class SpecialistClaim(NamedTuple):
    """Canonical immutable claim record produced by a specialist.

    Fields
    ------
    family          : SpecialistFamily — which specialist produced this claim
    side            : ClaimSide — directional bias
    state           : ClaimState — current lifecycle state
    setup_family    : str — human-readable setup label (e.g. "SURGE_CONTINUATION_LONG")
    action_state    : ActionState — router-facing action state
    ownership       : OwnershipFlag — who holds ownership for this pair at emit time
    score           : float — specialist confidence score (0.0 – 1.0)
    reasons         : Tuple[str, ...] — ordered rationale strings
    required_inputs : Tuple[str, ...] — input fields consumed to produce this claim
    invalidation    : Optional[InvalidationReason] — hard invalidation cause (if fired)
    maturity        : Optional[MaturityReason] — maturity cause (if reached)
    freshness_bars  : int — bars since claim was emitted (0 = just emitted)
    shadow_mode     : bool — True when claim is shadow-logged only (no execution)
    training_only   : bool — True for TRAINING_ONLY role claims
    meta            : Dict[str, Any] — specialist-specific supplementary data
    """
    family:          SpecialistFamily
    side:            ClaimSide
    state:           ClaimState
    setup_family:    str
    action_state:    ActionState
    ownership:       OwnershipFlag
    score:           float
    reasons:         Tuple[str, ...]
    required_inputs: Tuple[str, ...]
    invalidation:    Optional[InvalidationReason]
    maturity:        Optional[MaturityReason]
    freshness_bars:  int
    shadow_mode:     bool
    training_only:   bool
    meta:            Dict[str, Any]


class RoutingDecision(NamedTuple):
    """Immutable record of the Structure/Oracle routing decision for a bar.

    Fields
    ------
    accepted_claim  : Optional[SpecialistClaim] — claim accepted for execution (None if vetoed/no claim)
    vetoed_claims   : Tuple[SpecialistClaim, ...] — claims that were blocked
    owner           : OwnershipFlag — ownership in effect after this decision
    veto_reasons    : Tuple[VetoReason, ...] — reasons for vetoes applied
    router_notes    : Tuple[str, ...] — human-readable routing context
    """
    accepted_claim: Optional[SpecialistClaim]
    vetoed_claims:  Tuple[SpecialistClaim, ...]
    owner:          OwnershipFlag
    veto_reasons:   Tuple[VetoReason, ...]
    router_notes:   Tuple[str, ...]


# ── 5. Ownership Precedence and Veto Policy ───────────────────────────────────

# Precedence order — lower index = higher authority.
# Structure/Oracle is always index 0 and is the final router.
OWNERSHIP_PRECEDENCE: Tuple[OwnershipFlag, ...] = (
    OwnershipFlag.STRUCTURE,
    OwnershipFlag.RTS,
    OwnershipFlag.VOLATILE,
    OwnershipFlag.RANGE,
    OwnershipFlag.TREND_RECOVERY,
    OwnershipFlag.NONE,
)


def ownership_rank(flag: OwnershipFlag) -> int:
    """Return the precedence rank of an OwnershipFlag (lower = higher authority).

    Structure is always 0.  NONE is always the lowest rank.
    Raises ValueError if the flag is not in the precedence table (should not happen).
    """
    return OWNERSHIP_PRECEDENCE.index(flag)


def should_veto(
    challenger: SpecialistClaim,
    current_owner: OwnershipFlag,
    rts_trap_confirmed: bool,
    volatile_expansion_active: bool,
    volatile_claim_mature: bool,
    volatile_claim_invalidated: bool,
) -> Tuple[bool, Optional[VetoReason]]:
    """Deterministic ownership/veto check.

    Parameters
    ----------
    challenger                : The incoming claim to evaluate.
    current_owner             : OwnershipFlag currently in effect for this pair/side.
    rts_trap_confirmed        : True when RTS has a confirmed trap active (global safety veto).
    volatile_expansion_active : True when Gimba Volatile owns an active expansion.
    volatile_claim_mature     : True when the active Volatile expansion is mature.
    volatile_claim_invalidated: True when the active Volatile expansion is invalidated.

    Returns
    -------
    (should_veto, veto_reason)
        should_veto  — True if the challenger claim should be vetoed.
        veto_reason  — The applicable VetoReason, or None if not vetoed.

    Veto Rules (in precedence order)
    ---------------------------------
    1. Shadow-mode families are always vetoed (SHADOW_MODE).
    2. A confirmed RTS trap vetoes every non-RTS directional claim regardless of
       long/short direction; RTS's own claim remains exempt (RTS_TRAP_CONFIRMED).
    3. Gimba Volatile owns active expansion until the expansion is mature OR
       invalidated; all other same-direction claims are vetoed while expansion
       is active and not yet resolved (EXPANSION_ACTIVE_VOLATILE).
    4. Gimba Range is rotation-only and must yield when an expansion claim is
       accepted (RANGE_YIELDING_EXPANSION).
    5. Structure/Oracle is the final router and may always block any claim
       (STRUCTURE_ROUTER_BLOCK).  This is enforced externally by the router; this
       function only checks the deterministic specialist-level rules above.
    """
    # Rule 1: shadow/training families are never execution-eligible
    family_role = FAMILY_ROLE.get(challenger.family)
    if family_role in (SpecialistRole.SHADOW, SpecialistRole.TRAINING_ONLY):
        return True, VetoReason.SHADOW_MODE

    # Rule 2: confirmed RTS trap vetoes every non-RTS directional claim regardless of direction;
    # RTS's own claim is exempt.
    if (
        rts_trap_confirmed
        and challenger.family != SpecialistFamily.RTS_LIQUIDITY
        and challenger.side != ClaimSide.FLAT
    ):
        return True, VetoReason.RTS_TRAP_CONFIRMED

    # Rule 3: Volatile owns active expansion until mature or invalidated;
    # non-Range, non-RTS directional claims are blocked while expansion holds.
    # (GIMBA_RANGE is excluded here so Rule 4 can assign the more specific reason.)
    if (
        volatile_expansion_active
        and not volatile_claim_mature
        and not volatile_claim_invalidated
        and challenger.family not in (
            SpecialistFamily.GIMBA_VOLATILE,
            SpecialistFamily.RTS_LIQUIDITY,
            SpecialistFamily.GIMBA_RANGE,
        )
        and challenger.side != ClaimSide.FLAT
    ):
        return True, VetoReason.EXPANSION_ACTIVE_VOLATILE

    # Rule 4: Range is rotation-only and must yield while an expansion is active
    # and not yet resolved (mature or invalidated).
    if (
        challenger.family == SpecialistFamily.GIMBA_RANGE
        and volatile_expansion_active
        and not volatile_claim_mature
        and not volatile_claim_invalidated
    ):
        return True, VetoReason.RANGE_YIELDING_EXPANSION

    return False, None


# ── 6. Shadow-Mode Behavior Constants ────────────────────────────────────────

# Families currently in shadow (observation/recovery) mode.
# When a family is in this set its claims are given ClaimState.SHADOW_LOGGED
# and are never forwarded to the execution router.
SHADOW_MODE_FAMILIES: FrozenSet[SpecialistFamily] = frozenset({
    SpecialistFamily.GIMBA_VOLATILE,
    SpecialistFamily.TREND_RECOVERY,
})

# Trend Recovery is reclaim/pullback-continuation only — it must not emit
# expansion or breakout setup families.
TREND_RECOVERY_VALID_SETUP_PREFIXES: Tuple[str, ...] = (
    "RECLAIM_",
    "PULLBACK_CONTINUATION_",
    "PULLBACK_HOLD_",
)


def is_valid_trend_recovery_setup(setup_family: str) -> bool:
    """Return True only if setup_family is a reclaim/pullback-continuation type."""
    return any(setup_family.startswith(pfx) for pfx in TREND_RECOVERY_VALID_SETUP_PREFIXES)


# ── 7. Score Band Named Constants ─────────────────────────────────────────────
# These are documentation-only labels for score ranges.
# They do NOT change any existing runtime thresholds.

class ScoreBand:
    """Named score-band constants.  Read-only documentation anchors.

    Bands apply to the normalized specialist confidence score (0.0 – 1.0).
    No existing runtime threshold is altered by these definitions.
    """
    STRONG_CONVICTION   = 0.80   # ≥ 0.80 — high-confidence claim
    MODERATE_CONVICTION = 0.60   # ≥ 0.60 — moderate-confidence claim
    WEAK_SIGNAL         = 0.40   # ≥ 0.40 — weak / borderline signal
    NO_SIGNAL           = 0.00   # < 0.40 — below meaningful threshold

    # RTS score anchors
    RTS_TRAP_HIGH_CONF  = 0.75
    RTS_TRAP_LOW_CONF   = 0.50

    # Volatile score anchors
    VOLATILE_EXPANSION_HIGH = 0.80
    VOLATILE_EXPANSION_LOW  = 0.55

    # Range score anchors
    RANGE_ROTATION_HIGH = 0.70
    RANGE_ROTATION_LOW  = 0.45

    # Trend Recovery score anchors
    TREND_RECOVERY_HIGH = 0.72
    TREND_RECOVERY_LOW  = 0.48
