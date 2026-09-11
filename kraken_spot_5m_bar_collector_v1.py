from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent
TRAINING_LOGS = ROOT / "training_logs"

AUDIT_PATH = ROOT / "kraken_spot_context_symbol_audit_v1.json"
LEDGER_PATH = TRAINING_LOGS / "episode_5m_bars_kraken_spot_v1.jsonl"
HEALTH_PATH = TRAINING_LOGS / "episode_5m_bars_kraken_spot_health_v1.json"

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
INTERVAL_MINUTES = 5
REQUEST_TIMEOUT_SECONDS = 20
MIN_COMPLETED_CANDLES = 15
REQUEST_PAUSE_SECONDS = 0.12

RECORDTYPE = "EPISODE5MBAR"
SCHEMA_VERSION = "episode5mbar_kraken_spot_v1"


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def utc_from_epoch(value: Any) -> Optional[datetime]:
    try:
        epoch = int(float(value))
    except (TypeError, ValueError):
        return None

    if epoch <= 0:
        return None

    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def load_json_object(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")

    return payload


def load_resolved_markets() -> List[Dict[str, Any]]:
    audit = load_json_object(AUDIT_PATH)
    rows = audit.get("rows")

    if not isinstance(rows, list):
        raise ValueError("Audit payload must contain list-valued 'rows'")

    markets: List[Dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        if str(row.get("resolution_state") or "").upper() != "RESOLVED":
            continue

        pair = str(row.get("context_pair") or "").upper().strip()
        request_pair = str(
            row.get("kraken_altname")
            or row.get("api_pair_key")
            or ""
        ).upper().strip()

        if not pair or "/" not in pair or not request_pair:
            continue

        markets.append(
            {
                "pair": pair,
                "request_pair": request_pair,
                "api_pair_key": row.get("api_pair_key"),
                "kraken_altname": row.get("kraken_altname"),
                "kraken_wsname": row.get("kraken_wsname"),
            }
        )

    markets.sort(key=lambda row: row["pair"])
    return markets


def existing_bar_keys(path: Path) -> Set[Tuple[str, str]]:
    keys: Set[Tuple[str, str]] = set()

    if not path.exists():
        return keys

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not isinstance(row, dict):
                continue

            pair = str(row.get("pair") or "").upper().strip()
            bar_end = str(row.get("bar_end") or "").strip()

            if pair and bar_end:
                keys.add((pair, bar_end))

    return keys


def fetch_ohlc(request_pair: str) -> Tuple[str, List[List[Any]]]:
    query = urllib.parse.urlencode(
        {
            "pair": request_pair,
            "interval": INTERVAL_MINUTES,
        }
    )

    request = urllib.request.Request(
        f"{KRAKEN_OHLC_URL}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "JHL-KrakenSpotM5Collector/1.0",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=REQUEST_TIMEOUT_SECONDS,
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))

    errors = payload.get("error") or []
    if errors:
        raise RuntimeError("; ".join(map(str, errors)))

    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Kraken OHLC response has no result object")

    candle_key = next((key for key in result if key != "last"), None)
    candles = result.get(candle_key) if candle_key else None

    if not candle_key or not isinstance(candles, list):
        raise RuntimeError("Kraken OHLC response has no candle series")

    return str(candle_key), candles


def build_records(
    market: Dict[str, Any],
    candle_key: str,
    raw_candles: Iterable[List[Any]],
    seen: Set[Tuple[str, str]],
) -> List[Dict[str, Any]]:
    raw_list = list(raw_candles)

    # Kraken returns the active/current candle as its final row.
    completed = raw_list[:-1] if len(raw_list) > 1 else []
    records: List[Dict[str, Any]] = []

    for candle in completed:
        try:
            start = utc_from_epoch(candle[0])
            open_price = float(candle[1])
            high_price = float(candle[2])
            low_price = float(candle[3])
            close_price = float(candle[4])
            volume = float(candle[6])
        except (IndexError, TypeError, ValueError):
            continue

        if start is None:
            continue

        if (
            open_price <= 0
            or high_price <= 0
            or low_price <= 0
            or close_price <= 0
            or high_price < low_price
            or volume < 0
        ):
            continue

        end = start.timestamp() + (INTERVAL_MINUTES * 60)
        bar_end = datetime.fromtimestamp(end, tz=timezone.utc)

        pair = market["pair"]
        key = (pair, iso_utc(bar_end))
        if key in seen:
            continue

        records.append(
            {
                "recordtype": RECORDTYPE,
                "schemaversion": SCHEMA_VERSION,
                "observationonly": True,
                "doesnotauthorizetrade": True,
                "doesnotchangequeue": True,
                "pair": pair,
                "symbol": pair,
                "kraken_spot_pair": candle_key,
                "kraken_api_pair_key": market.get("api_pair_key"),
                "kraken_altname": market.get("kraken_altname"),
                "kraken_wsname": market.get("kraken_wsname"),
                "bar_start": iso_utc(start),
                "bar_end": iso_utc(bar_end),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "source": "kraken_spot_ohlc",
                "written_at_utc": utc_now(),
            }
        )

    records.sort(key=lambda row: row["bar_end"])
    return records


def write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def append_records(path: Path, records: Iterable[Dict[str, Any]]) -> int:
    count = 0

    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    return count


def main() -> None:
    TRAINING_LOGS.mkdir(parents=True, exist_ok=True)

    markets = load_resolved_markets()
    seen = existing_bar_keys(LEDGER_PATH)

    fetched = 0
    failed: List[Dict[str, str]] = []
    all_new_records: List[Dict[str, Any]] = []

    for market in markets:
        try:
            candle_key, raw_candles = fetch_ohlc(market["request_pair"])
            records = build_records(market, candle_key, raw_candles, seen)

            all_new_records.extend(records)
            seen.update(
                (record["pair"], record["bar_end"])
                for record in records
            )
            fetched += 1

        except Exception as exc:
            failed.append(
                {
                    "pair": market["pair"],
                    "request_pair": market["request_pair"],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

        time.sleep(REQUEST_PAUSE_SECONDS)

    written = append_records(LEDGER_PATH, all_new_records)

    health = {
        "recordtype": "EPISODE5MBARSPOTHEALTH",
        "schema_version": "episode5mbar_kraken_spot_health_v1",
        "generated_at_utc": utc_now(),
        "manual_review_only": True,
        "entry_authority": False,
        "does_not_authorize_trade": True,
        "does_not_change_queue": True,
        "source_audit_file": AUDIT_PATH.name,
        "output_ledger_file": LEDGER_PATH.name,
        "interval_minutes": INTERVAL_MINUTES,
        "resolved_market_count": len(markets),
        "fetch_success_count": fetched,
        "fetch_failure_count": len(failed),
        "new_completed_bars_written": written,
        "failures": failed,
    }

    write_json_atomic(HEALTH_PATH, health)

    print(f"Resolved markets: {len(markets)}")
    print(f"Fetched successfully: {fetched}")
    print(f"Fetch failures: {len(failed)}")
    print(f"New completed bars written: {written}")
    print(f"Ledger: {LEDGER_PATH}")
    print(f"Health: {HEALTH_PATH}")


if __name__ == "__main__":
    main()
