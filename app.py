from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests
from flask import Flask, jsonify, render_template

app = Flask(__name__)

MAIN_FEED_URL = os.environ.get("MAIN_FEED_URL", "").strip().rstrip("/")
MAIN_FEED_TIMEOUT_SECONDS = max(
    3,
    int(os.environ.get("MAIN_FEED_TIMEOUT_SECONDS", "15")),
)


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def safe_text(value: Any, default: str = "Not available") -> str:
    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


def normalize_direction(value: Any) -> str:
    direction = safe_text(value, "NEUTRAL").upper()

    if direction in {"LONG", "BUY", "UP"}:
        return "LONG"

    if direction in {"SHORT", "SELL", "DOWN"}:
        return "SHORT"

    return "NEUTRAL"


def battle_state_to_eligibility(battle_state: Any) -> str:
    state = safe_text(battle_state, "TRACKING").upper()

    if state == "LOCKED IN":
        return "ELIGIBLE"

    if state in {"PRESSURE BUILDING", "RELOAD ZONE"}:
        return "ELIGIBLE_WATCH"

    return "HIDDEN"


def battle_state_to_weighted_score(battle_state: Any) -> float:
    state = safe_text(battle_state, "TRACKING").upper()

    if state == "LOCKED IN":
        return 1.00

    if state == "PRESSURE BUILDING":
        return 0.75

    if state == "RELOAD ZONE":
        return 0.60

    return 0.00


def main_signal_to_owner_record(signal: dict[str, Any]) -> dict[str, Any]:
    battle_state = safe_text(signal.get("battle_state"), "TRACKING")
    reason = safe_text(signal.get("reason"), "No source reason supplied.")
    speed_phase = safe_text(signal.get("speed_phase"), "UNAVAILABLE")
    direction = normalize_direction(signal.get("speed_direction"))

    eligibility_state = battle_state_to_eligibility(battle_state)
    score = battle_state_to_weighted_score(battle_state)

    blockers: list[str] = []

    if eligibility_state == "ELIGIBLE_WATCH":
        blockers.append(f"watch_state:{battle_state}")

    if eligibility_state == "HIDDEN":
        blockers.append(f"not_publishable:{battle_state}")

    return {
        "pair": safe_text(signal.get("pair"), "UNKNOWN"),
        "direction": direction,
        "weighted_core_score": score,
        "weighted_core_gate": battle_state,
        "speed_state": speed_phase,
        "speed_policy": "MAIN_FEED_READ_ONLY",
        "speed_caution_reason": reason,
        "eligibility_state": eligibility_state,
        "eligibility_blockers": blockers,
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "risk_reward": None,
        "event_timestamp_utc": signal.get("event_timestamp_utc"),
        "source": "april-12-prism-lar-battlefield",
        "prism_status": signal.get("prism_status"),
        "prism_first_block": signal.get("prism_first_block"),
        "lar_state": signal.get("lar_state"),
        "lar_pool_side": signal.get("lar_pool_side"),
        "lar_pool_type": signal.get("lar_pool_type"),
        "lar_description": signal.get("lar_description"),
        "battle_state": battle_state,
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
    }


def source_unavailable_record(reason: str) -> dict[str, Any]:
    return {
        "pair": "MAIN_FEED_UNAVAILABLE",
        "direction": "NEUTRAL",
        "weighted_core_score": 0.00,
        "weighted_core_gate": "UNAVAILABLE",
        "speed_state": "UNAVAILABLE",
        "speed_policy": "MAIN_FEED_READ_ONLY",
        "speed_caution_reason": reason,
        "eligibility_state": "HIDDEN",
        "eligibility_blockers": [reason],
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "risk_reward": None,
        "event_timestamp_utc": utc_now_iso(),
        "source": "april-mobile-feed",
        "battle_state": "UNAVAILABLE",
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
    }


def fetch_main_feed_payload() -> dict[str, Any]:
    if not MAIN_FEED_URL:
        raise RuntimeError(
            "MAIN_FEED_URL is not configured. "
            "Set it in Render to the public base URL of the April 12 "
            "PRISM/LAR Battlefield service."
        )

    response = requests.get(
        f"{MAIN_FEED_URL}/api/observations",
        timeout=MAIN_FEED_TIMEOUT_SECONDS,
        headers={"Accept": "application/json"},
    )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise RuntimeError(
            "Main feed returned an invalid payload: expected a JSON object."
        )

    return payload


def get_owner_feed_records() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        payload = fetch_main_feed_payload()

        raw_signals = payload.get("signals", [])

        if not isinstance(raw_signals, list):
            raise RuntimeError(
                "Main feed returned an invalid signals field: expected a list."
            )

        records = [
            main_signal_to_owner_record(signal)
            for signal in raw_signals
            if isinstance(signal, dict)
        ]

        meta = {
            "source_status": "LIVE",
            "source_url": MAIN_FEED_URL,
            "source_timestamp": payload.get("timestamp")
            or payload.get("last_successful_scan_at_utc"),
            "active_signals_count": payload.get("active_signals_count", len(records)),
            "upstream_health": payload.get("last_error"),
            "upstream_mode": payload.get("mode"),
            "retrieved_at_utc": utc_now_iso(),
        }

        return records, meta

    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"

        return (
            [source_unavailable_record(reason)],
            {
                "source_status": "UNAVAILABLE",
                "source_url": MAIN_FEED_URL or None,
                "source_timestamp": None,
                "active_signals_count": 0,
                "upstream_health": reason,
                "upstream_mode": None,
                "retrieved_at_utc": utc_now_iso(),
            },
        )


def format_price(value: Any, label: str) -> str | None:
    if isinstance(value, (int, float)):
        return f"{label} {value:.2f}"

    return None


def april_display_state(eligibility_state: Any) -> str:
    state = safe_text(eligibility_state, "HIDDEN").upper()

    if state == "ELIGIBLE":
        return "QUALIFIED"

    if state == "ELIGIBLE_WATCH":
        return "WATCH"

    return "HIDDEN"


def to_april_record(record: dict[str, Any]) -> dict[str, Any]:
    state = safe_text(record.get("eligibility_state"), "HIDDEN")
    weighted_score = record.get("weighted_core_score", 0.0)
    blockers = record.get("eligibility_blockers", [])

    if not isinstance(weighted_score, (int, float)):
        weighted_score = 0.0

    if not isinstance(blockers, list):
        blockers = [str(blockers)]

    entry = record.get("entry")
    stop_loss = record.get("stop_loss")
    take_profit = record.get("take_profit")
    risk_reward = record.get("risk_reward")

    return {
        "symbol": safe_text(record.get("pair"), "UNKNOWN"),
        "pair": safe_text(record.get("pair"), "UNKNOWN"),
        "direction": normalize_direction(record.get("direction")),
        "display_state": april_display_state(state),
        "weighted_eligibility_score": f"{weighted_score:.0%}",
        "active_weighted_threshold": "60%",
        "weighted_core_score": weighted_score,
        "weighted_core_gate": safe_text(record.get("weighted_core_gate")),
        "confidence": f"{weighted_score:.0%}",
        "speed_state": safe_text(record.get("speed_state")),
        "speed_policy": safe_text(record.get("speed_policy")),
        "speed_caution_reason": safe_text(
            record.get("speed_caution_reason")
        ),
        "eligibility_state": state,
        "eligibility_blockers": blockers,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": risk_reward,
        "entry_display": format_price(entry, "Entry"),
        "stop_loss_display": format_price(stop_loss, "Stop"),
        "take_profit_display": format_price(take_profit, "Target"),
        "risk_reward_display": (
            f"R:R {risk_reward:.2f}"
            if isinstance(risk_reward, (int, float))
            else None
        ),
        "event_timestamp_utc": record.get("event_timestamp_utc"),
        "source": safe_text(record.get("source")),
        "battle_state": safe_text(record.get("battle_state")),
        "prism_status": safe_text(record.get("prism_status")),
        "prism_first_block": safe_text(record.get("prism_first_block")),
        "lar_state": safe_text(record.get("lar_state")),
        "lar_pool_side": safe_text(record.get("lar_pool_side")),
        "lar_pool_type": safe_text(record.get("lar_pool_type")),
        "lar_description": safe_text(record.get("lar_description")),
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
    }


@app.get("/")
def dashboard():
    return render_template("index.html")


@app.get("/api/feed")
def api_feed():
    owner_records, source_meta = get_owner_feed_records()

    april_records = [
        to_april_record(record)
        for record in owner_records
    ]

    qualified = [
        record
        for record in april_records
        if record["display_state"] == "QUALIFIED"
    ]

    watch = [
        record
        for record in april_records
        if record["display_state"] == "WATCH"
    ]

    hidden = [
        record
        for record in april_records
        if record["display_state"] == "HIDDEN"
    ]

    return jsonify(
        {
            "service": "oracle-feed-mobile",
            "mode": "MAIN_FEED_READ_ONLY",
            "manual_review_only": True,
            "trade_authority": False,
            "entry_authority": False,
            "generated_at_utc": utc_now_iso(),
            "source": source_meta,
            "tabs": {
                "qualified": qualified,
                "watch": watch,
                "hidden": hidden,
            },
            "records": april_records,
        }
    )


@app.get("/health")
def health():
    _, source_meta = get_owner_feed_records()

    return jsonify(
        {
            "status": (
                "healthy"
                if source_meta["source_status"] == "LIVE"
                else "degraded"
            ),
            "service": "oracle-feed-mobile",
            "mode": "MAIN_FEED_READ_ONLY",
            "source": source_meta,
            "checked_at_utc": utc_now_iso(),
        }
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
    )