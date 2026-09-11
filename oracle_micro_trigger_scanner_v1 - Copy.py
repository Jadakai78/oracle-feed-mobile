"""Oracle Micro Trigger Scanner v1 ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â read-only 60-second timing layer.

Consumes only the adapter-selected Oracle Prop micro watchlist. It does not
create a market thesis, route orders, publish GitHub, send alerts, or modify a
queue. It emits timing states for manual review: ARMED, READY, EXTENDED,
INVALID, and EXPIRED.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent
FEED_PATH = ROOT / "oracle_prop_feed_v1.json"
STATE_PATH = ROOT / "oracle_micro_trigger_state_v1.json"
EVENTS_PATH = ROOT / "oracle_micro_trigger_events_v1.jsonl"
POLL_SECONDS = 60
ALERT_CANDIDATES_PATH = ROOT / "oracle_micro_alert_candidates_v1.jsonl"
DRY_RUN_ALERTS_ONLY = True
ALERT_COOLDOWN_SECONDS = 1800
ALERT_REL_VOLUME_MIN = 0.75
ALERT_REL_VOLUME_MAX = 8.0
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
        ranges.append(max(cur["high"] - cur["low"], abs(cur["high"] - prev["close"]), abs(cur["low"] - prev["close"])))
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
    for row in rows[:-1]:  # completed one-minute bars only
        candles.append({
            "ts": float(row[0]), "open": float(row[1]), "high": float(row[2]),
            "low": float(row[3]), "close": float(row[4]), "volume": float(row[6]),
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
        return {str(item.get("pair")): item for item in states if isinstance(item, dict) and item.get("pair")}
    except Exception:
        return {}


def _validate_feed(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if payload.get("recordtype") != "ORACLEPROPFEED":
        raise ValueError("feed_recordtype_invalid")
    if payload.get("venue") != "PROP" or payload.get("universe") != "APRIL_12_FIXED":
        raise ValueError("feed_scope_invalid")
    if payload.get("manual_review_only") is not True:
        raise ValueError("feed_not_manual_review_only")
    age = _age_seconds(payload.get("context_generated_at_utc"))
    if age is None or age > CONTEXT_MAX_AGE_SECONDS:
        raise ValueError("feed_context_stale")
    watchlist = payload.get("micro_watchlist")
    if not isinstance(watchlist, list) or len(watchlist) > MAX_WATCHLIST:
        raise ValueError("watchlist_invalid")
    return watchlist


def _base_state(card: Dict[str, Any], state: str, reason: str, **metrics: Any) -> Dict[str, Any]:
    return {
        "pair": card.get("pair"),
        "directional_context": card.get("directional_context"),
        "state": state,
        "trigger_family": None,
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

    closes = [item["close"] for item in candles]
    atr = _atr(candles)
    ema5, ema13 = _ema(closes, 5), _ema(closes, 13)
    if not atr or not ema5 or not ema13 or closes[-1] <= 0:
        return _base_state(card, "EXPIRED", "MICRO_INDICATORS_UNAVAILABLE")

    price = closes[-1]
    last = candles[-1]
    prior = candles[-2]
    recent = candles[-6:]
    local_low = min(item["low"] for item in recent)
    local_high = max(item["high"] for item in recent)
    range_pct = atr / price
    speed = abs(closes[-1] - closes[-3]) / atr if atr > 0 else 0.0
    body = abs(last["close"] - last["open"])
    body_ratio = body / max(last["high"] - last["low"], 1e-12)
    average_volume = sum(item["volume"] for item in candles[-11:-1]) / 10

    # Never permit a micro trigger from unusable ATR or volume data.
    if atr is None or atr <= 0:
        return _base_state(card, "EXPIRED", "MICRO_ATR_INVALID")

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

    metrics = {
        "price": round(price, 8), "atr": round(atr, 8), "atr_pct": round(range_pct * 100, 4),
        "speed_atr": round(speed, 3), "relative_volume": round(rel_volume, 3),
        "body_ratio": round(body_ratio, 3), "extension_atr": round(extension, 3),
    }

    if extension >= 2.0:
        return _base_state(card, "EXTENDED", "MICRO_EXTENSION_LIMIT", **metrics)
    if not held:
        return _base_state(card, "INVALID", "MICRO_STRUCTURE_LOST", **metrics)
    if reclaim and aligned and momentum and body_ratio >= 0.35 and rel_volume >= 0.75:
        return _base_state(card, "READY", "RETEST_RECLAIM_CONFIRMED", trigger_family="RETEST_RECLAIM", **metrics)
    if body_ratio < 0.35 or rel_volume < 0.75:
        return _base_state(
            card,
            "ARMED",
            "WAITING_FOR_CANDLE_AND_VOLUME_CONFIRMATION",
            **metrics,
        )
    if aligned and momentum:
        return _base_state(card, "ARMED", "WAITING_FOR_RECLAIM", **metrics)
    return _base_state(card, "ARMED", "WAITING_FOR_MICRO_CONFIRMATION", **metrics)


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

def _dry_run_alert_records(events: List[Dict[str, Any]], watchlist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    eligible = {
        (card.get("pair"), card.get("directional_context")): card
        for card in watchlist
        if card.get("shield") == "CLEAR"
        and card.get("correlation_role") == "PRIMARY"
        and card.get("manual_review_only", True) is not False
    }
    prior_alert_at: Dict[Tuple[str, str], datetime] = {}
    if ALERT_CANDIDATES_PATH.exists():
        for raw in ALERT_CANDIDATES_PATH.read_text(encoding="utf-8").splitlines():
            try:
                prior = json.loads(raw)
                if prior.get("decision") != "WOULD_ALERT":
                    continue
                at = _parse_utc(prior.get("observed_at_utc"))
                if at:
                    prior_alert_at[(prior.get("pair"), prior.get("directional_context"))] = at
            except Exception:
                continue

    records: List[Dict[str, Any]] = []
    for event in events:
        reasons: List[str] = []
        metrics = event.get("metrics") or {}
        rel_volume = metrics.get("relative_volume")
        key = (event.get("pair"), event.get("directional_context"))
        observed_at = _parse_utc(event.get("observed_at_utc"))

        if event.get("from_state") != "ARMED" or event.get("to_state") != "READY":
            reasons.append("NOT_ARMED_TO_READY")
        if key not in eligible:
            reasons.append("NOT_CURRENT_CLEAR_PRIMARY_MICRO_WATCHLIST")
        if not isinstance(rel_volume, (int, float)) or not ALERT_REL_VOLUME_MIN <= rel_volume <= ALERT_REL_VOLUME_MAX:
            reasons.append("RELATIVE_VOLUME_OUTSIDE_ALERT_RANGE")
        prior_at = prior_alert_at.get(key)
        if observed_at and prior_at and (observed_at - prior_at).total_seconds() < ALERT_COOLDOWN_SECONDS:
            reasons.append("COOLDOWN_ACTIVE")

        records.append({
            "recordtype": "ORACLEMICROALERTCANDIDATE",
            "observed_at_utc": event.get("observed_at_utc"),
            "pair": event.get("pair"),
            "directional_context": event.get("directional_context"),
            "from_state": event.get("from_state"),
            "to_state": event.get("to_state"),
            "trigger_family": event.get("trigger_family"),
            "decision": "WOULD_ALERT" if not reasons else "SKIPPED",
            "reason_codes": reasons or ["DRY_RUN_ELIGIBLE"],
            "metrics": metrics,
            "manual_review_only": True,
            "dry_run_only": DRY_RUN_ALERTS_ONLY,
        })
    return records

    alert_candidates = _dry_run_alert_records(events, watchlist)
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
    if alert_candidates:
        with ALERT_CANDIDATES_PATH.open("a", encoding="utf-8") as handle:
            for candidate in alert_candidates:
                handle.write(json.dumps(candidate, ensure_ascii=False) + "\n")
    return output


def main() -> None:
    print("Oracle Micro Trigger Scanner ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â 60-second, PROP, manual-review-only")
    while True:
        try:
            result = run_cycle()
            summary = ", ".join(f"{item['pair']}={item['state']}" for item in result["states"])
            print(f"{result['generated_at_utc']} {summary or 'no micro watchlist'}")
        except Exception as exc:
            print(f"{_now_utc()} micro cycle blocked: {type(exc).__name__}: {exc}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()


