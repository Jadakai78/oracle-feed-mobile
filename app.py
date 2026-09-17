import os
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template

app = Flask(__name__)


def get_owner_feed_records():
    """
    Deployment adapter boundary.

    Replace this controlled record with the call that collects raw candidates
    and routes each candidate through delta_tempo_prop_router.evaluate(...).

    Never expose broker keys, provider tokens, or raw private diagnostics here.
    """
    return [
        {
            "pair": "DEPLOYMENT_SMOKE_TEST",
            "direction": "LONG",
            "weighted_core_score": 1.00,
            "weighted_core_gate": "QUALIFIED",
            "speed_state": "CAUTION",
            "speed_policy": "CAUTION_NOT_BLOCK",
            "speed_caution_reason": "Render smoke-test record",
            "eligibility_state": "ELIGIBLE_WATCH",
            "eligibility_blockers": [
                "speed_caution:Render smoke-test record"
            ],
            "entry": 100.00,
            "stop_loss": 99.00,
            "take_profit": 102.00,
            "risk_reward": 2.00,
        }
    ]


def format_price(value, label):
    """Return a display-safe price line for the April compatibility UI."""
    if isinstance(value, (int, float)):
        return f"{label} {value:.2f}"
    return None


def april_display_state(eligibility_state):
    """Map the router state to the existing April tab/card state."""
    if eligibility_state == "ELIGIBLE":
        return "QUALIFIED"
    if eligibility_state == "ELIGIBLE_WATCH":
        return "WATCH"
    return "HIDDEN"


def to_april_record(record):
    """
    Translate a clean owner/router record into April's legacy UI contract.

    This function is display-only. It does not change router scores, policy,
    qualification, eligibility, geometry, or any trade decision.
    """
    state = record.get("eligibility_state", "")
    weighted_score = record.get("weighted_core_score", 0.0)
    blockers = record.get("eligibility_blockers", [])

    if not isinstance(blockers, list):
        blockers = [str(blockers)]

    return {
        "symbol": record.get("pair", "UNKNOWN"),
        "pair": record.get("pair", "UNKNOWN"),
        "direction": record.get("direction", "NEUTRAL"),
        "display_state": april_display_state(state),

        # April legacy scoring fields
        "weighted_eligibility_score": f"{weighted_score:.0%}",
        "active_weighted_threshold": "60%",
        "weighted_core_score": weighted_score,
        "weighted_core_gate": record.get("weighted_core_gate", ""),
        "confidence": f"{weighted_score:.0%}",

        # April legacy trade-plan fields
        "entry_framework": format_price(record.get("entry"), "Entry"),
        "exit_trigger": format_price(
            record.get("take_profit"),
            "Target",
        ),
        "invalidation": format_price(
            record.get("stop_loss"),
            "Stop",
        ),

        # Keep raw geometry available too
        "entry": record.get("entry"),
        "stop_loss": record.get("stop_loss"),
        "take_profit": record.get("take_profit"),
        "risk_reward": record.get("risk_reward"),

        # Router states and caution display
        "eligibility_state": state,
        "speed_state": record.get("speed_state", "UNKNOWN"),
        "speed_policy": record.get("speed_policy", ""),
        "speed_caution_reason": record.get(
            "speed_caution_reason",
            "",
        ),
        "shield": "; ".join(blockers),
        "notes": record.get("speed_caution_reason", ""),

        # April diagnostics drawer fields
        "score_version": "weighted-core-45-35-25-v1",
        "weighted_eligibility_reason_codes": blockers,
        "diagnostics": {
            "weighted_eligibility_reason_codes": blockers,
            "weighted_core_score": weighted_score,
            "weighted_core_gate": record.get(
                "weighted_core_gate",
                "",
            ),
            "eligibility_state": state,
            "speed_state": record.get("speed_state", "UNKNOWN"),
            "speed_policy": record.get("speed_policy", ""),
            "speed_caution_reason": record.get(
                "speed_caution_reason",
                "",
            ),
            "entry": record.get("entry"),
            "stop_loss": record.get("stop_loss"),
            "take_profit": record.get("take_profit"),
            "risk_reward": record.get("risk_reward"),
        },
    }


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "delta-tempo-owner-feed",
            "release": os.getenv("RELEASE_TAG", "local"),
        }
    )


@app.get("/api/owner-feed")
def owner_feed():
    """
    Clean API contract for the router, future Sales Center UI,
    and other consumers.
    """
    return jsonify(
        {
            "status": "ok",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "records": get_owner_feed_records(),
        }
    )


@app.get("/api/feed")
def april_feed():
    """
    Compatibility endpoint for the existing April HTML/feed.js shell.

    The front end expects:
    prop, execute, shadow, market_map.
    """
    records = get_owner_feed_records()

    prop = []
    execute = []
    shadow = []
    market_map = []

    for record in records:
        april_record = to_april_record(record)
        display_state = april_record["display_state"]

        if display_state == "QUALIFIED":
            prop.append(april_record)
            execute.append(april_record)
        elif display_state == "WATCH":
            # A watch/caution candidate retains its valid trade geometry.
            shadow.append(april_record)
            execute.append(april_record)

        market_map.append(
            {
                "symbol": record.get("pair", "UNKNOWN"),
                "pair": record.get("pair", "UNKNOWN"),
                "direction": record.get("direction", "NEUTRAL"),
                "display_state": display_state,
                "state": display_state,
                "weighted_eligibility_score": (
                    april_record["weighted_eligibility_score"]
                ),
                "active_weighted_threshold": "60%",
                "weighted_core_score": record.get(
                    "weighted_core_score",
                    0.0,
                ),
                "speed_state": record.get("speed_state", "UNKNOWN"),
                "speed_policy": record.get("speed_policy", ""),
                "eligibility_state": record.get(
                    "eligibility_state",
                    "",
                ),
                "shield": april_record["shield"],
            }
        )

    return jsonify(
        {
            "prop": prop,
            "execute": execute,
            "shadow": shadow,
            "market_map": market_map,
        }
    )


@app.get("/")
def dashboard():
    return render_template("index.html")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)