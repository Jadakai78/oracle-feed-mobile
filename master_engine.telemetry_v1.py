"""
Master Orchestration Engine - Elite 9 Command Center
-----------------------------------------------------
Operational telemetry edition:
- Preserves existing Elite 9 candidate and paper-position behavior.
- Adds cycle health, universe coverage, symbol scan records, and rejection funnel.
- Adds explicit /health, expanded /api/feed, and expanded /api/universe/status.
"""

import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ai_arbiter import AIArbiter
from hostile_sentinel_analyzer import HostileActivitySentinel
from oracle_feed_v2 import OracleFeedV2
from pair_universe import MarketDataSource
from speed_phase import analyze_completed_candles


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

app = FastAPI(title="JHL Confluence Dashboard Engine - Elite 9 Matrix")

ELITE_9_SYMBOLS = [
    "SOL",
    "ETH",
    "BTC",
    "AVAX",
    "DOGE",
    "XRP",
    "ADA",
    "SUI",
    "NEAR",
]

ASSET_WEAPON_MAPPING = {
    "BTC": [
        "prism_momentum_expansion_breakout_v1",
        "prism_shelf_absorption_fade_v1",
    ],
    "ETH": [
        "prism_momentum_expansion_breakout_v1",
        "prism_range_mean_reversion_v1",
    ],
    "SOL": [
        "reacceleration_reclaim_continuation_v1",
        "momentum_expansion_continuation_v1",
    ],
    "AVAX": [
        "reacceleration_reclaim_continuation_v1",
        "prism_momentum_expansion_breakout_v1",
    ],
    "DOGE": [
        "prism_range_mean_reversion_v1",
        "sell_absorption_reclaim_v1",
    ],
    "XRP": [
        "prism_range_mean_reversion_v1",
        "sell_absorption_reclaim_v1",
    ],
    "ADA": [
        "prism_range_mean_reversion_v1",
        "prism_shelf_absorption_fade_v1",
    ],
    "SUI": [
        "momentum_expansion_continuation_v1",
        "reacceleration_reclaim_continuation_v1",
    ],
    "NEAR": [
        "prism_shelf_absorption_fade_v1",
        "momentum_expansion_continuation_v1",
    ],
}

ACCOUNT_EQUITY = 10000.0
ENGINE_MODE = "PAPER"
ENGINE_STARTED_UTC = datetime.now(timezone.utc).isoformat()

REJECTION_KEYS = (
    "missing_candles",
    "invalid_price",
    "insufficient_window",
    "anti_delta_or_volume",
    "location_filter",
    "supertrend_conflict",
    "feed_unmatched_candidate",
    "hostility_veto",
    "arbiter_abstain",
    "feed_generation_error",
    "runtime_errors",
)

latest_engine_payload = {
    "active_signals_count": 0,
    "timestamp": "00:00:00 UTC",
    "signals": [],
    "staging_monitors": [],
    "engine_health": {
        "status": "STARTING",
        "engine_started_utc": ENGINE_STARTED_UTC,
        "last_cycle_started_utc": None,
        "last_successful_cycle_utc": None,
        "last_cycle_duration_ms": None,
        "cycle_age_seconds": None,
        "last_cycle_error": None,
    },
    "universe_telemetry": {
        "configured_pair_count": len(ELITE_9_SYMBOLS),
        "candles_fetched_count": 0,
        "scanned_pair_count": 0,
        "staging_monitor_count": 0,
        "raw_candidate_count": 0,
        "feed_candidate_count": 0,
        "authorized_signal_count": 0,
        "scan_failures": [],
        "symbol_status": [],
    },
    "rejection_funnel": {key: 0 for key in REJECTION_KEYS},
}

active_positions = []


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def round_price(value):
    if value is None:
        return None
    return round(value, 4 if value < 10 else 2)


def build_empty_rejection_funnel():
    return {key: 0 for key in REJECTION_KEYS}


def cycle_age_seconds(last_successful_cycle_utc):
    if not last_successful_cycle_utc:
        return None

    try:
        last_cycle = datetime.fromisoformat(
            last_successful_cycle_utc.replace("Z", "+00:00")
        )
        age = (datetime.now(timezone.utc) - last_cycle).total_seconds()
        return max(0, round(age, 1))
    except (TypeError, ValueError):
        return None


def health_snapshot():
    health = latest_engine_payload.get("engine_health", {})
    last_success = health.get("last_successful_cycle_utc")
    age_seconds = cycle_age_seconds(last_success)

    if last_success is None:
        status = "STARTING"
    elif age_seconds is not None and age_seconds > 180:
        status = "STALE"
    elif health.get("last_cycle_error"):
        status = "DEGRADED"
    else:
        status = "HEALTHY"

    return {
        "status": status,
        "mode": ENGINE_MODE,
        "engine_started_utc": ENGINE_STARTED_UTC,
        "last_cycle_started_utc": health.get("last_cycle_started_utc"),
        "last_successful_cycle_utc": last_success,
        "last_cycle_duration_ms": health.get("last_cycle_duration_ms"),
        "cycle_age_seconds": age_seconds,
        "last_cycle_error": health.get("last_cycle_error"),
    }


def calculate_supertrend(candles, period=10, multiplier=3.0):
    if len(candles) < period:
        return {
            "value": 0.0,
            "direction": "NEUTRAL",
            "distance_pct": 0.0,
        }

    atr_list = []
    for index in range(1, len(candles)):
        high = candles[index]["high"]
        low = candles[index]["low"]
        previous_close = candles[index - 1]["close"]
        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )
        atr_list.append(true_range)

    if not atr_list:
        return {
            "value": candles[-1]["close"],
            "direction": "NEUTRAL",
            "distance_pct": 0.0,
        }

    recent_atr = sum(atr_list[-period:]) / min(period, len(atr_list))
    current = candles[-1]
    midpoint = (current["high"] + current["low"]) / 2.0
    basic_upper = midpoint + (multiplier * recent_atr)
    basic_lower = midpoint - (multiplier * recent_atr)
    close = current["close"]

    direction = "LONG" if close > basic_lower else "SHORT"
    supertrend_value = basic_lower if direction == "LONG" else basic_upper
    distance_pct = abs(close - supertrend_value) / close * 100

    return {
        "value": round(supertrend_value, 4),
        "direction": direction,
        "distance_pct": round(distance_pct, 2),
    }


def evaluate_noise_and_zone_regime(candles):
    if len(candles) < 30:
        return {
            "regime": "UNKNOWN",
            "zone": "NEUTRAL",
            "noise_multiplier": 1.0,
        }

    recent = candles[-20:]
    closes = [candle["close"] for candle in recent]
    mean_close = sum(closes) / len(closes)
    variance = sum((close - mean_close) ** 2 for close in closes) / len(closes)
    standard_deviation = variance ** 0.5 if variance > 0 else mean_close * 0.001

    price_range_pct = (
        max(candle["high"] for candle in recent)
        - min(candle["low"] for candle in recent)
    ) / mean_close

    average_volume = sum(candle["volume"] for candle in recent) / len(recent)
    volume_ratio = candles[-1]["volume"] / max(1.0, average_volume)

    if price_range_pct < 0.003 and volume_ratio < 0.7:
        regime = "CHOPPY_NOISE"
        noise_multiplier = 0.5
    elif price_range_pct > 0.02:
        regime = "HIGH_DISPERSION"
        noise_multiplier = 0.8
    else:
        regime = "NORMAL_TAPE"
        noise_multiplier = 1.0

    last_close = candles[-1]["close"]
    if last_close > mean_close + (1.5 * standard_deviation):
        zone = "UPPER_EXTENDED"
    elif last_close < mean_close - (1.5 * standard_deviation):
        zone = "LOWER_EXTENDED"
    else:
        zone = "CENTRAL_VALUE"

    return {
        "regime": regime,
        "zone": zone,
        "noise_multiplier": noise_multiplier,
    }


def calculate_dynamic_stealth_allocation(
    account_equity,
    stop_pct,
    candles,
    noise_multiplier,
):
    if stop_pct <= 0:
        return 400, "DEFAULT"

    base_risk_usd = account_equity * 0.0075
    raw_position_size = base_risk_usd / stop_pct

    if len(candles) >= 20:
        recent_volumes = [candle["volume"] for candle in candles[-20:]]
        average_volume = sum(recent_volumes) / len(recent_volumes)
        volume_expansion_ratio = candles[-1]["volume"] / max(1.0, average_volume)
    else:
        volume_expansion_ratio = 1.0

    if volume_expansion_ratio > 1.8:
        volume_scale_factor = 2.0
        stealth_tag = "AGGRESSIVE EXPANSION ($BIG MONEY TIER$)"
    elif volume_expansion_ratio < 0.7:
        volume_scale_factor = 0.4
        stealth_tag = "STEALTH MASK ACTIVE (GHOST TIER)"
    else:
        volume_scale_factor = 1.0
        stealth_tag = "NORMAL PROPORTIONAL TIER"

    final_multiplier = volume_scale_factor * noise_multiplier
    allocation = int(raw_position_size * final_multiplier)
    allocation = max(300, min(4000, allocation))

    return allocation, stealth_tag


def calculate_live_health_score(
    entry_price,
    current_price,
    is_long,
    minutes_remaining,
    max_minutes=90,
):
    health = 100.0

    if is_long:
        price_delta_pct = ((current_price - entry_price) / entry_price) * 100
    else:
        price_delta_pct = ((entry_price - current_price) / entry_price) * 100

    if price_delta_pct < 0:
        health -= abs(price_delta_pct) * 35.0

    time_elapsed_pct = max(
        0.0,
        min(1.0, (max_minutes - minutes_remaining) / max_minutes),
    )

    if price_delta_pct < 0:
        health -= time_elapsed_pct * 50.0 * abs(price_delta_pct)
    else:
        health += min(20.0, price_delta_pct * 10.0)

    return round(max(0.0, min(100.0, health)), 1)


def monitor_adaptive_clash_defense(
    entry_price,
    current_price,
    is_long,
    window_candles,
    current_step,
    max_steps=18,
):
    if is_long:
        price_delta_pct = ((current_price - entry_price) / entry_price) * 100
    else:
        price_delta_pct = ((entry_price - current_price) / entry_price) * 100

    recent_candles = (
        window_candles[-5:]
        if len(window_candles) >= 5
        else window_candles
    )

    if not recent_candles:
        return "HOLD", None

    green_aggregate = sum(
        candle["volume"] * max(0.01, candle["close"] - candle["low"])
        for candle in recent_candles
    )
    red_aggregate = sum(
        candle["volume"] * max(0.01, candle["high"] - candle["close"])
        for candle in recent_candles
    )

    dominant_aggregate = green_aggregate if is_long else red_aggregate
    opposing_aggregate = red_aggregate if is_long else green_aggregate
    dominance_ratio = opposing_aggregate / max(1.0, dominant_aggregate)

    if price_delta_pct < -0.8 and dominance_ratio > 1.5:
        return "SCRATCH", current_price

    progress_pct = current_step / max_steps
    if progress_pct > 0.6 and price_delta_pct < 0.2 and dominance_ratio > 1.2:
        return "SCRATCH", current_price

    if price_delta_pct > 0.5:
        new_stop = (
            entry_price + (current_price - entry_price) * 0.2
            if is_long
            else entry_price - (entry_price - current_price) * 0.2
        )
        return "TRAIL_STOP", new_stop

    return "HOLD", None


def github_sync_worker():
    logging.info("GitHub Synchronization Worker initialized.")

    while True:
        try:
            time.sleep(1800)
            logging.info("Executing automated GitHub repository synchronization...")

            subprocess.run(["git", "add", "."], check=False)
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    (
                        "Auto-sync: Elite 9 Weapon Mapping Matrix checkpoint "
                        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    ),
                ],
                check=False,
            )

            result = subprocess.run(
                ["git", "push"],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                logging.info("GitHub repository successfully synchronized.")
            else:
                logging.warning(
                    "GitHub sync push notice: %s",
                    result.stderr.strip(),
                )
        except Exception as exc:
            logging.error("Error during GitHub synchronization worker: %s", exc)


def update_positions(candles_cache):
    for position in active_positions:
        position["time_in_range_mins"] = (
            position.get("time_in_range_mins", 0) + 1
        )

        symbol_key = position["pair"].replace("USD", "")
        symbol_candles = candles_cache.get(symbol_key, [])
        current_price = (
            symbol_candles[-1]["close"]
            if symbol_candles
            else position["entry"]
        )
        minutes_remaining = max(
            0,
            90 - position["time_in_range_mins"],
        )

        position["health_score"] = calculate_live_health_score(
            entry_price=position["entry"],
            current_price=current_price,
            is_long=position.get("is_long", True),
            minutes_remaining=minutes_remaining,
            max_minutes=90,
        )

        action, defense_parameter = monitor_adaptive_clash_defense(
            entry_price=position["entry"],
            current_price=current_price,
            is_long=position.get("is_long", True),
            window_candles=(
                symbol_candles[-10:]
                if len(symbol_candles) >= 10
                else symbol_candles
            ),
            current_step=position["time_in_range_mins"],
            max_steps=18,
        )

        if action == "SCRATCH":
            position["warning"] = "DEFENSE SCRATCH TRIGGERED: CLEAN BLEED AVOIDED"
            position["gate_status"] = "Early Scratch Executed"
        elif action == "TRAIL_STOP":
            position["stop"] = defense_parameter
            position["warning"] = (
                f"PRISM ACTIVE (Dynamic Tier: ${position['allocation_size']} | "
                "Stop Trailed)"
            )

        if (
            position["time_in_range_mins"] > 90
            and position["gate_status"] != "Early Scratch Executed"
        ):
            position["warning"] = (
                "90M TEMPORAL WINDOW REACHED: AUTOMATED ROTATION EXIT"
            )
            position["gate_status"] = "Temporal Exit Triggered"


def build_symbol_record(symbol):
    return {
        "symbol": symbol,
        "pair": f"{symbol}USD",
        "status": "PENDING",
        "reason": None,
        "bar_count": 0,
        "last_price": None,
        "speed_phase": None,
        "supertrend_direction": None,
        "raw_candidate": False,
    }


def run_master_orchestration():
    global latest_engine_payload

    logging.info("Master Engine + Elite 9 Weapon Matrix initialized 24/7.")

    feed_generator = OracleFeedV2(account_balance=ACCOUNT_EQUITY)
    sentinel = HostileActivitySentinel(hostility_threshold=0.80)
    arbiter = AIArbiter(mode="ACTIVE")
    market_data_source = MarketDataSource()

    while True:
        cycle_started = utc_now_iso()
        cycle_started_monotonic = time.monotonic()
        rejection_funnel = build_empty_rejection_funnel()
        symbol_status = []
        scan_failures = []
        raw_candidates = []
        staging_monitors = []
        candles_cache = {}
        feed_candidate_count = 0
        cycle_error = None

        try:
            for symbol in ELITE_9_SYMBOLS:
                symbol_record = build_symbol_record(symbol)

                try:
                    candles = market_data_source.fetch_5m_candles(
                        symbol,
                        min_candles=60,
                    )
                except Exception as exc:
                    rejection_funnel["missing_candles"] += 1
                    symbol_record["status"] = "FETCH_ERROR"
                    symbol_record["reason"] = str(exc)
                    scan_failures.append(
                        {
                            "symbol": symbol,
                            "stage": "fetch_5m_candles",
                            "reason": str(exc),
                        }
                    )
                    symbol_status.append(symbol_record)
                    continue

                if not candles:
                    rejection_funnel["missing_candles"] += 1
                    symbol_record["status"] = "NO_CANDLES"
                    symbol_record["reason"] = "No completed 5m candles returned."
                    scan_failures.append(
                        {
                            "symbol": symbol,
                            "stage": "fetch_5m_candles",
                            "reason": symbol_record["reason"],
                        }
                    )
                    symbol_status.append(symbol_record)
                    continue

                symbol_record["bar_count"] = len(candles)
                candles_cache[symbol] = candles

                try:
                    current = candles[-1]
                    last_price = current["close"]
                except (IndexError, KeyError, TypeError) as exc:
                    rejection_funnel["invalid_price"] += 1
                    symbol_record["status"] = "INVALID_CANDLE"
                    symbol_record["reason"] = str(exc)
                    scan_failures.append(
                        {
                            "symbol": symbol,
                            "stage": "current_candle",
                            "reason": str(exc),
                        }
                    )
                    symbol_status.append(symbol_record)
                    continue

                if not isinstance(last_price, (int, float)) or last_price <= 0:
                    rejection_funnel["invalid_price"] += 1
                    symbol_record["status"] = "INVALID_PRICE"
                    symbol_record["reason"] = f"Invalid close price: {last_price!r}"
                    symbol_status.append(symbol_record)
                    continue

                symbol_record["last_price"] = round_price(last_price)

                try:
                    supertrend = calculate_supertrend(
                        candles,
                        period=10,
                        multiplier=3.0,
                    )
                    noise_audit = evaluate_noise_and_zone_regime(candles)
                    speed_result = analyze_completed_candles(candles)
                    speed_phase = speed_result.get("phase", "NONE")
                except Exception as exc:
                    rejection_funnel["runtime_errors"] += 1
                    symbol_record["status"] = "ANALYSIS_ERROR"
                    symbol_record["reason"] = str(exc)
                    scan_failures.append(
                        {
                            "symbol": symbol,
                            "stage": "analysis",
                            "reason": str(exc),
                        }
                    )
                    symbol_status.append(symbol_record)
                    continue

                symbol_record["speed_phase"] = speed_phase
                symbol_record["supertrend_direction"] = supertrend["direction"]

                if speed_phase == "REACCELERATION":
                    cvd_slope = "DIVERGENT"
                    rts_state = "ALIGNED"
                elif speed_phase == "CONTROLLED_PULLBACK":
                    cvd_slope = "EXPANDING"
                    rts_state = "ALIGNED"
                elif speed_phase == "DECAY":
                    cvd_slope = "DIVERGENT"
                    rts_state = "LIQUIDATION_WARNING"
                else:
                    cvd_slope = "FLAT"
                    rts_state = "NEUTRAL"

                staging_monitors.append(
                    {
                        "pair": f"{symbol}USD",
                        "price": round_price(last_price),
                        "speed_phase": speed_phase,
                        "supertrend_dir": supertrend["direction"],
                        "st_distance_pct": supertrend["distance_pct"],
                        "noise_regime": noise_audit["regime"],
                        "structural_zone": noise_audit["zone"],
                        "staging_status": "MONITORING SETUP FORMATION",
                    }
                )

                if len(candles) >= 40:
                    window = candles[-40:]
                    closes = [candle["close"] for candle in window]
                    mean_390 = sum(closes) / len(closes)
                    variance = sum(
                        (close - mean_390) ** 2
                        for close in closes
                    ) / len(closes)
                    standard_deviation = (
                        variance ** 0.5
                        if variance > 0
                        else last_price * 0.01
                    )

                    price_range = current["high"] - current["low"]
                    anti_delta_score = int(
                        min(100.0, (price_range / last_price) * 5000)
                    )

                    average_volume = (
                        sum(candle["volume"] for candle in window[-10:]) / 10
                    )
                    volume_expansion = current["volume"] / max(
                        1.0,
                        average_volume,
                    )

                    if anti_delta_score > 75 or volume_expansion < 0.8:
                        rejection_funnel["anti_delta_or_volume"] += 1
                        symbol_record["status"] = "FILTERED"
                        symbol_record["reason"] = (
                            "anti_delta_or_volume"
                            f" (anti_delta={anti_delta_score}, "
                            f"volume_expansion={round(volume_expansion, 3)})"
                        )
                        symbol_status.append(symbol_record)
                        continue

                    distance_from_mean = (
                        (last_price - mean_390) / standard_deviation
                        if standard_deviation > 0
                        else 0.0
                    )

                    if abs(distance_from_mean) > 1.0:
                        rejection_funnel["location_filter"] += 1
                        symbol_record["status"] = "FILTERED"
                        symbol_record["reason"] = (
                            "location_filter"
                            f" (distance_from_mean={round(distance_from_mean, 3)})"
                        )
                        symbol_status.append(symbol_record)
                        continue

                    is_long = distance_from_mean <= 0.0
                else:
                    rejection_funnel["insufficient_window"] += 1
                    is_long = True
                    distance_from_mean = 0.0
                    anti_delta_score = 40

                derived_direction = "LONG" if is_long else "SHORT"

                if (
                    supertrend["direction"] != "NEUTRAL"
                    and supertrend["direction"] != derived_direction
                ):
                    rejection_funnel["supertrend_conflict"] += 1
                    symbol_record["status"] = "FILTERED"
                    symbol_record["reason"] = (
                        "supertrend_conflict"
                        f" (supertrend={supertrend['direction']}, "
                        f"derived={derived_direction})"
                    )
                    symbol_status.append(symbol_record)
                    continue

                allowed_setups = ASSET_WEAPON_MAPPING.get(
                    symbol,
                    ["prism_momentum_expansion_breakout_v1"],
                )
                absolute_distance = abs(distance_from_mean)

                if absolute_distance < 0.5 and allowed_setups:
                    setup_family = allowed_setups[0]
                elif len(allowed_setups) > 1:
                    setup_family = allowed_setups[1]
                else:
                    setup_family = allowed_setups[0]

                if symbol in {"BTC", "ETH"}:
                    stop_pct = 0.010
                elif last_price > 50.0:
                    stop_pct = 0.015
                else:
                    stop_pct = 0.020

                raw_candidates.append(
                    {
                        "pair": f"{symbol}USD",
                        "setup_family": setup_family,
                        "stop_distance_pct": stop_pct,
                        "base_price": last_price,
                        "is_long": is_long,
                        "speed_phase": speed_phase,
                        "cvd_slope": cvd_slope,
                        "rts_state": rts_state,
                        "anti_delta_score": anti_delta_score,
                        "noise_audit": noise_audit,
                        "supertrend": supertrend,
                        "candles": candles,
                    }
                )

                symbol_record["status"] = "RAW_CANDIDATE"
                symbol_record["reason"] = "Passed pre-feed filters."
                symbol_record["raw_candidate"] = True
                symbol_status.append(symbol_record)

            formatted_signals = []

            if raw_candidates:
                shuffled = sorted(
                    raw_candidates,
                    key=lambda candidate: (
                        0
                        if candidate["speed_phase"] == "REACCELERATION"
                        else 1
                    ),
                )

                try:
                    feed_data = feed_generator.generate_feed(shuffled)
                    feed_signals = feed_data.get("signals", [])
                    feed_candidate_count = len(feed_signals)
                except Exception as exc:
                    rejection_funnel["feed_generation_error"] += 1
                    cycle_error = f"feed_generation_error: {exc}"
                    logging.error("Feed generation error: %s", exc)
                    feed_signals = []

                for signal in feed_signals:
                    pair_name = signal.get("pair")
                    matching_candidate = next(
                        (
                            candidate
                            for candidate in shuffled
                            if candidate["pair"] == pair_name
                        ),
                        None,
                    )

                    if not matching_candidate:
                        rejection_funnel["feed_unmatched_candidate"] += 1
                        continue

                    base_price = matching_candidate["base_price"]
                    stop_distance_pct = matching_candidate["stop_distance_pct"]
                    is_long = matching_candidate["is_long"]

                    parameters = signal.get("parameters", {})
                    take_profit_multiplier = parameters.get(
                        "sl_tp_multiplier",
                        1.0,
                    )

                    speed_phase = matching_candidate["speed_phase"]
                    cvd_slope = matching_candidate["cvd_slope"]
                    rts_state = matching_candidate["rts_state"]
                    anti_delta_score = matching_candidate["anti_delta_score"]
                    noise_audit = matching_candidate["noise_audit"]
                    supertrend = matching_candidate["supertrend"]
                    candidate_candles = matching_candidate["candles"]

                    try:
                        is_hostile, hostility_score, hostility_reason = (
                            sentinel.evaluate_hostility(
                                {
                                    "offensive_review": {
                                        "speed_phase": speed_phase,
                                        "cvd_slope_state": cvd_slope,
                                        "anti_delta_score": anti_delta_score,
                                        "rts_state": rts_state,
                                    }
                                }
                            )
                        )
                    except Exception as exc:
                        rejection_funnel["runtime_errors"] += 1
                        logging.error(
                            "Hostility evaluation error for %s: %s",
                            pair_name,
                            exc,
                        )
                        continue

                    if is_hostile:
                        rejection_funnel["hostility_veto"] += 1

                    candidate_card = {
                        "pair": pair_name,
                        "speed_phase": speed_phase,
                        "cvd_slope": cvd_slope,
                        "anti_delta_score": anti_delta_score,
                        "hostility_score": hostility_score,
                        "status": "VETOED" if is_hostile else "MATCH",
                    }

                    is_weekend = datetime.now(timezone.utc).weekday() >= 5

                    try:
                        ai_result = arbiter.evaluate_candidate(
                            candidate_card,
                            {"is_weekend": is_weekend},
                        )
                    except Exception as exc:
                        rejection_funnel["runtime_errors"] += 1
                        logging.error(
                            "Arbiter evaluation error for %s: %s",
                            pair_name,
                            exc,
                        )
                        continue

                    if ai_result.get("decision", "ABSTAIN") != "TAKE":
                        rejection_funnel["arbiter_abstain"] += 1
                        continue

                    score = int(ai_result.get("confidence", 0.85) * 100)

                    allocation_size, stealth_tag = (
                        calculate_dynamic_stealth_allocation(
                            ACCOUNT_EQUITY,
                            stop_distance_pct,
                            candidate_candles,
                            noise_audit["noise_multiplier"],
                        )
                    )

                    status_label = (
                        f"SNIPER WEAPON MATCH ({stealth_tag})"
                    )

                    if is_long:
                        stop_price = round_price(
                            base_price * (1.0 - stop_distance_pct)
                        )
                        target_price = round_price(
                            base_price
                            * (
                                1.0
                                + (
                                    stop_distance_pct
                                    * take_profit_multiplier
                                )
                            )
                        )
                        direction_label = "LONG"
                    else:
                        stop_price = round_price(
                            base_price * (1.0 + stop_distance_pct)
                        )
                        target_price = round_price(
                            base_price
                            * (
                                1.0
                                - (
                                    stop_distance_pct
                                    * take_profit_multiplier
                                )
                            )
                        )
                        direction_label = "SHORT"

                    scaled_risk = round(
                        allocation_size * stop_distance_pct,
                        2,
                    )

                    formatted_signals.append(
                        {
                            "pair": pair_name,
                            "setup_family": signal.get(
                                "setup_family",
                                matching_candidate["setup_family"],
                            ),
                            "entry": round_price(base_price),
                            "stop": stop_price,
                            "target": target_price,
                            "is_long": is_long,
                            "direction": direction_label,
                            "allocation_size": allocation_size,
                            "risk_usd": scaled_risk,
                            "score": score,
                            "anti_delta_score": anti_delta_score,
                            "speed_phase": speed_phase,
                            "cvd_slope": cvd_slope,
                            "rts_state": rts_state,
                            "hostility_score": hostility_score,
                            "status": status_label,
                            "prism_map": (
                                f"ST DIST: {supertrend['distance_pct']}% | "
                                f"{stealth_tag}"
                            ),
                            "eight_gates": "8/8",
                        }
                    )

            formatted_signals.sort(
                key=lambda signal: signal["score"],
                reverse=True,
            )

            update_positions(candles_cache)

        except Exception as exc:
            rejection_funnel["runtime_errors"] += 1
            cycle_error = f"orchestration_error: {exc}"
            logging.exception("Error during orchestration loop: %s", exc)

        cycle_finished = utc_now_iso()
        duration_ms = round(
            (time.monotonic() - cycle_started_monotonic) * 1000,
            1,
        )

        scanned_pair_count = sum(
            1
            for record in symbol_status
            if record["status"]
            not in {
                "FETCH_ERROR",
                "NO_CANDLES",
                "INVALID_CANDLE",
                "INVALID_PRICE",
            }
        )

        candles_fetched_count = sum(
            1
            for record in symbol_status
            if record["bar_count"] > 0
        )

        latest_engine_payload = {
            "active_signals_count": len(formatted_signals),
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            "signals": formatted_signals,
            "staging_monitors": staging_monitors,
            "engine_health": {
                "status": "HEALTHY" if cycle_error is None else "DEGRADED",
                "engine_started_utc": ENGINE_STARTED_UTC,
                "last_cycle_started_utc": cycle_started,
                "last_successful_cycle_utc": (
                    cycle_finished if cycle_error is None else None
                ),
                "last_cycle_duration_ms": duration_ms,
                "cycle_age_seconds": 0.0,
                "last_cycle_error": cycle_error,
            },
            "universe_telemetry": {
                "configured_pair_count": len(ELITE_9_SYMBOLS),
                "candles_fetched_count": candles_fetched_count,
                "scanned_pair_count": scanned_pair_count,
                "staging_monitor_count": len(staging_monitors),
                "raw_candidate_count": len(raw_candidates),
                "feed_candidate_count": feed_candidate_count,
                "authorized_signal_count": len(formatted_signals),
                "scan_failures": scan_failures,
                "symbol_status": symbol_status,
            },
            "rejection_funnel": rejection_funnel,
        }

        logging.info(
            "Cycle complete: scanned=%s/%s monitors=%s raw=%s feed=%s "
            "authorized=%s duration_ms=%s",
            scanned_pair_count,
            len(ELITE_9_SYMBOLS),
            len(staging_monitors),
            len(raw_candidates),
            feed_candidate_count,
            len(formatted_signals),
            duration_ms,
        )

        time.sleep(60)


@app.get("/api/feed", response_class=JSONResponse)
def get_feed_api():
    payload = dict(latest_engine_payload)
    payload["engine_health"] = health_snapshot()
    return payload


@app.get("/api/positions", response_class=JSONResponse)
def get_positions_api():
    return {
        "positions": active_positions,
        "max_cap": "UNLIMITED",
        "cooldown_active": False,
        "mode": ENGINE_MODE,
    }


@app.get("/api/universe/status", response_class=JSONResponse)
def get_universe_telemetry():
    return {
        "status": health_snapshot()["status"],
        "mode": ENGINE_MODE,
        "active_whitelist": ELITE_9_SYMBOLS,
        "weapon_matrix": ASSET_WEAPON_MAPPING,
        "staging_monitors": latest_engine_payload.get(
            "staging_monitors",
            [],
        ),
        "engine_health": health_snapshot(),
        "universe_telemetry": latest_engine_payload.get(
            "universe_telemetry",
            {},
        ),
        "rejection_funnel": latest_engine_payload.get(
            "rejection_funnel",
            {},
        ),
    }


@app.post("/api/execute", response_class=JSONResponse)
async def execute_trade(request: Request):
    global active_positions

    data = await request.json()

    new_position = {
        "id": f"pos_{int(time.time())}",
        "pair": data.get("pair"),
        "setup_family": data.get("setup_family"),
        "entry": data.get("entry"),
        "stop": data.get("stop"),
        "target": data.get("target"),
        "is_long": data.get("is_long", True),
        "direction": "LONG" if data.get("is_long", True) else "SHORT",
        "allocation_size": data.get("allocation_size", 750),
        "risk_usd": data.get("risk_usd"),
        "health_score": 100.0,
        "anti_delta_pressure": 45,
        "rts_state": "ALIGNED",
        "time_in_range_mins": 0,
        "gate_status": "Pair-Specific Weapon Matrix Active",
        "warning": (
            f"PRISM ACTIVE (Dynamic Tier: "
            f"${data.get('allocation_size', 750)} | 90m Hold)"
        ),
        "opened_at": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
    }

    active_positions.insert(0, new_position)

    return {
        "status": "SUCCESS",
        "mode": ENGINE_MODE,
        "position": new_position,
    }


@app.post("/api/close", response_class=JSONResponse)
async def close_trade(request: Request):
    global active_positions

    try:
        body = await request.json()
        position_id = body.get("id")
        active_positions = [
            position
            for position in active_positions
            if position["id"] != position_id
        ]
        return {"status": "CLOSED", "mode": ENGINE_MODE}
    except Exception as exc:
        return {"status": "ERROR", "reason": str(exc), "mode": ENGINE_MODE}


@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    try:
        with open("dashboard_template.html", "r", encoding="utf-8") as file_handle:
            return HTMLResponse(content=file_handle.read())
    except Exception as exc:
        return HTMLResponse(
            content=f"<h3>Dashboard template error: {exc}</h3>",
            status_code=500,
        )


@app.get("/health", response_class=JSONResponse)
def health_check():
    return {
        "service": "JHL Oracle Feed",
        "health": health_snapshot(),
        "universe_telemetry": latest_engine_payload.get(
            "universe_telemetry",
            {},
        ),
    }


if __name__ == "__main__":
    sync_thread = threading.Thread(
        target=github_sync_worker,
        daemon=True,
    )
    sync_thread.start()

    engine_thread = threading.Thread(
        target=run_master_orchestration,
        daemon=True,
    )
    engine_thread.start()

    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
