"""
prism_ledger_validator_v1.py — PRISM clean-room read-only ledger validator.

CLI usage:
    python prism_ledger_validator_v1.py OBSERVATIONS_JSONL STATE_JSON

Never writes or repairs any file. Exit code 0 for PASS, 1 for FAIL.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from prism_common_v1 import BAR_INTERVAL, is_finite_number, parse_utc, scan_forbidden_keys

EXPECTED_RECORDTYPE = "PRISM_WIDTH_REGIME_OBSERVATION"
EXPECTED_SCHEMA_VERSION = "prism_width_regime_v1"
EXPECTED_ID_SUFFIX = "PRISM_WIDTH_REGIME_V1"

REQUIRED_TERRAIN_KEYS = {"state", "zone", "middle_slope", "bandwidth"}
REQUIRED_WIDTH_KEYS = {
    "state",
    "current_width",
    "prior_width_count",
    "width_slope",
    "width_percentile",
    "regime",
}

VALID_ZONES = {
    "EXTREME_LOWER_DISPLACEMENT",
    "LOWER_OUTER_ZONE",
    "LOWER_VALUE_ZONE",
    "CENTRAL_ROTATION_ZONE",
    "UPPER_VALUE_ZONE",
    "UPPER_OUTER_ZONE",
    "EXTREME_UPPER_DISPLACEMENT",
}
VALID_MIDDLE_SLOPES = {"UP", "DOWN", "FLAT", "UNAVAILABLE"}
VALID_WIDTH_SLOPES = {"UP", "DOWN", "FLAT", "UNAVAILABLE"}
VALID_REGIMES = {
    "WIDTH_CONTRACTING",
    "WIDTH_COMPRESSED",
    "WIDTH_EXPANDING",
    "WIDTH_ELEVATED",
    "WIDTH_NEUTRAL",
    "WIDTH_UNAVAILABLE",
}


def _load_state_strict(state_path: Path) -> tuple[dict | None, str | None]:
    """Strict state load for validation purposes: unlike the ledger's own
    recovery-safe load_state(), a missing or corrupt state file here is an
    explicit validation failure, not a silent normalization to empty."""
    state_path = Path(state_path)
    if not state_path.exists():
        return None, f"state file not found: {state_path}"
    try:
        raw = state_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"state file is corrupt or unreadable: {exc}"

    if not isinstance(data, dict):
        return None, "state file does not contain a JSON object"

    observation_ids = data.get("observation_ids")
    outcome_ids = data.get("outcome_ids")
    if not isinstance(observation_ids, list) or not all(isinstance(item, str) for item in observation_ids):
        return None, "state.observation_ids missing or malformed"
    if not isinstance(outcome_ids, list) or not all(isinstance(item, str) for item in outcome_ids):
        return None, "state.outcome_ids missing or malformed"

    return {"observation_ids": list(observation_ids), "outcome_ids": list(outcome_ids)}, None


def _record_issues(index: int, record: Any) -> list[str]:
    issues: list[str] = []
    prefix = f"line {index}"

    if not isinstance(record, dict):
        return [f"{prefix}: not a JSON object"]

    forbidden = scan_forbidden_keys(record)
    if forbidden:
        issues.append(f"{prefix}: forbidden keys present: {forbidden}")

    if record.get("recordtype") != EXPECTED_RECORDTYPE:
        issues.append(f"{prefix}: unexpected recordtype {record.get('recordtype')!r}")
    if record.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        issues.append(f"{prefix}: unexpected schema_version {record.get('schema_version')!r}")
    if record.get("status") != "OPEN":
        issues.append(f"{prefix}: status must remain OPEN, found {record.get('status')!r}")

    for flag in ("manual_review_only", "does_not_authorize_trade", "does_not_simulate_order"):
        if record.get(flag) is not True:
            issues.append(f"{prefix}: safety flag {flag!r} is not True")

    pair = record.get("pair")
    timeframe = record.get("timeframe")
    close_utc = record.get("reference_bar_close_utc")
    observation_id = record.get("observation_id")

    if isinstance(pair, str) and isinstance(timeframe, str) and isinstance(close_utc, str):
        expected_id = f"{pair}|{timeframe}|{close_utc}|{EXPECTED_ID_SUFFIX}"
        if observation_id != expected_id:
            issues.append(f"{prefix}: observation_id {observation_id!r} != expected {expected_id!r}")
    else:
        issues.append(f"{prefix}: pair/timeframe/reference_bar_close_utc missing or wrong type")

    parsed_close = parse_utc(close_utc)
    if parsed_close is None:
        issues.append(f"{prefix}: reference_bar_close_utc not parseable UTC: {close_utc!r}")
    elif parsed_close.minute % 15 != 0 or parsed_close.second != 0 or parsed_close.microsecond != 0:
        issues.append(f"{prefix}: reference_bar_close_utc not 15-minute aligned: {close_utc!r}")

    price = record.get("reference_price")
    if not is_finite_number(price) or price <= 0:
        issues.append(f"{prefix}: reference_price not a positive finite number: {price!r}")

    width = record.get("width")
    if not isinstance(width, dict):
        issues.append(f"{prefix}: width is not an object")
    else:
        missing_width_keys = REQUIRED_WIDTH_KEYS.difference(width)
        if missing_width_keys:
            issues.append(f"{prefix}: width missing keys: {sorted(missing_width_keys)}")

        if width.get("prior_width_count") != 25:
            issues.append(f"{prefix}: width.prior_width_count != 25: {width.get('prior_width_count')!r}")
        if width.get("state") != "AVAILABLE":
            issues.append(f"{prefix}: width.state != AVAILABLE: {width.get('state')!r}")

        current_width = width.get("current_width")
        if not is_finite_number(current_width):
            issues.append(f"{prefix}: width.current_width is not a finite number: {current_width!r}")

        percentile = width.get("width_percentile")
        if not is_finite_number(percentile) or not (0.0 <= percentile <= 1.0):
            issues.append(f"{prefix}: width.width_percentile out of range: {percentile!r}")

        width_slope = width.get("width_slope")
        if width_slope not in VALID_WIDTH_SLOPES:
            issues.append(f"{prefix}: width.width_slope unknown label: {width_slope!r}")

        regime = width.get("regime")
        if regime not in VALID_REGIMES:
            issues.append(f"{prefix}: width.regime unknown label: {regime!r}")

        # An OPEN record with width.state == AVAILABLE has, by construction,
        # a valid classification — WIDTH_UNAVAILABLE in that combination is
        # an internal contradiction, not a legitimate descriptive state.
        if record.get("status") == "OPEN" and width.get("state") == "AVAILABLE" and regime == "WIDTH_UNAVAILABLE":
            issues.append(f"{prefix}: contradiction: OPEN record with width.state AVAILABLE but regime WIDTH_UNAVAILABLE")

    terrain = record.get("terrain")
    if not isinstance(terrain, dict):
        issues.append(f"{prefix}: terrain is not an object")
    else:
        missing_terrain_keys = REQUIRED_TERRAIN_KEYS.difference(terrain)
        if missing_terrain_keys:
            issues.append(f"{prefix}: terrain missing keys: {sorted(missing_terrain_keys)}")

        if terrain.get("state") != "AVAILABLE":
            issues.append(f"{prefix}: terrain.state != AVAILABLE: {terrain.get('state')!r}")

        zone = terrain.get("zone")
        if zone not in VALID_ZONES:
            issues.append(f"{prefix}: terrain.zone unknown label: {zone!r}")

        middle_slope = terrain.get("middle_slope")
        if middle_slope not in VALID_MIDDLE_SLOPES:
            issues.append(f"{prefix}: terrain.middle_slope unknown label: {middle_slope!r}")

        bandwidth = terrain.get("bandwidth")
        if not is_finite_number(bandwidth):
            issues.append(f"{prefix}: terrain.bandwidth is not a finite number: {bandwidth!r}")

    return issues


def validate_ledger(observations_path: Path, state_path: Path) -> tuple[bool, list[str], str]:
    observations_path = Path(observations_path)
    issues: list[str] = []

    if not observations_path.exists():
        return False, [f"observations file not found: {observations_path}"], ""

    lines = [line for line in observations_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    records: list[dict] = []

    for index, raw_line in enumerate(lines, start=1):
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            issues.append(f"line {index}: invalid JSON: {exc}")
            continue
        issues.extend(_record_issues(index, record))
        if isinstance(record, dict):
            records.append(record)

    ids = [record.get("observation_id") for record in records if isinstance(record.get("observation_id"), str)]
    id_counts = Counter(ids)
    duplicates = {obs_id: count for obs_id, count in id_counts.items() if count > 1}
    if duplicates:
        issues.append(f"duplicate observation_id values: {duplicates}")

    parsed_all = [parse_utc(record.get("reference_bar_close_utc")) for record in records]
    valid_pairs = [(ts, idx) for idx, ts in enumerate(parsed_all, start=1) if ts is not None]
    notes: list[str] = []
    for (earlier, idx_e), (later, idx_l) in zip(valid_pairs, valid_pairs[1:]):
        if later <= earlier:
            issues.append(f"line {idx_l}: timestamp not strictly increasing after line {idx_e}")
        else:
            skipped = int((later - earlier) / BAR_INTERVAL) - 1
            if skipped > 0:
                notes.append(
                    f"informational: {skipped} skipped 15m interval(s) between line {idx_e} and line {idx_l}"
                )

    jsonl_id_set = set(ids)

    state, state_error = _load_state_strict(state_path)
    if state_error is not None:
        issues.append(f"state validation failed: {state_error}")
    else:
        state_id_set = set(state["observation_ids"])
        if jsonl_id_set != state_id_set:
            only_jsonl = sorted(jsonl_id_set - state_id_set)
            only_state = sorted(state_id_set - jsonl_id_set)
            issues.append(
                f"observation_id set mismatch between JSONL and state: "
                f"only_in_jsonl={only_jsonl} only_in_state={only_state}"
            )

        outcome_id_set = set(state.get("outcome_ids", []))
        unknown_outcomes = sorted(outcome_id_set - jsonl_id_set)
        if unknown_outcomes:
            issues.append(f"state.outcome_ids references unknown observation ids: {unknown_outcomes}")

    regime_counts = Counter(
        (record.get("width") or {}).get("regime") for record in records if isinstance(record.get("width"), dict)
    )
    pair_counts = Counter(record.get("pair") for record in records)

    summary_lines = [
        f"Row count: {len(lines)}",
        f"Unique observation_id count: {len(jsonl_id_set)}",
        f"Pair counts: {dict(pair_counts)}",
        f"Regime distribution: {dict(regime_counts)}",
    ]
    summary_lines.extend(notes)
    summary = "\n".join(summary_lines)

    return (len(issues) == 0), issues, summary


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python prism_ledger_validator_v1.py OBSERVATIONS_JSONL STATE_JSON")
        return 1

    observations_path = Path(argv[1])
    state_path = Path(argv[2])

    ok, issues, summary = validate_ledger(observations_path, state_path)

    print(summary)
    if not ok:
        print(f"\nFAIL: {len(issues)} issue(s):")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
