"""
April 12 PRISM/LAR Battlefield Service

Completed-bar scanner for:
BTC, ETH, SOL, XRP, DOGE, AVAX, ADA, SUI, NEAR, LINK, LTC, BCH.

Routes:
- /                   April 12 dashboard
- /api/observations   Full scanner payload
- /api/alert-test     One-time Pushover test
- /health             Service health

The service does not submit exchange orders.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pair_universe import MarketDataSource, PROP_SYMBOLS
from prism_passive_observer_v2 import observe_completed_bar
from speed_phase import analyze_completed_candles
from delta_tempo_v1 import build_delta_tempo
from anti_delta_01_module import build_anti_delta


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

LOGGER = logging.getLogger("april_12_battlefield")

APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(
    os.environ.get(
        "PRISM_DATA_DIR",
        "/tmp/prism-observation-data",
    )
)

APRIL_49_SYMBOLS = list(PROP_SYMBOLS)
ACTIVE_SYMBOLS = APRIL_49_SYMBOLS
TIMEFRAME = os.environ.get(
    "PRISM_TIMEFRAME",
    "5m",
).strip()

MIN_CANDLES = int(
    os.environ.get(
        "PRISM_MIN_CANDLES",
        "100",
    )
)

POLL_SECONDS = max(
    30,
    int(
        os.environ.get(
            "PRISM_POLL_SECONDS",
            "60",
        )
    ),
)

STOP_DISTANCE_PCT = float(
    os.environ.get(
        "PRISM_STOP_DISTANCE_PCT",
        "0.02",
    )
)

LAR_ATR_MULTIPLIER = float(
    os.environ.get(
        "PRISM_LAR_ATR_MULTIPLIER",
        "0.15",
    )
)

PUSHOVER_USER_KEY = os.environ.get(
    "PUSHOVER_USER_KEY",
    "",
).strip()

PUSHOVER_APP_TOKEN = os.environ.get(
    "PUSHOVER_APP_TOKEN",
    "",
).strip()

ALERTABLE_STATES = {
    "LOCKED IN",
    "PRESSURE BUILDING",
    "RELOAD ZONE",
    "DATA FAULT",
}

SIZING_CONFIG = {
    "account_risk_cap_usd": 100.0,
    "max_notional_cap_usd": 5000.0,
    "max_activity_participation": 0.05,
    "minimum_activity_ratio": 0.50,
    "reduced_capacity_multiplier": 0.50,
    "noisy_regime_multiplier": 0.50,
    "high_dispersion_multiplier": 0.75,
}

OBSERVATION_LEDGER_PATH = (
    DATA_DIR /
    "prism_observations_research_v2.jsonl"
)

LAR_ANNOTATION_LEDGER_PATH = (
    DATA_DIR /
    "prism_lar_annotations_research_v1.jsonl"
)

ENGINE_STARTED_AT_UTC = (
    datetime.now(timezone.utc)
    .replace(microsecond=0)
    .isoformat()
    .replace("+00:00", "Z")
)

STATE_LOCK = threading.Lock()

SERVICE_STATE: dict[str, Any] = {
    "service": "april-12-prism-lar-battlefield",
    "mode": "SNIPER_INTEL",
    "started_at_utc": ENGINE_STARTED_AT_UTC,
    "storage_mode": (
        "PERSISTENT_DISK"
        if "PRISM_DATA_DIR" in os.environ
        else "EPHEMERAL_LOCAL_RUNTIME"
    ),
    "storage_note": f"Data directory: {DATA_DIR}",
    "poll_seconds": POLL_SECONDS,
    "symbols": ACTIVE_SYMBOLS,
    "timeframe": TIMEFRAME,
    "last_poll_started_at_utc": None,
    "last_successful_scan_at_utc": None,
    "last_error": None,
    "last_alert_error": None,
    "worker_running": False,
    "observations": [],
    "signals": [],
    "development_board": [],
    "alert_history": [],
    "alert_keys_sent": [],
    "universe_telemetry": {
        "configured_pair_count": len(ACTIVE_SYMBOLS),
        "candles_fetched_count": 0,
        "scanned_pair_count": 0,
        "signal_count": 0,
        "scan_failures": [],
    },
}


app = FastAPI(
    title="April 12 PRISM/LAR Battlefield Board",
    version="3.0.0",
)

STATIC_DIR = APP_ROOT / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def safe_text(
    value: Any,
    default: str = "Not available",
) -> str:
    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


def get_dashboard_html() -> str:
    dashboard_path = APP_ROOT / "dashboard_template.html"

    try:
        return dashboard_path.read_text(encoding="utf-8")
    except OSError as exc:
        return (
            "<html><body>"
            "<h2>Dashboard template error</h2>"
            f"<pre>{exc}</pre>"
            "</body></html>"
        )


def build_public_observation(
    result: dict[str, Any],
    phase_result: dict[str, Any],
) -> dict[str, Any]:
    evaluation = result.get("evaluation", {})
    if not isinstance(evaluation, dict):
        evaluation = {}

    decision = evaluation.get("decision", {})
    if not isinstance(decision, dict):
        decision = {}

    lar = result.get("lar", {})
    if not isinstance(lar, dict):
        lar = {}

    lar_result = lar.get("result", {})
    if not isinstance(lar_result, dict):
        lar_result = {}

    liquidity_gate = lar_result.get("liquidity_gate", {})
    if not isinstance(liquidity_gate, dict):
        liquidity_gate = {}

    source = result.get("source", {})
    if not isinstance(source, dict):
        source = {}

    observation_ledger = result.get(
        "observation_ledger",
        {},
    )
    if not isinstance(observation_ledger, dict):
        observation_ledger = {}

    annotation_ledger = lar.get(
        "annotation_ledger",
        {},
    )
    if not isinstance(annotation_ledger, dict):
        annotation_ledger = {}

    return {
        "event_type": "PRISM_LAR_OBSERVATION",
        "event_timestamp_utc": safe_text(
            source.get("completed_bar_timestamp_utc")
        ),
        "observed_at_utc": utc_now_iso(),
        "pair": safe_text(result.get("pair")),
        "timeframe": safe_text(result.get("timeframe")),
        "candle_count": source.get("candle_count"),
        "speed_phase": safe_text(
            phase_result.get("phase")
        ),
        "speed_direction": safe_text(
            phase_result.get("direction")
        ),
        "prism_status": safe_text(
            decision.get("status"),
            default="UNKNOWN",
        ),
        "prism_reason": safe_text(
            decision.get("reason"),
            default="No PRISM decision reason supplied.",
        ),
        "prism_first_block": safe_text(
            decision.get("first_block"),
            default="NONE",
        ),
        "lar_state": safe_text(
            liquidity_gate.get("state")
        ),
        "lar_pool_side": safe_text(
            liquidity_gate.get("pool_side")
        ),
        "lar_pool_type": safe_text(
            liquidity_gate.get("pool_type")
        ),
        "lar_description": safe_text(
            liquidity_gate.get("entry_permission")
        ),
        "lar_reason": safe_text(
            liquidity_gate.get("reason")
        ),
        "lar_pending_sweep_present": (
            lar.get("pending_sweep_for_next_bar") is not None
        ),
        "observation_ledger_status": safe_text(
            observation_ledger.get("status")
        ),
        "lar_annotation_ledger_status": safe_text(
            annotation_ledger.get("status")
        ),
        "observation_key": safe_text(
            observation_ledger.get("observation_key")
        ),
        "observation_id": safe_text(
            observation_ledger.get("observation_id")
        ),
        "lar_annotation_key": safe_text(
            annotation_ledger.get("annotation_key")
        ),
        "lar_annotation_id": safe_text(
            annotation_ledger.get("annotation_id")
        ),
        "source": (
            "render_completed_5m_prism_lar_april_12"
        ),
    }


def battlefield_state(
    observation: dict[str, Any],
) -> str:
    prism = safe_text(
        observation.get("prism_status"),
        "UNKNOWN",
    )

    lar = safe_text(
        observation.get("lar_state"),
        "UNKNOWN",
    )

    speed = safe_text(
        observation.get("speed_phase"),
        "UNKNOWN",
    )

    if prism == "BLOCK":
        return "NO SHOT"

    if (
        lar in {
            "BREAKOUT_ACCEPTED",
            "REJECTION_RECLAIM",
        }
        and speed == "REACCELERATION"
    ):
        return "LOCKED IN"

    if speed == "REACCELERATION":
        return "PRESSURE BUILDING"

    if speed == "CONTROLLED_PULLBACK":
        return "RELOAD ZONE"

    if speed == "DECAY":
        return "MOMENTUM FADING"

    if prism == "WATCH":
        return "TRACKING"

    return "TRACKING"


def build_development_card(
    symbol: str,
    observation: dict[str, Any] | None,
    error: str | None,
) -> dict[str, Any]:
    if error is not None:
        return {
            "pair": f"{symbol}USD",
            "symbol": symbol,
            "battle_state": "DATA FAULT",
            "scan_status": "FETCH_OR_ANALYSIS_ERROR",
            "reason": error,
            "speed_phase": "UNAVAILABLE",
            "speed_direction": "UNAVAILABLE",
            "prism_status": "UNAVAILABLE",
            "prism_first_block": "UNAVAILABLE",
            "lar_state": "UNAVAILABLE",
            "lar_pool_side": "UNAVAILABLE",
            "lar_pool_type": "UNAVAILABLE",
            "lar_description": "UNAVAILABLE",
            "event_timestamp_utc": None,
            "candle_count": 0,
            "observation_ledger_status": "UNAVAILABLE",
            "lar_annotation_ledger_status": "UNAVAILABLE",
        }

    if observation is None:
        return {
            "pair": f"{symbol}USD",
            "symbol": symbol,
            "battle_state": "SCANNING",
            "scan_status": "NO_RESULT",
            "reason": "No completed observation returned.",
            "speed_phase": "UNAVAILABLE",
            "speed_direction": "UNAVAILABLE",
            "prism_status": "UNAVAILABLE",
            "prism_first_block": "UNAVAILABLE",
            "lar_state": "UNAVAILABLE",
            "lar_pool_side": "UNAVAILABLE",
            "lar_pool_type": "UNAVAILABLE",
            "lar_description": "UNAVAILABLE",
            "event_timestamp_utc": None,
            "candle_count": 0,
            "observation_ledger_status": "UNAVAILABLE",
            "lar_annotation_ledger_status": "UNAVAILABLE",
        }

    return {
        "pair": observation.get(
            "pair",
            f"{symbol}USD",
        ),
        "symbol": symbol,
        "battle_state": battlefield_state(observation),
        "scan_status": "ONLINE",
        "reason": observation.get("prism_reason"),
        "speed_phase": observation.get("speed_phase"),
        "speed_direction": observation.get(
            "speed_direction"
        ),
        "prism_status": observation.get("prism_status"),
        "prism_first_block": observation.get(
            "prism_first_block"
        ),
        "lar_state": observation.get("lar_state"),
        "lar_pool_side": observation.get(
            "lar_pool_side"
        ),
        "lar_pool_type": observation.get(
            "lar_pool_type"
        ),
        "lar_description": observation.get(
            "lar_description"
        ),
        "event_timestamp_utc": observation.get(
            "event_timestamp_utc"
        ),
        "candle_count": observation.get("candle_count"),
        "observation_ledger_status": observation.get(
            "observation_ledger_status"
        ),
        "lar_annotation_ledger_status": observation.get(
            "lar_annotation_ledger_status"
        ),
        "delta_tempo": observation.get(
            "delta_tempo",
            {},
        ),
        "anti_delta": observation.get(
            "anti_delta",
            {},
        ),
    }


def build_signal_card(
    card: dict[str, Any],
) -> dict[str, Any] | None:
    state = safe_text(
        card.get("battle_state"),
        "TRACKING",
    )

    if state not in {
        "LOCKED IN",
        "PRESSURE BUILDING",
        "RELOAD ZONE",
    }:
        return None

    return {
        "pair": card.get("pair"),
        "battle_state": state,
        "speed_phase": card.get("speed_phase"),
        "speed_direction": card.get("speed_direction"),
        "prism_status": card.get("prism_status"),
        "prism_first_block": card.get(
            "prism_first_block"
        ),
        "lar_state": card.get("lar_state"),
        "lar_pool_side": card.get("lar_pool_side"),
        "lar_pool_type": card.get("lar_pool_type"),
        "lar_description": card.get(
            "lar_description"
        ),
        "reason": card.get("reason"),
        "event_timestamp_utc": card.get(
            "event_timestamp_utc"
        ),
    }


def alert_key_for_card(
    card: dict[str, Any],
) -> str:
    return "|".join(
        [
            safe_text(card.get("pair"), "UNKNOWN"),
            safe_text(
                card.get("event_timestamp_utc"),
                "UNKNOWN",
            ),
            safe_text(
                card.get("battle_state"),
                "UNKNOWN",
            ),
        ]
    )


def build_alert_message(
    card: dict[str, Any],
) -> tuple[str, str]:
    state = safe_text(
        card.get("battle_state"),
        "TRACKING",
    )

    pair = safe_text(card.get("pair"), "UNKNOWN")

    title = f"APRIL 12 | {state} | {pair}"

    lines = [
        (
            "Completed bar: "
            f"{safe_text(card.get('event_timestamp_utc'))}"
        ),
        (
            "Speed: "
            f"{safe_text(card.get('speed_phase'))} / "
            f"{safe_text(card.get('speed_direction'))}"
        ),
        f"PRISM: {safe_text(card.get('prism_status'))}",
        (
            "First block: "
            f"{safe_text(card.get('prism_first_block'))}"
        ),
        f"LAR: {safe_text(card.get('lar_state'))}",
        (
            "Pool: "
            f"{safe_text(card.get('lar_pool_side'))} / "
            f"{safe_text(card.get('lar_pool_type'))}"
        ),
        (
            "LAR read: "
            f"{safe_text(card.get('lar_description'))}"
        ),
        f"Reason: {safe_text(card.get('reason'))}",
    ]

    return title, "\n".join(lines)


def send_pushover_alert(
    title: str,
    message: str,
    priority: int,
) -> tuple[bool, str]:
    if not PUSHOVER_USER_KEY or not PUSHOVER_APP_TOKEN:
        return False, (
            "Pushover credentials are not configured."
        )

    encoded_data = urllib.parse.urlencode(
        {
            "token": PUSHOVER_APP_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "title": title,
            "message": message,
            "priority": str(priority),
            "sound": (
                "persistent"
                if priority >= 1
                else "pushover"
            ),
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.pushover.net/1/messages.json",
        data=encoded_data,
        method="POST",
        headers={
            "Content-Type": (
                "application/x-www-form-urlencoded"
            ),
            "User-Agent": "April12Battlefield/1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=15,
        ) as response:
            body = response.read().decode(
                "utf-8",
                errors="replace",
            )

        return True, body

    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def dispatch_alert_for_card(
    card: dict[str, Any],
    force: bool = False,
) -> dict[str, Any] | None:
    state = safe_text(
        card.get("battle_state"),
        "TRACKING",
    )

    if state not in ALERTABLE_STATES:
        return None

    alert_key = alert_key_for_card(card)

    with STATE_LOCK:
        prior_keys = set(
            SERVICE_STATE.get("alert_keys_sent", [])
        )

    if not force and alert_key in prior_keys:
        return {
            "key": alert_key,
            "pair": card.get("pair"),
            "state": state,
            "status": "DUPLICATE_SUPPRESSED",
            "sent_at_utc": utc_now_iso(),
        }

    title, message = build_alert_message(card)

    priority = (
        1
        if state in {"LOCKED IN", "DATA FAULT"}
        else 0
    )

    sent, detail = send_pushover_alert(
        title=title,
        message=message,
        priority=priority,
    )

    record = {
        "key": alert_key,
        "pair": card.get("pair"),
        "state": state,
        "completed_bar": card.get(
            "event_timestamp_utc"
        ),
        "sent_at_utc": utc_now_iso(),
        "pushover_sent": sent,
        "pushover_detail": detail,
    }

    with STATE_LOCK:
        keys = SERVICE_STATE.get(
            "alert_keys_sent",
            [],
        )

        if alert_key not in keys:
            keys.append(alert_key)

        SERVICE_STATE["alert_keys_sent"] = keys[-500:]

        history = SERVICE_STATE.get(
            "alert_history",
            [],
        )

        history.insert(0, record)

        SERVICE_STATE["alert_history"] = history[:100]

        SERVICE_STATE["last_alert_error"] = (
            None if sent else detail
        )

    return record


def build_delta_anti_readout(
    observation: dict[str, Any],
    candles: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build descriptive Delta/Tempo and Anti-Delta contexts only."""

    pair = safe_text(
        observation.get("pair"),
        default="UNKNOWN",
    )

    timeframe = safe_text(
        observation.get("timeframe"),
        default=TIMEFRAME,
    )

    speed_phase = safe_text(
        observation.get("speed_phase"),
        default="NONE",
    )

    speed_direction = safe_text(
        observation.get("speed_direction"),
        default="NEUTRAL",
    ).upper()

    trend_alignment = (
        speed_direction
        if speed_direction in {"LONG", "SHORT"}
        else "NEUTRAL"
    )

    prism_status = safe_text(
        observation.get("prism_status"),
        default="UNKNOWN",
    ).upper()

    route = "OBSERVE" if prism_status == "WATCH" else "NO_ROUTE"

    lar_state = safe_text(
        observation.get("lar_state"),
        default="UNAVAILABLE",
    ).upper()

    terrain_state = (
        "UNAVAILABLE"
        if lar_state == "UNAVAILABLE"
        else "OBSERVE"
    )

    prism_context = {
        "terrain": {
            "trend_alignment": trend_alignment,
            "route": route,
            "terrain_state": terrain_state,
        },
    }

    delta_context = build_delta_tempo(
        pair=pair,
        candles=candles,
        speed_phase=speed_phase,
        prism_context=prism_context,
        timeframe=timeframe,
    )

    anti_delta_context = build_anti_delta(
        pair=pair,
        candles=candles,
        delta_context=delta_context,
        timeframe=timeframe,
    )

    return delta_context, anti_delta_context


def run_one_symbol_observation(
    market_data_source: MarketDataSource,
    symbol: str,
) -> dict[str, Any]:
    candles = market_data_source.fetch_5m_candles(
        symbol,
        min_candles=MIN_CANDLES,
    )

    if not candles:
        raise RuntimeError(
            f"No completed {TIMEFRAME} candles "
            f"returned for {symbol}"
        )

    phase_result = analyze_completed_candles(candles)

    speed_phase = safe_text(
        phase_result.get("phase"),
        default="NONE",
    )

    result = observe_completed_bar(
        observation_ledger_path=OBSERVATION_LEDGER_PATH,
        lar_annotation_ledger_path=(
            LAR_ANNOTATION_LEDGER_PATH
        ),
        symbol=symbol,
        candles=candles,
        speed_phase=speed_phase,
        sizing_config=SIZING_CONFIG,
        stop_distance_pct=STOP_DISTANCE_PCT,
        timeframe=TIMEFRAME,
        quote="USD",
        source_label="render_prism_lar_april_12",
        lar_atr_multiplier=LAR_ATR_MULTIPLIER,
        lar_pending_sweep=None,
    )

    observation = build_public_observation(
        result=result,
        phase_result=phase_result,
    )

    try:
        delta_context, anti_delta_context = (
            build_delta_anti_readout(
                observation=observation,
                candles=candles,
            )
        )
    except Exception as exc:
        LOGGER.exception(
            "Delta/Anti-Delta readout unavailable pair=%s",
            observation.get("pair"),
        )
        delta_context = {
            "record_type": "DELTA_TEMPO",
            "data_health": {
                "state": "UNAVAILABLE",
                "reason_codes": [
                    f"DELTA_TEMPO.READOUT.ERROR:{type(exc).__name__}"
                ],
            },
            "pressure": {"state": "UNAVAILABLE"},
            "participation": {"state": "UNKNOWN"},
            "tempo": {"state": "UNKNOWN"},
            "transition": {"state": "UNAVAILABLE"},
            "prism_alignment": {"state": "UNAVAILABLE"},
            "manual_review_only": True,
            "trade_authority": False,
            "entry_authority": False,
            "does_not_send_alerts": True,
            "does_not_change_queue": True,
        }
        anti_delta_context = {
            "record_type": "ANTI_DELTA",
            "data_health": {
                "state": "UNAVAILABLE",
                "reason_codes": [
                    f"ANTI_DELTA.READOUT.ERROR:{type(exc).__name__}"
                ],
            },
            "state": "UNAVAILABLE",
            "manual_review_only": True,
            "trade_authority": False,
            "entry_authority": False,
        }

    observation["delta_tempo"] = delta_context
    observation["anti_delta"] = anti_delta_context

    LOGGER.info(
        (
            "Observation complete pair=%s bar=%s "
            "prism=%s ledger=%s lar=%s"
        ),
        observation["pair"],
        observation["event_timestamp_utc"],
        observation["prism_status"],
        observation["observation_ledger_status"],
        observation["lar_annotation_ledger_status"],
    )

    return observation


def run_battlefield_scan() -> None:
    with STATE_LOCK:
        SERVICE_STATE["last_poll_started_at_utc"] = (
            utc_now_iso()
        )
        SERVICE_STATE["last_error"] = None

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    market_data_source = MarketDataSource()
    observations: list[dict[str, Any]] = []
    development_board: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    scan_failures: list[dict[str, str]] = []
    candles_fetched_count = 0

    for symbol in ACTIVE_SYMBOLS:
        try:
            observation = run_one_symbol_observation(
                market_data_source,
                symbol,
            )

            candles_fetched_count += 1
            observations.append(observation)

            card = build_development_card(
                symbol=symbol,
                observation=observation,
                error=None,
            )

            development_board.append(card)

            signal = build_signal_card(card)

            if signal is not None:
                signals.append(signal)

            dispatch_alert_for_card(card)

        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"

            LOGGER.exception(
                "Observation failed pair=%s error=%s",
                symbol,
                error_text,
            )

            scan_failures.append(
                {
                    "symbol": symbol,
                    "reason": error_text,
                }
            )

            card = build_development_card(
                symbol=symbol,
                observation=None,
                error=error_text,
            )

            development_board.append(card)

            dispatch_alert_for_card(card)

    priority_order = {
        "LOCKED IN": 0,
        "PRESSURE BUILDING": 1,
        "RELOAD ZONE": 2,
    }

    signals.sort(
        key=lambda item: priority_order.get(
            item.get("battle_state"),
            99,
        )
    )

    with STATE_LOCK:
        SERVICE_STATE["observations"] = observations
        SERVICE_STATE["development_board"] = (
            development_board
        )
        SERVICE_STATE["signals"] = signals
        SERVICE_STATE["last_successful_scan_at_utc"] = (
            utc_now_iso()
        )
        SERVICE_STATE["last_error"] = None
        SERVICE_STATE["universe_telemetry"] = {
            "configured_pair_count": len(
                ACTIVE_SYMBOLS
            ),
            "candles_fetched_count": (
                candles_fetched_count
            ),
            "scanned_pair_count": len(observations),
            "signal_count": len(signals),
            "scan_failures": scan_failures,
        }


def battlefield_worker() -> None:
    with STATE_LOCK:
        SERVICE_STATE["worker_running"] = True

    LOGGER.info(
        (
            "April 12 worker started symbols=%s "
            "timeframe=%s poll=%ss"
        ),
        ",".join(ACTIVE_SYMBOLS),
        TIMEFRAME,
        POLL_SECONDS,
    )

    while True:
        try:
            run_battlefield_scan()

        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"

            LOGGER.exception(
                "Battlefield scan failed: %s",
                error_text,
            )

            with STATE_LOCK:
                SERVICE_STATE["last_error"] = error_text

        time.sleep(POLL_SECONDS)


@app.on_event("startup")
def start_battlefield_worker() -> None:
    thread = threading.Thread(
        target=battlefield_worker,
        name="april-12-battlefield-worker",
        daemon=True,
    )

    thread.start()


@app.get("/", response_class=HTMLResponse)
def get_dashboard() -> HTMLResponse:
    return HTMLResponse(content=get_dashboard_html())


@app.get("/api/feed", response_class=JSONResponse)
def get_feed() -> JSONResponse:
    with STATE_LOCK:
        observations = copy.deepcopy(
            SERVICE_STATE.get("observations", [])
        )
        signals = copy.deepcopy(
            SERVICE_STATE.get("signals", [])
        )
        development_board = copy.deepcopy(
            SERVICE_STATE.get("development_board", [])
        )

    def feed_card(record: dict[str, Any], display_state: str) -> dict[str, Any]:
        direction = safe_text(
            record.get("speed_direction")
            or record.get("direction"),
            default="NEUTRAL",
        ).upper()

        delta_tempo = record.get("delta_tempo") or {}
        pressure = delta_tempo.get("pressure") or {}
        participation = delta_tempo.get("participation") or {}
        tempo = delta_tempo.get("tempo") or {}

        buyer_pressure = pressure.get("buyer_pressure")
        seller_pressure = pressure.get("seller_pressure")

        pressure_imbalance_score = None
        if isinstance(buyer_pressure, (int, float)) and isinstance(
            seller_pressure,
            (int, float),
        ):
            pressure_imbalance_score = round(
                abs(buyer_pressure - seller_pressure) * 100,
                4,
            )

        threshold = 10.0

        return {
            **record,
            "display_state": display_state,
            "direction": direction,
            "data_availability": (
                "live"
                if safe_text(
                    record.get("scan_status"),
                    default="ONLINE",
                ).upper() == "ONLINE"
                else "unavailable"
            ),
            "weighted_eligibility_score": pressure_imbalance_score,
            "active_weighted_threshold": threshold,
            "pressure_strength": pressure.get("state"),
            "absolute_tempo": tempo.get("range_expansion_ratio"),
            "delta_state": pressure.get("state"),
            "score_version": (
                "DELTA_TEMPO_PRESSURE_IMBALANCE_V1"
            ),
            "diagnostics": {
                "weighted_eligibility_reason_codes": [
                    (
                        "DISPLAY_ONLY: pressure imbalance is "
                        "abs(buyer_pressure - seller_pressure) * 100; "
                        "it is not a trade-qualification score."
                    )
                ],
                "legacy_reason_codes": [
                    f"PRISM_STATUS:{safe_text(record.get('prism_status'))}",
                    f"PRISM_BLOCK:{safe_text(record.get('prism_first_block'))}",
                    f"LAR_STATE:{safe_text(record.get('lar_state'))}",
                    (
                        "PARTICIPATION:"
                        f"{safe_text(participation.get('state'))}"
                    ),
                    f"TEMPO:{safe_text(tempo.get('state'))}",
                    (
                        "TEMPO_TRANSITION:"
                        f"{safe_text(tempo.get('transition'))}"
                    ),
                ],
            },
        }

    signal_keys = {
        safe_text(
            record.get("observation_key")
            or record.get("pair")
        )
        for record in signals
    }

    execute = [
        feed_card(record, "QUALIFIED")
        for record in signals
    ]

    shadow = [
        feed_card(record, "WATCH")
        for record in development_board
        if safe_text(
            record.get("observation_key")
            or record.get("pair")
        ) not in signal_keys
    ]

    prop = list(execute)

    market_map = [
        feed_card(
            record,
            (
                "QUALIFIED"
                if safe_text(
                    record.get("observation_key")
                    or record.get("pair")
                ) in signal_keys
                else "WATCH"
                if safe_text(
                    record.get("prism_status"),
                    default="",
                ).upper() == "WATCH"
                else "HIDDEN"
            ),
        )
        for record in observations
    ]

    return JSONResponse(
        content={
            "prop": prop,
            "execute": execute,
            "shadow": shadow,
            "market_map": market_map,
        }
    )

@app.get(
    "/api/observations",
    response_class=JSONResponse,
)
def get_observations() -> JSONResponse:
    with STATE_LOCK:
        payload = copy.deepcopy(SERVICE_STATE)

    payload["active_signals_count"] = len(
        payload.get("signals", [])
    )

    payload["timestamp"] = payload.get(
        "last_successful_scan_at_utc"
    )

    return JSONResponse(content=payload)


@app.get(
    "/api/alert-test",
    response_class=JSONResponse,
)
def alert_test() -> JSONResponse:
    test_card = {
        "pair": "APRIL12_TEST",
        "battle_state": "LOCKED IN",
        "event_timestamp_utc": utc_now_iso(),
        "speed_phase": "TEST",
        "speed_direction": "TEST",
        "prism_status": "TEST",
        "prism_first_block": "NONE",
        "lar_state": "TEST",
        "lar_pool_side": "TEST",
        "lar_pool_type": "TEST",
        "lar_description": "TEST_ALERT",
        "reason": "Manual Pushover alert test.",
    }

    result = dispatch_alert_for_card(
        test_card,
        force=True,
    )

    return JSONResponse(
        content={
            "status": "TEST_DISPATCHED",
            "result": result,
        }
    )


@app.get("/health", response_class=JSONResponse)
def get_health() -> JSONResponse:
    with STATE_LOCK:
        has_scan = (
            SERVICE_STATE["last_successful_scan_at_utc"]
            is not None
        )

        error = SERVICE_STATE["last_error"]

        status = (
            "degraded"
            if error
            else "healthy"
            if has_scan
            else "starting"
        )

        return JSONResponse(
            content={
                "status": status,
                "service": SERVICE_STATE["service"],
                "mode": SERVICE_STATE["mode"],
                "symbols": ACTIVE_SYMBOLS,
                "storage_mode": SERVICE_STATE[
                    "storage_mode"
                ],
                "last_successful_scan_at_utc": (
                    SERVICE_STATE[
                        "last_successful_scan_at_utc"
                    ]
                ),
                "last_error": error,
                "last_alert_error": SERVICE_STATE[
                    "last_alert_error"
                ],
            }
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
    )