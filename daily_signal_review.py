"""Generate editable daily JHL signal reviews from read-only queue/map/coverage artifacts."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"
QUEUE_AUDIT = LOG_DIR / "kraken_btcc_top3_queue_audit.jsonl"
QUEUE_STATE = LOG_DIR / "kraken_btcc_top3_queue_state.json"
MAP_LATEST = LOG_DIR / "kraken_btcc_top3_map_latest.json"
COVERAGE = LOG_DIR / "btcc_kraken_coverage_audit.json"
REVIEWS = LOG_DIR / "daily_reviews"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def date_from_event(row: dict[str, Any]) -> str:
    value = str(row.get("timestamp_utc") or "")
    return value[:10] if len(value) >= 10 else ""


def coverage_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("kraken_symbol") or "").upper(): row for row in payload.get("included", []) if row.get("kraken_symbol")}


def map_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("kraken_symbol") or "").upper(): row for row in payload.get("candidates", []) if row.get("kraken_symbol")}


def map_summary(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"status": "UNAVAILABLE"}
    return {
        "status": row.get("status"),
        "alignment": row.get("alignment"),
        "4h_zone": (row.get("map_4h") or {}).get("location_zone"),
        "4h_z_score": (row.get("map_4h") or {}).get("z_score"),
        "1h_zone": (row.get("map_1h") or {}).get("location_zone"),
        "1h_z_score": (row.get("map_1h") or {}).get("z_score"),
    }


def blank_review(source: dict[str, Any], coverage: dict[str, Any] | None, mapped: dict[str, Any] | None) -> dict[str, Any]:
    candidate = source.get("candidate") or {}
    symbol = str(candidate.get("kraken_symbol") or "").upper()
    return {
        "source_event_type": source.get("event_type"),
        "source_timestamp_utc": source.get("timestamp_utc"),
        "source_reason": source.get("reason"),
        "system": {
            "kraken_symbol": symbol,
            "btcc_symbol": candidate.get("btcc_symbol") or (coverage or {}).get("btcc_symbol"),
            "direction": candidate.get("direction"),
            "score_pct": candidate.get("score_pct"),
            "last_price": candidate.get("last_price"),
            "admitted_at_utc": candidate.get("admitted_at_utc"),
            "data_venue": candidate.get("data_venue") or "KRAKEN_FUTURES",
            "execution_venue": candidate.get("execution_venue") or "BTCC",
            "quote_mismatch": candidate.get("quote_mismatch") or "KRAKEN_USD__BTCC_USDT",
            "map": map_summary(mapped),
            "manual_btcc_checks_required": (coverage or {}).get("manual_btcc_checks_required", []),
        },
        "trader_review": {
            "decision": "NOT_REVIEWED",
            "decision_reason": "",
            "entry": "",
            "stop": "",
            "targets": "",
            "risk_amount": "",
            "exit": "",
            "pnl": "",
            "result": "OPEN",
            "trader_read": "",
            "what_was_clean": "",
            "what_felt_wrong": "",
            "execution_quality": "",
            "price_acceptance": "",
            "delta_tempo_agreement": "",
            "drive_acceptance_agreement": "",
            "classification": [],
            "lesson": "",
            "suggested_system_change": "",
        },
    }


def markdown(review: dict[str, Any], date: str, drops: list[dict[str, Any]]) -> str:
    cards = review["signals"]
    lines = [
        "# JHL Daily Signal Review",
        f"Date: {date}",
        "Discovery venue: Kraken Futures",
        "Execution venue: BTCC USDT-M perpetuals — manual only",
        "Day status: OPEN | NO_TRADES_TAKEN | COMPLETE",
        "",
        "## Daily Notes",
        "Market tempo:",
        "What I saw:",
        "Reason no trades were taken, if applicable:",
        "",
        "## Signal Review Cards",
    ]
    if not cards:
        lines += ["", "No admission or replacement events were recorded for this date."]
    for i, card in enumerate(cards, 1):
        s = card["system"]
        m = s["map"]
        checks = ", ".join(s["manual_btcc_checks_required"]) or "contract_active, live_price, funding, spread_depth, liquidation_safety"
        lines += [
            "",
            f"### Signal {i:02d}",
            f"Source event: {card['source_event_type']} — {card['source_timestamp_utc']}",
            f"Reason: {card['source_reason']}",
            f"Pair: {s['kraken_symbol']} → {s['btcc_symbol']}",
            f"Ignition side: {s['direction']}",
            f"5m move: {s['score_pct']}",
            f"Kraken last: {s['last_price']}",
            f"Map: 4H {m.get('4h_zone')} ({m.get('4h_z_score')}σ) | 1H {m.get('1h_zone')} ({m.get('1h_z_score')}σ) | {m.get('alignment')}",
            f"BTCC preflight: {checks}",
            "",
            "Decision: TAKEN | PASSED | EXPIRED | NOT_REVIEWED",
            "Decision reason:",
            "",
            "#### If Taken",
            "Entry:",
            "Stop:",
            "Target(s):",
            "Risk amount:",
            "Exit:",
            "P&L:",
            "Result: WIN | LOSS | SCRATCH | OPEN",
            "",
            "Trader read before entry:",
            "What was clean:",
            "What felt wrong:",
            "Execution quality: EARLY | ON_TIME | LATE",
            "Price acceptance: YES | NO | UNCLEAR",
            "Delta / Tempo agreement: YES | NO | UNAVAILABLE",
            "Drive / Acceptance agreement: YES | NO | UNAVAILABLE",
            "",
            "Classification: LOCATION | TIMING | TRIGGER | STOP | TARGET | DELTA_CVD | DRIVE_ACCEPTANCE | MARKET_TEMPO | BTCC_MISMATCH | TRADER_EXECUTION | OTHER",
            "Lesson:",
            "Suggested system change:",
        ]
    lines += ["", "## Signals That Died"]
    if not drops:
        lines += ["", "No drop events were recorded for this date."]
    else:
        for row in drops:
            c = row.get("candidate") or {}
            lines.append(f"- {c.get('kraken_symbol')} → {c.get('btcc_symbol')} | {c.get('direction')} | drop reason: {row.get('reason')} | at: {row.get('timestamp_utc')}")
    lines += [
        "",
        "## Paste-Ready Trade Block",
        "```text",
        "JHL TRADE REVIEW",
        f"Date: {date}",
        "Pair / contract:",
        "State when taken:",
        "Direction:",
        "Market tempo:",
        "Map:",
        "Entry / stop / target:",
        "Exit / P&L:",
        "Result:",
        "Trader read:",
        "System read:",
        "What worked or failed:",
        "Category:",
        "One proposed upgrade:",
        "```",
        "",
        "Raw source files remain unchanged. This review is a human-editable companion record.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    date = args.date

    events = [row for row in read_jsonl(QUEUE_AUDIT) if date_from_event(row) == date]
    coverage = coverage_index(read_json(COVERAGE, {}))
    maps = map_index(read_json(MAP_LATEST, {}))
    signal_events = [row for row in events if row.get("event_type") in {"ADMISSION", "REPLACEMENT"}]
    drops = [row for row in events if row.get("event_type") == "DROP"]

    signals = []
    seen = set()
    for event in signal_events:
        candidate = event.get("candidate") or {}
        key = (str(candidate.get("kraken_symbol") or "").upper(), str(candidate.get("admitted_at_utc") or event.get("timestamp_utc") or ""))
        if key in seen:
            continue
        seen.add(key)
        symbol = key[0]
        signals.append(blank_review(event, coverage.get(symbol), maps.get(symbol)))

    payload = {
        "schema_version": "1.0",
        "date": date,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "HUMAN_EDITABLE_DAILY_SIGNAL_REVIEW",
        "source_files": [str(QUEUE_AUDIT), str(QUEUE_STATE), str(MAP_LATEST), str(COVERAGE)],
        "signals": signals,
        "drop_events": drops,
        "day_status": "OPEN",
        "raw_sources_modified": False,
        "orders_enabled": False,
    }
    REVIEWS.mkdir(parents=True, exist_ok=True)
    json_path = REVIEWS / f"{date}_signal_review.json"
    md_path = REVIEWS / f"{date}_signal_review.md"
    if (json_path.exists() or md_path.exists()) and not args.overwrite:
        print(f"Review already exists: {md_path}")
        print("Use --overwrite only if you intentionally want to regenerate blank review fields.")
        return 0
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(markdown(payload, date, drops), encoding="utf-8")
    print(f"Signals: {len(signals)} | drops: {len(drops)}")
    print(f"Wrote: {md_path}")
    print(f"Wrote: {json_path}")
    print("RESULT: PASS — daily review generated; raw logs, queue state, alerts, and orders unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
