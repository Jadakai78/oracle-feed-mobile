from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import csv
import json

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"
INPUT_PATH = LOG_DIR / "episode_excursion_outcomes_v1.jsonl"
JSON_OUTPUT_PATH = LOG_DIR / "episode_excursion_summary_v1.json"
CSV_OUTPUT_PATH = LOG_DIR / "episode_excursion_summary_v1.csv"
MIN_RESOLVED_SAMPLE = 30


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def outcome_rows(rows):
    valid = []
    for row in rows:
        if row.get("recordtype") != "EPISODEEXCURSIONOUTCOME":
            continue
        if not row.get("observationonly", False):
            continue
        if not isinstance(row.get("brackets"), list):
            continue
        valid.append(row)
    return valid


def empty_counts():
    return {
        "FORWARD_FIRST": 0,
        "BACKWARD_FIRST": 0,
        "UNRESOLVED": 0,
        "AMBIGUOUS_SAME_5M_BAR": 0,
        "OTHER": 0,
    }


def add_result(counts, value):
    result = str(value or "OTHER").upper()
    if result not in counts:
        result = "OTHER"
    counts[result] += 1


def expected_value_proxy(forward_rate, forward_pct, backward_pct):
    if forward_rate is None:
        return None
    return (forward_rate * forward_pct) - ((1 - forward_rate) * backward_pct)


def make_summary(key, counts, total_records, forward_pct, backward_pct):
    forward = counts["FORWARD_FIRST"]
    backward = counts["BACKWARD_FIRST"]
    unresolved = counts["UNRESOLVED"]
    ambiguous = counts["AMBIGUOUS_SAME_5M_BAR"]
    other = counts["OTHER"]
    resolved = forward + backward
    forward_rate = forward / resolved if resolved else None
    proxy = expected_value_proxy(forward_rate, forward_pct, backward_pct)
    return {
        **key,
        "settlement_records": total_records,
        "forward_first": forward,
        "backward_first": backward,
        "unresolved": unresolved,
        "ambiguous_same_5m_bar": ambiguous,
        "other_result": other,
        "resolved_count": resolved,
        "forward_first_rate_resolved": round(forward_rate, 6) if forward_rate is not None else None,
        "expected_value_proxy_pct_per_resolved": round(proxy, 6) if proxy is not None else None,
        "minimum_sample_threshold": MIN_RESOLVED_SAMPLE,
        "minimum_sample_met": resolved >= MIN_RESOLVED_SAMPLE,
        "interpretation": (
            "DESCRIPTIVE_ONLY_MINIMUM_SAMPLE_NOT_MET"
            if resolved < MIN_RESOLVED_SAMPLE
            else "DESCRIPTIVE_ONLY_NOT_A_TRADING_SIGNAL"
        ),
    }


def analyze(rows):
    aggregates = {}
    for row in rows:
        horizon_bars = row.get("horizon_bars")
        horizon_minutes = row.get("horizon_minutes")
        direction = str(row.get("episode_direction") or "UNKNOWN").upper()
        for bracket in row.get("brackets", []):
            if not isinstance(bracket, dict):
                continue
            name = str(bracket.get("name") or "UNNAMED")
            try:
                forward_pct = float(bracket.get("forward_pct"))
                backward_pct = float(bracket.get("backward_pct"))
            except (TypeError, ValueError):
                continue
            key = (horizon_bars, horizon_minutes, direction, name, forward_pct, backward_pct)
            if key not in aggregates:
                aggregates[key] = {"counts": empty_counts(), "records": 0}
            aggregates[key]["records"] += 1
            add_result(aggregates[key]["counts"], bracket.get("result"))

    summaries = []
    for key, value in sorted(aggregates.items(), key=lambda item: (str(item[0][0]), str(item[0][2]), item[0][3])):
        horizon_bars, horizon_minutes, direction, name, forward_pct, backward_pct = key
        summaries.append(make_summary(
            {
                "segment": "HORIZON_DIRECTION_BRACKET",
                "horizon_bars": horizon_bars,
                "horizon_minutes": horizon_minutes,
                "episode_direction": direction,
                "bracket": name,
                "forward_pct": forward_pct,
                "backward_pct": backward_pct,
            },
            value["counts"],
            value["records"],
            forward_pct,
            backward_pct,
        ))
    return summaries


def write_csv(rows):
    fields = [
        "segment", "horizon_bars", "horizon_minutes", "episode_direction", "bracket",
        "forward_pct", "backward_pct", "settlement_records", "forward_first", "backward_first",
        "unresolved", "ambiguous_same_5m_bar", "other_result", "resolved_count",
        "forward_first_rate_resolved", "expected_value_proxy_pct_per_resolved",
        "minimum_sample_threshold", "minimum_sample_met", "interpretation",
    ]
    with CSV_OUTPUT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    source = load_jsonl(INPUT_PATH)
    if not INPUT_PATH.exists():
        raise SystemExit(f"Missing outcome ledger: {INPUT_PATH}")
    rows = outcome_rows(source)
    summaries = analyze(rows)
    payload = {
        "recordtype": "EPISODEEXCURSIONSUMMARY",
        "schemaversion": "episodeexcursionanalyzev1",
        "observationonly": True,
        "doesnotauthorizetrade": True,
        "doesnotchangequeue": True,
        "source_file": INPUT_PATH.name,
        "created_at_utc": now_utc(),
        "minimum_resolved_sample": MIN_RESOLVED_SAMPLE,
        "input_rows": len(source),
        "eligible_outcome_records": len(rows),
        "segments": summaries,
    }
    with JSON_OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    write_csv(summaries)

    print(f"Input ledger rows: {len(source)}")
    print(f"Eligible outcome records: {len(rows)}")
    print(f"Summary segments: {len(summaries)}")
    print(f"JSON summary: {JSON_OUTPUT_PATH}")
    print(f"CSV summary: {CSV_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
