from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_LEDGER_DIR = Path(__file__).resolve().parent / "shadow_audit"
DEFAULT_LEDGER_PATH = DEFAULT_LEDGER_DIR / "shadow_audit_ledger.jsonl"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_record(
    *,
    scan_id: str,
    pair: str,
    oracle_action_state: str,
    shadow: Dict[str, Any],
    timestamp: Optional[str] = None,
    row: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    row = row or {}
    metadata = metadata or {}
    shadow = shadow or {}

    diagnostics = row.get("diagnostics") or {}
    execution = diagnostics.get("oracle_execution") or {}
    indicators = row.get("indicators") or {}
    context = row.get("oracle_context") or {}

    return {
        "schema_version": 1,
        "recorded_at": timestamp or utc_now_iso(),
        "scan_id": str(scan_id),
        "record_key": (
            f"{scan_id}|{pair}|"
            f"{oracle_action_state}|"
            f"{shadow.get('verdict') or 'unavailable'}"
        ),
        "pair": str(pair),
        "oracle": {
            "action_state": str(oracle_action_state),
            "side": row.get("side"),
            "why_now": row.get("why_now"),
            "entry": row.get("entry_idea"),
            "stop_loss": row.get("stop_idea"),
            "take_profit": row.get("target_idea"),
            "setup_family": row.get("setup_family"),
            "management_state": diagnostics.get("management_state"),
            "tp1": diagnostics.get("tp1"),
            "tp2": diagnostics.get("tp2"),
            "tp3": diagnostics.get("tp3"),
            "execution": execution,
        },
        "shadow": {
            "mode": shadow.get("mode", "shadow"),
            "verdict": shadow.get("verdict", "unavailable"),
            "score": shadow.get("score"),
            "reasons": list(shadow.get("reasons") or []),
            "evidence": dict(shadow.get("evidence") or {}),
        },
        "specialist_observations": list(
            metadata.get("sentinel_observations") or []
        ),
        "gimba_range_alignment": dict(
            metadata.get("gimba_range_alignment") or {}
        ),
        "market_context": {
            "timeframe": context.get("timeframe"),
            "session": context.get("session"),
            "fear_greed": context.get("fear_greed"),
            "market_regime": context.get("market_regime"),
            "last_price": diagnostics.get("last_price"),
            "quote_source": diagnostics.get("quote_source"),
            "quote_timestamp": diagnostics.get("quote_timestamp"),
            "quote_age_seconds": diagnostics.get("quote_age_seconds"),
            "live_quote_valid": diagnostics.get("live_quote_valid"),
            "ohlc_ready": indicators.get("ohlc_ready"),
            "relative_volume_25": metadata.get("relative_volume_25"),
            "volume_state_15m": metadata.get("volume_state_15m"),
            "impulse_state": metadata.get("impulse_state"),
            "impulse_reason": metadata.get("impulse_reason"),
            "momentum_bias": metadata.get("momentum_bias"),
            "volatility_state": metadata.get("volatility_state"),
            "trap_risk": metadata.get("trap_risk"),
        },
        "outcome": {
            "status": "pending",
            "evaluated_at": None,
            "horizon": None,
            "return_pct": None,
            "mfe_pct": None,
            "mae_pct": None,
            "notes": None,
        },
    }


class ShadowAuditLedger:
    """
    Append-only JSONL audit ledger for observation-only Shadow decisions.

    This class does not trade, modify signals, change scanner state, or
    evaluate outcomes. It only records and reads audit observations.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_LEDGER_PATH

    def append(self, record: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        serialized = json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized + "\n")

    def append_many(self, records: Iterable[Dict[str, Any]]) -> int:
        count = 0

        for record in records:
            self.append(record)
            count += 1

        return count

    def read_all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []

        records: List[Dict[str, Any]] = []

        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()

                if not text:
                    continue

                try:
                    record = json.loads(text)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        "Invalid JSONL ledger entry "
                        f"at line {line_number}: {error.msg}"
                    ) from error

                if not isinstance(record, dict):
                    raise ValueError(
                        "Ledger entry is not an object "
                        f"at line {line_number}"
                    )

                records.append(record)

        return records

    def contains_record_key(self, record_key: str) -> bool:
        return any(
            record.get("record_key") == record_key
            for record in self.read_all()
        )

    def append_if_new(self, record: Dict[str, Any]) -> bool:
        record_key = str(record.get("record_key") or "").strip()

        if not record_key:
            raise ValueError("record_key is required")

        if self.contains_record_key(record_key):
            return False

        self.append(record)
        return True


def summarize(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    verdicts: Dict[str, int] = {}
    actions: Dict[str, int] = {}
    total = 0

    for record in records:
        total += 1

        verdict = str(
            (record.get("shadow") or {}).get("verdict")
            or "unavailable"
        )
        action = str(
            (record.get("oracle") or {}).get("action_state")
            or "unknown"
        )

        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        actions[action] = actions.get(action, 0) + 1

    return {
        "record_count": total,
        "shadow_verdict_counts": verdicts,
        "oracle_action_counts": actions,
    }

