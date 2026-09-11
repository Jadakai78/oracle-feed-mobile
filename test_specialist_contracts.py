"""
test_specialist_contracts.py — Focused tests for specialist_contracts.py.

Tests cover:
- All six canonical families defined
- All families have an explicit role
- Ownership precedence table is ordered correctly and STRUCTURE is first
- should_veto() — shadow mode, RTS veto, Volatile expansion lock, Range yields
- should_veto() — deterministic (same inputs → same output, always)
- No execution capability: SpecialistClaim and RoutingDecision are inert NamedTuples
- ScoreBand constants are in [0.0, 1.0] and STRONG > MODERATE > WEAK ≥ NO_SIGNAL
- SHADOW_MODE_FAMILIES and TRAINING-ONLY families cannot produce non-shadow claims
- Trend Recovery valid-setup predicate matches only reclaim/pullback prefixes
- FAMILY_ROLE covers every SpecialistFamily member
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pytest

GIMBA_DIR = Path(__file__).parent
sys.path.insert(0, str(GIMBA_DIR))

import specialist_contracts as sc
from specialist_contracts import (
    ActionState,
    ClaimSide,
    ClaimState,
    OwnershipFlag,
    RoutingDecision,
    ScoreBand,
    SpecialistClaim,
    SpecialistFamily,
    SpecialistRole,
    VetoReason,
    FAMILY_ROLE,
    OWNERSHIP_PRECEDENCE,
    SHADOW_MODE_FAMILIES,
    TREND_RECOVERY_VALID_SETUP_PREFIXES,
    is_valid_trend_recovery_setup,
    ownership_rank,
    should_veto,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_claim(
    family: SpecialistFamily = SpecialistFamily.GIMBA_RANGE,
    side: ClaimSide = ClaimSide.LONG,
    state: ClaimState = ClaimState.PENDING,
    setup_family: str = "LOWER_BAND_BOUNCE_LONG",
    score: float = 0.7,
    shadow_mode: bool = False,
    training_only: bool = False,
) -> SpecialistClaim:
    return SpecialistClaim(
        family=family,
        side=side,
        state=state,
        setup_family=setup_family,
        action_state=ActionState.WAITING,
        ownership=OwnershipFlag.NONE,
        score=score,
        reasons=("test reason",),
        required_inputs=("ohlcv", "structure"),
        invalidation=None,
        maturity=None,
        freshness_bars=0,
        shadow_mode=shadow_mode,
        training_only=training_only,
        meta={},
    )


# ── 1. Canonical Families ─────────────────────────────────────────────────────

class TestCanonicalFamilies:
    def test_all_six_families_defined(self):
        names = {f.value for f in SpecialistFamily}
        assert names == {
            "RTS_LIQUIDITY",
            "GIMBA_VOLATILE",
            "GIMBA_RANGE",
            "TREND_RECOVERY",
            "STRUCTURE",
            "GIMBA_PULSE",
        }

    def test_family_role_covers_all_families(self):
        for family in SpecialistFamily:
            assert family in FAMILY_ROLE, f"{family} missing from FAMILY_ROLE"

    def test_structure_is_oracle(self):
        assert FAMILY_ROLE[SpecialistFamily.STRUCTURE] == SpecialistRole.ORACLE_STRUCTURE

    def test_rts_is_proposal(self):
        assert FAMILY_ROLE[SpecialistFamily.RTS_LIQUIDITY] == SpecialistRole.PROPOSAL

    def test_range_is_proposal(self):
        assert FAMILY_ROLE[SpecialistFamily.GIMBA_RANGE] == SpecialistRole.PROPOSAL

    def test_volatile_is_shadow(self):
        assert FAMILY_ROLE[SpecialistFamily.GIMBA_VOLATILE] == SpecialistRole.SHADOW

    def test_trend_recovery_is_shadow(self):
        assert FAMILY_ROLE[SpecialistFamily.TREND_RECOVERY] == SpecialistRole.SHADOW

    def test_pulse_is_training_only(self):
        assert FAMILY_ROLE[SpecialistFamily.GIMBA_PULSE] == SpecialistRole.TRAINING_ONLY


# ── 2. Ownership Precedence ───────────────────────────────────────────────────

class TestOwnershipPrecedence:
    def test_structure_is_first(self):
        assert OWNERSHIP_PRECEDENCE[0] == OwnershipFlag.STRUCTURE

    def test_none_is_last(self):
        assert OWNERSHIP_PRECEDENCE[-1] == OwnershipFlag.NONE

    def test_rts_outranks_volatile(self):
        assert ownership_rank(OwnershipFlag.RTS) < ownership_rank(OwnershipFlag.VOLATILE)

    def test_volatile_outranks_range(self):
        assert ownership_rank(OwnershipFlag.VOLATILE) < ownership_rank(OwnershipFlag.RANGE)

    def test_range_outranks_trend_recovery(self):
        assert ownership_rank(OwnershipFlag.RANGE) < ownership_rank(OwnershipFlag.TREND_RECOVERY)

    def test_structure_outranks_all(self):
        for flag in OwnershipFlag:
            if flag != OwnershipFlag.STRUCTURE:
                assert ownership_rank(OwnershipFlag.STRUCTURE) < ownership_rank(flag)

    def test_all_flags_in_precedence_table(self):
        for flag in OwnershipFlag:
            assert flag in OWNERSHIP_PRECEDENCE, f"{flag} not in OWNERSHIP_PRECEDENCE"


# ── 3. Veto Policy ────────────────────────────────────────────────────────────

class TestVetoPolicy:
    """All veto decisions must be deterministic: same inputs → same output."""

    def _call(
        self,
        claim: SpecialistClaim,
        current_owner: OwnershipFlag = OwnershipFlag.NONE,
        rts_confirmed: bool = False,
        vol_active: bool = False,
        vol_mature: bool = False,
        vol_invalid: bool = False,
    ):
        return should_veto(
            challenger=claim,
            current_owner=current_owner,
            rts_trap_confirmed=rts_confirmed,
            volatile_expansion_active=vol_active,
            volatile_claim_mature=vol_mature,
            volatile_claim_invalidated=vol_invalid,
        )

    # Shadow mode veto
    def test_shadow_volatile_always_vetoed(self):
        claim = _make_claim(family=SpecialistFamily.GIMBA_VOLATILE)
        vetoed, reason = self._call(claim)
        assert vetoed is True
        assert reason == VetoReason.SHADOW_MODE

    def test_shadow_trend_recovery_always_vetoed(self):
        claim = _make_claim(family=SpecialistFamily.TREND_RECOVERY)
        vetoed, reason = self._call(claim)
        assert vetoed is True
        assert reason == VetoReason.SHADOW_MODE

    def test_training_only_pulse_always_vetoed(self):
        claim = _make_claim(family=SpecialistFamily.GIMBA_PULSE, training_only=True)
        vetoed, reason = self._call(claim)
        assert vetoed is True
        assert reason == VetoReason.SHADOW_MODE

    # RTS confirmed trap veto
    def test_rts_confirmed_vetos_range(self):
        claim = _make_claim(family=SpecialistFamily.GIMBA_RANGE, side=ClaimSide.LONG)
        vetoed, reason = self._call(claim, rts_confirmed=True)
        assert vetoed is True
        assert reason == VetoReason.RTS_TRAP_CONFIRMED

    def test_rts_confirmed_vetos_range_opposite_direction(self):
        """RTS trap vetoes non-RTS claims regardless of long/short direction."""
        claim = _make_claim(family=SpecialistFamily.GIMBA_RANGE, side=ClaimSide.SHORT)
        vetoed, reason = self._call(claim, rts_confirmed=True)
        assert vetoed is True
        assert reason == VetoReason.RTS_TRAP_CONFIRMED

    def test_rts_claim_not_vetoed_by_own_trap(self):
        claim = _make_claim(family=SpecialistFamily.RTS_LIQUIDITY, side=ClaimSide.LONG)
        vetoed, reason = self._call(claim, rts_confirmed=True)
        assert vetoed is False

    # Volatile expansion lock
    def test_volatile_active_expansion_blocks_range(self):
        claim = _make_claim(family=SpecialistFamily.GIMBA_RANGE, side=ClaimSide.LONG)
        vetoed, reason = self._call(claim, vol_active=True, vol_mature=False, vol_invalid=False)
        assert vetoed is True
        assert reason == VetoReason.RANGE_YIELDING_EXPANSION

    def test_volatile_mature_does_not_block_range(self):
        claim = _make_claim(family=SpecialistFamily.GIMBA_RANGE, side=ClaimSide.LONG)
        vetoed, reason = self._call(claim, vol_active=True, vol_mature=True, vol_invalid=False)
        assert vetoed is False

    def test_volatile_invalidated_does_not_block_range(self):
        claim = _make_claim(family=SpecialistFamily.GIMBA_RANGE, side=ClaimSide.LONG)
        vetoed, reason = self._call(claim, vol_active=True, vol_mature=False, vol_invalid=True)
        assert vetoed is False

    def test_volatile_does_not_block_rts(self):
        claim = _make_claim(family=SpecialistFamily.RTS_LIQUIDITY, side=ClaimSide.LONG)
        vetoed, reason = self._call(claim, vol_active=True, vol_mature=False, vol_invalid=False)
        assert vetoed is False

    # Range yields when expansion accepted
    def test_range_yields_when_expansion_active(self):
        claim = _make_claim(family=SpecialistFamily.GIMBA_RANGE, side=ClaimSide.LONG)
        vetoed, reason = self._call(claim, vol_active=True, vol_mature=False, vol_invalid=False)
        assert vetoed is True
        assert reason == VetoReason.RANGE_YIELDING_EXPANSION

    # No veto for clean RTS claim
    def test_rts_passes_clean(self):
        claim = _make_claim(family=SpecialistFamily.RTS_LIQUIDITY, side=ClaimSide.LONG)
        vetoed, reason = self._call(claim)
        assert vetoed is False

    # Determinism check: same inputs always produce same output
    def test_veto_is_deterministic(self):
        claim = _make_claim(family=SpecialistFamily.GIMBA_RANGE, side=ClaimSide.LONG)
        results = [
            self._call(claim, rts_confirmed=True) for _ in range(10)
        ]
        assert all(r == results[0] for r in results)


# ── 4. No Execution Capability ────────────────────────────────────────────────

class TestNoExecutionCapability:
    """SpecialistClaim and RoutingDecision are inert data containers only."""

    def test_specialist_claim_has_no_execute_method(self):
        claim = _make_claim()
        assert not hasattr(claim, "execute")
        assert not hasattr(claim, "place_order")
        assert not hasattr(claim, "send")
        assert not hasattr(claim, "submit")

    def test_routing_decision_has_no_execute_method(self):
        decision = RoutingDecision(
            accepted_claim=None,
            vetoed_claims=(),
            owner=OwnershipFlag.NONE,
            veto_reasons=(),
            router_notes=(),
        )
        assert not hasattr(decision, "execute")
        assert not hasattr(decision, "place_order")
        assert not hasattr(decision, "send")

    def test_specialist_contracts_does_not_import_scanner(self):
        import specialist_contracts as _sc
        assert "scanner" not in dir(_sc)
        # Verify scanner is not a dependency of the module
        import importlib
        spec = importlib.util.find_spec("scanner")
        # scanner.py may exist on sys.path but specialist_contracts must not import it
        module_globals = vars(_sc)
        assert "scanner" not in module_globals

    def test_specialist_claim_is_namedtuple(self):
        claim = _make_claim()
        assert isinstance(claim, tuple)

    def test_routing_decision_is_namedtuple(self):
        decision = RoutingDecision(
            accepted_claim=None,
            vetoed_claims=(),
            owner=OwnershipFlag.NONE,
            veto_reasons=(),
            router_notes=(),
        )
        assert isinstance(decision, tuple)


# ── 5. Score Band Constants ───────────────────────────────────────────────────

class TestScoreBands:
    def test_bands_in_unit_interval(self):
        for attr in dir(ScoreBand):
            if attr.startswith("_"):
                continue
            val = getattr(ScoreBand, attr)
            if isinstance(val, float):
                assert 0.0 <= val <= 1.0, f"ScoreBand.{attr} = {val} out of [0,1]"

    def test_strong_greater_than_moderate(self):
        assert ScoreBand.STRONG_CONVICTION > ScoreBand.MODERATE_CONVICTION

    def test_moderate_greater_than_weak(self):
        assert ScoreBand.MODERATE_CONVICTION > ScoreBand.WEAK_SIGNAL

    def test_weak_greater_than_no_signal(self):
        assert ScoreBand.WEAK_SIGNAL > ScoreBand.NO_SIGNAL

    def test_no_signal_is_zero(self):
        assert ScoreBand.NO_SIGNAL == 0.0


# ── 6. Shadow-Mode Families ───────────────────────────────────────────────────

class TestShadowMode:
    def test_volatile_in_shadow_mode_set(self):
        assert SpecialistFamily.GIMBA_VOLATILE in SHADOW_MODE_FAMILIES

    def test_trend_recovery_in_shadow_mode_set(self):
        assert SpecialistFamily.TREND_RECOVERY in SHADOW_MODE_FAMILIES

    def test_rts_not_in_shadow_mode_set(self):
        assert SpecialistFamily.RTS_LIQUIDITY not in SHADOW_MODE_FAMILIES

    def test_range_not_in_shadow_mode_set(self):
        assert SpecialistFamily.GIMBA_RANGE not in SHADOW_MODE_FAMILIES

    def test_structure_not_in_shadow_mode_set(self):
        assert SpecialistFamily.STRUCTURE not in SHADOW_MODE_FAMILIES


# ── 7. Trend Recovery Setup Predicate ────────────────────────────────────────

class TestTrendRecoverySetup:
    def test_reclaim_prefix_valid(self):
        assert is_valid_trend_recovery_setup("RECLAIM_LONG")
        assert is_valid_trend_recovery_setup("RECLAIM_SHORT")

    def test_pullback_continuation_valid(self):
        assert is_valid_trend_recovery_setup("PULLBACK_CONTINUATION_LONG")

    def test_pullback_hold_valid(self):
        assert is_valid_trend_recovery_setup("PULLBACK_HOLD_SHORT")

    def test_expansion_setup_invalid(self):
        assert not is_valid_trend_recovery_setup("SURGE_CONTINUATION_LONG")
        assert not is_valid_trend_recovery_setup("CASCADE_RECOVERY_LONG")
        assert not is_valid_trend_recovery_setup("BREAKOUT_LONG")

    def test_empty_string_invalid(self):
        assert not is_valid_trend_recovery_setup("")
