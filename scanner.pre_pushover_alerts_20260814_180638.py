"""scanner.py — JHL Gimba Scanner

Runs the four specialists, writes canonical signals and one training observation per
completed 15-minute pressure candle. Kraken public OHLC and trade data are used
only for market-data observation; this file places no orders.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gimba_range
import gimba_trend
import gimba_volatile
import gimba_volume_flow
import gimba_drive
import gimba_pulse
import market_noise
import market_timing
import rts_liquidation
import structure_bias
from knn_engine import KNNEngine
import market_state_engine
import shadow_gimba_volatile
import shadow_trend_recovery
import delta_tempo_prop_router
PAIRS = [
    ("SOL/USD", "SOLUSD"), ("BTC/USD", "XBTUSD"), ("ETH/USD", "ETHUSD"),
    ("XRP/USD", "XRPUSD"), ("ADA/USD", "ADAUSD"), ("DOGE/USD", "XDGUSD"),
    ("LINK/USD", "LINKUSD"), ("AVAX/USD", "AVAXUSD"), ("DOT/USD", "DOTUSD"),
    ("MATIC/USD", "MATICUSD"), ("AAVE/USD", "AAVEUSD"), ("LTC/USD", "XLTCZUSD"),
]
SCAN_INTERVAL = 300
FLOW_INTERVAL_MINUTES = 15
FLOW_SOURCE = "kraken_public_trades"
KRAKEN_API = "https://api.kraken.com/0/public"
OUTPUT_FILE = Path(__file__).parent / "signals.json"
LOG_DIR = Path(__file__).parent / "training_logs"
LOG_DIR.mkdir(exist_ok=True)

_VOLUME_STATE: Dict[str, Dict[str, Any]] = {}
_SEEN_EVENT_KEYS: set[str] = set()


def _get_volume_state(pair: str) -> Dict[str, Any]:
    if pair not in _VOLUME_STATE:
        _VOLUME_STATE[pair] = {"cvd": 0.0, "window": [], "vol_ma": 0.0}
    return _VOLUME_STATE[pair]


def _request(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{KRAKEN_API}{path}?{query}", timeout=12) as response:
        payload = json.loads(response.read())
    if payload.get("error"):
        raise RuntimeError("; ".join(payload["error"]))
    return payload.get("result") or {}


def _result_rows(result: Dict[str, Any]) -> List[list]:
    key = next((name for name in result if name != "last"), None)
    return list(result.get(key) or []) if key else []



def _fetch_completed_bar_trades_paginated(
    kraken_pair: str,
    start: int,
    end: int,
    max_pages: int = 20,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Collect Kraken public trades for one completed bar using cursor pagination.

    Fails closed on a repeated/missing cursor or page-cap exhaustion. The final
    result is de-duplicated by Kraken trade id before it is used for pressure.
    """
    since = str(start)
    seen_cursors: set[str] = set()
    trades_by_id: Dict[str, Dict[str, Any]] = {}

    try:
        for _ in range(max_pages):
            result = _request("/Trades", {"pair": kraken_pair, "since": since, "count": 1000})
            raw_trades = _result_rows(result)
            next_cursor = str(result.get("last") or "")

            for raw in raw_trades:
                if len(raw) < 7:
                    continue
                trade_time = float(raw[2])
                if start <= trade_time < end:
                    trade_id = str(raw[6])
                    trades_by_id[trade_id] = {
                        "price": float(raw[0]),
                        "size": float(raw[1]),
                        "side": str(raw[3]).lower(),
                        "timestamp": trade_time,
                        "trade_id": trade_id,
                    }

            # A short page means Kraken has exhausted currently available rows.
            if len(raw_trades) < 1000:
                return list(trades_by_id.values()), None

            # At 1,000 rows we must advance with Kraken's cursor; never use a capped page.
            if not next_cursor or next_cursor == since or next_cursor in seen_cursors:
                return [], "trade_pagination_cursor_stalled"
            seen_cursors.add(since)
            since = next_cursor

        return [], f"trade_pagination_page_limit_{max_pages}"
    except Exception as exc:
        return [], f"kraken_trade_pagination_error:{type(exc).__name__}"


def fetch_bar_data(pair: str, kraken_pair: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Optional[str]]:
    """Get one completed 15m OHLC bar and its classified Kraken public trades.

    Kraken's OHLC endpoint always includes an incomplete final bar, so this uses
    the penultimate row. A trade response at its 1000-trade cap is rejected
    rather than used as incomplete pressure data.
    """
    try:
        ohlc_result = _request("/OHLC", {"pair": kraken_pair, "interval": FLOW_INTERVAL_MINUTES})
        rows = _result_rows(ohlc_result)
        if len(rows) < 2:
            return [], {}, "insufficient_ohlc_rows"
        row = rows[-2]
        start = int(float(row[0]))
        end = start + FLOW_INTERVAL_MINUTES * 60
        ohlcv = {
            "open": float(row[1]), "high": float(row[2]), "low": float(row[3]),
            "close": float(row[4]), "volume": float(row[6]), "bar_start": start, "bar_end": end,
        }

        trades, trade_error = _fetch_completed_bar_trades_paginated(
            kraken_pair=kraken_pair,
            start=start,
            end=end,
        )
        if trade_error:
            return [], ohlcv, trade_error
        return trades, ohlcv, None
    except Exception as exc:
        return [], {}, f"kraken_fetch_error:{type(exc).__name__}"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _ts_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conviction_bar(value: float, width: int = 10) -> str:
    filled = max(0, min(width, int(round(value * width))))
    return "[" + "█" * filled + "░" * (width - filled) + f"] {value:.2f}"


def _append_training_log(
    bot_name: str, pair: str, signal: Dict[str, Any], ts: str, event_key: str,
    structure: Dict[str, Any], diagnostics: Dict[str, Any], volume_flow: Dict[str, Any],
) -> None:
    if event_key in _SEEN_EVENT_KEYS:
        return
    _SEEN_EVENT_KEYS.add(event_key)
    persisted_diagnostics = dict(diagnostics or {})
    persisted_diagnostics.update(signal.get("diagnostics") or {})
    record = {
        "schema_version": 2,
        "event_key": event_key,
        "ts": ts,
        "pair": pair,
        "bot": bot_name,
        "setup_type": signal.get("setup_type", ""),
        "state": signal.get("pulse_state") or signal.get("setup_type", ""),
        "bias": signal.get("bias", "NONE"),
        "conviction": signal.get("conviction", 0.0),
        "pulse_score": signal.get("pulse_score"),
        "action": signal.get("action_state", "idle"),
        "why": signal.get("why", ""),
        "training_only": bool(signal.get("training_only")),
        "diagnostic_only": bool(signal.get("diagnostic_only")),
        "indicators": signal.get("indicators", {}),
        "trap_score": signal.get("trap_score"),
        "entry": signal.get("entry"), "sl": signal.get("sl"), "tp": signal.get("tp"),
        "structure": structure,
        "diagnostics": persisted_diagnostics,
        "volume_flow": volume_flow,
        "market_noise": signal.get("market_noise") or market_noise.unavailable("market_noise_missing"),
        "market_timing": signal.get("market_timing") or market_timing.unavailable("market_timing_missing"),
        "outcome": {"status": "pending", "label": None},
    }
    with (LOG_DIR / f"{bot_name}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")





def _delta_eligibility(
    delta: Dict[str, Any],
    volume_flow: Dict[str, Any],
    structure: Dict[str, Any],
) -> Dict[str, Any]:
    """Classify a Delta card for display/alert readiness only; never places orders."""
    event = str(delta.get("event") or "NO_DELTA")
    side = "LONG" if event.startswith("DELTA_LONG") else "SHORT" if event.startswith("DELTA_SHORT") else "NONE"
    shield_raw = delta.get("shield") or []
    shield = [str(item) for item in ([shield_raw] if isinstance(shield_raw, str) else shield_raw)]
    shield_lower = {item.lower() for item in shield}
    geometry_status = str(delta.get("geometry_status") or "PENDING")
    radar = str(delta.get("radar_state") or "NO_TARGET")
    executioner = str(delta.get("executioner_state") or "NO_TRADE")
    flow_ready = bool(volume_flow.get("ready", False))
    bos = bool(delta.get("bos", False))

    data_tokens = (
        "kraken_fetch_error",
        "trade_response_at_limit",
        "trade_pagination_",
        "local_15m_bars_unavailable",
        "local_bars_unavailable",
        "delta_unavailable",
    )
    has_data_failure = (
        not flow_ready
        or geometry_status in {"LOCAL_15M_BARS_UNAVAILABLE", "LOCAL_BARS_UNAVAILABLE"}
        or any(any(token in item for token in data_tokens) for item in shield_lower)
    )
    if has_data_failure:
        return {
            "eligibility_state": "NO_DATA",
            "eligibility_blockers": ["market_data_unavailable"],
            "eligibility_reason": "Market-data inputs are incomplete; card is not evaluable",
            "side": side,
        }

    location_tokens = {
        "range_long_into_premium",
        "range_short_into_discount",
        "range_midpoint_no_room",
    }
    has_location_failure = bool(shield_lower & location_tokens)
    geometry_valid = geometry_status == "LOCAL_STRUCTURE_VALID"
    try:
        room_to_risk = float(delta.get("room_to_risk"))
    except (TypeError, ValueError):
        room_to_risk = 0.0
    geometry_ok = geometry_valid and room_to_risk >= 1.50

    if side == "NONE" or event == "NO_DELTA":
        return {
            "eligibility_state": "BUILDING",
            "eligibility_blockers": ["no_directional_delta"],
            "eligibility_reason": "No directional Delta event yet",
            "side": side,
        }

    if has_location_failure or radar == "NO_TARGET":
        return {
            "eligibility_state": "REJECTED",
            "eligibility_blockers": [item for item in shield if item in location_tokens] or ["no_valid_target"],
            "eligibility_reason": "Location or target radar rejects this direction",
            "side": side,
        }

    if not geometry_ok:
        return {
            "eligibility_state": "BUILDING",
            "eligibility_blockers": ["geometry_below_minimum"],
            "eligibility_reason": "Directional idea exists but local geometry is below the 1.50R floor",
            "side": side,
        }

    confirmation_blockers = []
    if "pressure_not_aligned" in shield_lower:
        confirmation_blockers.append("pressure")
    if "cvd_not_aligned" in shield_lower:
        confirmation_blockers.append("cvd")
    if not bos:
        confirmation_blockers.append("bos")
    if executioner not in {"READY", "EXECUTION_READY"}:
        confirmation_blockers.append("executioner")

    if confirmation_blockers:
        return {
            "eligibility_state": "ELIGIBLE_WATCH",
            "eligibility_blockers": confirmation_blockers,
            "eligibility_reason": "Valid map and target; waiting for confirmation gates",
            "side": side,
        }

    return {
        "eligibility_state": "EXECUTION_ELIGIBLE",
        "eligibility_blockers": [],
        "eligibility_reason": "All observation gates are aligned; manual review only",
        "side": side,
    }


def _delta_candidate_repair(delta: Dict[str, Any], structure: Dict[str, Any]) -> tuple[str, str]:
    """Return a machine key and concise next-step text for an observation-only Delta card."""
    shield_raw = delta.get("shield") or []
    shield = {str(item) for item in ([shield_raw] if isinstance(shield_raw, str) else shield_raw)}
    event = str(delta.get("event") or "NO_DELTA")
    side = "LONG" if event.startswith("DELTA_LONG") else "SHORT" if event.startswith("DELTA_SHORT") else "NONE"
    trend = str(delta.get("trend") or structure.get("trend") or "unknown")
    zone = str(delta.get("zone") or structure.get("zone") or "neutral")
    geometry = str(delta.get("geometry_status") or "PENDING")
    room = delta.get("room_to_risk")
    bos = bool(delta.get("bos", False))

    data_unavailable = (
        event == "NO_DELTA"
        and any(
            token in " ".join(shield).lower()
            for token in (
                "kraken_fetch_error",
                "trade_response_at_limit",
                "local_15m_bars_unavailable",
                "local_bars_unavailable",
                "delta_unavailable",
            )
        )
    ) or any(
        token in " ".join(shield).lower()
        for token in (
            "kraken_fetch_error",
            "trade_response_at_limit",
            "local_15m_bars_unavailable",
            "local_bars_unavailable",
        )
    ) or geometry in {"LOCAL_15M_BARS_UNAVAILABLE", "LOCAL_BARS_UNAVAILABLE"}

    if data_unavailable:
        return "restore_data", "Restore market-data inputs; do not evaluate this card"

    needs_location = (
        "range_long_into_premium" in shield
        or "range_short_into_discount" in shield
        or "range_midpoint_no_room" in shield
    )
    if needs_location:
        if side == "LONG":
            return "await_discount_edge", "Wait for a verified discount-edge reclaim"
        if side == "SHORT":
            return "await_premium_edge", "Wait for a verified premium-edge rejection"
        return "await_range_edge", "Wait for a verified range-edge test"

    insufficient_room = "room_to_risk_below_1.50" in shield or geometry == "GEOMETRY_REJECTED"
    if insufficient_room or (isinstance(room, (int, float)) and room < 1.50):
        return "rebuild_geometry", "Wait for a new local map with at least 1.50R"

    if "pressure_not_aligned" in shield and "cvd_not_aligned" in shield:
        return "await_pressure_and_cvd", "Wait for completed-bar pressure and CVD alignment"
    if "pressure_not_aligned" in shield:
        return "await_pressure_alignment", "Wait for completed-bar pressure alignment"
    if "cvd_not_aligned" in shield:
        return "await_cvd_alignment", "Wait for completed-bar CVD alignment"

    if not bos and str(delta.get("radar_state") or "") in {"TARGET_RECLAIM", "TARGET_REVERSAL"}:
        if trend == "up" and side == "LONG":
            return "await_reclaim_bos", "Wait for reclaim/BOS confirmation"
        if trend == "down" and side == "SHORT":
            return "await_reclaim_bos", "Wait for reclaim/BOS confirmation"
        return "await_reclaim_confirmation", "Wait for local reclaim or BOS confirmation"

    if event == "NO_DELTA":
        return "no_action", "No Delta pressure event; continue observing"

    return "observe", "Continue observing for confirmation or invalidation"


def _append_delta_ledger(
    pair: str,
    delta: Dict[str, Any],
    ts: str,
    volume_flow: Dict[str, Any],
    structure: Dict[str, Any],
    market_noise: Dict[str, Any],
    market_timing: Dict[str, Any],
    market_state: Dict[str, Any],
) -> None:
    """Write one canonical Delta 2.0 observation per completed pressure bar."""
    bar_start = volume_flow.get("bar_start")
    if bar_start is None:
        return

    event_key = f"{pair}|delta_tempo|{FLOW_INTERVAL_MINUTES}m|{bar_start}"
    ledger_path = LOG_DIR / "delta_tempo.jsonl"
    seen_path = LOG_DIR / "delta_tempo_seen.json"

    try:
        seen = set(json.loads(seen_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        seen = set()

    if event_key in seen:
        return

    shield = delta.get("shield") or []
    if isinstance(shield, str):
        shield = [shield]

    event = str(delta.get("event") or "NO_DELTA")
    router_side = str(delta.get("side") or "NONE").upper()
    if event.startswith("DELTA_LONG"):
        side = "LONG"
    elif event.startswith("DELTA_SHORT"):
        side = "SHORT"
    else:
        side = router_side

    next_condition, repair_text = _delta_candidate_repair(delta, structure)

    record = {
        "schema_version": 1,
        "event_key": event_key,
        "ts": ts,
        "pair": pair,
        "timeframe": f"{FLOW_INTERVAL_MINUTES}m",
        "bar_start": bar_start,
        "bar_end": volume_flow.get("bar_end"),
        "event": event,
        "side": side,
        "speed_score": delta.get("speed_score"),
        "speed_change_ratio": delta.get("speed_change_ratio"),
        "market_condition": (
            delta.get("market_condition")
            or structure.get("market_condition")
            or market_state.get("market_condition")
        ),
        "trend": delta.get("trend") or structure.get("trend", "unknown"),
        "zone": delta.get("zone") or structure.get("zone", "neutral"),
        "radar_state": delta.get("radar_state", "NO_TARGET"),
        "executioner_state": delta.get("executioner_state", "NO_TRADE"),
        "bos": bool(delta.get("bos", False)),
        "geometry_status": delta.get("geometry_status", "PENDING"),
        "geometry_reason": delta.get("geometry_reason"),
        "entry": delta.get("entry"),
        "sl": delta.get("sl"),
        "tp": delta.get("tp"),
        "room_to_risk": delta.get("room_to_risk"),
        "shield": shield,
        "eligibility": delta.get("eligibility") or _delta_eligibility(delta, volume_flow, structure),
        "next_condition": next_condition,
        "repair_text": repair_text,
        "timing_state": market_timing.get("timing_state", "OBSERVE"),
        "noise_regime": market_noise.get("regime", "unavailable"),
        "noise_score": market_noise.get("noise_score"),
        "flow_ready": bool(volume_flow.get("ready", False)),
        "flow_reason": volume_flow.get("reason"),
        "structure": structure,
        "market_state": market_state,
        "outcome": {
            "status": "pending",
            "label": None,
            "resolved_at": None,
            "first_touch": None,
            "bars_to_resolution": None,
        },
    }

    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    seen.add(event_key)
    seen_path.write_text(
        json.dumps(sorted(seen), ensure_ascii=False),
        encoding="utf-8",
    )


def _apply_knn(bot_name: str, signal: Dict[str, Any], structure: Dict[str, Any], volume_flow: Dict[str, Any]) -> None:
    candidate = dict(signal)
    candidate["structure"] = structure
    candidate["diagnostics"] = signal.get("diagnostics") or {}
    candidate["volume_flow"] = volume_flow
    try:
        adjustment, samples = KNNEngine(bot_name, LOG_DIR, min_samples=30).adjust(candidate)
    except Exception:
        adjustment, samples = 0.0, 0
    signal["knn_adj"] = adjustment if samples >= 30 else 0.0
    signal["knn_samples"] = samples
    if samples >= 30 and signal.get("action_state") == "watch":
        signal["conviction"] = round(max(0.0, min(1.0, float(signal.get("conviction", 0.0)) + adjustment)), 3)


def _log_counts() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for bot in ("gimba_volatile", "gimba_range", "rts_liquidation", "gimba_trend", "gimba_drive", "gimba_pulse",
                "shadow_volatile", "shadow_trend_recovery"):
        path = LOG_DIR / f"{bot}.jsonl"
        counts[bot] = sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else 0
    return counts


def _event_bar_key(bot_name: str, signal: Dict[str, Any], volume_flow: Dict[str, Any], ts: str) -> str:
    bar_start = volume_flow.get("bar_start")
    if bar_start is not None:
        return str(bar_start)
    if bot_name == "gimba_pulse":
        pulse_bar_start = (signal.get("diagnostics") or {}).get("reference_bar_start")
        if pulse_bar_start is not None:
            return str(pulse_bar_start)
    return str(ts)


def _print_table(results: List[Dict[str, Any]], cycle: int, ts: str) -> None:
    os.system("cls" if os.name == "nt" else "clear")
    counts = _log_counts()

    print("╔══════════════════════════════════════════════════════════════════════════════╗")
    print(f"║ JHL DELTA 2.0 │ Cycle {cycle:03d} │ {ts:<43}║")
    print(
        f"║ Logs: GV={counts['gimba_volatile']:>4} GR={counts['gimba_range']:>4} "
        f"RTS={counts['rts_liquidation']:>4} DRV={counts['gimba_drive']:>4} "
        f"PUL={counts['gimba_pulse']:>4} │ ORDERS DISABLED{'':>17}║"
    )
    print("╠══════════════════════════════════════════════════════════════════════════════╣")

    for row in results:
        pair = row["pair"]
        delta = row.get("delta_tempo") or {}
        structure = row.get("structure") or {}
        timing = row.get("market_timing") or {}
        noise = row.get("market_noise") or {}
        pressure = row.get("volume_flow") or {}

        event = str(delta.get("event") or "NO_DELTA")
        radar = str(delta.get("radar_state") or "NO_TARGET")
        executioner = str(delta.get("executioner_state") or "NO_TRADE")
        shield = ", ".join(str(item) for item in (delta.get("shield") or [])) or "clear"

        speed = delta.get("speed_score")
        speed_text = "—" if speed is None else f"{float(speed):.3f}"

        ratio = delta.get("speed_change_ratio")
        ratio_text = "—" if ratio is None else f"{float(ratio):.2f}x"

        market_condition = str(
            delta.get("market_condition")
            or structure.get("market_condition")
            or "UNKNOWN"
        )
        trend = str(delta.get("trend") or structure.get("trend") or "unknown")
        zone = str(delta.get("zone") or structure.get("zone") or "neutral")
        bos = "YES" if delta.get("bos") else "NO"

        geometry_status = str(delta.get("geometry_status") or "PENDING")

        if geometry_status == "LOCAL_STRUCTURE_VALID":
            entry = delta.get("entry")
            stop = delta.get("sl")
            target = delta.get("tp")
            room = delta.get("room_to_risk")

            if all(value is not None for value in (entry, stop, target, room)):
                geometry_text = (
                    f"Entry {float(entry):.6g} | Stop {float(stop):.6g} | "
                    f"Target {float(target):.6g} | {float(room):.2f}R"
                )
            else:
                geometry_text = "VALID but one or more numeric levels missing"
        elif geometry_status == "GEOMETRY_REJECTED":
            geometry_text = f"REJECTED: {delta.get('geometry_reason', 'unknown')}"
        else:
            geometry_text = str(delta.get("geometry_reason") or geometry_status)

        print(f"║ ── {pair:<9} EVENT {event:<28} SPEED {speed_text:<7} Δ {ratio_text:<6}║")
        print(
            f"║ STRUCTURE  {market_condition:<25} "
            f"TREND {trend:<8} ZONE {zone:<9}║"
        )
        print(
            f"║ RADAR      {radar:<22} EXECUTIONER {executioner:<20} "
            f"BOS {bos:<3}║"
        )
        print(f"║ GEOMETRY   {geometry_text[:62]:<62}║")
        eligibility = _delta_eligibility(delta, pressure, structure)
        eligibility_state = str(eligibility.get("eligibility_state") or "BUILDING")
        blockers = eligibility.get("eligibility_blockers") or []
        blockers_text = "CLEAR" if not blockers else ", ".join(str(item) for item in blockers)
        print(f"║ STATUS     {eligibility_state[:62]:<62}║")
        print(f"║ GATES      {blockers_text[:62]:<62}║")
        print(f"║ SHIELD     {shield[:62]:<62}║")
        _, repair_text = _delta_candidate_repair(delta, structure)
        print(f"║ FIX        {repair_text[:62]:<62}║")

        if noise.get("available"):
            noise_text = (
                f"{noise.get('regime', 'UNKNOWN')} "
                f"{float(noise.get('noise_score', 0.0)):.2f}"
            )
        else:
            noise_text = "unavailable"

        print(
            f"║ CONTEXT    timing={timing.get('timing_state', 'OBSERVE')} "
            f"noise={noise_text} "
            f"KNN({delta.get('knn_samples', 0)}) "
            f"{float(delta.get('knn_adjustment', 0.0)):+.3f}║"
        )

        pulse = row.get("gimba_pulse") or {}
        drive = row.get("gimba_drive") or {}
        rts = row.get("rts_liq") or {}
        gr = row.get("gimba_range") or {}

        pulse_label = pulse.get("pulse_state") or pulse.get("setup_type") or "—"
        drive_label = drive.get("setup_type") or "—"
        range_label = gr.get("setup_type") or "—"
        rts_label = rts.get("setup_type") or "—"

        telemetry = (
            f"Pulse={pulse_label} | Drive={drive_label} | "
            f"Range={range_label} | RTS={rts_label}"
        )
        print(f"║ TELEMETRY  {telemetry[:62]:<62}║")

        status = (
            "READY"
            if pressure.get("ready")
            else f"OFF:{pressure.get('reason', 'unknown')}"
        )
        print(f"║ FLOW       {status[:68]:<68}║")
        print("║")

    print("╚══════════════════════════════════════════════════════════════════════════════╝")
    print(
        f"Next scan in {SCAN_INTERVAL}s │ Flow candle {FLOW_INTERVAL_MINUTES}m │ "
        "Delta 2.0 observation only │ Ctrl+C to stop"
    )


def _apply_structure_amplifier(signals: List[Dict[str, Any]], structure: Dict[str, Any]) -> None:
    trend = structure.get("trend", "ranging")
    zone = structure.get("zone", "neutral")
    amp = float(structure.get("amplifier", 1.0))
    counter = float(structure.get("counter_amplifier", 0.70))
    for signal in signals:
        bias = signal.get("bias", "NONE")
        if bias == "NONE" or signal.get("action_state") != "watch":
            continue
        if signal.get("engine") == "GimbaRange":
            multiplier = 1.10 if (bias == "LONG" and zone == "discount") or (bias == "SHORT" and zone == "premium") else 0.65 if (bias == "LONG" and zone == "premium") or (bias == "SHORT" and zone == "discount") else 1.0
        else:
            multiplier = amp if (trend == "up" and bias == "LONG") or (trend == "down" and bias == "SHORT") else counter if (trend == "up" and bias == "SHORT") or (trend == "down" and bias == "LONG") else 1.0
        signal["conviction"] = round(min(float(signal.get("conviction", 0.0)) * multiplier, 1.0), 3)
        signal["structure_amp"] = multiplier


def _fetch_ohlc_arrays(kraken_pair: str, interval: int = 15, limit: int = 60) -> Optional[tuple]:
    """Fetch OHLCV rows from Kraken and return numpy arrays (o, h, l, c, v, last_ts).

    Returns None on error or insufficient data.
    """
    import json as _json
    import numpy as _np

    url = f"https://api.kraken.com/0/public/OHLC?pair={kraken_pair}&interval={interval}"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = _json.loads(r.read())
        if data.get("error"):
            return None
        result = data.get("result", {})
        key = [k for k in result if k != "last"]
        if not key:
            return None
        rows = result[key[0]][-limit:]
        if len(rows) < 30:
            return None
        o = _np.array([float(row[1]) for row in rows], dtype=float)
        h = _np.array([float(row[2]) for row in rows], dtype=float)
        l = _np.array([float(row[3]) for row in rows], dtype=float)
        c = _np.array([float(row[4]) for row in rows], dtype=float)
        v = _np.array([float(row[6]) for row in rows], dtype=float)
        last_ts = int(float(rows[-1][0]))
        return o, h, l, c, v, last_ts
    except Exception:
        return None


def _append_shadow_log(
    bot_name: str, pair: str, signal: Dict[str, Any], ts: str, event_key: str,
    structure: Dict[str, Any], volume_flow: Dict[str, Any],
) -> None:
    """Persist a shadow candidate record to its dedicated JSONL file."""
    if event_key in _SEEN_EVENT_KEYS:
        return
    _SEEN_EVENT_KEYS.add(event_key)
    record = {
        "schema_version": 2,
        "event_key": event_key,
        "ts": ts,
        "pair": pair,
        "bot": bot_name,
        "setup_family": signal.get("setup_family", ""),
        "side": signal.get("side", "NONE"),
        "score": signal.get("score", 0.0),
        "state": signal.get("state", ""),
        "reasons": signal.get("reasons", []),
        "required_inputs": signal.get("required_inputs", []),
        "invalidation_level": signal.get("invalidation_level"),
        "maturity_context": signal.get("maturity_context"),
        "reference_price": signal.get("reference_price"),
        "reference_bar_ts": signal.get("reference_bar_ts"),
        "shadow_mode": signal.get("shadow_mode", True),
        "diagnostic_only": signal.get("diagnostic_only", True),
        "training_only": signal.get("training_only", True),
        "action_state": signal.get("action_state", "observe"),
        "entry": None,
        "sl": None,
        "tp": None,
        "indicators": signal.get("indicators", {}),
        "structure": structure,
        "volume_flow": volume_flow,
        "market_noise": signal.get("market_noise") or market_noise.unavailable("market_noise_missing"),
        "market_timing": signal.get("market_timing") or market_timing.unavailable("market_timing_missing"),
        "outcome": {"status": "pending", "label": None},
    }
    with (LOG_DIR / f"{bot_name}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _attach_market_noise(signal: Dict[str, Any], noise: Dict[str, Any]) -> Dict[str, Any]:
    signal["market_noise"] = dict(noise or market_noise.unavailable("market_noise_missing"))
    return signal


def _attach_market_timing(signal: Dict[str, Any], timing: Dict[str, Any]) -> Dict[str, Any]:
    signal["market_timing"] = dict(timing or market_timing.unavailable("market_timing_missing"))
    return signal


def _evaluate_raw(module, pair: str, kraken_pair: str, fg_score: int) -> Dict[str, Any]:
    """
    Call the specialist's raw evaluator without using its internal KNN wrapper.

    The installed bot files do not all use the same raw evaluator spelling.
    We intentionally do not fall back to evaluate_with_knn(), because the
    scanner must attach structure and volume_flow before KNN is applied.
    """
    for name in ("evaluate_pair", "evaluatepair", "evaluate"):
        fn = getattr(module, name, None)
        if callable(fn):
            return fn(pair, kraken_pair, 0.0, fg_score)

    available = sorted(
        name for name in dir(module)
        if name.startswith("evaluate")
    )
    raise AttributeError(
        f"{module.__name__} has no raw evaluator. "
        f"Found evaluator names: {available}"
    )


def run_cycle(cycle: int, fg_score: int = 50) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    ts = _ts_iso()

    for pair, kraken_pair in PAIRS:
        # 1. Shared structure context
        structure = structure_bias.evaluate(pair, kraken_pair)

        # 2. Completed-candle pressure context
        trades, ohlcv, fetch_error = fetch_bar_data(pair, kraken_pair)
        state = _get_volume_state(pair)

        if fetch_error:
            volume_flow = gimba_volume_flow.unavailable(
                fetch_error,
                FLOW_SOURCE,
            )
        else:
            volume = float(ohlcv.get("volume", 0.0))

            if state["vol_ma"] <= 0:
                state["vol_ma"] = volume
            else:
                state["vol_ma"] = (
                    0.9 * state["vol_ma"]
                    + 0.1 * volume
                )

            volume_flow = gimba_volume_flow.volume_specialist(
                trades_bar=trades,
                ohlcv=ohlcv,
                vol_ma=state["vol_ma"],
                prev_cvd=state["cvd"],
                prev_cvd_window=state["window"],
                cvd_window_size=20,
                source=FLOW_SOURCE,
            )

            if volume_flow.get("ready"):
                state["cvd"] = float(volume_flow["cvd"])
                state["window"] = (
                    state["window"] + [state["cvd"]]
                )[-20:]

        volume_flow["timeframe"] = f"{FLOW_INTERVAL_MINUTES}m"
        volume_flow["bar_start"] = ohlcv.get("bar_start")
        volume_flow["bar_end"] = ohlcv.get("bar_end")

        # 3. Raw specialist evaluation.
        # Do NOT call evaluate_with_knn here.
        gv = _evaluate_raw(
            gimba_volatile,
            pair,
            kraken_pair,
            fg_score,
        )
        gr = _evaluate_raw(
            gimba_range,
            pair,
            kraken_pair,
            fg_score,
        )
        rts = _evaluate_raw(
            rts_liquidation,
            pair,
            kraken_pair,
            fg_score,
        )
        trd = _evaluate_raw(
            gimba_trend,
            pair,
            kraken_pair,
            fg_score,
        )
        pulse = gimba_pulse.evaluate(pair, kraken_pair, 0.0, fg_score)
        # Drive is evaluated with shared structure context to avoid duplicate
        # OHLC fetches and to ensure consistent HTF alignment interpretation.
        drv = gimba_drive.evaluate(pair, kraken_pair, 0.0, fg_score, structure=structure)

        # Shadow candidate specialists — fetch OHLCV arrays once and share.
        # These are always inert (shadow_mode=True, action_state='observe').
        _ohlcv_arrays = _fetch_ohlc_arrays(kraken_pair, interval=15, limit=60)
        _ref_ts = volume_flow.get("bar_start")
        shared_market_noise = market_noise.unavailable(
            "market_noise_fetch_failed",
            reference_bar_start=_ref_ts,
        )
        if _ohlcv_arrays is not None:
            _o, _h, _l, _c, _v, _last_ts = _ohlcv_arrays
            _bar_ts = _ref_ts if _ref_ts is not None else _last_ts
            _noise_ref_ts = _ref_ts if _ref_ts is not None else _last_ts - FLOW_INTERVAL_MINUTES * 60
            shared_market_noise = market_noise.observe(
                _o[:-1],
                _h[:-1],
                _l[:-1],
                _c[:-1],
                _v[:-1],
                reference_bar_start=_noise_ref_ts,
            )
            shd_vol = shadow_gimba_volatile.evaluate_arrays(
                pair, _o, _h, _l, _c, _v, reference_bar_ts=_bar_ts,
            )
            shd_trd = shadow_trend_recovery.evaluate_arrays(
                pair, _o, _h, _l, _c, _v,
                structure_context=structure,
                reference_bar_ts=_bar_ts,
            )
        else:
            shd_vol = shadow_gimba_volatile._null_result(pair, "ohlcv_fetch_failed")
            shd_trd = shadow_trend_recovery._null_result(pair, "ohlcv_fetch_failed")

        # gimba_volatile and gimba_trend are diagnostic context providers only.
        # They must not generate execution eligibility.
        gv["diagnostic_only"] = True
        trd["diagnostic_only"] = True
        # Drive and Pulse are Delta Tempo contributors only; neither has entry authority.
        drv["training_only"] = False
        drv["diagnostic_only"] = False
        pulse["training_only"] = False
        pulse["diagnostic_only"] = False
        # Active execution specialists only (Range, RTS); Drive is training-only.
        exec_signals = [gr, rts]

        # 4. Infer observed market state.
        market_state = market_state_engine.evaluate(
            structure=structure,
            volume_flow=volume_flow,
            signals={
                "gimba_volatile": gv,
                "gimba_range": gr,
                "rts_liq": rts,
                "gimba_trend": trd,
            },
        )

        # 5. Apply structure amplifier to active execution specialists only.
        _apply_structure_amplifier(exec_signals, structure)

        # 6. Apply KNN to active execution specialists and Drive (training).
        for bot_name, signal in zip(
            (
                "gimba_range",
                "rts_liquidation",
                "gimba_drive",
            ),
            exec_signals + [drv],
        ):
            _apply_knn(
                bot_name,
                signal,
                structure,
                volume_flow,
            )

        for signal in (gv, gr, rts, trd, drv, pulse, shd_vol, shd_trd):
            _attach_market_noise(signal, shared_market_noise)

        shared_market_timing = market_timing.observe(
            structure=structure,
            volume_flow=volume_flow,
            market_noise=shared_market_noise,
            market_state=market_state,
            rts_signal=rts,
            range_signal=gr,
        )
        for signal in (gv, gr, rts, trd, drv, pulse, shd_vol, shd_trd):
            _attach_market_timing(signal, shared_market_timing)

        # 6b. Delta Tempo is the sole entry authority. Range, RTS, Drive, and

        # Pulse contribute context and claims only; none emits its own entry card.

        _apply_knn("gimba_pulse", pulse, structure, volume_flow)

        delta_tempo = delta_tempo_prop_router.evaluate(

            pair=pair,

            kraken_pair=kraken_pair,

            volume_flow=volume_flow,

            market_timing=shared_market_timing,

            signals={

                "gimba_range": gr,

                "rts_liq": rts,

                "gimba_drive": drv,

                "gimba_pulse": pulse,

                
            },

            log_dir=LOG_DIR,
        structure=structure,
        market_state=market_state,
        ohlcv_arrays=_ohlcv_arrays,
    )



        _append_delta_ledger(
            pair=pair,
            delta=delta_tempo,
            ts=ts,
            volume_flow=volume_flow,
            structure=structure,
            market_noise=shared_market_noise,
            market_timing=shared_market_timing,
            market_state=market_state,
        )

        delta_tempo["eligibility"] = _delta_eligibility(
            delta_tempo,
            volume_flow,
            structure,
        )

        # 7. Log one observation per bot per completed pressure candle.
        for bot_name, signal in zip(
            (
                "gimba_volatile",
                "gimba_range",
                "rts_liquidation",
                "gimba_trend",
                "gimba_drive",
                "gimba_pulse",
            ),
            [gv, gr, rts, trd, drv, pulse],
        ):
            event_key = (
                f"{pair}|{bot_name}|"
                f"{FLOW_INTERVAL_MINUTES}m|{_event_bar_key(bot_name, signal, volume_flow, ts)}"
            )

            _append_training_log(
                bot_name=bot_name,
                pair=pair,
                signal=signal,
                ts=ts,
                event_key=event_key,
                structure=structure,
                diagnostics=signal.get("diagnostics") or {},
                volume_flow=volume_flow,
            )

        # Shadow candidate specialists — dedicated JSONL logs, always [SHADOW].
        for shd_bot, shd_sig in (
            ("shadow_volatile", shd_vol),
            ("shadow_trend_recovery", shd_trd),
        ):
            shd_event_key = (
                f"{pair}|{shd_bot}|"
                f"{FLOW_INTERVAL_MINUTES}m|{_event_bar_key(shd_bot, shd_sig, volume_flow, ts)}"
            )
            _append_shadow_log(
                bot_name=shd_bot,
                pair=pair,
                signal=shd_sig,
                ts=ts,
                event_key=shd_event_key,
                structure=structure,
                volume_flow=volume_flow,
            )

        # 8. Publish the unified row for the scanner, readers, and HTML.
        results.append(
            {
                "pair": pair,
                "gimba_volatile": gv,
                "gimba_range": gr,
                "rts_liq": rts,
                "gimba_trend": trd,
                "gimba_drive": drv,
                "gimba_pulse": pulse,
            "delta_tempo": delta_tempo,
            
            
                "shadow_volatile": shd_vol,
                "shadow_trend_recovery": shd_trd,
                "structure": structure,
                "volume_flow": volume_flow,
                "market_noise": dict(shared_market_noise),
                "market_timing": dict(shared_market_timing),
                "market_state": market_state,
            }
        )

    return results

def main() -> None:
    cycle = 1
    print("Starting JHL Gimba Scanner — 12 pairs, canonical logs active...")
    while True:
        try:
            results = run_cycle(cycle)
            ts = _now()
            _print_table(results, cycle, ts)
            OUTPUT_FILE.write_text(json.dumps({"ts": ts, "cycle": cycle, "signals": results}, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            print(f"\n[ERROR] Cycle {cycle}: {exc}")
        cycle += 1
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScanner stopped.")
