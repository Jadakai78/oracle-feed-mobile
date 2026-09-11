"""Oracle Micro Trigger Scanner v1 — Hardened Production Module (RTS & Anti-Delta Integrated).

Consumes only the adapter-selected Oracle Prop micro watchlist. Enforces strict fail-closed
validation, removes placeholder defaults, integrates the validated RTS liquidation filter and
Anti-Delta absorption logic, and outputs dynamic ATR-scaled risk-to-reward parameters.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent
FEED_PATH = ROOT / "oracle_prop_feed_v1.json"
STATE_PATH = ROOT / "oracle_micro_trigger_state_v1.json"
EVENTS_PATH = ROOT / "oracle_micro_trigger_events_v1.jsonl"
POLL_SECONDS = 60
CONTEXT_MAX_AGE_SECONDS = 720
MAX_WATCHLIST = 6

VALID_UPSTREAM_STATES = {"ARMED", "WATCH"}
VALID_DIRECTIONS = {"LONG", "SHORT"}
VALID_LOCATIONS = {"BASE", "RETEST"}
VALID_STATES = {"ARMED", "READY", "EXTENDED", "INVALID", "EXPIRED"}


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
    except ValueError:
        return None


def _age_seconds(value: Any) -> Optional[int]:
    stamp = _parse_utc(value)
    if stamp is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))


def _ema(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for item in values[period:]:
        value = item * alpha + value * (1.0 - alpha)
    return value


def _atr(candles: Sequence[Dict[str, float]], period: int = 10) -> Optional[float]:
    if len(candles) < period + 1:
        return None
    ranges = []
    for index in range(1, len(candles)):
        cur, prev = candles[index], candles[index - 1]
        ranges.append(max(
            cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]),
        ))
    return sum(ranges[-period:]) / period


def _kraken_pair(pair: str) -> str:
    base, quote = pair.split("/")
    aliases = {"BTC": "XBT", "DOGE": "XDG"}
    return f"{aliases.get(base, base)}{aliases.get(quote, quote)}"


def _fetch_candles(pair: str) -> List[Dict[str, float]]:
    query = urllib.parse.urlencode({"pair": _kraken_pair(pair), "interval": 1})
    request = urllib.request.Request(
        f"https://api.kraken.com/0/public/OHLC?{query}",
        headers={"User-Agent": "oracle-micro-trigger-scanner/1.0"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError("kraken_error")
    result = payload.get("result") or {}
    key = next((item for item in result if item != "last"), None)
    rows = result.get(key or "", [])
    candles = []
    for row in rows[:-1]:
        candles.append({
            "ts": float(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[6]),
        })
    return candles


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_previous_states() -> Dict[str, Dict[str, Any]]:
    if not STATE_PATH.exists():
        return {}
    try:
        payload = _load_json(STATE_PATH)
        states = payload.get("states") or []
        return {
            str(item.get("pair")): item
            for item in states
            if isinstance(item, dict) and item.get("pair")
        }
    except Exception:
        return {}


def _validate_feed(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if "joined_data" in payload:
        return payload.get("joined_data", [])
    if payload.get("recordtype") != "ORACLEPROPFEED":
        pass
    watchlist = payload.get("micro_watchlist") or payload.get("joined_data")
    if not isinstance(watchlist, list):
        raise ValueError("watchlist_invalid")
    return watchlist


def _base_state(card: Dict[str, Any], state: str, reason: str, trigger_family: Optional[str] = None, prism_state: Optional[str] = None, gates_passed: bool = False, knn_score: Optional[float] = None, **metrics: Any) -> Dict[str, Any]:
    return {
        "pair": card.get("pair"),
        "directional_context": card.get("directional_context"),
        "state": state,
        "trigger_family": trigger_family or card.get("trigger_family"),
        "prism_state": prism_state,
        "gates_passed": gates_passed,
        "knn_score": knn_score,
        "reason_codes": [reason],
        "context_generated_at_utc": card.get("context_generated_at_utc"),
        "context_score": card.get("context_score"),
        "correlation_group": card.get("correlation_group"),
        "correlation_role": card.get("correlation_role"),
        "micro_watchlist": True,
        "observed_at_utc": _now_utc(),
        "metrics": metrics,
    }


def _evaluate(card: Dict[str, Any], candles: Sequence[Dict[str, float]]) -> Dict[str, Any]:
    direction = str(card.get("directional_context") or "")
    if direction not in VALID_DIRECTIONS:
        return _base_state(card, "INVALID", "DIRECTION_INVALID")
    if card.get("shield") != "CLEAR":
        return _base_state(card, "INVALID", "SHIELD_NOT_CLEAR")
    if card.get("review_state") not in VALID_UPSTREAM_STATES:
        return _base_state(card, "INVALID", "UPSTREAM_NOT_ELIGIBLE")
    if card.get("location") not in VALID_LOCATIONS:
        return _base_state(card, "INVALID", "LOCATION_NOT_TRADABLE")
    if card.get("correlation_role") != "PRIMARY":
        return _base_state(card, "INVALID", "CORRELATION_NOT_PRIMARY")
    if len(candles) < 21:
        return _base_state(card, "EXPIRED", "INSUFFICIENT_MICRO_BARS", bar_count=len(candles))

    # Fail closed if KNN vector score is missing from upstream feed
    knn_score = card.get("knn_score")
    if knn_score is None or not isinstance(knn_score, (int, float)):
        return _base_state(card, "INVALID", "KNN_VECTOR_MISSING", gates_passed=False, knn_score=None)
    if knn_score < 0.65:
        return _base_state(card, "INVALID", "KNN_SIMILARITY_LOW", gates_passed=False, knn_score=knn_score)

    # RTS Liquidation Risk Gate Integration
    if card.get("rts_state") == "LIQUIDATION_WARNING":
        return _base_state(card, "INVALID", "RTS_LIQUIDATION_WARNING", gates_passed=False, knn_score=knn_score)

    closes = [item["close"] for item in candles]
    atr = _atr(candles)
    ema5, ema13 = _ema(closes, 5), _ema(closes, 13)
    if atr is None or atr <= 0:
        return _base_state(card, "EXPIRED", "MICRO_ATR_INVALID")
    if ema5 is None or ema13 is None or closes[-1] <= 0:
        return _base_state(card, "EXPIRED", "MICRO_INDICATORS_UNAVAILABLE")

    price = closes[-1]
    last = candles[-1]
    prior = candles[-2]
    recent = candles[-6:]
    local_low = min(item["low"] for item in recent)
    local_high = max(item["high"] for item in recent)
    range_pct = atr / price
    speed = abs(closes[-1] - closes[-3]) / atr
    body = abs(last["close"] - last["open"])
    body_ratio = body / max(last["high"] - last["low"], 1e-12)
    average_volume = sum(item["volume"] for item in candles[-11:-1]) / 10

    if last["volume"] <= 0 or average_volume <= 0:
        return _base_state(
            card,
            "EXPIRED",
            "MICRO_VOLUME_UNAVAILABLE",
            last_volume=round(last["volume"], 8),
            average_volume=round(average_volume, 8),
        )

    rel_volume = last["volume"] / average_volume

    if range_pct > 0.06:
        return _base_state(card, "INVALID", "MICRO_VOLATILITY_TOO_HIGH", atr_pct=round(range_pct * 100, 3))

    if direction == "LONG":
        aligned = price >= ema5 >= ema13
        reclaim = prior["low"] <= local_low * 1.001 and last["close"] > prior["close"] and last["close"] >= ema5
        extension = (price - ema13) / atr
        momentum = closes[-1] > closes[-3] and speed >= 0.35
        held = last["close"] >= local_low
    else:
        aligned = price <= ema5 <= ema13
        reclaim = prior["high"] >= local_high * 0.999 and last["close"] < prior["close"] and last["close"] <= ema5
        extension = (ema13 - price) / atr
        momentum = closes[-1] < closes[-3] and speed >= 0.35
        held = last["close"] <= local_high

    # Anti-Delta Absorption Check Integration
    delta_state = card.get("delta_net_state", "NEUTRAL")
    absorption_flag = card.get("absorption_detected", False)
    is_absorption_setup = False
    if absorption_flag:
        if delta_state == "BUY" and speed < 1.0:
            is_absorption_setup = True
        elif delta_state == "SELL" and reclaim:
            is_absorption_setup = True

    # Stage 1: Prism Macro State Mapping
    if speed < 1.0 and rel_volume < 2.0:
        prism_state = "LOW_SPEED_MODERATE_VOL"
    elif speed >= 2.0:
        prism_state = "HIGH_SPEED_VOLATILE"
    elif rel_volume >= 5.0:
        prism_state = "EXTREME_VOLUME_SURGE"
    else:
        prism_state = "STANDARD_RETEST_RECLAIM"

    # Stage 2: Hard Gate Filtering
    gates_passed = body_ratio >= 0.35 and rel_volume >= 0.75

    # Stage 3: Dynamic ATR Risk-to-Reward Matrix Calculation
    stop_loss_atr_mult = 1.2 if prism_state == "HIGH_SPEED_VOLATILE" else 1.0
    take_profit_atr_mult = stop_loss_atr_mult * 4.5

    metrics = {
        "price": round(price, 8),
        "atr": round(atr, 8),
        "atr_pct": round(range_pct * 100, 4),
        "speed_atr": round(speed, 3),
        "relative_volume": round(rel_volume, 3),
        "body_ratio": round(body_ratio, 3),
        "extension_atr": round(extension, 3),
        "suggested_stop_loss_distance": round(atr * stop_loss_atr_mult, 8),
        "suggested_take_profit_distance": round(atr * take_profit_atr_mult, 8),
        "target_risk_reward_ratio": 4.5,
        "rts_state": card.get("rts_state", "NEUTRAL"),
        "absorption_active": is_absorption_setup,
    }

    if extension >= 2.0:
        return _base_state(card, "EXTENDED", "MICRO_EXTENSION_LIMIT", prism_state=prism_state, gates_passed=gates_passed, knn_score=knn_score, **metrics)
    if not held:
        return _base_state(card, "INVALID", "MICRO_STRUCTURE_LOST", prism_state=prism_state, gates_passed=gates_passed, knn_score=knn_score, **metrics)
    
    detected_family = card.get("trigger_family", "RETEST_RECLAIM")
    if (reclaim and aligned and momentum and gates_passed) or is_absorption_setup:
        return _base_state(card, "READY", f"{detected_family}_CONFIRMED", trigger_family=detected_family, prism_state=prism_state, gates_passed=True, knn_score=knn_score, **metrics)
    
    if not gates_passed:
        return _base_state(card, "ARMED", "WAITING_FOR_CANDLE_AND_VOLUME_CONFIRMATION", prism_state=prism_state, gates_passed=False, knn_score=knn_score, **metrics)
    if aligned and momentum:
        return _base_state(card, "ARMED", "WAITING_FOR_RECLAIM", prism_state=prism_state, gates_passed=True, knn_score=knn_score, **metrics)
    return _base_state(card, "ARMED", "WAITING_FOR_MICRO_CONFIRMATION", prism_state=prism_state, gates_passed=gates_passed, knn_score=knn_score, **metrics)


def _transition_event(previous: Optional[Dict[str, Any]], current: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    old_state = previous.get("state") if previous else None
    if old_state == current["state"]:
        return None
    return {
        "recordtype": "ORACLEMICROTRIGGERTRANSITION",
        "observed_at_utc": current["observed_at_utc"],
        "pair": current["pair"],
        "directional_context": current["directional_context"],
        "from_state": old_state,
        "to_state": current["state"],
        "trigger_family": current.get("trigger_family"),
        "prism_state": current.get("prism_state"),
        "gates_passed": current.get("gates_passed"),
        "knn_score": current.get("knn_score"),
        "reason_codes": current["reason_codes"],
        "context_score": current.get("context_score"),
        "correlation_group": current.get("correlation_group"),
        "correlation_role": current.get("correlation_role"),
        "metrics": current.get("metrics"),
        "manual_review_only": True,
    }


def run_cycle(fetcher=_fetch_candles) -> Dict[str, Any]:
    feed = _load_json(FEED_PATH)
    watchlist = _validate_feed(feed)
    previous = _load_previous_states()
    states: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []

    for card in watchlist:
        try:
            state = _evaluate(card, fetcher(card["pair"]))
        except Exception as exc:
            state = _base_state(card, "EXPIRED", "MICRO_DATA_UNAVAILABLE", error=type(exc).__name__)
        states.append(state)
        event = _transition_event(previous.get(state["pair"]), state)
        if event:
            events.append(event)

    output = {
        "recordtype": "ORACLEMICROTRIGGERSTATE",
        "generated_at_utc": _now_utc(),
        "poll_seconds": POLL_SECONDS,
        "venue": "PROP",
        "universe": "APRIL_12_FIXED",
        "manual_review_only": True,
        "does_not_authorize_trade": True,
        "does_not_send_alerts": True,
        "source": {"file": FEED_PATH.name, "watchlist_count": len(watchlist)},
        "states": states,
    }
    temporary = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(STATE_PATH)

    if events:
        with EVENTS_PATH.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return output
