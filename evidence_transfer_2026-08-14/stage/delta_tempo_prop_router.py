from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from knn_engine import KNNEngine

KRAKEN_API = "https://api.kraken.com/0/public"
_INTERVAL = 15
_STATE: Dict[str, Dict[str, Any]] = defaultdict(dict)


def _n(value: Any):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _side(value: Any) -> str:
    value = str(value or "").upper()
    if value in {"LONG", "UP", "BUY"}:
        return "LONG"
    if value in {"SHORT", "DOWN", "SELL"}:
        return "SHORT"
    return "NONE"


def _hma(values: List[float], period: int = 7):
    if len(values) < period:
        return None
    def wma(data, length):
        if len(data) < length:
            return None
        weights = list(range(1, length + 1))
        return sum(v * w for v, w in zip(data[-length:], weights)) / sum(weights)
    half = max(1, period // 2)
    root = max(1, int(math.sqrt(period)))
    transformed = []
    for index in range(period - 1, len(values)):
        window = values[:index + 1]
        fast, slow = wma(window, half), wma(window, period)
        if fast is not None and slow is not None:
            transformed.append(2 * fast - slow)
    return wma(transformed, root)


def _bars(kraken_pair: str):
    try:
        query = urllib.parse.urlencode({"pair": kraken_pair, "interval": _INTERVAL})
        with urllib.request.urlopen(f"{KRAKEN_API}/OHLC?{query}", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("error"):
            return None
        result = payload.get("result") or {}
        key = next((k for k in result if k != "last"), None)
        rows = list(result.get(key) or []) if key else []
        return rows[-31:-1] if len(rows) >= 31 else None
    except Exception:
        return None


def _fresh_claims(side: str, signals: Dict[str, Dict[str, Any]]):
    claims = []
    for source, key in (("RANGE", "gimba_range"), ("RTS", "rts_liq"), ("DRIVE", "gimba_drive")):
        sig = signals.get(key) or {}
        if str(sig.get("action_state", "")).lower() == "watch" and _side(sig.get("bias")) == side:
            claims.append({"source": source, "entry": sig.get("entry"), "sl": sig.get("sl"), "tp": sig.get("tp")})
    pulse = signals.get("gimba_pulse") or {}
    pulse_side = _side((pulse.get("diagnostics") or {}).get("observer_direction"))
    if str(pulse.get("pulse_state") or pulse.get("setup_type") or "") == "PULSE_IMPULSIVE" and pulse_side == side:
        claims.append({"source": "PULSE", "entry": None, "sl": None, "tp": None})
    return claims


def _risk_packet(side: str, claims, fallback_entry):
    for claim in claims:
        entry, sl, tp = _n(claim.get("entry")), _n(claim.get("sl")), _n(claim.get("tp"))
        if entry is None or sl is None or tp is None:
            continue
        if side == "LONG" and sl < entry < tp:
            return entry, sl, tp, claim["source"]
        if side == "SHORT" and tp < entry < sl:
            return entry, sl, tp, claim["source"]
    return fallback_entry, None, None, None


def evaluate(pair: str, kraken_pair: str, volume_flow: Dict[str, Any], market_timing: Dict[str, Any], signals: Dict[str, Dict[str, Any]], log_dir: str | Path) -> Dict[str, Any]:
    flow = volume_flow or {}
    delta = _n(flow.get("delta"))
    volume = _n(flow.get("volume"))
    slope = _n(flow.get("cvd_slope"))
    ready = bool(flow.get("ready")) and delta is not None and volume is not None and volume > 0 and slope is not None
    side = "LONG" if ready and delta > 0 else "SHORT" if ready and delta < 0 else "NONE"
    speed = abs(delta) / volume if ready else None
    state = _STATE[pair]
    prior_speed = state.get("speed")
    ratio = speed / prior_speed if speed is not None and prior_speed and prior_speed > 0 else None
    if speed is None:
        lifecycle = "SPEED_MISSING"
    elif prior_speed is None:
        lifecycle = "SPEED_INITIALIZED"
    elif ratio > 1.01:
        lifecycle = "SPEED_INCREASING"
    elif ratio < 0.99:
        lifecycle = "SPEED_DECAYING"
    else:
        lifecycle = "SPEED_FLAT"
    if speed is not None:
        state["speed"] = speed

    pressure_side = "LONG" if str(flow.get("delta_state", "")).lower() == "buy" else "SHORT" if str(flow.get("delta_state", "")).lower() == "sell" else "NONE"
    cvd_side = "LONG" if slope is not None and slope > 0 else "SHORT" if slope is not None and slope < 0 else "NONE"
    timing_state = str((market_timing or {}).get("timing_state", "")).upper()
    timing_fresh = timing_state not in {"", "OBSERVE", "UNAVAILABLE"}
    claims = _fresh_claims(side, signals) if side != "NONE" else []

    bars = _bars(kraken_pair)
    close = hma7 = None
    hma_confirmed = False
    if bars:
        closes = [float(row[4]) for row in bars]
        close, hma7 = closes[-1], _hma(closes, 7)
        hma_confirmed = hma7 is not None and ((side == "LONG" and close > hma7) or (side == "SHORT" and close < hma7))
    entry, sl, tp, risk_source = _risk_packet(side, claims, close)

    candidate = {"pair": pair, "speed_score": speed, "prior_speed_score": prior_speed, "speed_change_ratio": ratio, "tempo_lifecycle": lifecycle, "delta_direction": side, "pressure_direction": pressure_side, "cvd_slope_direction": cvd_side, "timing_confluence_fresh": timing_fresh, "timing_state": timing_state or "OBSERVE", "setup_claims": claims, "hma7": hma7, "close": close, "hma7_confirmed": hma_confirmed, "entry": entry, "sl": sl, "tp": tp, "risk_source": risk_source, "state": "WAITING", "reason": ""}
    gates = [
        (ready, "SPEED_UNAVAILABLE"), (side != "NONE", "DELTA_FLAT"), (side == pressure_side, "PRESSURE_NOT_ALIGNED"),
        (side == cvd_side, "CVD_NOT_ALIGNED"), (timing_fresh, "TIMING_NOT_FRESH"), (bool(claims), "NO_RANGE_RTS_DRIVE_PULSE_SETUP"),
        (lifecycle != "SPEED_DECAYING", "TEMPO_DECAY"), (hma_confirmed, "WAITING_HMA7"), (sl is not None and tp is not None, "INVALID_RISK_PACKET"),
    ]
    failures = [reason for ok, reason in gates if not ok]
    if lifecycle == "SPEED_DECAYING":
        candidate["state"] = "DECAYING"
    elif not failures:
        candidate["state"] = "ENTRY"
    elif ready and claims and side == pressure_side and side == cvd_side:
        candidate["state"] = "ARMED"
    candidate["reason"] = "all_delta_tempo_gates_met" if not failures else ";".join(failures)

    features = {"pair": pair, "bias": side, "conviction": min(1.0, speed or 0.0), "action_state": "watch" if candidate["state"] == "ENTRY" else "observe", "volume_flow": flow, "market_timing": market_timing or {}, "indicators": {"speed_score": speed, "speed_change_ratio": ratio, "hma7_confirmed": hma_confirmed}}
    try:
        adj, samples = KNNEngine("delta_tempo", Path(log_dir), min_samples=30).adjust(features)
    except Exception:
        adj, samples = 0.0, 0
    candidate["knn_samples"] = samples
    candidate["knn_adjustment"] = adj if samples >= 30 else 0.0
    candidate["knn_score"] = max(0.0, min(1.0, (speed or 0.0) + candidate["knn_adjustment"]))
    candidate["orders_enabled"] = False
    return candidate
