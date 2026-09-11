"""Oracle Prop Feed Adapter v1 — read-only mobile feed projection.

Consumes oracle_prop_context_v1.json and writes oracle_prop_feed_v1.json.
No execution, order, alert, queue, market-data collection, or GitHub publishing.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parent
INPUT_PATH = ROOT / "oracle_prop_context_v1.json"
OUTPUT_PATH = ROOT / "oracle_prop_feed_v1.json"

INPUT_RECORDTYPE = "ORACLEPROPCONTEXT"
OUTPUT_RECORDTYPE = "ORACLEPROPFEED"
UNIVERSE = "APRIL_12_FIXED"
MAX_MICRO_WATCHLIST = 6


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _age_seconds(value: Any) -> int | None:
    stamp = _parse_utc(value)
    if stamp is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))


def _reason_claim(pair: Dict[str, Any]) -> str:
    reasons = pair.get("reason_codes") or []
    if not reasons:
        return "CONTEXT_CLEAR"
    return ", ".join(str(item) for item in reasons[:4])


def _tier_for(pair: Dict[str, Any]) -> str:
    state = pair["review_state"]
    shield = pair["shield"]
    if state == "ARMED" and shield == "CLEAR":
        return "BEST_NOW"
    if state == "BLOCK" or shield == "BLOCK":
        return "REJECTED_CONTEXT"
    if shield == "CAUTION":
        return "SHIELDED"
    return "WATCH_NEEDS_TRIGGER"


def _cluster_key(pair: Dict[str, Any]) -> str:
    direction = pair["directional_context"]
    market_type = pair["market_type"]
    return f"{direction}:{market_type}"


def _validate_input(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("context_payload_not_object")
    if payload.get("recordtype") != INPUT_RECORDTYPE:
        raise ValueError("unexpected_context_recordtype")
    if payload.get("venue") != "PROP" or payload.get("universe") != UNIVERSE:
        raise ValueError("unexpected_context_scope")
    if payload.get("manual_review_only") is not True:
        raise ValueError("context_not_manual_review_only")
    pairs = payload.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != 49:
        raise ValueError("context_pair_count_must_be_49")
    expected = {
        "pair", "directional_context", "market_type", "structure", "tempo", "flow",
        "shield", "location", "review_state", "reason_codes", "context_score",
    }
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != expected:
            raise ValueError("context_pair_schema_mismatch")
    return pairs


def _make_cards(pairs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cards = []
    for pair in pairs:
        card = {
            "pair": pair["pair"],
            "directional_context": pair["directional_context"],
            "market_type": pair["market_type"],
            "structure": pair["structure"],
            "tempo": pair["tempo"],
            "flow": pair["flow"],
            "shield": pair["shield"],
            "location": pair["location"],
            "review_state": pair["review_state"],
            "reason_codes": list(pair["reason_codes"]),
            "context_claim": _reason_claim(pair),
            "context_score": pair["context_score"],
            "tier": _tier_for(pair),
            "correlation_group": _cluster_key(pair),
            "correlation_role": "UNASSIGNED",
            "micro_watchlist": False,
            "micro_state": "OFF",
        }
        cards.append(card)
    return cards


def _assign_correlation_roles(cards: List[Dict[str, Any]]) -> None:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for card in cards:
        groups.setdefault(card["correlation_group"], []).append(card)
    tier_rank = {"BEST_NOW": 0, "WATCH_NEEDS_TRIGGER": 1, "SHIELDED": 2, "REJECTED_CONTEXT": 3}
    for members in groups.values():
        members.sort(key=lambda card: (tier_rank[card["tier"]], -card["context_score"], card["pair"]))
        for index, card in enumerate(members):
            card["correlation_role"] = "PRIMARY" if index == 0 else "DUPLICATE"


def _select_micro_watchlist(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates = [
        card for card in cards
        if card["tier"] in {"BEST_NOW", "WATCH_NEEDS_TRIGGER"}
        and card["correlation_role"] == "PRIMARY"
        and card["shield"] != "BLOCK"
    ]
    candidates.sort(key=lambda card: (-card["context_score"], card["pair"]))
    selected = candidates[:MAX_MICRO_WATCHLIST]
    for card in selected:
        card["micro_watchlist"] = True
        card["micro_state"] = "ARMED" if card["review_state"] == "ARMED" else "WATCH"
    return selected


def build_payload(context_payload: Dict[str, Any]) -> Dict[str, Any]:
    pairs = _validate_input(context_payload)
    cards = _make_cards(pairs)
    _assign_correlation_roles(cards)
    micro_watchlist = _select_micro_watchlist(cards)
    tiers = {
        "best_now": [card for card in cards if card["tier"] == "BEST_NOW"],
        "watch_needs_trigger": [card for card in cards if card["tier"] == "WATCH_NEEDS_TRIGGER"],
        "shielded": [card for card in cards if card["tier"] == "SHIELDED"],
        "rejected_context": [card for card in cards if card["tier"] == "REJECTED_CONTEXT"],
    }
    tier_order = {"BEST_NOW": 0, "WATCH_NEEDS_TRIGGER": 1, "SHIELDED": 2, "REJECTED_CONTEXT": 3}
    for card_list in list(tiers.values()):
        card_list.sort(key=lambda card: (-card["context_score"], card["pair"]))
    cards.sort(key=lambda card: (tier_order[card["tier"]], -card["context_score"], card["pair"]))
    return {
        "recordtype": OUTPUT_RECORDTYPE,
        "generated_at_utc": _now_utc(),
        "context_generated_at_utc": context_payload["generated_at_utc"],
        "context_age_seconds": _age_seconds(context_payload["generated_at_utc"]),
        "venue": "PROP",
        "universe": UNIVERSE,
        "manual_review_only": True,
        "does_not_authorize_trade": True,
        "does_not_change_queue": True,
        "does_not_send_alerts": True,
        "source": {"file": INPUT_PATH.name, "recordtype": INPUT_RECORDTYPE, "pair_count": len(pairs)},
        "health": {
            "pair_count": len(cards),
            "best_now_count": len(tiers["best_now"]),
            "watch_needs_trigger_count": len(tiers["watch_needs_trigger"]),
            "shielded_count": len(tiers["shielded"]),
            "rejected_context_count": len(tiers["rejected_context"]),
            "micro_watchlist_count": len(micro_watchlist),
            "review_state_counts": dict(sorted(Counter(card["review_state"] for card in cards).items())),
        },
        "tiers": tiers,
        "micro_watchlist": micro_watchlist,
        "cards": cards,
    }


def write_payload(payload: Dict[str, Any], output_path: Path = OUTPUT_PATH) -> None:
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output_path)


def main() -> None:
    context_payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    payload = build_payload(context_payload)
    write_payload(payload)
    health = payload["health"]
    print(f"Oracle Prop Feed Adapter wrote: {OUTPUT_PATH}")
    print(f"Pairs: {health['pair_count']} | Best Now: {health['best_now_count']} | Watch: {health['watch_needs_trigger_count']} | Shielded: {health['shielded_count']} | Rejected: {health['rejected_context_count']}")
    print(f"Micro watchlist: {health['micro_watchlist_count']}")


if __name__ == "__main__":
    main()
