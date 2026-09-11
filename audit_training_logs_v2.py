from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OBSERVATION_LOGS = {
    "gimba_drive", "gimba_pulse", "gimba_range", "gimba_trend",
    "gimba_volatile", "rts_liquidation", "shadow_trend_recovery", "shadow_volatile",
}
AUDIT_ONLY_LOGS = {"shadow_audit_ledger"}


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_text(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None else default


def event_bar(record: dict[str, Any]) -> str:
    flow = as_dict(record.get("volume_flow"))
    diagnostics = as_dict(record.get("diagnostics"))
    for value in (flow.get("bar_start"), diagnostics.get("reference_bar_start"), record.get("reference_bar_ts")):
        if value is not None:
            return as_text(value)
    parts = as_text(record.get("event_key")).split("|")
    if len(parts) >= 4 and parts[-1]:
        return parts[-1]
    return as_text(record.get("ts") or record.get("timestamp"))


def canonical_event_id(record: dict[str, Any]) -> str | None:
    pair = as_text(record.get("pair"))
    bar = event_bar(record)
    if not pair or not bar:
        return None
    return f"{pair}|15m|{bar}"


def label_info(record: dict[str, Any]) -> dict[str, Any]:
    value = as_dict(record.get("outcome"))
    return {
        "source": as_text(record.get("bot"), "unknown"),
        "status": as_text(value.get("status"), "pending"),
        "label": value.get("label"),
        "reason": as_text(value.get("reason")),
        "geometry": {"entry": record.get("entry"), "invalidation": record.get("sl"), "target": record.get("tp")},
    }


def source_summary(name: str, records: list[dict[str, Any]], parse_rejections: int) -> dict[str, Any]:
    fields = Counter()
    pairs, event_ids, times = set(), set(), []
    actions, directions, outcomes = Counter(), Counter(), Counter()
    for record in records:
        fields.update(record.keys())
        pairs.add(as_text(record.get("pair"), "UNKNOWN"))
        key = canonical_event_id(record)
        if key:
            event_ids.add(key)
        stamp = as_text(record.get("ts") or record.get("timestamp"))
        if stamp:
            times.append(stamp)
        directions[as_text(record.get("bias") or record.get("side"), "NONE")] += 1
        actions[as_text(record.get("action") or record.get("action_state"), "unknown")] += 1
        outcome = as_dict(record.get("outcome"))
        outcomes[f"{as_text(outcome.get('status'), 'pending')}:{outcome.get('label')}"] += 1
    return {
        "source": name,
        "classification": "observation_candidate" if name in OBSERVATION_LOGS else "audit_only",
        "records": len(records),
        "unique_pair_candle_events": len(event_ids),
        "parse_rejections": parse_rejections,
        "pairs": sorted(pairs),
        "date_start": min(times) if times else None,
        "date_end": max(times) if times else None,
        "direction_counts": dict(directions),
        "action_counts": dict(actions),
        "outcome_counts": dict(outcomes),
        "top_level_field_coverage": dict(sorted(fields.items())),
    }


def normalize(records: list[dict[str, Any]]) -> dict[str, Any]:
    records = sorted(records, key=lambda r: as_text(r.get("ts") or r.get("timestamp")))
    first = records[0]
    structure = next((as_dict(r.get("structure")) for r in records if as_dict(r.get("structure"))), {})
    flow = next((as_dict(r.get("volume_flow")) for r in records if as_dict(r.get("volume_flow"))), {})
    noise = next((as_dict(r.get("market_noise")) for r in records if as_dict(r.get("market_noise"))), {})
    timing = next((as_dict(r.get("market_timing")) for r in records if as_dict(r.get("market_timing"))), {})
    evidence = []
    for record in records:
        evidence.append({
            "source": as_text(record.get("bot"), "unknown"),
            "setup_type": as_text(record.get("setup_type") or record.get("state") or record.get("setup_family")),
            "direction": as_text(record.get("bias") or record.get("side"), "NONE"),
            "action": as_text(record.get("action") or record.get("action_state"), "unknown"),
            "conviction": record.get("conviction"),
            "trap_score": record.get("trap_score"),
            "why": as_text(record.get("why")),
        })
    return {
        "brain_version": "1.0",
        "event_id": canonical_event_id(first),
        "observed_at": as_text(first.get("ts") or first.get("timestamp")),
        "pair": as_text(first.get("pair")),
        "timeframe": "15m",
        "trend": {"higher_timeframe_direction": as_text(structure.get("trend") or structure.get("d1_trend"), "UNKNOWN"), "raw": structure},
        "alignment": {"state": as_text(structure.get("state") or structure.get("market_condition"), "UNKNOWN"), "zone": as_text(structure.get("zone"), "UNKNOWN"), "equilibrium_position": structure.get("eq_pct")},
        "pressure": {"ready": flow.get("ready"), "volume_state": as_text(flow.get("volume_state"), "UNKNOWN"), "delta": flow.get("delta"), "delta_norm": flow.get("delta_norm"), "delta_state": as_text(flow.get("delta_state"), "UNKNOWN"), "cvd": flow.get("cvd"), "cvd_slope": flow.get("cvd_slope")},
        "participation": {"volume": flow.get("volume"), "volume_norm": flow.get("volume_norm"), "volatility_state": as_text(structure.get("volatility_state"), "UNKNOWN")},
        "terrain": {"noise": noise, "timing": timing},
        "legacy_evidence": {"source_count": len(records), "sources": sorted({as_text(r.get("bot"), "unknown") for r in records}), "signals": evidence},
        "legacy_outcomes": [label_info(record) for record in records],
        "eight_gates_outcome": {"status": "legacy_context_only", "label": None},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only audit and normalization of legacy training logs.")
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    source_dir, out_dir = args.source_dir.resolve(), args.out_dir.resolve()
    if not source_dir.is_dir():
        raise SystemExit(f"Source directory not found: {source_dir}")
    (out_dir / "training").mkdir(parents=True, exist_ok=True)

    source_records: dict[str, list[dict[str, Any]]] = {}
    rejected, all_observations = [], []
    for path in sorted(source_dir.glob("*.jsonl")):
        name = path.stem
        if name not in OBSERVATION_LOGS | AUDIT_ONLY_LOGS:
            continue
        valid, rejects = [], 0
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("JSON value is not an object")
            except Exception as exc:
                rejects += 1
                rejected.append({"source_file": path.name, "line": line_no, "reason": type(exc).__name__, "raw": line[:2000]})
                continue
            record["bot"] = as_text(record.get("bot"), name)
            valid.append(record)
            if name in OBSERVATION_LOGS:
                event = canonical_event_id(record)
                if event:
                    all_observations.append(record)
                else:
                    rejected.append({"source_file": path.name, "line": line_no, "reason": "missing_pair_or_event_bar", "raw": json.dumps(record, ensure_ascii=False)[:2000]})
        source_records[name] = valid
        source_records[f"{name}__parse_rejections"] = rejects

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in all_observations:
        groups[canonical_event_id(record)].append(record)
    brain = [normalize(records) for _, records in sorted(groups.items())]
    source_summaries = [source_summary(name, records, int(source_records[f"{name}__parse_rejections"])) for name, records in source_records.items() if not name.endswith("__parse_rejections")]
    total_records = sum(summary["records"] for summary in source_summaries)
    candidate_records = len(all_observations)
    audit = {
        "audit_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(source_dir),
        "source_logs": source_summaries,
        "total_source_records": total_records,
        "observation_candidate_records": candidate_records,
        "canonical_pair_candle_events": len(brain),
        "cross_log_duplicate_candidate_records": candidate_records - len(brain),
        "rejected_records": len(rejected),
        "audit_only_sources": sorted(AUDIT_ONLY_LOGS),
        "outcome_policy": "Legacy outcomes retain original source geometry and remain context-only until native Eight Gates outcomes exist.",
    }
    index = {
        "brain_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canonical_events": len(brain),
        "pairs": sorted({row["pair"] for row in brain}),
        "sources_per_event": dict(Counter(str(row["legacy_evidence"]["source_count"]) for row in brain)),
        "outcome_policy": audit["outcome_policy"],
    }
    (out_dir / "training_audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "eight_gates_brain_index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "rejected_legacy_records.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rejected), encoding="utf-8")
    (out_dir / "training" / "eight_gates_brain.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in brain), encoding="utf-8")
    print(json.dumps({"total_source_records": total_records, "candidate_records": candidate_records, "canonical_events": len(brain), "rejected_records": len(rejected), "out_dir": str(out_dir)}, indent=2))


if __name__ == "__main__":
    main()
