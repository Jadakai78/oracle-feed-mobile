from __future__ import annotations

from typing import Any, Dict, List

from shadow_sentinel import ShadowSentinel
from shadow_audit_ledger import ShadowAuditLedger
from shadow_audit_adapter import append_payload_observations


_sentinel = ShadowSentinel()


def _shadow_metadata_from_gimba_row(row: Dict[str, Any]) -> Dict[str, Any]:
    structure = row.get("structure") or {}
    rts = row.get("rts_liq") or {}
    vol = row.get("gimba_volatile") or {}
    trend = row.get("gimba_trend") or {}

    # Live quote / OHLC: Gimba uses Kraken, but we don't have a freshness flag here.
    live_quote_valid = True
    ohlc_ready = structure.get("state") not in ("STRUCTURE_UNCLEAR", None)

    # Trap risk from RTS trap_score (with softer thresholds)
    trap_score = rts.get("trap_score")
    try:
        trap_score_f = float(trap_score) if trap_score is not None else 0.5
    except (TypeError, ValueError):
        trap_score_f = 0.5

    if trap_score_f >= 0.75:
        trap_risk = "high"
    elif trap_score_f >= 0.55:
        trap_risk = "elevated"
    else:
        trap_risk = "normal"

    # Relative volume: from volatile indicators
    indicators = vol.get("indicators") or {}
    rvol = indicators.get("rvol")

    if isinstance(rvol, (int, float)):
        if rvol < 0.5:
            volume_state_15m = "thin"
        elif rvol >= 1.5:
            volume_state_15m = "high"
        else:
            volume_state_15m = "normal"
    else:
        volume_state_15m = "unknown"

    # Volatility state: use ATR in context of structure state
    atr = indicators.get("atr") or 0.0
    volatility_state = "normal"
    try:
        atr_f = float(atr)
        # Treat crypto ATR approx as % of price; we don't have price so just bucket absolute
        if atr_f >= 2.0:         # BTC-like big ATR, SHIFT thresholds by instrument later
            volatility_state = "explosive"
        elif atr_f >= 0.5:
            volatility_state = "expansion"
        elif atr_f <= 0.05:
            volatility_state = "compression"
        else:
            volatility_state = "normal"
    except (TypeError, ValueError):
        pass

    # Impulse state from tempo fields
    # If most bots are EARLY or BUILDING, call it impulse_up/down based on trend.
    tempo_flags = [
        (structure.get("tempo") or "").upper(),
        (vol.get("tempo") or "").upper(),
        (rts.get("tempo") or "").upper(),
        (trend.get("tempo") or "").upper(),
    ]
    early_count = sum(1 for t in tempo_flags if t in ("EARLY", "BUILDING", "LIVE"))
    dead_count = sum(1 for t in tempo_flags if t == "DEAD")

    struct_trend = (structure.get("trend") or "ranging").lower()
    if early_count >= 2 and struct_trend in ("up", "down"):
        impulse_state = "impulse_up" if struct_trend == "up" else "impulse_down"
    elif dead_count >= 3:
        impulse_state = "rotation_chop"  # dead / noisy field
    else:
        impulse_state = "quiet"

    # Momentum bias from trend specialist + structure
    trend_bias = (trend.get("bias") or "").upper()
    if trend_bias == "LONG":
        raw_mom = "bullish"
    elif trend_bias == "SHORT":
        raw_mom = "bearish"
    else:
        raw_mom = "neutral"

    if struct_trend == "up":
        momentum_bias = "trend" if raw_mom == "bullish" else "fade" if raw_mom == "bearish" else "neutral"
    elif struct_trend == "down":
        momentum_bias = "trend" if raw_mom == "bearish" else "fade" if raw_mom == "bullish" else "neutral"
    else:
        momentum_bias = "neutral"

    return {
        "live_quote_valid": live_quote_valid,
        "ohlc_ready": ohlc_ready,
        "relative_volume_25": rvol,
        "volume_state_15m": volume_state_15m,
        "impulse_state": impulse_state,
        "momentum_bias": momentum_bias,
        "trap_risk": trap_risk,
        "volatility_state": volatility_state,
    }


def attach_shadow_to_gimba_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Attach ShadowSentinel decision to a single Gimba row as
    row["diagnostics"]["shadow_sentinel"].

    Does not change any bot signals.
    """
    # Derive a side and action_state from the "strongest" bot if any
    # Preference order: RTS, VOL, RNG when in WATCH state with bias.
    side = "BUY"
    action_state = "watch"

    for key in ("rts_liq", "gimba_volatile", "gimba_range"):
        sig = row.get(key) or {}
        if sig.get("action_state") == "watch" and sig.get("bias") in ("LONG", "SHORT"):
            side = "BUY" if sig["bias"] == "LONG" else "SELL"
            action_state = "watch"
            break

    metadata = _shadow_metadata_from_gimba_row(row)
    execution: Dict[str, Any] = {}  # no explicit execution context in Gimba

    decision = _sentinel.evaluate(
        metadata=metadata,
        action_state=action_state,
        side=side,
        execution=execution,
    )

    diagnostics = row.get("diagnostics") or {}
    diagnostics["shadow_sentinel"] = decision.to_dict()
    row["diagnostics"] = diagnostics
    return row


def attach_shadow_to_gimba_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Given a Gimba scanner payload:
      {"ts": ..., "cycle": ..., "signals": [row, ...]}
    attach ShadowSentinel to each row in place.
    """
    signals = payload.get("signals")
    if not isinstance(signals, list):
        return payload

    new_signals: List[Dict[str, Any]] = []
    for row in signals:
        if not isinstance(row, dict):
            continue
        new_signals.append(attach_shadow_to_gimba_row(row))

    payload["signals"] = new_signals
    return payload


def audit_gimba_payload_to_shadow_ledger(
    payload: Dict[str, Any],
    ledger_path: str | None = None,
) -> Dict[str, Any]:
    """
    Attach ShadowSentinel decisions to Gimba payload and append observations
    to the ShadowAuditLedger using shadow_audit_adapter.

    We adapt the Gimba signals into a pseudo-Oracled panel structure:
    opportunities = all WATCH rows with a shadow payload.
    """
    attached = attach_shadow_to_gimba_payload(dict(payload))

    # Build a lightweight panel for the adapter
    opportunities: List[Dict[str, Any]] = []
    for row in attached.get("signals", []):
        diag = row.get("diagnostics") or {}
        if "shadow_sentinel" in diag:
            opportunities.append(
                {
                    "pair": row.get("pair"),
                    "action_state": "watch",
                    "why_now": None,
                    "diagnostics": diag,
                }
            )

    panel_payload = {
        "generated_at": attached.get("ts"),
        "last_scan": attached.get("ts"),
        "panel": {
            "opportunities": opportunities,
            "watchlist": [],
            "killed": [],
        },
    }

    ledger = ShadowAuditLedger(path=ledger_path) if ledger_path else ShadowAuditLedger()
    summary = append_payload_observations(panel_payload, ledger)
    return summary
