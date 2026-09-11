from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import json

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"
INPUT_PATH = LOG_DIR / "episode_excursion_outcomes_v1.jsonl"
JSON_OUTPUT_PATH = LOG_DIR / "episode_excursion_cluster_audit_v1.json"
CSV_OUTPUT_PATH = LOG_DIR / "episode_excursion_cluster_audit_v1.csv"
CLUSTER_GAP_MINUTES = 30
MIN_CLUSTER_SAMPLE = 10


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def valid_rows(rows):
    output = []
    for row in rows:
        if row.get("recordtype") != "EPISODEEXCURSIONOUTCOME":
            continue
        opened_at = parse_time(row.get("episode_opened_at_utc"))
        if opened_at is None or not row.get("episode_id"):
            continue
        output.append({**row, "_opened_at": opened_at})
    return output


def make_clusters(rows):
    clusters = []
    grouped = defaultdict(list)
    for row in rows:
        direction = str(row.get("episode_direction") or "UNKNOWN").upper()
        grouped[direction].append(row)

    next_id = 1
    for direction, members in grouped.items():
        members.sort(key=lambda row: row["_opened_at"])
        current = []
        previous = None
        for row in members:
            if previous is not None:
                gap = (row["_opened_at"] - previous).total_seconds() / 60
                if gap > CLUSTER_GAP_MINUTES:
                    clusters.append((f"CL{next_id:04d}", direction, current))
                    next_id += 1
                    current = []
            current.append(row)
            previous = row["_opened_at"]
        if current:
            clusters.append((f"CL{next_id:04d}", direction, current))
            next_id += 1
    return clusters


def result_counts(rows, bracket_name):
    counts = Counter()
    for row in rows:
        for bracket in row.get("brackets", []):
            if str(bracket.get("name")) == bracket_name:
                counts[str(bracket.get("result") or "OTHER").upper()] += 1
    return counts


def rate(counts):
    forward = counts["FORWARD_FIRST"]
    backward = counts["BACKWARD_FIRST"]
    resolved = forward + backward
    return (forward / resolved if resolved else None), resolved


def cluster_record(cluster_id, direction, rows):
    symbols = Counter(str(row.get("kraken_symbol") or "UNKNOWN") for row in rows)
    opened = [row["_opened_at"] for row in rows]
    return {
        "cluster_id": cluster_id,
        "episode_direction": direction,
        "episode_count": len(rows),
        "unique_symbols": len(symbols),
        "largest_symbol": symbols.most_common(1)[0][0],
        "largest_symbol_episode_count": symbols.most_common(1)[0][1],
        "opened_at_first_utc": min(opened).isoformat(),
        "opened_at_last_utc": max(opened).isoformat(),
    }


def summarize(rows, clusters):
    bracket_names = sorted({
        str(bracket.get("name"))
        for row in rows
        for bracket in row.get("brackets", [])
        if isinstance(bracket, dict) and bracket.get("name")
    })
    output = []
    for horizon in sorted({row.get("horizon_bars") for row in rows}, key=str):
        for direction in sorted({str(row.get("episode_direction") or "UNKNOWN").upper() for row in rows}):
            scoped = [row for row in rows if row.get("horizon_bars") == horizon and str(row.get("episode_direction") or "UNKNOWN").upper() == direction]
            cluster_ids = {row.get("episode_id"): cid for cid, cdir, members in clusters if cdir == direction for row in members}
            scoped_cluster_ids = {cluster_ids.get(row.get("episode_id")) for row in scoped} - {None}
            for bracket in bracket_names:
                counts = result_counts(scoped, bracket)
                raw_rate, resolved = rate(counts)
                winning_clusters = 0
                losing_clusters = 0
                tie_clusters = 0
                for cluster_id in scoped_cluster_ids:
                    members = [row for row in scoped if cluster_ids.get(row.get("episode_id")) == cluster_id]
                    cc = result_counts(members, bracket)
                    if cc["FORWARD_FIRST"] > cc["BACKWARD_FIRST"]:
                        winning_clusters += 1
                    elif cc["BACKWARD_FIRST"] > cc["FORWARD_FIRST"]:
                        losing_clusters += 1
                    else:
                        tie_clusters += 1
                decided_clusters = winning_clusters + losing_clusters
                output.append({
                    "horizon_bars": horizon,
                    "horizon_minutes": int(horizon) * 5 if str(horizon).isdigit() else None,
                    "episode_direction": direction,
                    "bracket": bracket,
                    "episode_records": len(scoped),
                    "resolved_episode_records": resolved,
                    "raw_forward_first_rate": round(raw_rate, 6) if raw_rate is not None else None,
                    "clusters": len(scoped_cluster_ids),
                    "forward_dominant_clusters": winning_clusters,
                    "backward_dominant_clusters": losing_clusters,
                    "tied_or_unresolved_clusters": tie_clusters,
                    "cluster_forward_dominance_rate": round(winning_clusters / decided_clusters, 6) if decided_clusters else None,
                    "minimum_cluster_sample": MIN_CLUSTER_SAMPLE,
                    "minimum_cluster_sample_met": len(scoped_cluster_ids) >= MIN_CLUSTER_SAMPLE,
                    "interpretation": "DESCRIPTIVE_ONLY_NOT_A_TRADING_SIGNAL",
                })
    return output


def main():
    if not INPUT_PATH.exists():
        raise SystemExit(f"Missing outcome ledger: {INPUT_PATH}")
    rows = valid_rows(load_jsonl(INPUT_PATH))
    clusters = make_clusters(rows)
    cluster_rows = [cluster_record(cluster_id, direction, members) for cluster_id, direction, members in clusters]
    summaries = summarize(rows, clusters)

    payload = {
        "recordtype": "EPISODECLUSTERAUDIT",
        "schemaversion": "episodeexcursionclusterauditv1",
        "observationonly": True,
        "doesnotauthorizetrade": True,
        "doesnotchangequeue": True,
        "source_file": INPUT_PATH.name,
        "created_at_utc": now_utc(),
        "cluster_gap_minutes": CLUSTER_GAP_MINUTES,
        "input_outcome_records": len(rows),
        "clusters": cluster_rows,
        "summary": summaries,
    }
    with JSON_OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    fields = list(summaries[0].keys()) if summaries else ["horizon_bars", "episode_direction", "bracket"]
    with CSV_OUTPUT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summaries)

    print(f"Input outcome records: {len(rows)}")
    print(f"Episode clusters: {len(clusters)}")
    print(f"Summary rows: {len(summaries)}")
    print(f"JSON audit: {JSON_OUTPUT_PATH}")
    print(f"CSV audit: {CSV_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
