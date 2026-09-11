from __future__ import annotations

import json
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent

CONTEXT_PATH = ROOT / "oracle_prop_context_v1.json"
OUTPUT_JSON_PATH = ROOT / "kraken_spot_context_symbol_audit_v1.json"
OUTPUT_CSV_PATH = ROOT / "kraken_spot_context_symbol_audit_v1.csv"

ASSET_PAIRS_URL = "https://api.kraken.com/0/public/AssetPairs"
TIMEOUT_SECONDS = 20


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_json_object(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")

    return payload


def fetch_asset_pairs() -> Dict[str, Dict[str, Any]]:
    request = urllib.request.Request(
        ASSET_PAIRS_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "JHL-KrakenSpotSymbolAudit/1.0",
        },
    )

    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))

    errors = payload.get("error") or []
    if errors:
        raise RuntimeError("Kraken AssetPairs error: " + "; ".join(map(str, errors)))

    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Kraken AssetPairs returned no result object")

    return {
        str(key).upper(): value
        for key, value in result.items()
        if isinstance(value, dict)
    }


def normalize_asset(value: Any) -> str:
    asset = str(value or "").upper().strip()

    aliases = {
        "XXBT": "BTC",
        "XBT": "BTC",
        "XDG": "DOGE",
        "XXDG": "DOGE",
        "XETH": "ETH",
        "ZUSD": "USD",
    }

    if asset in aliases:
        return aliases[asset]

    if asset.startswith("X") and len(asset) > 3:
        return asset[1:]

    if asset.startswith("Z") and len(asset) > 3:
        return asset[1:]

    return asset


def context_pair(value: Any) -> str:
    return str(value or "").upper().strip()


def pair_base(pair: str) -> str:
    if "/" not in pair:
        raise ValueError(f"Invalid context pair: {pair!r}")
    return pair.split("/", 1)[0].strip().upper()


def candidate_record(
    pair_key: str,
    pair_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    altname = str(pair_data.get("altname") or "").upper().strip()
    wsname = str(pair_data.get("wsname") or "").upper().strip()
    base = normalize_asset(pair_data.get("base"))
    quote = normalize_asset(pair_data.get("quote"))

    if quote != "USD":
        return None

    if base != pair_key:
        return None

    status = str(pair_data.get("status") or "online").lower()
    if status not in {"online", ""}:
        return None

    return {
        "kraken_pair_key": pair_key,
        "kraken_altname": altname or None,
        "kraken_wsname": wsname or None,
        "kraken_base": base,
        "kraken_quote": quote,
        "kraken_status": status or "online",
        "pair_decimals": pair_data.get("pair_decimals"),
        "lot_decimals": pair_data.get("lot_decimals"),
    }


def choose_market(
    base: str,
    asset_pairs: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    for api_key, data in asset_pairs.items():
        candidate = candidate_record(base, data)
        if candidate is None:
            continue

        candidate["api_pair_key"] = api_key
        candidates.append(candidate)

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            0 if item["kraken_altname"] else 1,
            item["api_pair_key"],
        )
    )

    return candidates[0]


def csv_value(value: Any) -> str:
    text = "" if value is None else str(value)
    return '"' + text.replace('"', '""') + '"'


def write_csv(rows: List[Dict[str, Any]]) -> None:
    columns = [
        "context_pair",
        "context_base",
        "resolution_state",
        "reason",
        "api_pair_key",
        "kraken_altname",
        "kraken_wsname",
        "kraken_base",
        "kraken_quote",
        "kraken_status",
        "pair_decimals",
        "lot_decimals",
    ]

    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(csv_value(row.get(column)) for column in columns))

    temporary = OUTPUT_CSV_PATH.with_suffix(".csv.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT_CSV_PATH)


def build_payload() -> Dict[str, Any]:
    context = load_json_object(CONTEXT_PATH)
    records = context.get("pairs")

    if not isinstance(records, list):
        raise ValueError("Context payload must contain a list-valued 'pairs'")

    asset_pairs = fetch_asset_pairs()
    rows: List[Dict[str, Any]] = []

    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Context pair entries must be objects")

        pair = context_pair(record.get("pair"))
        base = pair_base(pair)
        market = choose_market(base, asset_pairs)

        if market is None:
            rows.append(
                {
                    "context_pair": pair,
                    "context_base": base,
                    "resolution_state": "UNRESOLVED",
                    "reason": "NO_ONLINE_KRAKEN_SPOT_USD_MARKET",
                    "api_pair_key": None,
                    "kraken_altname": None,
                    "kraken_wsname": None,
                    "kraken_base": None,
                    "kraken_quote": "USD",
                    "kraken_status": None,
                    "pair_decimals": None,
                    "lot_decimals": None,
                }
            )
        else:
            rows.append(
                {
                    "context_pair": pair,
                    "context_base": base,
                    "resolution_state": "RESOLVED",
                    "reason": None,
                    "api_pair_key": market["api_pair_key"],
                    "kraken_altname": market["kraken_altname"],
                    "kraken_wsname": market["kraken_wsname"],
                    "kraken_base": market["kraken_base"],
                    "kraken_quote": market["kraken_quote"],
                    "kraken_status": market["kraken_status"],
                    "pair_decimals": market["pair_decimals"],
                    "lot_decimals": market["lot_decimals"],
                }
            )

    counts = Counter(row["resolution_state"] for row in rows)

    payload = {
        "recordtype": "KRAKENSPOTCONTEXTSYMBOLAUDIT",
        "schema_version": "kraken_spot_context_symbol_audit_v1",
        "generated_at_utc": utc_now(),
        "manual_review_only": True,
        "entry_authority": False,
        "does_not_authorize_trade": True,
        "does_not_change_queue": True,
        "source": {
            "context_file": CONTEXT_PATH.name,
            "asset_pairs_endpoint": ASSET_PAIRS_URL,
        },
        "health": {
            "context_pair_count": len(rows),
            "kraken_asset_pair_catalog_count": len(asset_pairs),
            "resolution_counts": dict(sorted(counts.items())),
        },
        "rows": rows,
    }

    write_csv(rows)
    return payload


def write_json(payload: Dict[str, Any]) -> None:
    temporary = OUTPUT_JSON_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(OUTPUT_JSON_PATH)


def main() -> None:
    payload = build_payload()
    write_json(payload)

    health = payload["health"]
    print(f"Wrote: {OUTPUT_JSON_PATH}")
    print(f"Wrote: {OUTPUT_CSV_PATH}")
    print(f"Context pairs: {health['context_pair_count']}")
    print(f"Kraken catalog pairs: {health['kraken_asset_pair_catalog_count']}")

    for status, count in health["resolution_counts"].items():
        print(f"{status}: {count}")


if __name__ == "__main__":
    main()
