\
"""Oracle Paper Outcome Recorder v1 — read-only READY-state outcome observer.

Reads transitions from oracle_micro_trigger_events_v1.jsonl. A transition to READY
opens one paper observation, freezes its reference price and context, and records
forward directional returns and favorable/adverse excursion at 1/5/15/30/60 minutes.

No alerts, orders, stops, targets, routing, queue modifications, or execution.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent
EVENTS_PATH = ROOT / "oracle_micro_trigger_events_v1.jsonl"
STATE_PATH = ROOT / "oracle_paper_outcome_state_v1.json"
OBSERVATIONS_PATH = ROOT / "oracle_paper_observations_v1.jsonl"
OUTCOMES_PATH = ROOT / "oracle_paper_outcomes_v1.jsonl"
POLL_SECONDS = 30
HORIZONS_SECONDS = (60, 300, 900, 1800, 3600)
MAX_EVENT_AGE_SECONDS = 90


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except ValueError:
        return None


def _kraken_pair(pair: str) -> str:
    base, quote = pair.split("/")
    aliases = {"BTC": "XBT", "DOGE": "XDG"}
    return f"{aliases.get(base, base)}{aliases.get(quote, quote)}"


def _price(pair: str) -> float:
    query = urllib.parse.urlencode({"pair": _kraken_pair(pair)})
    request = urllib.request.Request(
        f"https://api.kraken.com/0/public/Ticker?{query}",
        headers={"User-Agent": "oracle-paper-outcome-recorder/1.0"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError("kraken_ticker_error")
    result = payload.get("result") or {}
    record = next(iter(result.values()), None)
    if not record:
        raise RuntimeError("kraken_ticker_missing")
    return float(record["c"][0])


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"schema_version": "oraclepaperoutcomestatev1", "event_offset": 0, "observations": {}}
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        payload.setdefault("event_offset", 0)
        payload.setdefault("observations", {})
        return payload
    except Exception:
        return {"schema_version": "oraclepaperoutcomestatev1", "event_offset": 0, "observations": {}}


def _save_state(state: Dict[str, Any]) -> None:
    state["updated_at_utc"] = _iso()
    state["manual_review_only"] = True
    state["does_not_authorize_trade"] = True
    temp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(STATE_PATH)


def _append(path: Path, record: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_new_events(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    raw = EVENTS_PATH.read_text(encoding="utf-8")
    offset = int(state.get("event_offset") or 0)
    if offset > len(raw):
        offset = 0
    chunk = raw[offset:]
    state["event_offset"] = len(raw)
    records = []
    for line in chunk.splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                records.append(item)
        except json.JSONDecodeError:
            continue
    return records


def _observation_id(event: Dict[str, Any]) -> str:
    return "|".join([
        str(event.get("pair") or ""),
        str(event.get("directional_context") or ""),
        str(event.get("observed_at_utc") or ""),
    ])


def _open_ready_observations(state: Dict[str, Any], events: Sequence[Dict[str, Any]]) -> int:
    opened = 0
    now = _now()
    for event in events:
        if event.get("recordtype") != "ORACLEMICROTRIGGERTRANSITION":
            continue
        if event.get("to_state") != "READY" or event.get("from_state") == "READY":
            continue
        pair = event.get("pair")
        direction = event.get("directional_context")
        observed = _parse(event.get("observed_at_utc"))
        if not pair or direction not in {"LONG", "SHORT"} or observed is None:
            continue
        if (now - observed).total_seconds() > MAX_EVENT_AGE_SECONDS:
            continue
        ident = _observation_id(event)
        if ident in state["observations"]:
            continue
        try:
            reference = _price(pair)
        except Exception:
            continue
        record = {
            "recordtype": "ORACLEPAPEROBSERVATION",
            "schema_version": "oraclepaperoutcomev1",
            "observation_id": ident,
            "opened_at_utc": _iso(),
            "ready_transition_at_utc": event.get("observed_at_utc"),
            "pair": pair,
            "directional_context": direction,
            "reference_price": reference,
            "context_score": event.get("context_score"),
            "correlation_group": event.get("correlation_group"),
            "correlation_role": event.get("correlation_role"),
            "trigger_family": event.get("trigger_family"),
            "reason_codes": event.get("reason_codes") or [],
            "trigger_metrics": event.get("metrics") or {},
            "horizons_seconds": list(HORIZONS_SECONDS),
            "samples": {},
            "max_favorable_pct": 0.0,
            "max_adverse_pct": 0.0,
            "status": "OPEN",
            "manual_review_only": True,
            "does_not_authorize_trade": True,
            "does_not_simulate_order": True,
        }
        state["observations"][ident] = record
        _append(OBSERVATIONS_PATH, record)
        opened += 1
    return opened


def _directional_return(direction: str, reference: float, price: float) -> float:
    raw = (price / reference - 1.0) * 100.0
    return raw if direction == "LONG" else -raw


def _update_observations(state: Dict[str, Any]) -> int:
    now = _now()
    finalized = 0
    for ident, record in list(state["observations"].items()):
        if record.get("status") != "OPEN":
            continue
        opened = _parse(record.get("opened_at_utc"))
        if opened is None:
            record["status"] = "INVALID"
            continue
        try:
            price = _price(record["pair"])
        except Exception as exc:
            record["last_data_error"] = type(exc).__name__
            continue
        elapsed = max(0, int((now - opened).total_seconds()))
        result_pct = _directional_return(record["directional_context"], float(record["reference_price"]), price)
        record["last_price"] = price
        record["last_observed_at_utc"] = _iso(now)
        record["max_favorable_pct"] = round(max(float(record.get("max_favorable_pct") or 0.0), result_pct), 6)
        record["max_adverse_pct"] = round(min(float(record.get("max_adverse_pct") or 0.0), result_pct), 6)
        for horizon in HORIZONS_SECONDS:
            key = str(horizon)
            if elapsed >= horizon and key not in record["samples"]:
                record["samples"][key] = {
                    "horizon_seconds": horizon,
                    "observed_at_utc": _iso(now),
                    "elapsed_seconds": elapsed,
                    "price": price,
                    "directional_return_pct": round(result_pct, 6),
                }
        if elapsed >= max(HORIZONS_SECONDS):
            record["status"] = "CLOSED"
            record["closed_at_utc"] = _iso(now)
            outcome = {
                "recordtype": "ORACLEPAPEROUTCOME",
                "schema_version": "oraclepaperoutcomev1",
                "observation_id": ident,
                "pair": record["pair"],
                "directional_context": record["directional_context"],
                "ready_transition_at_utc": record["ready_transition_at_utc"],
                "reference_price": record["reference_price"],
                "context_score": record.get("context_score"),
                "trigger_family": record.get("trigger_family"),
                "reason_codes": record.get("reason_codes") or [],
                "trigger_metrics": record.get("trigger_metrics") or {},
                "samples": record["samples"],
                "max_favorable_pct": record["max_favorable_pct"],
                "max_adverse_pct": record["max_adverse_pct"],
                "closed_at_utc": record["closed_at_utc"],
                "manual_review_only": True,
                "does_not_authorize_trade": True,
                "does_not_simulate_order": True,
            }
            _append(OUTCOMES_PATH, outcome)
            finalized += 1
    return finalized


def run_cycle() -> Dict[str, int]:
    state = _load_state()
    events = _read_new_events(state)
    opened = _open_ready_observations(state, events)
    closed = _update_observations(state)
    _save_state(state)
    return {"events_read": len(events), "observations_opened": opened, "outcomes_closed": closed}


def main() -> None:
    print("Oracle Paper Outcome Recorder v1 — READY transitions only; read-only; no alerts/execution")
    while True:
        try:
            result = run_cycle()
            print(f"{_iso()} events={result['events_read']} opened={result['observations_opened']} closed={result['outcomes_closed']}")
        except Exception as exc:
            print(f"{_iso()} paper cycle blocked: {type(exc).__name__}: {exc}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
