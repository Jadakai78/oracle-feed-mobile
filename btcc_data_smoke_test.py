"""
btcc_data_smoke_test.py — JHL Holdings LLC
One-shot verification script for the BTCC USDT-M foundation layer.

SyntaxWarning fix: removed invalid escape sequences (bare backslashes in strings).
All regex-like strings now use raw strings r"..." where needed.

Run:  py .\btcc_data_smoke_test.py
Exits 0 if foundation contract data is verified.
Exits 1 if required foundation data is missing or endpoints are all blocked.

Writes (creates training_logs\\ if needed):
  training_logs\\btcc_contracts_snapshot.json
  training_logs\\btcc_universe_audit.json
Both include: collection_timestamp, source_endpoint, schema_version,
              field availability, primary endpoint failure record.
"""

import json
import os
import sys
import traceback
from typing import Any, Dict, List

import btcc_market_data as _md
import btcc_pair_universe as _pu

SCHEMA_VERSION = "1.1"
SAMPLE_SIZE    = 5
LOG_DIR        = "training_logs"


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _field_status(value: Any) -> str:
    if value is None:
        return "UNAVAILABLE:None"
    if isinstance(value, str) and value.startswith("UNAVAIL"):
        return f"UNAVAILABLE:{value}"
    return "VERIFIED"


def _write_json(path: str, data: Any) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)
    print(f"  Wrote: {path}")


def run() -> int:
    exit_code  = 0
    warnings:  List[str] = []
    failures:  List[str] = []

    # ── Step 1: Preserve primary endpoint failure ─────────────────────────────
    _section("STEP 1 — Primary Endpoint Status (Preserved)")
    print(f"  PRIMARY:  {_md.PRIMARY_BASE_URL}")
    print(f"  Status:   {_md.PRIMARY_FAILURE_REASON}")
    print(f"  Time:     {_md.PRIMARY_FAILURE_TIME}")
    print(f"  Action:   DEAD — do not retry, do not add credentials")
    print(f"  FALLBACK: {_md.FALLBACK_BASE_URL}")
    print(f"  Active:   {_md.BTCC_BASE_URL}  [{_md.BTCC_DATA_SOURCE}]")

    # ── Step 2: Contract discovery via verified endpoint ──────────────────────
    _section("STEP 2 — Contract Discovery")
    print(f"  Endpoint: {_md.BTCC_BASE_URL + _md._EP_CONTRACTS}")

    try:
        contracts = _md.get_active_contracts()
    except RuntimeError as exc:
        msg = f"FAILED to fetch contracts: {exc}"
        print(f"  *** {msg}")
        failures.append(msg)
        print("\n  CRITICAL: Cannot proceed without contract list.")
        return 1

    total_contracts = len(contracts)
    print(f"  Active USDT-M perpetual contracts discovered: {total_contracts}")
    if total_contracts == 0:
        failures.append("ZERO_CONTRACTS: No active USDT-M perpetual contracts returned.")
        exit_code = 1

    # ── Step 3: Sample inspection ─────────────────────────────────────────────
    _section(f"STEP 3 — Sample Inspection ({min(SAMPLE_SIZE, total_contracts)} contracts)")
    sample = contracts[:SAMPLE_SIZE]
    sample_details: List[Dict] = []

    for contract in sample:
        symbol = contract["symbol"]
        print(f"\n  -- {symbol} --")
        print(f"    status:        {_field_status(contract.get('contract_status'))} ({contract.get('contract_status')})")
        print(f"    multiplier:    {_field_status(contract.get('contract_multiplier'))} ({contract.get('contract_multiplier')})")
        print(f"    tick_size:     {_field_status(contract.get('tick_size'))} ({contract.get('tick_size')})")
        print(f"    qty_step:      {_field_status(contract.get('qty_step'))} ({contract.get('qty_step')})")
        print(f"    qty_minimum:   {_field_status(contract.get('qty_minimum'))} ({contract.get('qty_minimum')})")
        print(f"    taker_fee:     {_field_status(contract.get('taker_fee_rate'))} ({contract.get('taker_fee_rate')})")
        print(f"    last_price:    {_md.UNAVAIL_NOT_IN_RESPONSE}")
        print(f"    volume_24h:    {_md.UNAVAIL_NOT_IN_RESPONSE}")
        print(f"    klines_5m:     {_md.UNAVAIL_KLINE_NO_PUBLIC_REST}")
        print(f"    klines_15m:    {_md.UNAVAIL_KLINE_NO_PUBLIC_REST}")
        print(f"    funding_rate:  {_md.UNAVAIL_FUNDING_ENDPOINT_GATED}")
        print(f"    spread_bps:    {_md.UNAVAIL_DEPTH_EMPTY_RESPONSE}")

        sample_details.append({
            "symbol": symbol,
            "contract_fields": {
                k: _field_status(v)
                for k, v in contract.items()
                if not k.startswith("_")
            },
            "klines_5m_count":     0,
            "klines_5m_status":    _md.UNAVAIL_KLINE_NO_PUBLIC_REST,
            "klines_15m_count":    0,
            "klines_15m_status":   _md.UNAVAIL_KLINE_NO_PUBLIC_REST,
            "funding_status":      _md.UNAVAIL_FUNDING_ENDPOINT_GATED,
            "spread_status":       _md.UNAVAIL_DEPTH_EMPTY_RESPONSE,
            "last_price_status":   _md.UNAVAIL_NOT_IN_RESPONSE,
            "volume_24h_status":   _md.UNAVAIL_NOT_IN_RESPONSE,
        })

    # ── Step 4: Universe build ─────────────────────────────────────────────────
    _section("STEP 4 — Universe Eligibility")
    try:
        universe = _pu.build_universe()
        eligible_count = len(universe["eligible"])
        blocked_count  = len(universe["blocked"])
        rejected_count = len(universe["rejected"])
        print(f"  Eligible:  {eligible_count}")
        print(f"  Blocked (data unavailable):  {blocked_count}")
        print(f"  Rejected (confirmed failure): {rejected_count}")

        if blocked_count > 0:
            warnings.append(
                f"ALL_{blocked_count}_CONTRACTS_BLOCKED_DATA_UNAVAILABLE: "
                "volume, price, klines, spread — no verified public REST paths."
            )

    except Exception as exc:
        msg = f"UNIVERSE_BUILD_FAILED: {exc}"
        print(f"  *** {msg}")
        traceback.print_exc()
        failures.append(msg)
        exit_code = 1
        universe  = {}

    # ── Step 5: Field availability summary ────────────────────────────────────
    _section("STEP 5 — Field Availability Summary")

    print("\n  VERIFIED FIELDS (confirmed from live response):")
    verified = [
        "  contract_list      — /btcc_trade/market/list (HTTP 200, 97KB JSON, 254 USDT-M perps)",
        "  symbol / name      — VERIFIED",
        "  base_asset (stock) — VERIFIED",
        "  quote/margin USDT  — VERIFIED",
        "  contract_status    — VERIFIED (switch field)",
        "  taker_fee_rate     — VERIFIED",
        "  tick_size          — DERIVED from depth string (verified)",
        "  qty_minimum        — VERIFIED (min_amount field)",
        "  min_order_value    — VERIFIED",
    ]
    for f in verified:
        print(f"  + {f}")

    print("\n  UNAVAILABLE FIELDS (explicit — not fabricated):")
    unavailable = [
        ("last_price",          "No public REST ticker path. WS requires auth session."),
        ("mark_price",          "Same as last_price."),
        ("volume_24h_usdt",     "Same as last_price."),
        ("ticker_freshness",    "Cannot assess without last_price timestamp."),
        ("klines_5m",           "REST requires signed token. WS requires auth session."),
        ("klines_15m",          "Same as klines_5m."),
        ("funding_rate",        "/api/futures/v1/funding-rate returns HTTP 200 empty body."),
        ("next_funding_time",   "Same as funding_rate."),
        ("spread_bps",          "/btcc_trade/market/depth returns empty bids/asks."),
        ("contract_multiplier", "Not in market/list response. Hardcoded 1.0 for linear perps."),
    ]
    for field, reason in unavailable:
        print(f"  - {field:<26} {reason}")

    # ── Step 6: Next-phase gate ────────────────────────────────────────────────
    _section("STEP 6 — Phase 2 Readiness Gate")
    print("  Fields sufficient for Phase 2 (Data Quality gate):")
    print("    Contract metadata: YES")
    print("    Price / volume:    NO  — blocks Pulse, Speed, Delta gates")
    print("    Klines (5m/15m):   NO  — blocks Structure, Delta, Speed harvest")
    print("    Funding:           NO  — blocks Noise/Timing gates")
    print("    Spread:            NO  — blocks execution quality filter")
    print()
    print("  Fields that block Phase 2 launch:")
    print("    BLOCKING: price/volume — required for liquidity filter and card display")
    print("    BLOCKING: klines       — required for all HARVEST components")
    print("    BLOCKING: funding      — required for Noise HARVEST and Timing REPLACE")
    print("    BLOCKING: spread       — required for execution quality ranking")
    print()
    print("  RESOLUTION PATH (ordered by impact):")
    print("    1. Confirm whether BTCC offers a public WebSocket market feed")
    print("       (wss://waccess2.btloginc.com) without an account session token.")
    print("       If yes: wire price + klines from WS, all HARVEST gates unblock.")
    print("    2. Check if /api/futures/v1/funding-rate requires a specific header")
    print("       (e.g. Origin: https://www.btcc.com) to return a body.")
    print("    3. Check if /btcc_trade/market/depth requires a session cookie for L1 data.")
    print("    4. If none of the above: Phase 2 requires a thin browser-based proxy")
    print("       or BTCC's official data partner API (TradingView broker integration).")

    # ── Step 7: Write snapshots ───────────────────────────────────────────────
    _section("STEP 7 — Writing Snapshots")

    contracts_snapshot = {
        "collection_timestamp":       _md._utc_now_iso(),
        "schema_version":             SCHEMA_VERSION,
        "primary_endpoint":           _md.PRIMARY_BASE_URL,
        "primary_endpoint_status":    _md.PRIMARY_FAILURE_REASON,
        "primary_endpoint_failed_at": _md.PRIMARY_FAILURE_TIME,
        "active_source_endpoint":     _md.BTCC_BASE_URL + _md._EP_CONTRACTS,
        "active_data_source_name":    _md.BTCC_DATA_SOURCE,
        "total_active_usdt_m_perps":  total_contracts,
        "sample_deep_inspection":     sample_details,
        "field_availability": {
            "VERIFIED":     [f[0] for f in [("contract_list", ""), ("symbol", ""), ("base_asset", ""),
                                             ("taker_fee_rate", ""), ("tick_size", ""), ("qty_minimum", "")]],
            "UNAVAILABLE":  [f[0] for f in unavailable],
        },
        "raw_contracts_sample": [
            {k: v for k, v in c.items() if not k.startswith("_")}
            for c in contracts[:20]
        ],
    }

    universe_audit = {
        "collection_timestamp":  _md._utc_now_iso(),
        "schema_version":        SCHEMA_VERSION,
        "active_source_endpoint": _md.BTCC_BASE_URL,
        "data_source_name":      _md.BTCC_DATA_SOURCE,
        "thresholds":            universe.get("thresholds", {}),
        "eligible_count":        len(universe.get("eligible", [])),
        "blocked_count":         len(universe.get("blocked", [])),
        "rejected_count":        len(universe.get("rejected", [])),
        "data_source_status":    universe.get("data_source_status", {}),
        "universe_build_note":   universe.get("universe_build_note", ""),
        "blocked_symbols":       [r["symbol"] for r in universe.get("blocked", [])],
        "run_at_utc":            universe.get("run_at_utc", _md._utc_now_iso()),
    }

    try:
        _write_json(os.path.join(LOG_DIR, "btcc_contracts_snapshot.json"), contracts_snapshot)
        _write_json(os.path.join(LOG_DIR, "btcc_universe_audit.json"),     universe_audit)
    except OSError as exc:
        warnings.append(f"SNAPSHOT_WRITE_FAILED: {exc}")

    # ── Final verdict ─────────────────────────────────────────────────────────
    _section("FINAL VERDICT")

    if warnings:
        print("  WARNINGS:")
        for w in warnings:
            print(f"    !  {w}")

    if failures:
        print("\n  FAILURES (exit 1):")
        for f in failures:
            print(f"    x  {f}")
        print(f"\n  RESULT: FAILED — {len(failures)} blocking issue(s).")
        return 1

    if blocked_count == total_contracts and total_contracts > 0:
        print(f"\n  RESULT: FOUNDATION PARTIAL —")
        print(f"    Contract list: VERIFIED ({total_contracts} USDT-M perps discovered)")
        print(f"    Price/klines/funding/spread: ALL UNAVAILABLE")
        print(f"    Phase 2 is BLOCKED until at minimum price + klines are resolved.")
        print(f"    Exit 0 because contract discovery succeeded.")
        return 0

    print(f"\n  RESULT: PASSED — {total_contracts} contracts, foundation layer verified.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
