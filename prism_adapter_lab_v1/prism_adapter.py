"""
PRISM Adapter Lab v1

Offline-only fixture aggregator.
No live reads, GitHub publishing, scanner imports, router imports, alerts,
orders, queue changes, scoring changes, or trade authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional


RECORDTYPE = "PRISMADAPTERFEED"
SCHEMA_VERSION = 1
SOURCE_AVAILABLE = "AVAILABLE"
SOURCE_UNAVAILABLE = "UNAVAILABLE"
SOURCE_STALE = "STALE"
SOURCE_INVALID = "INVALID"
SOURCE_PAIR_MISMATCH = "PAIR_MISMATCH"

SOURCE_STATES = {
    SOURCE_AVAILABLE,
    SOURCE_UNAVAILABLE,
    SOURCE_STALE,
    SOURCE_INVALID,
    SOURCE_PAIR_MISMATCH,
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def unavailable(reason: str) -> Dict[str, Any]:
    return {"state": SOURCE_UNAVAILABLE, "reason": reason}


def source_health(
    state: str,
    generated_at_utc: Optional[str] = None,
    age_seconds: Optional[int] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    if state not in SOURCE_STATES:
        raise ValueError(f"invalid_source_state:{state}")
    result: Dict[str, Any] = {"state": state}
    if generated_at_utc is not None:
        result["generated_at_utc"] = generated_at_utc
    if age_seconds is not None:
        result["age_seconds"] = age_seconds
    if reason is not None:
        result["reason"] = reason
    return result


def index_by_pair(records: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    indexed: Dict[str, Mapping[str, Any]] = {}
    for record in records:
        pair = record.get("pair")
        if not isinstance(pair, str) or not pair:
            raise ValueError("record_missing_pair")
        if pair in indexed:
            raise ValueError(f"duplicate_pair:{pair}")
        indexed[pair] = record
    return indexed


def oracle_context(record: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if record is None:
        return {
            "higher_timeframe": "UNAVAILABLE",
            "lane": "UNAVAILABLE",
            "regime": "UNAVAILABLE",
            "location": "UNAVAILABLE",
            "constraint_state": "UNAVAILABLE",
            "constraint_reasons": ["oracle_source_not_connected"],
            "context_score": None,
        }

    return {
        "higher_timeframe": record.get("directional_context", "UNAVAILABLE"),
        "lane": record.get("review_state", "UNAVAILABLE"),
        "regime": record.get("market_type", "UNAVAILABLE"),
        "location": record.get("location", "UNAVAILABLE"),
        "constraint_state": record.get("constraint_state", "DESCRIPTIVE"),
        "constraint_reasons": list(record.get("constraint_reasons") or []),
        "context_score": None,
    }


def prism_map(record: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if record is None:
        return {
            "state": "UNAVAILABLE",
            "construction": "UNAVAILABLE",
            "fair_price_relationship": "UNAVAILABLE",
            "band_travel_state": "UNAVAILABLE",
            "routes_ranked": [],
            "map_quality": "UNAVAILABLE",
        }

    return {
        "state": record.get("state", "UNAVAILABLE"),
        "construction": record.get("construction", "UNAVAILABLE"),
        "fair_price_relationship": record.get("fair_price_relationship", "UNAVAILABLE"),
        "band_travel_state": record.get("band_travel_state", "UNAVAILABLE"),
        "routes_ranked": list(record.get("routes_ranked") or []),
        "map_quality": record.get("map_quality", "UNAVAILABLE"),
    }


def eight_gates_confluence(record: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if record is None:
        return {
            "state": SOURCE_UNAVAILABLE,
            "score": None,
            "eligibility": "UNAVAILABLE",
            "reason_codes": ["eight_gates_source_not_connected"],
        }

    return {
        "state": SOURCE_AVAILABLE,
        "score": record.get("score"),
        "eligibility": record.get("eligibility", "UNAVAILABLE"),
        "reason_codes": list(record.get("reason_codes") or []),
    }


def delta_confluence(record: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if record is None:
        return {
            "state": SOURCE_UNAVAILABLE,
            "shadow_score": None,
            "shadow_score_state": "NOT_DEFINED",
            "episode_state": "UNAVAILABLE",
            "direction": "NONE",
            "promotion_pattern": None,
            "watch_active": False,
            "active_feed_visibility": False,
            "reason_codes": ["delta_tempo_v2_source_not_connected"],
            "manual_review_only": True,
            "entry_authority": False,
        }

    if record.get("delta_tempo_version") != 2:
        raise ValueError(f"invalid_delta_version:{record.get('delta_tempo_version')}")

    if record.get("v2_manual_review_only") is not True:
        raise ValueError("delta_not_manual_review_only")

    if record.get("v2_entry_authority") is not False:
        raise ValueError("delta_has_entry_authority")

    return {
        "state": SOURCE_AVAILABLE,
        "shadow_score": record.get("shadow_score"),
        "shadow_score_state": "NOT_DEFINED" if record.get("shadow_score") is None else "SOURCE_OWNED",
        "episode_state": record.get("v2_episode_state"),
        "direction": record.get("v2_episode_direction"),
        "promotion_pattern": record.get("v2_promotion_pattern"),
        "watch_active": bool(record.get("v2_watch_active")),
        "active_feed_visibility": bool(record.get("v2_active_feed_visibility")),
        "reason_codes": list(record.get("v2_reason_codes") or []),
        "manual_review_only": True,
        "entry_authority": False,
    }


def build_payload(
    pairs: List[str],
    oracle_records: Iterable[Mapping[str, Any]],
    eight_gates_records: Iterable[Mapping[str, Any]],
    delta_records: Iterable[Mapping[str, Any]],
    prism_records: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    if len(pairs) != 49 or len(set(pairs)) != 49:
        raise ValueError("pair_universe_must_contain_exactly_49_unique_pairs")

    oracle_by_pair = index_by_pair(oracle_records)
    eight_by_pair = index_by_pair(eight_gates_records)
    delta_by_pair = index_by_pair(delta_records)
    prism_by_pair = index_by_pair(prism_records)

    cards: List[Dict[str, Any]] = []

    for pair in pairs:
        oracle_record = oracle_by_pair.get(pair)
        eight_record = eight_by_pair.get(pair)
        delta_record = delta_by_pair.get(pair)
        prism_record = prism_by_pair.get(pair)

        health = {
            "oracle": source_health(
                SOURCE_AVAILABLE if oracle_record else SOURCE_UNAVAILABLE,
                generated_at_utc=oracle_record.get("generated_at_utc") if oracle_record else None,
                age_seconds=oracle_record.get("age_seconds") if oracle_record else None,
                reason=None if oracle_record else "source_not_connected",
            ),
            "prism": source_health(
                SOURCE_AVAILABLE if prism_record else SOURCE_UNAVAILABLE,
                generated_at_utc=prism_record.get("generated_at_utc") if prism_record else None,
                age_seconds=prism_record.get("age_seconds") if prism_record else None,
                reason=None if prism_record else "source_not_connected",
            ),
            "eight_gates": source_health(
                SOURCE_AVAILABLE if eight_record else SOURCE_UNAVAILABLE,
                generated_at_utc=eight_record.get("generated_at_utc") if eight_record else None,
                age_seconds=eight_record.get("age_seconds") if eight_record else None,
                reason=None if eight_record else "source_not_connected",
            ),
            "delta_tempo_v2": source_health(
                SOURCE_AVAILABLE if delta_record else SOURCE_UNAVAILABLE,
                generated_at_utc=delta_record.get("generated_at_utc") if delta_record else None,
                age_seconds=delta_record.get("age_seconds") if delta_record else None,
                reason=None if delta_record else "source_not_connected",
            ),
        }

        delta = delta_confluence(delta_record)
        eight = eight_gates_confluence(eight_record)
        pmap = prism_map(prism_record)

        risk_reasons: List[str] = []
        if prism_record is None:
            risk_reasons.append("prism_source_not_connected")
        if oracle_record is None:
            risk_reasons.append("oracle_context_unavailable")

        card = {
            "pair": pair,
            "source_health": health,
            "context": oracle_context(oracle_record),
            "prism_map": pmap,
            "confluence": {
                "eight_gates": eight,
                "delta_tempo_v2": delta,
                "score_relationship": "INDEPENDENT_NOT_COMBINED",
            },
            "risk": {
                "structural_invalidation": "UNAVAILABLE",
                "opposing_structure": "UNAVAILABLE",
                "available_distance": "UNAVAILABLE",
                "room_status": "UNAVAILABLE",
                "liquidation_coverage": "UNAVAILABLE",
                "risk_reasons": risk_reasons or ["no_prism_risk_map"],
            },
            "display": {
                "attention_state": "OBSERVE",
                "manual_review_only": True,
                "entry_authority": False,
                "summary": "Independent sources shown; no combined score or trade authority.",
            },
        }
        cards.append(card)

    return {
        "recordtype": RECORDTYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now_utc(),
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
        "does_not_send_alerts": True,
        "does_not_change_queue": True,
        "cards": cards,
    }