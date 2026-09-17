from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template

APP_ROOT = Path(__file__).resolve().parent
SALE_FEED_PATH = APP_ROOT / "signals.json"
SALE_FEED_RECORDS_KEY = "all_pairs"

app = Flask(__name__)


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


def safe_number(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default

    if isinstance(value, (int, float)):
        return float(value)

    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def normalize_direction(value: Any) -> str:
    direction = safe_text(value, "NEUTRAL").upper()

    if direction in {"LONG", "BUY", "UP"}:
        return "LONG"

    if direction in {"SHORT", "SELL", "DOWN"}:
        return "SHORT"

    return "NEUTRAL"


def eligibility_to_display_state(value: Any) -> str:
    eligibility = safe_text(value, "REJECTED").upper()

    if eligibility == "EXECUTION_ELIGIBLE":
        return "QUALIFIED"

    if eligibility in {"ELIGIBLE_WATCH", "BUILDING"}:
        return "WATCH"

    return "HIDDEN"


def format_price(value: Any, label: str) -> str | None:
    number = safe_number(value)

    if number is None:
        return None

    if abs(number) >= 1000:
        return f"{label} {number:,.2f}"

    if abs(number) >= 1:
        return f"{label} {number:.4f}"

    return f"{label} {number:.8f}"


def calculate_risk_reward(
    side: str,
    entry: float | None,
    stop_loss: float | None,
    take_profit: float | None,
) -> float | None:
    if (
        entry is None
        or stop_loss is None
        or take_profit is None
        or entry == stop_loss
    ):
        return None

    risk = (
        entry - stop_loss
        if side == "LONG"
        else stop_loss - entry
    )

    reward = (
        take_profit - entry
        if side == "LONG"
        else entry - take_profit
    )

    if risk <= 0 or reward <= 0:
        return None

    return reward / risk


def concise_gate_blockers(
    gates: Any,
    eligibility: str,
) -> list[str]:
    if eligibility == "EXECUTION_ELIGIBLE":
        return []

    blockers: list[str] = []

    if isinstance(gates, dict):
        for gate_name, gate_value in gates.items():
            if not isinstance(gate_value, dict):
                continue

            status = safe_text(
                gate_value.get("status"),
                "UNKNOWN",
            ).upper()

            if status not in {"PASS", "OK", "CLEAR"}:
                reason = safe_text(
                    gate_value.get("reason"),
                    status,
                )

                blockers.append(f"{gate_name}:{reason}")

    return blockers[:6]


def sale_signal_to_april_record(
    signal: dict[str, Any],
) -> dict[str, Any]:
    eligibility = safe_text(
        signal.get("eligibility"),
        "REJECTED",
    ).upper()

    display_state = eligibility_to_display_state(
        eligibility
    )

    geometry = signal.get("geometry", {})

    if not isinstance(geometry, dict):
        geometry = {}

    score = safe_number(signal.get("score"), 0.0)
    score = max(0.0, min(100.0, score or 0.0))
    weighted_score = score / 100.0

    side = normalize_direction(
        signal.get("side") or geometry.get("side")
    )

    entry = safe_number(geometry.get("entry"))
    stop_loss = safe_number(geometry.get("sl"))
    take_profit = safe_number(geometry.get("tp1"))
    take_profit_2 = safe_number(geometry.get("tp2"))

    risk_reward = calculate_risk_reward(
        side=side,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )

    blockers = concise_gate_blockers(
        gates=signal.get("gates", {}),
        eligibility=eligibility,
    )

    if display_state == "HIDDEN" and not blockers:
        blockers = [f"eligibility:{eligibility}"]

    return {
        "symbol": safe_text(
            signal.get("symbol"),
            safe_text(signal.get("pair"), "UNKNOWN"),
        ),
        "pair": safe_text(signal.get("pair"), "UNKNOWN"),
        "direction": side,
        "display_state": display_state,
        "weighted_eligibility_score": f"{score:.0f}%",
        "active_weighted_threshold": "60%",
        "weighted_core_score": weighted_score,
        "weighted_core_gate": eligibility,
        "confidence": f"{score:.0f}%",
        "speed_state": safe_text(
            signal.get("speed_state")
            or signal.get("speed_phase"),
            "UNAVAILABLE",
        ),
        "speed_policy": "SALE_FEED_SOURCE_OF_TRUTH",
        "speed_caution_reason": safe_text(
            signal.get("rejected_at"),
            "No rejection timestamp.",
        ),
        "eligibility_state": eligibility,
        "eligibility_blockers": blockers,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "take_profit_2": take_profit_2,
        "risk_reward": risk_reward,
        "entry_display": format_price(entry, "Entry"),
        "stop_loss_display": format_price(stop_loss, "Stop"),
        "take_profit_display": format_price(
            take_profit,
            "Target",
        ),
        "take_profit_2_display": format_price(
            take_profit_2,
            "Target 2",
        ),
        "risk_reward_display": (
            f"R:R {risk_reward:.2f}"
            if risk_reward is not None
            else None
        ),
        "event_timestamp_utc": (
            signal.get("ts")
            or signal.get("generated_at")
        ),
        "source": "signals.json",
        "higher_timeframe_direction": signal.get(
            "htf_direction"
        ),
        "geometry": geometry,
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
    }


def load_sale_feed() -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    str | None,
]:
    try:
        payload = json.loads(
            SALE_FEED_PATH.read_text(encoding="utf-8")
        )

        if not isinstance(payload, dict):
            raise ValueError(
                "signals.json must contain a JSON object."
            )

        raw_records = payload.get(
            SALE_FEED_RECORDS_KEY,
            [],
        )

        if not isinstance(raw_records, list):
            raise ValueError(
                f"signals.json {SALE_FEED_RECORDS_KEY} must be a list."
            )

        records = [
            sale_signal_to_april_record(item)
            for item in raw_records
            if isinstance(item, dict)
        ]

        return payload, records, None

    except Exception as exc:
        return {}, [], f"{type(exc).__name__}: {exc}"


def source_unavailable_record(error: str) -> dict[str, Any]:
    return {
        "symbol": "SALE_FEED_UNAVAILABLE",
        "pair": "SALE_FEED_UNAVAILABLE",
        "direction": "NEUTRAL",
        "display_state": "HIDDEN",
        "weighted_eligibility_score": "0%",
        "active_weighted_threshold": "60%",
        "weighted_core_score": 0.0,
        "weighted_core_gate": "UNAVAILABLE",
        "confidence": "0%",
        "speed_state": "UNAVAILABLE",
        "speed_policy": "SALE_FEED_SOURCE_OF_TRUTH",
        "speed_caution_reason": error,
        "eligibility_state": "UNAVAILABLE",
        "eligibility_blockers": [error],
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "take_profit_2": None,
        "risk_reward": None,
        "entry_display": None,
        "stop_loss_display": None,
        "take_profit_display": None,
        "take_profit_2_display": None,
        "risk_reward_display": None,
        "event_timestamp_utc": utc_now_iso(),
        "source": "signals.json",
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
    }


@app.get("/")
def dashboard():
    return render_template("index.html")


@app.get("/api/feed")
def api_feed():
    payload, records, error = load_sale_feed()

    if error is not None:
        records = [source_unavailable_record(error)]

    qualified = [
        record
        for record in records
        if record["display_state"] == "QUALIFIED"
    ]

    watch = [
        record
        for record in records
        if record["display_state"] == "WATCH"
    ]

    hidden = [
        record
        for record in records
        if record["display_state"] == "HIDDEN"
    ]

    summary = payload.get("summary", {})

    if not isinstance(summary, dict):
        summary = {}

    response = {
        "service": "oracle-feed-mobile",
        "mode": "SALE_FEED_ALL_49_PAIRS",
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
        "generated_at_utc": utc_now_iso(),
        "source": {
            "status": (
                "LIVE_SNAPSHOT"
                if error is None
                else "UNAVAILABLE"
            ),
            "file": "signals.json",
            "records_key": SALE_FEED_RECORDS_KEY,
            "file_generated_at": payload.get("generated_at"),
            "schema_version": payload.get("schema_version"),
            "error": error,
        },
        "universe": payload.get("universe", {}),
        "summary": summary,
        "tabs": {
            "qualified": qualified,
            "watch": watch,
            "hidden": hidden,
        },
        "records": records,
        "prop": qualified,
        "execute": qualified,
        "shadow": watch,
        "market_map": records,
        # Legacy API compatibility for the existing feed.js:
        "qualified": qualified,
        "watch": watch,
        "hidden": hidden,
    }

    return jsonify(response)


@app.get("/health")
def health():
    payload, records, error = load_sale_feed()

    return jsonify(
        {
            "status": "healthy" if error is None else "degraded",
            "service": "oracle-feed-mobile",
            "mode": "SALE_FEED_ALL_49_PAIRS",
            "source_file": "signals.json",
            "records_key": SALE_FEED_RECORDS_KEY,
            "file_generated_at": payload.get("generated_at"),
            "record_count": len(records),
            "universe": payload.get("universe", {}),
            "error": error,
            "checked_at_utc": utc_now_iso(),
        }
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
    )