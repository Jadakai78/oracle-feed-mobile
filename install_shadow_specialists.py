from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

SRC = Path(r"C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl-market-edge-drive\gimba")
DST = Path(r"C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba")

NEW_FILES = (
    "shadow_gimba_volatile.py",
    "shadow_trend_recovery.py",
    "shadow_utils.py",
    "shadow_scoreboard.py",
    "test_shadow_candidates.py",
)


def require_replace(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Patch anchor not found: {label}. Nothing was changed.")
    return text.replace(old, new, 1)


def backup(path: Path) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, path.with_name(f"{path.name}.{stamp}.bak"))


def patch_scanner(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = require_replace(
        text,
        "import market_state_engine\n",
        "import market_state_engine\nimport shadow_gimba_volatile\nimport shadow_trend_recovery\n",
        "scanner imports",
    )
    text = require_replace(
        text,
        'for bot in ("gimba_volatile", "gimba_range", "rts_liquidation", "gimba_trend", "gimba_drive", "gimba_pulse"):',
        'for bot in ("gimba_volatile", "gimba_range", "rts_liquidation", "gimba_trend", "gimba_drive", "gimba_pulse",\n                "shadow_volatile", "shadow_trend_recovery"):',
        "scanner log counts",
    )
    text = require_replace(
        text,
        "    print(f\"║ Training: GV={counts['gimba_volatile']:>4} GR={counts['gimba_range']:>4} RTS={counts['rts_liquidation']:>4} TRD={counts['gimba_trend']:>4} DRV={counts['gimba_drive']:>4} PUL={counts['gimba_pulse']:>4} ║\")\n",
        "    print(f\"║ Training: GV={counts['gimba_volatile']:>4} GR={counts['gimba_range']:>4} RTS={counts['rts_liquidation']:>4} TRD={counts['gimba_trend']:>4} DRV={counts['gimba_drive']:>4} PUL={counts['gimba_pulse']:>4} ║\")\n"
        "    print(f\"║ Shadow:   SV={counts['shadow_volatile']:>4} STR={counts['shadow_trend_recovery']:>3}                                                    ║\")\n",
        "scanner shadow header",
    )
    text = require_replace(
        text,
        "        print(\"║\")\n    print(\"╚══════════════════════════════════════════════════════════════════╝\")\n",
        "        for key, label in ((\"shadow_volatile\", \"SHD-VOL \"), (\"shadow_trend_recovery\", \"SHD-TRD \")):\n"
        "            sig = row.get(key, {})\n"
        "            if not sig:\n"
        "                continue\n"
        "            family = str(sig.get(\"setup_family\", \"\")).replace(\"SHADOW_\", \"\")[:28]\n"
        "            score = f\"{sig.get('score', 0.0):.2f}\"\n"
        "            side = str(sig.get(\"side\", \"NONE\"))\n"
        "            print(f\"║ {label} {side:<5} SCORE {score} {family:<28} [SHADOW]\")\n"
        "        print(\"║\")\n    print(\"╚══════════════════════════════════════════════════════════════════╝\")\n",
        "scanner shadow display",
    )
    helpers = '''\n\ndef _fetch_ohlc_arrays(kraken_pair: str, interval: int = 15, limit: int = 60) -> Optional[tuple]:\n    \"\"\"Fetch completed Kraken OHLCV bars as numpy arrays for shadow observers.\"\"\"\n    import numpy as np\n\n    try:\n        result = _request(\"/OHLC\", {\"pair\": kraken_pair, \"interval\": interval})\n        rows = _result_rows(result)\n        # Kraken includes an unfinished final candle; exclude it.\n        rows = rows[-(limit + 1):-1]\n        if len(rows) < 30:\n            return None\n        o = np.array([float(row[1]) for row in rows], dtype=float)\n        h = np.array([float(row[2]) for row in rows], dtype=float)\n        l = np.array([float(row[3]) for row in rows], dtype=float)\n        c = np.array([float(row[4]) for row in rows], dtype=float)\n        v = np.array([float(row[6]) for row in rows], dtype=float)\n        return o, h, l, c, v, int(float(rows[-1][0]))\n    except Exception:\n        return None\n\n\ndef _append_shadow_log(\n    bot_name: str, pair: str, signal: Dict[str, Any], ts: str, event_key: str,\n    structure: Dict[str, Any], volume_flow: Dict[str, Any],\n) -> None:\n    \"\"\"Write an inert shadow record to its dedicated JSONL log.\"\"\"\n    if event_key in _SEEN_EVENT_KEYS:\n        return\n    _SEEN_EVENT_KEYS.add(event_key)\n    record = {\n        \"schema_version\": 2,\n        \"event_key\": event_key,\n        \"ts\": ts,\n        \"pair\": pair,\n        \"bot\": bot_name,\n        \"setup_family\": signal.get(\"setup_family\", \"\"),\n        \"side\": signal.get(\"side\", \"NONE\"),\n        \"score\": signal.get(\"score\", 0.0),\n        \"state\": signal.get(\"state\", \"\"),\n        \"reasons\": signal.get(\"reasons\", []),\n        \"required_inputs\": signal.get(\"required_inputs\", []),\n        \"invalidation_level\": signal.get(\"invalidation_level\"),\n        \"maturity_context\": signal.get(\"maturity_context\"),\n        \"reference_price\": signal.get(\"reference_price\"),\n        \"reference_bar_ts\": signal.get(\"reference_bar_ts\"),\n        \"shadow_mode\": True,\n        \"diagnostic_only\": True,\n        \"training_only\": True,\n        \"action_state\": \"observe\",\n        \"entry\": None,\n        \"sl\": None,\n        \"tp\": None,\n        \"indicators\": signal.get(\"indicators\", {}),\n        \"structure\": structure,\n        \"volume_flow\": volume_flow,\n        \"outcome\": {\"status\": \"pending\", \"label\": None},\n    }\n    with (LOG_DIR / f\"{bot_name}.jsonl\").open(\"a\", encoding=\"utf-8\") as handle:\n        handle.write(json.dumps(record, ensure_ascii=False) + \"\\n\")\n\n'''
    text = require_replace(text, "\ndef _evaluate_raw(", helpers + "\ndef _evaluate_raw(", "scanner shadow helpers")
    text = require_replace(
        text,
        "        drv = gimba_drive.evaluate(pair, kraken_pair, 0.0, fg_score, structure=structure)\n",
        "        drv = gimba_drive.evaluate(pair, kraken_pair, 0.0, fg_score, structure=structure)\n\n"
        "        shadow_arrays = _fetch_ohlc_arrays(kraken_pair, interval=15, limit=60)\n"
        "        reference_bar_ts = volume_flow.get(\"bar_start\")\n"
        "        if shadow_arrays is not None:\n"
        "            o, h, l, c, v, last_ts = shadow_arrays\n"
        "            reference_bar_ts = reference_bar_ts or last_ts\n"
        "            shd_vol = shadow_gimba_volatile.evaluate_arrays(pair, o, h, l, c, v, reference_bar_ts=reference_bar_ts)\n"
        "            shd_trd = shadow_trend_recovery.evaluate_arrays(pair, o, h, l, c, v, structure_context=structure, reference_bar_ts=reference_bar_ts)\n"
        "        else:\n"
        "            shd_vol = shadow_gimba_volatile._null_result(pair, \"ohlcv_fetch_failed\")\n"
        "            shd_trd = shadow_trend_recovery._null_result(pair, \"ohlcv_fetch_failed\")\n",
        "scanner shadow evaluation",
    )
    text = require_replace(
        text,
        "        # 8. Publish the unified row for the scanner, readers, and HTML.\n",
        "        for shadow_bot, shadow_signal in ((\"shadow_volatile\", shd_vol), (\"shadow_trend_recovery\", shd_trd)):\n"
        "            shadow_key = f\"{pair}|{shadow_bot}|{FLOW_INTERVAL_MINUTES}m|{_event_bar_key(shadow_bot, shadow_signal, volume_flow, ts)}\"\n"
        "            _append_shadow_log(shadow_bot, pair, shadow_signal, ts, shadow_key, structure, volume_flow)\n\n"
        "        # 8. Publish the unified row for the scanner, readers, and HTML.\n",
        "scanner shadow logging",
    )
    text = require_replace(
        text,
        '                "gimba_pulse": pulse,\n',
        '                "gimba_pulse": pulse,\n                "shadow_volatile": shd_vol,\n                "shadow_trend_recovery": shd_trd,\n',
        "scanner result publication",
    )
    path.write_text(text, encoding="utf-8")


def patch_outcome_evaluator(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = require_replace(
        text,
        '"gimba_pulse",\n)',
        '"gimba_pulse",\n    "shadow_volatile",\n    "shadow_trend_recovery",\n)',
        "outcome BOT_LOGS",
    )
    helpers = '''\n\ndef _shadow_horizon(\n    candles: List[List[Any]],\n    reference_price: float,\n    side: str,\n    invalidation_level: Optional[float],\n) -> Dict[str, Any]:\n    if not candles or reference_price == 0:\n        return {}\n    divisor = max(abs(reference_price), 1e-9)\n    highs = [float(row[2]) for row in candles]\n    lows = [float(row[3]) for row in candles]\n    closes = [reference_price] + [float(row[4]) for row in candles]\n    final_close = float(candles[-1][4])\n    raw_return = (final_close - reference_price) / divisor\n    direction = 1.0 if side == \"LONG\" else -1.0 if side == \"SHORT\" else 0.0\n    net_return = raw_return * direction if direction else raw_return\n    path = sum(abs(right - left) for left, right in zip(closes, closes[1:]))\n    efficiency = abs(final_close - reference_price) / path if path else 0.0\n    if side == \"LONG\":\n        mfe = max((high - reference_price) / divisor for high in highs)\n        mae = min(0.0, min((low - reference_price) / divisor for low in lows))\n    elif side == \"SHORT\":\n        mfe = max((reference_price - low) / divisor for low in lows)\n        mae = min(0.0, min((reference_price - high) / divisor for high in highs))\n    else:\n        mfe = max(abs(high - reference_price) / divisor for high in highs)\n        mae = 0.0\n    hold_fail = None\n    if invalidation_level is not None and side in {\"LONG\", \"SHORT\"}:\n        violated = any(float(row[3]) < invalidation_level for row in candles) if side == \"LONG\" else any(float(row[2]) > invalidation_level for row in candles)\n        hold_fail = \"FAILED\" if violated else \"HELD\"\n    return {\n        \"net_directional_return\": round(net_return, 6),\n        \"realized_range\": round((max(highs) - min(lows)) / divisor, 6),\n        \"directional_efficiency\": round(efficiency, 6),\n        \"mfe\": round(mfe, 6),\n        \"mae\": round(mae, 6),\n        \"hold_fail\": hold_fail,\n    }\n\n\ndef _resolve_shadow(record: Dict[str, Any], now_epoch: int) -> Optional[Dict[str, Any]]:\n    current = record.get(\"outcome\") or {}\n    if str(current.get(\"status\") or \"\").lower() == \"resolved\" and isinstance(current.get(\"horizons\"), dict) and \"16bar\" in current[\"horizons\"]:\n        return None\n    observed = _parse_ts(record.get(\"ts\"))\n    reference_price = _number(record.get(\"reference_price\"))\n    reference_bar_ts = record.get(\"reference_bar_ts\")\n    if observed is None or reference_price is None:\n        return {\"status\": \"resolved\", \"label\": None, \"reason\": \"shadow_missing_reference_price_or_ts\", \"evaluated_at\": datetime.now(timezone.utc).isoformat()}\n    start_epoch = int(reference_bar_ts) if reference_bar_ts is not None else int(observed.timestamp() // (INTERVAL_MINUTES * 60) * (INTERVAL_MINUTES * 60))\n    if now_epoch < start_epoch + INTERVAL_MINUTES * 60:\n        return None\n    try:\n        rows = _ohlc(str(record.get(\"pair\")), start_epoch)\n    except Exception as exc:\n        return {\"status\": \"pending\", \"label\": None, \"reason\": f\"evaluator_fetch_error:{type(exc).__name__}\"}\n    candles = [row for row in rows if len(row) >= 5 and int(float(row[0])) > start_epoch]\n    if not candles:\n        return None\n    side = str(record.get(\"side\") or \"NONE\").upper()\n    invalidation_level = _number(record.get(\"invalidation_level\"))\n    horizons: Dict[str, Any] = {}\n    for label, count in ((\"15m\", 1), (\"30m\", 2), (\"60m\", 4), (\"16bar\", HORIZON_BARS)):\n        if len(candles) >= count:\n            horizons[label] = _shadow_horizon(candles[:count], reference_price, side, invalidation_level)\n    if not horizons:\n        return None\n    return {\n        \"status\": \"resolved\" if \"16bar\" in horizons else \"pending\",\n        \"label\": None,\n        \"reason\": \"shadow_candidate_forward_metrics\",\n        \"evaluated_at\": datetime.now(timezone.utc).isoformat(),\n        \"setup_family\": record.get(\"setup_family\") or record.get(\"setup_type\"),\n        \"side\": side,\n        \"horizons\": horizons,\n    }\n\n'''
    text = require_replace(text, "\ndef _resolve(record", helpers + "\ndef _resolve(record", "outcome shadow helpers")
    text = require_replace(
        text,
        '    if str(record.get("bot") or "") == "gimba_pulse":\n        return _resolve_pulse(record, now_epoch)\n',
        '    bot = str(record.get("bot") or "")\n    if bot == "gimba_pulse":\n        return _resolve_pulse(record, now_epoch)\n    if bot in ("shadow_volatile", "shadow_trend_recovery"):\n        return _resolve_shadow(record, now_epoch)\n',
        "outcome shadow dispatch",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if not SRC.is_dir() or not DST.is_dir():
        raise SystemExit(f"Source or destination folder is missing:\n{SRC}\n{DST}")
    for name in NEW_FILES:
        source = SRC / name
        if not source.exists():
            raise SystemExit(f"Missing source file: {source}")
    for name in ("scanner.py", "outcome_evaluator.py"):
        if not (DST / name).exists():
            raise SystemExit(f"Missing destination file: {DST / name}")

    for name in ("scanner.py", "outcome_evaluator.py"):
        backup(DST / name)
    for name in NEW_FILES:
        shutil.copy2(SRC / name, DST / name)

    patch_scanner(DST / "scanner.py")
    patch_outcome_evaluator(DST / "outcome_evaluator.py")
    print("Installed shadow modules and patched scanner.py/outcome_evaluator.py.")
    print("Backups were created beside the two patched files with a .bak suffix.")
    print("Next: run the shadow test suite from the destination folder before starting the scanner.")


if __name__ == "__main__":
    main()
