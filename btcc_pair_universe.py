"""
btcc_pair_universe.py — JHL Holdings LLC
Dynamic active-contract eligibility builder for BTCC USDT-M perpetuals.

DATA SOURCE STATUS (2026-08-18):
  AVAILABLE:   contract list (name, fees, min_amount, tick_size) via /btcc_trade/market/list
  UNAVAILABLE: last_price, mark_price   — no public REST ticker path verified
  UNAVAILABLE: volume_24h_quote_usdt    — no public REST ticker path verified
  UNAVAILABLE: klines (5m, 15m)         — requires authenticated WebSocket sign token
  UNAVAILABLE: funding_rate             — endpoint gated (HTTP 200 empty body)
  UNAVAILABLE: spread                   — depth endpoint returns empty bids/asks

ELIGIBILITY CONSEQUENCE:
  With volume, klines, spread, and price all UNAVAILABLE, no contract can be
  confirmed eligible under the standard thresholds. The universe builder records
  the exact unavailability reason for every contract.
  A contract is NOT rejected as illiquid — it is BLOCKED_DATA_UNAVAILABLE.
  This is the correct scientific posture: absence of data ≠ ineligible.

Schema version: 1.1
"""

import time
from typing import Any, Dict, List, Tuple

import btcc_market_data as _md

# ── Named configuration constants (never magic numbers) ───────────────────────
MIN_24H_QUOTE_VOLUME_USDT: float   = 1_000_000.0
MAX_FRESHNESS_AGE_SECONDS: int     = 60
MAX_SPREAD_BPS: float              = 20.0
MIN_COMPLETED_5M_CANDLES: int      = 20
MIN_COMPLETED_15M_CANDLES: int     = 8

_INTER_SYMBOL_DELAY: float = 0.30


def _check_symbol(contract: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Evaluate a single contract for eligibility.
    Returns (eligible: bool, reasons: list[str]).

    A reason prefixed BLOCKED_DATA_UNAVAILABLE means the contract cannot be
    confirmed ineligible — data is missing, not the contract itself failing.
    """
    symbol = contract["symbol"]
    reasons: List[str] = []

    # ── Volume ────────────────────────────────────────────────────────────────
    # No verified public REST path returns volume for BTCC perpetuals.
    reasons.append(
        f"BLOCKED_DATA_UNAVAILABLE: volume_24h_quote_usdt — "
        f"no verified public REST ticker path as of 2026-08-18. "
        f"Cannot confirm meets {MIN_24H_QUOTE_VOLUME_USDT:,.0f} USDT threshold."
    )

    # ── Price / ticker freshness ──────────────────────────────────────────────
    reasons.append(
        "BLOCKED_DATA_UNAVAILABLE: last_price — "
        "no verified public REST ticker path. "
        "BTCC ticker data served via authenticated WebSocket only."
    )

    # ── Klines ────────────────────────────────────────────────────────────────
    reasons.append(
        f"BLOCKED_DATA_UNAVAILABLE: klines_5m — "
        f"no verified public REST kline path. "
        f"Requires authenticated WebSocket sign token (ReqKline). "
        f"Cannot confirm {MIN_COMPLETED_5M_CANDLES} completed 5m bars."
    )
    reasons.append(
        f"BLOCKED_DATA_UNAVAILABLE: klines_15m — same block as klines_5m."
    )

    # ── Spread ────────────────────────────────────────────────────────────────
    reasons.append(
        f"BLOCKED_DATA_UNAVAILABLE: spread_bps — "
        f"/btcc_trade/market/depth returns empty bids/asks from non-browser IP. "
        f"Cannot confirm spread ≤ {MAX_SPREAD_BPS} bps."
    )

    # Not eligible: all required data fields are blocked
    return False, reasons


def build_universe() -> Dict[str, Any]:
    """
    Build the full BTCC USDT-M perpetual universe with eligibility assessment.

    Returns:
    {
      "eligible":           [],       # empty until data paths are unblocked
      "blocked":            [...],    # contracts with BLOCKED_DATA_UNAVAILABLE reasons
      "rejected":           [],       # contracts that fail on confirmed data
      "data_source_status": {...},    # per-field availability summary
      "run_at_utc":         str,
      "thresholds":         {...},
      "universe_build_note": str,
    }
    """
    contracts = _md.get_active_contracts()

    eligible_rows: List[Dict[str, Any]] = []
    blocked_rows:  List[Dict[str, Any]] = []
    rejected_rows: List[Dict[str, Any]] = []

    for i, contract in enumerate(contracts):
        symbol = contract["symbol"]
        print(f"  [{i+1}/{len(contracts)}] {symbol}")
        time.sleep(_INTER_SYMBOL_DELAY)

        try:
            ok, reasons = _check_symbol(contract)
        except Exception as exc:
            rejected_rows.append({
                "symbol":  symbol,
                "reasons": [f"UNEXPECTED_ERROR: {exc}"],
            })
            continue

        if ok:
            eligible_rows.append({
                "symbol":              symbol,
                "base_asset":          contract.get("base_asset"),
                "contract_multiplier": contract.get("contract_multiplier"),
                "tick_size":           contract.get("tick_size"),
                "qty_step":            contract.get("qty_step"),
                "volume_24h_quote_usdt": _md.UNAVAIL_NOT_IN_RESPONSE,
            })
        else:
            # Distinguish BLOCKED (data unavailable) from REJECTED (data confirms failure)
            is_blocked = any(r.startswith("BLOCKED_DATA_UNAVAILABLE") for r in reasons)
            if is_blocked:
                blocked_rows.append({"symbol": symbol, "reasons": reasons})
            else:
                rejected_rows.append({"symbol": symbol, "reasons": reasons})

    return {
        "eligible":   eligible_rows,
        "blocked":    blocked_rows,
        "rejected":   rejected_rows,
        "data_source_status": {
            "contract_list":       "VERIFIED — /btcc_trade/market/list",
            "last_price":          _md.UNAVAIL_NOT_IN_RESPONSE,
            "mark_price":          _md.UNAVAIL_NOT_IN_RESPONSE,
            "volume_24h_usdt":     _md.UNAVAIL_NOT_IN_RESPONSE,
            "klines_5m":           _md.UNAVAIL_KLINE_NO_PUBLIC_REST,
            "klines_15m":          _md.UNAVAIL_KLINE_NO_PUBLIC_REST,
            "funding_rate":        _md.UNAVAIL_FUNDING_ENDPOINT_GATED,
            "spread_bps":          _md.UNAVAIL_DEPTH_EMPTY_RESPONSE,
        },
        "run_at_utc": _md._utc_now_iso(),
        "thresholds": {
            "MIN_24H_QUOTE_VOLUME_USDT": MIN_24H_QUOTE_VOLUME_USDT,
            "MAX_FRESHNESS_AGE_SECONDS": MAX_FRESHNESS_AGE_SECONDS,
            "MAX_SPREAD_BPS":            MAX_SPREAD_BPS,
            "MIN_COMPLETED_5M_CANDLES":  MIN_COMPLETED_5M_CANDLES,
            "MIN_COMPLETED_15M_CANDLES": MIN_COMPLETED_15M_CANDLES,
        },
        "universe_build_note": (
            "No contracts are in 'eligible' because volume, price, klines, and spread "
            "data fields are all BLOCKED_DATA_UNAVAILABLE — no verified public REST paths exist. "
            "This is the correct state. Contracts in 'blocked' are not ineligible; "
            "they cannot be scored. Phase 2 is blocked until at least price + klines are resolved."
        ),
    }
