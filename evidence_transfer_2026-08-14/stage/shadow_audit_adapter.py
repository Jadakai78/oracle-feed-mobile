from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from shadow_audit_ledger import ShadowAuditLedger, build_record


PANEL_KEYS = ("opportunities", "watchlist", "killed")


def iter_panel_rows(payload: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    """Yield final panel rows from nested or legacy top-level payloads once."""
    panel = payload.get("panel") or {}
    panel = panel if isinstance(panel, dict) else {}
    seen = set()

    for panel_name in PANEL_KEYS:
        sources = (
            panel.get(panel_name),
            payload.get(panel_name),
        )

        for rows in sources:
            if not isinstance(rows, list):
                continue

            for row in rows:
                if not isinstance(row, dict):
                    continue

                identity = (
                    panel_name,
                    str(row.get("pair") or ""),
                    str(row.get("action_state") or ""),
                    str(row.get("why_now") or ""),
                )
                if identity in seen:
                    continue

                seen.add(identity)
                yield panel_name, row


def get_scan_id(payload: Dict[str, Any]) -> str:
    value = (
        payload.get("last_scan")
        or payload.get("generated_at")
        or payload.get("api_served_at")
        or "unknown-scan"
    )
    return str(value)


def row_shadow(row: Dict[str, Any]) -> Dict[str, Any]:
    diagnostics = row.get("diagnostics") or {}
    shadow = diagnostics.get("shadow_sentinel") or {}

    return shadow if isinstance(shadow, dict) else {}


def row_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
    diagnostics = row.get("diagnostics") or {}
    metadata = diagnostics.get("metadata") or {}

    return metadata if isinstance(metadata, dict) else {}


def build_records_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    scan_id = get_scan_id(payload)
    records: List[Dict[str, Any]] = []

    for panel_name, row in iter_panel_rows(payload):
        shadow = row_shadow(row)

        if not shadow:
            continue

        pair = str(row.get("pair") or "UNKNOWN")
        action_state = str(row.get("action_state") or panel_name)

        record = build_record(
            scan_id=scan_id,
            pair=pair,
            oracle_action_state=action_state,
            shadow=shadow,
            timestamp=payload.get("last_scan") or payload.get("generated_at"),
            row=row,
            metadata=row_metadata(row),
        )

        record["panel"] = panel_name
        records.append(record)

    return records


def append_payload_observations(
    payload: Dict[str, Any],
    ledger: ShadowAuditLedger,
) -> Dict[str, Any]:
    records = build_records_from_payload(payload)

    appended = 0
    duplicates = 0

    for record in records:
        if ledger.append_if_new(record):
            appended += 1
        else:
            duplicates += 1

    return {
        "mode": "shadow",
        "enforcement": "none",
        "scan_id": get_scan_id(payload),
        "rows_with_shadow": len(records),
        "appended": appended,
        "duplicates_skipped": duplicates,
        "ledger_path": str(ledger.path),
    }
