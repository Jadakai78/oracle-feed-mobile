from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Optional
import argparse
import json
import math

TOURNAMENT_VERSION = "shadow_tournament_v2_delta_tempo"
DELTA_TEMPO_LANE = "DELTA_TEMPO_KNN_V1"
LEGACY_LANES = {"ORACLE_DRIVE_FIXED_V1", "ORACLE_DRIVE_ADAPTIVE_V1", "ORACLE_AI_EXPLORER_V1"}
DECISIONS = {"TAKE", "PASS", "ABSTAIN"}
SIDES = {"LONG", "SHORT"}
SETUP_SOURCES = {"RANGE", "RTS", "DRIVE", "PULSE"}
ACTIVE_CARD_STATES = {"DISPLAYED", "ARMED"}


class ArenaReject(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_key(prefix: str, payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"{prefix}_{sha256(encoded).hexdigest()[:20]}"


def finite_number(value: Any, name: str) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ArenaReject(f"invalid_{name}") from exc
    if not math.isfinite(value):
        raise ArenaReject(f"invalid_{name}")
    return value


def text(value: Any, name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ArenaReject(f"missing_{name}")
    return value


def normalized_direction(value: Any, name: str) -> str:
    value = text(value, name).upper()
    aliases = {"UP": "LONG", "BUY": "LONG", "LONG": "LONG", "DOWN": "SHORT", "SELL": "SHORT", "SHORT": "SHORT"}
    if value not in aliases:
        raise ArenaReject(f"invalid_{name}")
    return aliases[value]


@dataclass(frozen=True)
class TournamentDecision:
    event_key: str
    lane: str
    oracle_event_key: str
    decision_ts: str
    pair: str
    decision: str
    side: Optional[str]
    entry: Optional[float]
    entry_reference: Optional[str]
    sl: Optional[float]
    tp: Optional[float]
    horizon_bars: Optional[int]
    risk_distance: Optional[float]
    model_or_rule_version: str
    feature_schema_version: Optional[str]
    confidence: Optional[float]
    reason: str


class ShadowTournamentArena:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.log_dir = self.root / "training_logs" / "shadow_tournament"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.oracle_log = self.log_dir / "oracle_packets.jsonl"
        self.transition_log = self.log_dir / "oracle_transitions.jsonl"
        self.decision_log = self.log_dir / "decisions.jsonl"
        self.rejection_log = self.log_dir / "rejections.jsonl"
        self.delta_event_log = self.log_dir / "delta_tempo_prop_feed_events.jsonl"
        self.entry_card_log = self.log_dir / "delta_tempo_prop_entry_cards.jsonl"

    def _append(self, path: Path, record: Dict[str, Any]) -> None:
        record = {**record, "written_at": utc_now(), "tournament_version": TOURNAMENT_VERSION}
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
            handle.flush()

    def _read_jsonl(self, path: Path):
        if not path.exists():
            return []
        rows = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def _reject(self, payload: Dict[str, Any], reason: str) -> str:
        rejected = {"record_type": "DECISION_REJECTED", "rejection_reason": reason, "lane": payload.get("lane"), "pair": payload.get("pair"), "oracle_event_key": payload.get("oracle_event_key"), "decision": payload.get("decision"), "original_payload": payload}
        key = str(payload.get("event_key") or stable_key("reject", rejected))
        rejected["event_key"] = key
        self._append(self.rejection_log, rejected)
        return key

    def _active_card(self, pair: str) -> Optional[Dict[str, Any]]:
        state = None
        for row in self._read_jsonl(self.entry_card_log):
            if row.get("pair") == pair:
                state = row
        return state if state and state.get("card_state") in ACTIVE_CARD_STATES else None

    def write_decision(self, payload: Dict[str, Any]) -> str:
        try:
            lane = text(payload.get("lane"), "lane").upper()
            if lane in LEGACY_LANES:
                raise ArenaReject("entry_authority_is_delta_tempo_only")
            if lane != DELTA_TEMPO_LANE:
                raise ArenaReject("unknown_lane")
            decision = text(payload.get("decision"), "decision").upper()
            if decision not in DECISIONS:
                raise ArenaReject("invalid_decision")
            pair = text(payload.get("pair"), "pair").replace("/", "")
            common = {"lane": lane, "oracle_event_key": text(payload.get("oracle_event_key"), "oracle_event_key"), "decision_ts": text(payload.get("decision_ts"), "decision_ts"), "pair": pair, "decision": decision, "model_or_rule_version": text(payload.get("model_or_rule_version"), "model_or_rule_version"), "feature_schema_version": payload.get("feature_schema_version"), "confidence": payload.get("confidence"), "reason": text(payload.get("reason"), "reason")}
            if common["confidence"] is not None:
                common["confidence"] = finite_number(common["confidence"], "confidence")
                if not 0 <= common["confidence"] <= 1:
                    raise ArenaReject("invalid_confidence")
            if decision != "TAKE":
                body = {**common, "side": None, "entry": None, "entry_reference": None, "sl": None, "tp": None, "horizon_bars": None, "risk_distance": None}
            else:
                side = normalized_direction(payload.get("side"), "side")
                entry, sl, tp = finite_number(payload.get("entry"), "entry"), finite_number(payload.get("sl"), "sl"), finite_number(payload.get("tp"), "tp")
                horizon = int(finite_number(payload.get("horizon_bars"), "horizon_bars"))
                if horizon < 1:
                    raise ArenaReject("invalid_horizon_bars")
                if side == "LONG" and not sl < entry < tp:
                    raise ArenaReject("invalid_long_geometry")
                if side == "SHORT" and not tp < entry < sl:
                    raise ArenaReject("invalid_short_geometry")
                body = {**common, "side": side, "entry": entry, "entry_reference": text(payload.get("entry_reference"), "entry_reference"), "sl": sl, "tp": tp, "horizon_bars": horizon, "risk_distance": abs(entry - sl)}
            key = str(payload.get("event_key") or stable_key("decision", body))
            self._append(self.decision_log, {"record_type": "TOURNAMENT_DECISION", "status": "PENDING", "event_key": key, **body})
            return key
        except ArenaReject as exc:
            return self._reject(payload, str(exc))

    def write_delta_tempo_candidate(self, payload: Dict[str, Any]) -> str:
        try:
            pair = text(payload.get("pair"), "pair").replace("/", "")
            side = normalized_direction(payload.get("delta_direction"), "delta_direction")
            if not bool(payload.get("speed_available")):
                raise ArenaReject("speed_unavailable")
            if not bool(payload.get("timely_for_next_bar")):
                raise ArenaReject("missed_timing")
            if normalized_direction(payload.get("pressure_direction"), "pressure_direction") != side:
                raise ArenaReject("pressure_not_aligned")
            if normalized_direction(payload.get("cvd_slope_direction"), "cvd_slope_direction") != side:
                raise ArenaReject("cvd_slope_not_aligned")
            if not bool(payload.get("timing_confluence_fresh")):
                raise ArenaReject("stale_timing_confluence")
            lifecycle = text(payload.get("tempo_lifecycle"), "tempo_lifecycle").upper()
            if lifecycle in {"SPEED_DECAYING", "DECAYING", "SPEED_MISSING"}:
                raise ArenaReject("tempo_decaying_or_missing")
            if not bool(payload.get("hma7_confirmed")):
                raise ArenaReject("hma7_not_confirmed")
            claims = payload.get("setup_claims") or []
            if not isinstance(claims, list):
                raise ArenaReject("invalid_setup_claims")
            sources = {str(item.get("source") if isinstance(item, dict) else item).upper() for item in claims}
            used_sources = sorted(sources & SETUP_SOURCES)
            if not used_sources:
                raise ArenaReject("no_fresh_range_rts_drive_or_pulse_claim")
            if self._active_card(pair):
                raise ArenaReject("active_delta_tempo_card_exists")
            knn_score = finite_number(payload.get("knn_score"), "knn_score")
            if not 0 <= knn_score <= 1:
                raise ArenaReject("invalid_knn_score")
            reason = " + ".join([f"delta_{side.lower()}", f"pressure_{side.lower()}", f"cvd_{side.lower()}", lifecycle.lower(), "hma7_confirmed", "setups_" + "+".join(used_sources).lower()])
            decision_payload = {"lane": DELTA_TEMPO_LANE, "oracle_event_key": text(payload.get("oracle_event_key"), "oracle_event_key"), "decision_ts": payload.get("decision_ts") or utc_now(), "pair": pair, "decision": "TAKE", "side": side, "entry": payload.get("entry"), "entry_reference": payload.get("entry_reference", "delta_tempo_completed_bar"), "sl": payload.get("sl"), "tp": payload.get("tp"), "horizon_bars": payload.get("horizon_bars", 12), "model_or_rule_version": text(payload.get("model_or_rule_version"), "model_or_rule_version"), "feature_schema_version": payload.get("feature_schema_version", "delta_tempo_prop_v1"), "confidence": knn_score, "reason": reason}
            decision_key = self.write_decision(decision_payload)
            if decision_key.startswith("reject_"):
                return decision_key
            card = {"record_type": "DELTA_TEMPO_ENTRY_CARD", "card_state": "DISPLAYED", "event_key": stable_key("card", {"decision_key": decision_key, "pair": pair}), "decision_event_key": decision_key, "pair": pair, "side": side, "entry": decision_payload["entry"], "sl": decision_payload["sl"], "tp": decision_payload["tp"], "knn_score": knn_score, "tempo_lifecycle": lifecycle, "setup_sources": used_sources, "why_now": reason, "orders_enabled": False}
            self._append(self.entry_card_log, card)
            self._append(self.delta_event_log, {"record_type": "DELTA_TEMPO_STATE", "state": "ENTRY", "pair": pair, "decision_event_key": decision_key, "reason": reason, "orders_enabled": False})
            return decision_key
        except ArenaReject as exc:
            self._append(self.delta_event_log, {"record_type": "DELTA_TEMPO_STATE", "state": "WAITING", "pair": payload.get("pair"), "reason": str(exc), "orders_enabled": False})
            return self._reject(payload, str(exc))

    def remove_delta_tempo_card(self, pair: str, reason: str, source_event_key: Optional[str] = None) -> bool:
        pair = text(pair, "pair").replace("/", "")
        active = self._active_card(pair)
        if not active:
            return False
        reason = text(reason, "reason").upper()
        if reason not in {"TEMPO_DECAY", "HMA_LOST", "STALE_CONTEXT", "MISSED_TIMING", "INVALID_RISK_PACKET"}:
            raise ArenaReject("invalid_removal_reason")
        self._append(self.entry_card_log, {"record_type": "DELTA_TEMPO_ENTRY_CARD", "card_state": "REMOVED", "event_key": active["event_key"], "decision_event_key": active.get("decision_event_key"), "pair": pair, "removal_reason": reason, "source_event_key": source_event_key, "orders_enabled": False})
        self._append(self.delta_event_log, {"record_type": "DELTA_TEMPO_STATE", "state": "REMOVED", "pair": pair, "decision_event_key": active.get("decision_event_key"), "reason": reason, "orders_enabled": False})
        return True

    def health(self) -> Dict[str, Any]:
        return {"root": str(self.root), "log_dir": str(self.log_dir), "logs": {name: str(path) for name, path in {"oracle_packets": self.oracle_log, "transitions": self.transition_log, "decisions": self.decision_log, "rejections": self.rejection_log, "delta_tempo_events": self.delta_event_log, "delta_tempo_entry_cards": self.entry_card_log}.items()}, "live_execution": False, "entry_authority": "DELTA_TEMPO_ONLY", "accepted_lane": DELTA_TEMPO_LANE, "tournament_version": TOURNAMENT_VERSION}


def main() -> None:
    parser = argparse.ArgumentParser(description="Delta Tempo shadow arena. It cannot place orders.")
    parser.add_argument("--root", default=r"C:\Users\OneDrive\Desktop\jhl_v2\jhl_v2gimba")
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args()
    arena = ShadowTournamentArena(args.root)
    if args.health:
        print(json.dumps(arena.health(), indent=2))


if __name__ == "__main__":
    main()
