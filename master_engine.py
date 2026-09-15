"""
Oracle Observation Service

Observation-only FastAPI service for completed-bar PRISM/LAR research.

This service:
- Fetches completed five-minute Kraken candles through MarketDataSource.
- Runs PRISM Passive Observer v2 and LAR annotation on completed bars.
- Serves an observation-only dashboard and read-only JSON API.
- Keeps an in-memory observation snapshot for the current service lifetime.

This service does not:
- Generate or route trade signals.
- Manage positions.
- Calculate entries, stops, targets, risk, sizing, or allocation.
- Send webhooks, alerts, orders, messages, or Git commits.
- Expose execution, close-position, or webhook endpoints.

Storage is ephemeral until a Render persistent disk is attached.
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
LOGGER = logging.getLogger("oracle_observation_service")

APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("PRISM_DATA_DIR", "/tmp/prism-observation-data"))

SYMBOL = os.environ.get("PRISM_SYMBOL", "SOL").strip().upper()
TIMEFRAME = os.environ.get("PRISM_TIMEFRAME", "5m").strip()
MIN_CANDLES = int(os.environ.get("PRISM_MIN_CANDLES", "100"))
POLL_SECONDS = max(15, int(os.environ.get("PRISM_POLL_SECONDS", "30")))
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
    "service": "oracle-observation-service",
    "mode": "OBSERVATION_ONLY",
    "started_at_utc": ENGINE_STARTED_AT_UTC,
    "storage_mode": "EPHEMERAL_LOCAL_RUNTIME",
    "storage_note": (
        "No persistent disk is configured. "
        "Observation history can reset after a Render restart or redeploy."
    ),
    "manual_review_only": True,
    "trade_authority": False,
    "entry_authority": False,
    "poll_seconds": POLL_SECONDS,
    "symbol": SYMBOL,
    "timeframe": TIMEFRAME,
    "last_poll_started_at_utc": None,
    "last_successful_observation_at_utc": None,
    "last_completed_bar_timestamp_utc": None,
    "last_observation_ledger_status": None,
    "last_lar_annotation_ledger_status": None,
    "last_error": None,
    "latest_observation": None,
    "worker_running": False,
}

app = FastAPI(
    title="Oracle Observation Service",
    version="1.0.0",
)


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def get_dashboard_html() -> str:
    dashboard_path = APP_ROOT / "dashboard_template.html"

    try:
        return dashboard_path.read_text(encoding="utf-8")
    except OSError as exc:
        return (
            "<!doctype html><html><body>"
            "<h1>Observation dashboard unavailable</h1>"
            f"<p>{exc}</p>"
            "</body></html>"
        )


def safe_text(value: Any, default: str = "Not available") -> str:
    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


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
        liquidity_gate if isinstance(liquidity_gate, dict) else {}
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
        "event_type": "PRISM_PASSIVE_OBSERVATION",
        "event_timestamp_utc": safe_text(
            source.get("completed_bar_timestamp_utc")
        ),
        "observed_at_utc": utc_now_iso(),
        "pair": safe_text(result.get("pair")),
        "timeframe": safe_text(result.get("timeframe")),
        "candle_count": source.get("candle_count"),
        "speed_phase": safe_text(phase_result.get("phase")),
        "speed_direction": safe_text(phase_result.get("direction")),
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
        "lar_state": safe_text(liquidity_gate.get("state")),
        "lar_pool_side": safe_text(liquidity_gate.get("pool_side")),
        "lar_pool_type": safe_text(liquidity_gate.get("pool_type")),
        "lar_description": safe_text(
            liquidity_gate.get("entry_permission")
        ),
        "lar_reason": safe_text(liquidity_gate.get("reason")),
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
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
        "source": "render_completed_5m_prism_passive_observer_v2",
    }
def run_one_observation() -> None:
    with STATE_LOCK:
        SERVICE_STATE["last_poll_started_at_utc"] = utc_now_iso()
        SERVICE_STATE["last_error"] = None

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    market_data_source = MarketDataSource()

    candles = market_data_source.fetch_5m_candles(
        SYMBOL,
        min_candles=MIN_CANDLES,
    )

    if not candles:
        raise RuntimeError(
            f"No completed {TIMEFRAME} candles returned for {SYMBOL}"
        )

    phase_result = analyze_completed_candles(candles)
    speed_phase = safe_text(
        phase_result.get("phase"),
        default="NONE",
    )

    result = observe_completed_bar(
        observation_ledger_path=OBSERVATION_LEDGER_PATH,
        lar_annotation_ledger_path=LAR_ANNOTATION_LEDGER_PATH,
        symbol=SYMBOL,
        candles=candles,
        speed_phase=speed_phase,
        sizing_config=SIZING_CONFIG,
        stop_distance_pct=STOP_DISTANCE_PCT,
        timeframe=TIMEFRAME,
        quote="USD",
        source_label="render_prism_observation_service_v1",
        lar_atr_multiplier=LAR_ATR_MULTIPLIER,
        lar_pending_sweep=None,
    )

    public_observation = build_public_observation(
        result=result,
        phase_result=phase_result,
    )

    with STATE_LOCK:
        SERVICE_STATE["last_successful_observation_at_utc"] = utc_now_iso()
        SERVICE_STATE["last_completed_bar_timestamp_utc"] = (
            public_observation["event_timestamp_utc"]
        )
        SERVICE_STATE["last_observation_ledger_status"] = (
            public_observation["observation_ledger_status"]
        )
        SERVICE_STATE["last_lar_annotation_ledger_status"] = (
            public_observation["lar_annotation_ledger_status"]
        )
        SERVICE_STATE["latest_observation"] = public_observation
        SERVICE_STATE["last_error"] = None

    LOGGER.info(
        "Observation complete pair=%s bar=%s prism=%s ledger=%s lar=%s",
        public_observation["pair"],
        public_observation["event_timestamp_utc"],
        public_observation["prism_status"],
        public_observation["observation_ledger_status"],
        public_observation["lar_annotation_ledger_status"],
    )


def observation_worker() -> None:
    with STATE_LOCK:
        SERVICE_STATE["worker_running"] = True

    LOGGER.info(
        "Observation worker started symbol=%s timeframe=%s poll=%ss",
        SYMBOL,
        TIMEFRAME,
        POLL_SECONDS,
    )

    while True:
        try:
            run_one_observation()
        except Exception as exc:
            LOGGER.exception("Observation cycle failed: %s", exc)

            with STATE_LOCK:
                SERVICE_STATE["last_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )

        time.sleep(POLL_SECONDS)


@app.on_event("startup")
def start_observation_worker() -> None:
    thread = threading.Thread(
        target=observation_worker,
        name="prism-observation-worker",
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

    payload["observations"] = (
        [payload["latest_observation"]]
        if payload["latest_observation"] is not None
        else []
    )

    return JSONResponse(content=payload)


@app.get("/health", response_class=JSONResponse)
def get_health() -> JSONResponse:
    with STATE_LOCK:
        latest = SERVICE_STATE["latest_observation"]
        error = SERVICE_STATE["last_error"]

    status = "healthy"

    if error:
        status = "degraded"
    elif latest is None:
        status = "starting"

    return JSONResponse(
        content={
            "status": status,
            "service": "oracle-observation-service",
            "mode": "OBSERVATION_ONLY",
            "manual_review_only": True,
            "trade_authority": False,
            "entry_authority": False,
            "storage_mode": "EPHEMERAL_LOCAL_RUNTIME",
            "last_completed_bar_timestamp_utc": (
                latest.get("event_timestamp_utc")
                if isinstance(latest, dict)
                else None
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


