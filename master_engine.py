"""
April 12 PRISM/LAR Battlefield Service

Completed-bar scanner for:
BTC, ETH, SOL, XRP, DOGE, AVAX, ADA, SUI, NEAR, LINK, LTC, BCH.

Routes:
- /                 Dashboard
- /api/observations Full 12-pair board
- /health           Service health

No exchange orders are sent by this service.
"""

from __future__ import annotations

import copy
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from pair_universe import MarketDataSource
from prism_passive_observer_v2 import observe_completed_bar
from speed_phase import analyze_completed_candles


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

LOGGER = logging.getLogger("april_12_battlefield")
APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("PRISM_DATA_DIR", "/tmp/prism-observation-data"))

APRIL_12_SYMBOLS = [
    "BTC",
    "ETH",
    "SOL",
    "XRP",
    "DOGE",
    "AVAX",
    "ADA",
    "SUI",
    "NEAR",
    "LINK",
    "LTC",
    "BCH",
]

TIMEFRAME = os.environ.get("PRISM_TIMEFRAME", "5m").strip()
MIN_CANDLES = int(os.environ.get("PRISM_MIN_CANDLES", "100"))
POLL_SECONDS = max(30, int(os.environ.get("PRISM_POLL_SECONDS", "60")))

STOP_DISTANCE_PCT = float(
    os.environ.get("PRISM_STOP_DISTANCE_PCT", "0.02")
)

LAR_ATR_MULTIPLIER = float(
    os.environ.get("PRISM_LAR_ATR_MULTIPLIER", "0.15")
)

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
    DATA_DIR / "prism_observations_research_v2.jsonl"
)

LAR_ANNOTATION_LEDGER_PATH = (
    DATA_DIR / "prism_lar_annotations_research_v1.jsonl"
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
    "storage_note": (
        f"Data directory: {DATA_DIR}"
    ),
    "poll_seconds": POLL_SECONDS,
    "symbols": APRIL_12_SYMBOLS,
    "timeframe": TIMEFRAME,
    "last_poll_started_at_utc": None,
    "last_successful_scan_at_utc": None,
    "last_error": None,
    "worker_running": False,
    "observations": [],
    "signals": [],
    "development_board": [],
    "universe_telemetry": {
        "configured_pair_count": len(APRIL_12_SYMBOLS),
        "candles_fetched_count": 0,
        "scanned_pair_count": 0,
        "signal_count": 0,
        "scan_failures": [],
    },
}


app = FastAPI(
    title="April 12 PRISM/LAR Battlefield Board",
    version="2.0.0",
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


def get_dashboard_html() -> str:
    dashboard_path = APP_ROOT / "dashboard_template.html"

    try:
        return dashboard_path.read_text(encoding="utf-8")
    except OSError as exc:
        return (
            "<html><body><h2>Dashboard template error</h2>"
            f"<pre>{exc}</pre></body></html>"
        )


def build_public_observation(
    result: dict[str, Any],
    phase_result: dict[str, Any],
) -> dict[str, Any]:
    evaluation = result.get("evaluation", {})
    evaluation = evaluation if isinstance(evaluation, dict) else {}

    decision = evaluation.get("decision", {})
    decision = decision if isinstance(decision, dict) else {}

    lar = result.get("lar", {})
    lar = lar if isinstance(lar, dict) else {}

    lar_result = lar.get("result", {})
    lar_result = lar_result if isinstance(lar_result, dict) else {}

    liquidity_gate = lar_result.get("liquidity_gate", {})
    liquidity_gate = (
        liquidity_gate
        if isinstance(liquidity_gate, dict)
        else {}
    )

    source = result.get("source", {})
    source = source if isinstance(source, dict) else {}

    observation_ledger = result.get("observation_ledger", {})
    observation_ledger = (
        observation_ledger
        if isinstance(observation_ledger, dict)
        else {}
    )

    annotation_ledger = lar.get("annotation_ledger", {})
    annotation_ledger = (
        annotation_ledger
        if isinstance(annotation_ledger, dict)
        else {}
    )

    return {
        "event_type": "PRISM_LAR_OBSERVATION",
        "event_timestamp_utc": safe_text(
            source.get("completed_bar_timestamp_utc")
        ),
        "observed_at_utc": utc_now_iso(),
        "pair": safe_text(result.get("pair")),
        "timeframe": safe_text(result.get("timeframe")),
        "candle_count": source.get("candle_count"),
        "speed_phase": safe_text(phase_result.get("phase")),
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
        "source": "render_completed_5m_prism_lar_april_12",
    }


def battlefield_state(observation: dict[str, Any]) -> str:
    prism = observation.get("prism_status", "UNKNOWN")
    lar = observation.get("lar_state", "UNKNOWN")
    speed = observation.get("speed_phase", "UNKNOWN")

    if prism == "BLOCK":
        return "NO SHOT"

    if (
        lar in {"BREAKOUT_ACCEPTED", "REJECTION_RECLAIM"}
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
    if error:
        return {
            "pair": f"{symbol}USD",
            "symbol": symbol,
            "battle_state": "DATA FAULT",
            "scan_status": "FETCH_OR_ANALYSIS_ERROR",
            "reason": error,
            "price": None,
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
        }

    if observation is None:
        return {
            "pair": f"{symbol}USD",
            "symbol": symbol,
            "battle_state": "SCANNING",
            "scan_status": "NO_RESULT",
            "reason": "No completed observation returned.",
            "price": None,
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
        }

    return {
        "pair": observation.get("pair", f"{symbol}USD"),
        "symbol": symbol,
        "battle_state": battlefield_state(observation),
        "scan_status": "ONLINE",
        "reason": observation.get("prism_reason"),
        "price": None,
        "speed_phase": observation.get("speed_phase"),
        "speed_direction": observation.get("speed_direction"),
        "prism_status": observation.get("prism_status"),
        "prism_first_block": observation.get("prism_first_block"),
        "lar_state": observation.get("lar_state"),
        "lar_pool_side": observation.get("lar_pool_side"),
        "lar_pool_type": observation.get("lar_pool_type"),
        "lar_description": observation.get("lar_description"),
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
    }


def build_signal_card(
    observation: dict[str, Any],
) -> dict[str, Any] | None:
    state = battlefield_state(observation)

    if state not in {
        "LOCKED IN",
        "PRESSURE BUILDING",
        "RELOAD ZONE",
    }:
        return None

    return {
        "pair": observation.get("pair"),
        "battle_state": state,
        "speed_phase": observation.get("speed_phase"),
        "speed_direction": observation.get("speed_direction"),
        "prism_status": observation.get("prism_status"),
        "prism_first_block": observation.get("prism_first_block"),
        "lar_state": observation.get("lar_state"),
        "lar_pool_side": observation.get("lar_pool_side"),
        "lar_pool_type": observation.get("lar_pool_type"),
        "lar_description": observation.get("lar_description"),
        "reason": observation.get("prism_reason"),
        "event_timestamp_utc": observation.get(
            "event_timestamp_utc"
        ),
    }


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
            f"No completed {TIMEFRAME} candles returned for {symbol}"
        )

    phase_result = analyze_completed_candles(candles)
    speed_phase = safe_text(
        phase_result.get("phase"),
        default="NONE",
    )

    result = observe_completed_bar(
        observation_ledger_path=OBSERVATION_LEDGER_PATH,
        lar_annotation_ledger_path=LAR_ANNOTATION_LEDGER_PATH,
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

    public_observation = build_public_observation(
        result=result,
        phase_result=phase_result,
    )

    LOGGER.info(
        "Observation complete pair=%s bar=%s prism=%s ledger=%s lar=%s",
        public_observation["pair"],
        public_observation["event_timestamp_utc"],
        public_observation["prism_status"],
        public_observation["observation_ledger_status"],
        public_observation["lar_annotation_ledger_status"],
    )

    return public_observation


def run_battlefield_scan() -> None:
    with STATE_LOCK:
        SERVICE_STATE["last_poll_started_at_utc"] = utc_now_iso()
        SERVICE_STATE["last_error"] = None

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    market_data_source = MarketDataSource()
    observations: list[dict[str, Any]] = []
    development_board: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    scan_failures: list[dict[str, str]] = []
    candles_fetched_count = 0

    for symbol in APRIL_12_SYMBOLS:
        try:
            observation = run_one_symbol_observation(
                market_data_source,
                symbol,
            )

            candles_fetched_count += 1
            observations.append(observation)

            development_board.append(
                build_development_card(
                    symbol=symbol,
                    observation=observation,
                    error=None,
                )
            )

            signal = build_signal_card(observation)

            if signal is not None:
                signals.append(signal)

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

            development_board.append(
                build_development_card(
                    symbol=symbol,
                    observation=None,
                    error=error_text,
                )
            )

    priority = {
        "LOCKED IN": 0,
        "PRESSURE BUILDING": 1,
        "RELOAD ZONE": 2,
    }

    signals.sort(
        key=lambda card: priority.get(
            card.get("battle_state"),
            99,
        )
    )

    with STATE_LOCK:
        SERVICE_STATE["observations"] = observations
        SERVICE_STATE["development_board"] = development_board
        SERVICE_STATE["signals"] = signals
        SERVICE_STATE["last_successful_scan_at_utc"] = utc_now_iso()
        SERVICE_STATE["last_error"] = None
        SERVICE_STATE["universe_telemetry"] = {
            "configured_pair_count": len(APRIL_12_SYMBOLS),
            "candles_fetched_count": candles_fetched_count,
            "scanned_pair_count": len(observations),
            "signal_count": len(signals),
            "scan_failures": scan_failures,
        }


def battlefield_worker() -> None:
    with STATE_LOCK:
        SERVICE_STATE["worker_running"] = True

    LOGGER.info(
        "April 12 worker started symbols=%s timeframe=%s poll=%ss",
        ",".join(APRIL_12_SYMBOLS),
        TIMEFRAME,
        POLL_SECONDS,
    )

    while True:
        try:
            run_battlefield_scan()

        except Exception as exc:
            LOGGER.exception("Battlefield scan failed: %s", exc)

            with STATE_LOCK:
                SERVICE_STATE["last_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )

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


@app.get("/api/observations", response_class=JSONResponse)
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


@app.get("/health", response_class=JSONResponse)
def get_health() -> JSONResponse:
    with STATE_LOCK:
        has_scan = SERVICE_STATE[
            "last_successful_scan_at_utc"
        ] is not None

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
                "symbols": APRIL_12_SYMBOLS,
                "storage_mode": SERVICE_STATE["storage_mode"],
                "last_successful_scan_at_utc": (
                    SERVICE_STATE[
                        "last_successful_scan_at_utc"
                    ]
                ),
                "last_error": error,
            }
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
    )