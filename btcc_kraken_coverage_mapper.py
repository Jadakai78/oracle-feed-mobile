"""
btcc_kraken_coverage_mapper.py — JHL Holdings LLC

Maps BTCC active USDT-M perpetual execution contracts to available
Kraken Futures PF_<ASSET>USD flexible-futures research instruments.

Purpose:
- Defines research coverage only.
- Does not score signals, fetch candles, send alerts, place orders,
  read accounts, or modify BTCC artifacts.
- Kraken values are never represented as BTCC values.

Approved matching exception:
BTCC <ASSET>USDT ↔ Kraken PF_<ASSET>USD
Base asset must match exactly after normalization.
Kraken XBT maps explicitly to BTC.
ADA is permanently quarantined.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

import btcc_market_data as btcc
import kraken_futures_market_data as kraken

SCHEMA_VERSION = "1.0"
LOG_DIR = "training_logs"
ADA_QUARANTINED = True

# Explicit asset aliases only. Do not add inferred aliases.
CANONICAL_ASSET_ALIASES = {
    "XBT": "BTC",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_asset(value: Any) -> str:
    asset = str(value or "").upper().strip()
    return CANONICAL_ASSET_ALIASES.get(asset, asset)


def is_btcc_usdt_perp(contract: Dict[str, Any]) -> bool:
    return (
        contract.get("contract_status") == "ACTIVE"
        and str(contract.get("quote_asset") or "").upper() == "USDT"
        and str(contract.get("margin_asset") or "").upper() == "USDT"
    )


def build_coverage() -> Dict[str, Any]:
    btcc_contracts = [
        row for row in btcc.get_active_contracts()
        if is_btcc_usdt_perp(row)
    ]

    kraken_contracts = kraken.get_active_linear_usd_perpetuals()

    kraken_by_base: Dict[str, List[Dict[str, Any]]] = {}
    for row in kraken_contracts:
        base = canonical_asset(
            row.get("canonical_base_asset") or row.get("base_asset")
        )
        if not base:
            continue
        kraken_by_base.setdefault(base, []).append(row)

    included: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []

    for contract in btcc_contracts:
        btcc_symbol = str(contract.get("symbol") or "").upper()
        btcc_base = canonical_asset(contract.get("base_asset"))

        if not btcc_base:
            excluded.append(
                {
                    "btcc_symbol": btcc_symbol,
                    "reason": "SYMBOL_MAPPING_UNRESOLVED: BTCC base_asset missing",
                }
            )
            continue

        if ADA_QUARANTINED and btcc_base == "ADA":
            excluded.append(
                {
                    "btcc_symbol": btcc_symbol,
                    "base_asset": btcc_base,
                    "reason": "ADA_QUARANTINED",
                }
            )
            continue

        candidates = kraken_by_base.get(btcc_base, [])
        if not candidates:
            excluded.append(
                {
                    "btcc_symbol": btcc_symbol,
                    "base_asset": btcc_base,
                    "reason": "NO_KRAKEN_PF_USD_RESEARCH_MARKET",
                }
            )
            continue

        # A duplicate same-base Kraken PF listing is not guessed through.
        if len(candidates) != 1:
            excluded.append(
                {
                    "btcc_symbol": btcc_symbol,
                    "base_asset": btcc_base,
                    "kraken_candidate_symbols": [
                        row.get("symbol") for row in candidates
                    ],
                    "reason": "SYMBOL_MAPPING_UNRESOLVED: multiple Kraken candidates",
                }
            )
            continue

        research = candidates[0]
        included.append(
            {
                "btcc_symbol": btcc_symbol,
                "btcc_base_asset": btcc_base,
                "btcc_contract_status": contract.get("contract_status"),
                "btcc_contract_source_endpoint": contract.get("source_endpoint"),
                "btcc_contract_source_fetched_at_utc": contract.get(
                    "source_fetched_at_utc"
                ),
                "kraken_symbol": research.get("symbol"),
                "kraken_base_asset": research.get("base_asset"),
                "kraken_contract_type": research.get("contract_type"),
                "kraken_source_endpoint": research.get("source_endpoint"),
                "kraken_source_fetched_at_utc": research.get(
                    "source_fetched_at_utc"
                ),
                "data_venue": "KRAKEN_FUTURES",
                "execution_venue": "BTCC",
                "data_quote_currency": "USD",
                "execution_quote_currency": "USDT",
                "quote_mismatch": "KRAKEN_USD__BTCC_USDT",
                "matching_rule": (
                    "SAME_UNDERLYING_EXACT_BASE_AFTER_NORMALIZATION;"
                    " XBT_TO_BTC_ONLY"
                ),
                "manual_btcc_checks_required": [
                    "contract_active",
                    "live_price",
                    "funding",
                    "spread_depth",
                    "liquidation_safety",
                ],
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "run_at_utc": utc_now_iso(),
        "purpose": "BTCC_EXECUTION_ELIGIBILITY__KRAKEN_RESEARCH_COVERAGE_ONLY",
        "matching_contract": {
            "rule": (
                "BTCC <ASSET>USDT ↔ Kraken PF_<ASSET>USD;"
                " exact normalized base match; XBT maps only to BTC"
            ),
            "data_venue": "KRAKEN_FUTURES",
            "execution_venue": "BTCC",
            "quote_mismatch_required_disclosure": "KRAKEN_USD__BTCC_USDT",
            "ada_quarantined": ADA_QUARANTINED,
            "no_orders": True,
        },
        "counts": {
            "btcc_active_usdt_m_contracts": len(btcc_contracts),
            "kraken_active_flexible_usd_contracts": len(kraken_contracts),
            "included_coverage": len(included),
            "excluded_btcc_contracts": len(excluded),
        },
        "included": included,
        "excluded": excluded,
    }


def main() -> int:
    try:
        audit = build_coverage()
    except Exception as exc:
        print(f"FAIL: coverage build: {type(exc).__name__}: {exc}")
        return 1

    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, "btcc_kraken_coverage_audit.json")

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(audit, handle, indent=2, default=str)

    counts = audit["counts"]
    print(f"BTCC active USDT-M contracts: {counts['btcc_active_usdt_m_contracts']}")
    print(f"Kraken active flexible USD contracts: {counts['kraken_active_flexible_usd_contracts']}")
    print(f"Research coverage included: {counts['included_coverage']}")
    print(f"BTCC contracts excluded: {counts['excluded_btcc_contracts']}")
    print(f"Wrote: {path}")
    print("RESULT: PASS — coverage map built; no prices, alerts, or orders were sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
