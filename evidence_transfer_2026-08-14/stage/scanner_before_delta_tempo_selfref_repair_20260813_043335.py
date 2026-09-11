"""scanner.py — JHL Gimba Scanner

Runs the four specialists, writes canonical signals and one training observation per
completed 15-minute pressure candle. Kraken public OHLC and trade data are used
only for market-data observation; this file places no orders.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gimba_range
import gimba_trend
import gimba_volatile
import gimba_volume_flow
import gimba_drive
import gimba_pulse
import market_noise
import market_timing
import rts_liquidation
import structure_bias
from knn_engine import KNNEngine
import market_state_engine
import shadow_gimba_volatile
import shadow_trend_recovery
import delta_tempo_prop_router
PAIRS = [
    ("SOL/USD", "SOLUSD"), ("BTC/USD", "XBTUSD"), ("ETH/USD", "ETHUSD"),
    ("XRP/USD", "XRPUSD"), ("ADA/USD", "ADAUSD"), ("DOGE/USD", "XDGUSD"),
    ("LINK/USD", "LINKUSD"), ("AVAX/USD", "AVAXUSD"), ("DOT/USD", "DOTUSD"),
    ("MATIC/USD", "MATICUSD"), ("AAVE/USD", "AAVEUSD"), ("LTC/USD", "XLTCZUSD"),
]
SCAN_INTERVAL = 300
FLOW_INTERVAL_MINUTES = 15
FLOW_SOURCE = "kraken_public_trades"
KRAKEN_API = "https://api.kraken.com/0/public"
OUTPUT_FILE = Path(__file__).parent / "signals.json"
LOG_DIR = Path(__file__).parent / "training_logs"
LOG_DIR.mkdir(exist_ok=True)

_VOLUME_STATE: Dict[str, Dict[str, Any]] = {}
_SEEN_EVENT_KEYS: set[str] = set()


def _get_volume_state(pair: str) -> Dict[str, Any]:
    if pair not in _VOLUME_STATE:
        _VOLUME_STATE[pair] = {"cvd": 0.0, "window": [], "vol_ma": 0.0}
    return _VOLUME_STATE[pair]


def _request(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{KRAKEN_API}{path}?{query}", timeout=12) as response:
        payload = json.loads(response.read())
    if payload.get("error"):
        raise RuntimeError("; ".join(payload["error"]))
    return payload.get("result") or {}


def _result_rows(result: Dict[str, Any]) -> List[list]:
    key = next((name for name in result if name != "last"), None)
    return list(result.get(key) or []) if key else []


def fetch_bar_data(pair: str, kraken_pair: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Optional[str]]:
    """Get one completed 15m OHLC bar and its classified Kraken public trades.

    Kraken's OHLC endpoint always includes an incomplete final bar, so this uses
    the penultimate row. A trade response at its 1000-trade cap is rejected
    rather than used as incomplete pressure data.
    """
    try:
        ohlc_result = _request("/OHLC", {"pair": kraken_pair, "interval": FLOW_INTERVAL_MINUTES})
        rows = _result_rows(ohlc_result)
        if len(rows) < 2:
            return [], {}, "insufficient_ohlc_rows"
        row = rows[-2]
        start = int(float(row[0]))
        end = start + FLOW_INTERVAL_MINUTES * 60
        ohlcv = {
            "open": float(row[1]), "high": float(row[2]), "low": float(row[3]),
            "close": float(row[4]), "volume": float(row[6]), "bar_start": start, "bar_end": end,
        }

        trades_result = _request("/Trades", {"pair": kraken_pair, "since": str(start), "count": 1000})
        raw_trades = _result_rows(trades_result)
        if len(raw_trades) >= 1000:
            return [], ohlcv, "trade_response_at_limit"

        trades: List[Dict[str, Any]] = []
        for raw in raw_trades:
            if len(raw) < 7:
                continue
            trade_time = float(raw[2])
            if start <= trade_time < end:
                trades.append({
                    "price": float(raw[0]), "size": float(raw[1]), "side": str(raw[3]).lower(),
                    "timestamp": trade_time, "trade_id": str(raw[6]),
                })
        return trades, ohlcv, None
    except Exception as exc:
        return [], {}, f"kraken_fetch_error:{type(exc).__name__}"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _ts_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conviction_bar(value: float, width: int = 10) -> str:
    filled = max(0, min(width, int(round(value * width))))
    return "[" + "█" * filled + "░" * (width - filled) + f"] {value:.2f}"


def _append_training_log(
    bot_name: str, pair: str, signal: Dict[str, Any], ts: str, event_key: str,
    structure: Dict[str, Any], diagnostics: Dict[str, Any], volume_flow: Dict[str, Any],
) -> None:
    if event_key in _SEEN_EVENT_KEYS:
        return
    _SEEN_EVENT_KEYS.add(event_key)
    persisted_diagnostics = dict(diagnostics or {})
    persisted_diagnostics.update(signal.get("diagnostics") or {})
    record = {
        "schema_version": 2,
        "event_key": event_key,
        "ts": ts,
        "pair": pair,
        "bot": bot_name,
        "setup_type": signal.get("setup_type", ""),
        "state": signal.get("pulse_state") or signal.get("setup_type", ""),
        "bias": signal.get("bias", "NONE"),
        "conviction": signal.get("conviction", 0.0),
        "pulse_score": signal.get("pulse_score"),
        "action": signal.get("action_state", "idle"),
        "why": signal.get("why", ""),
        "training_only": bool(signal.get("training_only")),
        "diagnostic_only": bool(signal.get("diagnostic_only")),
        "indicators": signal.get("indicators", {}),
        "trap_score": signal.get("trap_score"),
        "entry": signal.get("entry"), "sl": signal.get("sl"), "tp": signal.get("tp"),
        "structure": structure,
        "diagnostics": persisted_diagnostics,
        "volume_flow": volume_flow,
        "market_noise": signal.get("market_noise") or market_noise.unavailable("market_noise_missing"),
        "market_timing": signal.get("market_timing") or market_timing.unavailable("market_timing_missing"),
        "outcome": {"status": "pending", "label": None},
    }
    with (LOG_DIR / f"{bot_name}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _apply_knn(bot_name: str, signal: Dict[str, Any], structure: Dict[str, Any], volume_flow: Dict[str, Any]) -> None:
    candidate = dict(signal)
    candidate["structure"] = structure
    candidate["diagnostics"] = signal.get("diagnostics") or {}
    candidate["volume_flow"] = volume_flow
    try:
        adjustment, samples = KNNEngine(bot_name, LOG_DIR, min_samples=30).adjust(candidate)
    except Exception:
        adjustment, samples = 0.0, 0
    signal["knn_adj"] = adjustment if samples >= 30 else 0.0
    signal["knn_samples"] = samples
    if samples >= 30 and signal.get("action_state") == "watch":
        signal["conviction"] = round(max(0.0, min(1.0, float(signal.get("conviction", 0.0)) + adjustment)), 3)


def _log_counts() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for bot in ("gimba_volatile", "gimba_range", "rts_liquidation", "gimba_trend", "gimba_drive", "gimba_pulse",
                "shadow_volatile", "shadow_trend_recovery"):
        path = LOG_DIR / f"{bot}.jsonl"
        counts[bot] = sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else 0
    return counts


def _event_bar_key(bot_name: str, signal: Dict[str, Any], volume_flow: Dict[str, Any], ts: str) -> str:
    bar_start = volume_flow.get("bar_start")
    if bar_start is not None:
        return str(bar_start)
    if bot_name == "gimba_pulse":
        pulse_bar_start = (signal.get("diagnostics") or {}).get("reference_bar_start")
        if pulse_bar_start is not None:
            return str(pulse_bar_start)
    return str(ts)


def _print_table(results: List[Dict[str, Any]], cycle: int, ts: str) -> None:
    os.system("cls" if os.name == "nt" else "clear")
    counts = _log_counts()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print(f"║ JHL GIMBA SCANNER │ Cycle {cycle:03d} │ {ts} ║")
    print(f"║ Training: GV={counts['gimba_volatile']:>4} GR={counts['gimba_range']:>4} RTS={counts['rts_liquidation']:>4} TRD={counts['gimba_trend']:>4} DRV={counts['gimba_drive']:>4} PUL={counts['gimba_pulse']:>4} ║")
    print(f"║ Shadow:   SV={counts['shadow_volatile']:>4} STR={counts['shadow_trend_recovery']:>3}                                                    ║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    for row in results:
        pair = row["pair"]
        pressure = row.get("volume_flow", {})
        noise = row.get("market_noise") or {}
        status = "READY" if pressure.get("ready") else f"OFF:{pressure.get('reason', 'unknown')}"
        print(f"║ ── {pair} │ PRESSURE {status}")
        if noise.get("available"):
            print(
                f"║    MARKET NOISE {noise.get('regime', '—'):<7} "
                f"SCORE {float(noise.get('noise_score', 0.0)):.2f} [analytics only]"
            )
        else:
            print("║    MARKET NOISE unavailable [analytics only]")
        # Active execution specialists: Range and RTS
        for key, label in (("gimba_range", "RANGE   "), ("rts_liq", "RTS     ")):
            signal = row.get(key, {})
            if not signal:
                continue
            action = str(signal.get("action_state", "idle")).upper()
            knn = f"KNN({signal.get('knn_samples', 0)}) {signal.get('knn_adj', 0.0):+.3f}"
            print(f"║ {label} {signal.get('bias', 'NONE'):<6} {_conviction_bar(float(signal.get('conviction', 0.0)))} {action:<5} {knn}")
            print(f"║ {str(signal.get('setup_type', ''))[:58]}")
        # Training-only Drive specialist
        drv = row.get("gimba_drive", {})
        if drv:
            action = str(drv.get("action_state", "idle")).upper()
            knn = f"KNN({drv.get('knn_samples', 0)}) {drv.get('knn_adj', 0.0):+.3f}"
            print(f"║ DRIVE   {drv.get('bias', 'NONE'):<6} {_conviction_bar(float(drv.get('conviction', 0.0)))} {action:<5} {knn} [TRAINING]")
            print(f"║ {str(drv.get('setup_type', ''))[:58]}")
        pulse = row.get("gimba_pulse", {})
        if pulse:
            print(
                f"║ PULSE   {pulse.get('pulse_state', 'PULSE_DEAD'):<16} "
                f"SCORE {float(pulse.get('pulse_score', 0.0)):.2f} [TRAINING]"
            )
            print(f"║ {str(pulse.get('why', ''))[:58]}")
        # Diagnostic-only context providers (Volatile and Trend)
        for key, label in (("gimba_volatile", "CTX-VOL "), ("gimba_trend", "CTX-TRD ")):
            signal = row.get(key, {})
            if not signal:
                continue
            print(f"║ {label} {signal.get('bias', 'NONE'):<6} [diagnostic context only – no claim routing]")
        # Shadow candidate specialists
        for key, label in (("shadow_volatile", "SHD-VOL "), ("shadow_trend_recovery", "SHD-TRD ")):
            sig = row.get(key, {})
            if not sig:
                continue
            sf = str(sig.get("setup_family", "")).replace("SHADOW_", "")[:28]
            sc = f"{sig.get('score', 0.0):.2f}"
            side = str(sig.get("side", "NONE"))
            print(f"║ {label} {side:<5} SCORE {sc} {sf:<28} [SHADOW]")
        print("║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print(f"Next scan in {SCAN_INTERVAL}s │ Flow candle {FLOW_INTERVAL_MINUTES}m │ Ctrl+C to stop")


def _apply_structure_amplifier(signals: List[Dict[str, Any]], structure: Dict[str, Any]) -> None:
    trend = structure.get("trend", "ranging")
    zone = structure.get("zone", "neutral")
    amp = float(structure.get("amplifier", 1.0))
    counter = float(structure.get("counter_amplifier", 0.70))
    for signal in signals:
        bias = signal.get("bias", "NONE")
        if bias == "NONE" or signal.get("action_state") != "watch":
            continue
        if signal.get("engine") == "GimbaRange":
            multiplier = 1.10 if (bias == "LONG" and zone == "discount") or (bias == "SHORT" and zone == "premium") else 0.65 if (bias == "LONG" and zone == "premium") or (bias == "SHORT" and zone == "discount") else 1.0
        else:
            multiplier = amp if (trend == "up" and bias == "LONG") or (trend == "down" and bias == "SHORT") else counter if (trend == "up" and bias == "SHORT") or (trend == "down" and bias == "LONG") else 1.0
        signal["conviction"] = round(min(float(signal.get("conviction", 0.0)) * multiplier, 1.0), 3)
        signal["structure_amp"] = multiplier


def _fetch_ohlc_arrays(kraken_pair: str, interval: int = 15, limit: int = 60) -> Optional[tuple]:
    """Fetch OHLCV rows from Kraken and return numpy arrays (o, h, l, c, v, last_ts).

    Returns None on error or insufficient data.
    """
    import json as _json
    import numpy as _np

    url = f"https://api.kraken.com/0/public/OHLC?pair={kraken_pair}&interval={interval}"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = _json.loads(r.read())
        if data.get("error"):
            return None
        result = data.get("result", {})
        key = [k for k in result if k != "last"]
        if not key:
            return None
        rows = result[key[0]][-limit:]
        if len(rows) < 30:
            return None
        o = _np.array([float(row[1]) for row in rows], dtype=float)
        h = _np.array([float(row[2]) for row in rows], dtype=float)
        l = _np.array([float(row[3]) for row in rows], dtype=float)
        c = _np.array([float(row[4]) for row in rows], dtype=float)
        v = _np.array([float(row[6]) for row in rows], dtype=float)
        last_ts = int(float(rows[-1][0]))
        return o, h, l, c, v, last_ts
    except Exception:
        return None


def _append_shadow_log(
    bot_name: str, pair: str, signal: Dict[str, Any], ts: str, event_key: str,
    structure: Dict[str, Any], volume_flow: Dict[str, Any],
) -> None:
    """Persist a shadow candidate record to its dedicated JSONL file."""
    if event_key in _SEEN_EVENT_KEYS:
        return
    _SEEN_EVENT_KEYS.add(event_key)
    record = {
        "schema_version": 2,
        "event_key": event_key,
        "ts": ts,
        "pair": pair,
        "bot": bot_name,
        "setup_family": signal.get("setup_family", ""),
        "side": signal.get("side", "NONE"),
        "score": signal.get("score", 0.0),
        "state": signal.get("state", ""),
        "reasons": signal.get("reasons", []),
        "required_inputs": signal.get("required_inputs", []),
        "invalidation_level": signal.get("invalidation_level"),
        "maturity_context": signal.get("maturity_context"),
        "reference_price": signal.get("reference_price"),
        "reference_bar_ts": signal.get("reference_bar_ts"),
        "shadow_mode": signal.get("shadow_mode", True),
        "diagnostic_only": signal.get("diagnostic_only", True),
        "training_only": signal.get("training_only", True),
        "action_state": signal.get("action_state", "observe"),
        "entry": None,
        "sl": None,
        "tp": None,
        "indicators": signal.get("indicators", {}),
        "structure": structure,
        "volume_flow": volume_flow,
        "market_noise": signal.get("market_noise") or market_noise.unavailable("market_noise_missing"),
        "market_timing": signal.get("market_timing") or market_timing.unavailable("market_timing_missing"),
        "outcome": {"status": "pending", "label": None},
    }
    with (LOG_DIR / f"{bot_name}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _attach_market_noise(signal: Dict[str, Any], noise: Dict[str, Any]) -> Dict[str, Any]:
    signal["market_noise"] = dict(noise or market_noise.unavailable("market_noise_missing"))
    return signal


def _attach_market_timing(signal: Dict[str, Any], timing: Dict[str, Any]) -> Dict[str, Any]:
    signal["market_timing"] = dict(timing or market_timing.unavailable("market_timing_missing"))
    return signal


def _evaluate_raw(module, pair: str, kraken_pair: str, fg_score: int) -> Dict[str, Any]:
    """
    Call the specialist's raw evaluator without using its internal KNN wrapper.

    The installed bot files do not all use the same raw evaluator spelling.
    We intentionally do not fall back to evaluate_with_knn(), because the
    scanner must attach structure and volume_flow before KNN is applied.
    """
    for name in ("evaluate_pair", "evaluatepair", "evaluate"):
        fn = getattr(module, name, None)
        if callable(fn):
            return fn(pair, kraken_pair, 0.0, fg_score)

    available = sorted(
        name for name in dir(module)
        if name.startswith("evaluate")
    )
    raise AttributeError(
        f"{module.__name__} has no raw evaluator. "
        f"Found evaluator names: {available}"
    )


def run_cycle(cycle: int, fg_score: int = 50) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    ts = _ts_iso()

    for pair, kraken_pair in PAIRS:
        # 1. Shared structure context
        structure = structure_bias.evaluate(pair, kraken_pair)

        # 2. Completed-candle pressure context
        trades, ohlcv, fetch_error = fetch_bar_data(pair, kraken_pair)
        state = _get_volume_state(pair)

        if fetch_error:
            volume_flow = gimba_volume_flow.unavailable(
                fetch_error,
                FLOW_SOURCE,
            )
        else:
            volume = float(ohlcv.get("volume", 0.0))

            if state["vol_ma"] <= 0:
                state["vol_ma"] = volume
            else:
                state["vol_ma"] = (
                    0.9 * state["vol_ma"]
                    + 0.1 * volume
                )

            volume_flow = gimba_volume_flow.volume_specialist(
                trades_bar=trades,
                ohlcv=ohlcv,
                vol_ma=state["vol_ma"],
                prev_cvd=state["cvd"],
                prev_cvd_window=state["window"],
                cvd_window_size=20,
                source=FLOW_SOURCE,
            )

            if volume_flow.get("ready"):
                state["cvd"] = float(volume_flow["cvd"])
                state["window"] = (
                    state["window"] + [state["cvd"]]
                )[-20:]

        volume_flow["timeframe"] = f"{FLOW_INTERVAL_MINUTES}m"
        volume_flow["bar_start"] = ohlcv.get("bar_start")
        volume_flow["bar_end"] = ohlcv.get("bar_end")

        # 3. Raw specialist evaluation.
        # Do NOT call evaluate_with_knn here.
        gv = _evaluate_raw(
            gimba_volatile,
            pair,
            kraken_pair,
            fg_score,
        )
        gr = _evaluate_raw(
            gimba_range,
            pair,
            kraken_pair,
            fg_score,
        )
        rts = _evaluate_raw(
            rts_liquidation,
            pair,
            kraken_pair,
            fg_score,
        )
        trd = _evaluate_raw(
            gimba_trend,
            pair,
            kraken_pair,
            fg_score,
        )
        pulse = gimba_pulse.evaluate(pair, kraken_pair, 0.0, fg_score)
        # Drive is evaluated with shared structure context to avoid duplicate
        # OHLC fetches and to ensure consistent HTF alignment interpretation.
        drv = gimba_drive.evaluate(pair, kraken_pair, 0.0, fg_score, structure=structure)

        # Shadow candidate specialists — fetch OHLCV arrays once and share.
        # These are always inert (shadow_mode=True, action_state='observe').
        _ohlcv_arrays = _fetch_ohlc_arrays(kraken_pair, interval=15, limit=60)
        _ref_ts = volume_flow.get("bar_start")
        shared_market_noise = market_noise.unavailable(
            "market_noise_fetch_failed",
            reference_bar_start=_ref_ts,
        )
        if _ohlcv_arrays is not None:
            _o, _h, _l, _c, _v, _last_ts = _ohlcv_arrays
            _bar_ts = _ref_ts if _ref_ts is not None else _last_ts
            _noise_ref_ts = _ref_ts if _ref_ts is not None else _last_ts - FLOW_INTERVAL_MINUTES * 60
            shared_market_noise = market_noise.observe(
                _o[:-1],
                _h[:-1],
                _l[:-1],
                _c[:-1],
                _v[:-1],
                reference_bar_start=_noise_ref_ts,
            )
            shd_vol = shadow_gimba_volatile.evaluate_arrays(
                pair, _o, _h, _l, _c, _v, reference_bar_ts=_bar_ts,
            )
            shd_trd = shadow_trend_recovery.evaluate_arrays(
                pair, _o, _h, _l, _c, _v,
                structure_context=structure,
                reference_bar_ts=_bar_ts,
            )
        else:
            shd_vol = shadow_gimba_volatile._null_result(pair, "ohlcv_fetch_failed")
            shd_trd = shadow_trend_recovery._null_result(pair, "ohlcv_fetch_failed")

        # gimba_volatile and gimba_trend are diagnostic context providers only.
        # They must not generate execution eligibility.
        gv["diagnostic_only"] = True
        trd["diagnostic_only"] = True
        # Drive and Pulse are Delta Tempo contributors only; neither has entry authority.
        drv["training_only"] = False
        drv["diagnostic_only"] = False
        pulse["training_only"] = False
        pulse["diagnostic_only"] = False
        # Active execution specialists only (Range, RTS); Drive is training-only.
        exec_signals = [gr, rts]

        # 4. Infer observed market state.
        market_state = market_state_engine.evaluate(
            structure=structure,
            volume_flow=volume_flow,
            signals={
                "gimba_volatile": gv,
                "gimba_range": gr,
                "rts_liq": rts,
                "gimba_trend": trd,
            },
        )

        # 5. Apply structure amplifier to active execution specialists only.
        _apply_structure_amplifier(exec_signals, structure)

        # 6. Apply KNN to active execution specialists and Drive (training).
        for bot_name, signal in zip(
            (
                "gimba_range",
                "rts_liquidation",
                "gimba_drive",
            ),
            exec_signals + [drv],
        ):
            _apply_knn(
                bot_name,
                signal,
                structure,
                volume_flow,
            )

        for signal in (gv, gr, rts, trd, drv, pulse, shd_vol, shd_trd):
            _attach_market_noise(signal, shared_market_noise)

        shared_market_timing = market_timing.observe(
            structure=structure,
            volume_flow=volume_flow,
            market_noise=shared_market_noise,
            market_state=market_state,
            rts_signal=rts,
            range_signal=gr,
        )
        for signal in (gv, gr, rts, trd, drv, pulse, shd_vol, shd_trd):
            _attach_market_timing(signal, shared_market_timing)

        # 6b. Delta Tempo is the sole entry authority. Range, RTS, Drive, and

        # Pulse contribute context and claims only; none emits its own entry card.

        _apply_knn("gimba_pulse", pulse, structure, volume_flow)

        delta_tempo = delta_tempo_prop_router.evaluate(

            pair=pair,

            kraken_pair=kraken_pair,

            volume_flow=volume_flow,

            market_timing=shared_market_timing,

            signals={

                "gimba_range": gr,

                "rts_liq": rts,

                "gimba_drive": drv,

                "gimba_pulse": pulse,

                "delta_tempo": delta_tempo,
            },

            log_dir=LOG_DIR,

        )


        # 7. Log one observation per bot per completed pressure candle.
        for bot_name, signal in zip(
            (
                "gimba_volatile",
                "gimba_range",
                "rts_liquidation",
                "gimba_trend",
                "gimba_drive",
                "gimba_pulse",
            ),
            [gv, gr, rts, trd, drv, pulse],
        ):
            event_key = (
                f"{pair}|{bot_name}|"
                f"{FLOW_INTERVAL_MINUTES}m|{_event_bar_key(bot_name, signal, volume_flow, ts)}"
            )

            _append_training_log(
                bot_name=bot_name,
                pair=pair,
                signal=signal,
                ts=ts,
                event_key=event_key,
                structure=structure,
                diagnostics=signal.get("diagnostics") or {},
                volume_flow=volume_flow,
            )

        # Shadow candidate specialists — dedicated JSONL logs, always [SHADOW].
        for shd_bot, shd_sig in (
            ("shadow_volatile", shd_vol),
            ("shadow_trend_recovery", shd_trd),
        ):
            shd_event_key = (
                f"{pair}|{shd_bot}|"
                f"{FLOW_INTERVAL_MINUTES}m|{_event_bar_key(shd_bot, shd_sig, volume_flow, ts)}"
            )
            _append_shadow_log(
                bot_name=shd_bot,
                pair=pair,
                signal=shd_sig,
                ts=ts,
                event_key=shd_event_key,
                structure=structure,
                volume_flow=volume_flow,
            )

        # 8. Publish the unified row for the scanner, readers, and HTML.
        results.append(
            {
                "pair": pair,
                "gimba_volatile": gv,
                "gimba_range": gr,
                "rts_liq": rts,
                "gimba_trend": trd,
                "gimba_drive": drv,
                "gimba_pulse": pulse,
                "shadow_volatile": shd_vol,
                "shadow_trend_recovery": shd_trd,
                "structure": structure,
                "volume_flow": volume_flow,
                "market_noise": dict(shared_market_noise),
                "market_timing": dict(shared_market_timing),
                "market_state": market_state,
            }
        )

    return results

def main() -> None:
    cycle = 1
    print("Starting JHL Gimba Scanner — 12 pairs, canonical logs active...")
    while True:
        try:
            results = run_cycle(cycle)
            ts = _now()
            _print_table(results, cycle, ts)
            OUTPUT_FILE.write_text(json.dumps({"ts": ts, "cycle": cycle, "signals": results}, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            print(f"\n[ERROR] Cycle {cycle}: {exc}")
        cycle += 1
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScanner stopped.")
