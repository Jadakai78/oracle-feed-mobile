"""
kraken_btcc_top3_queue.py — JHL Holdings LLC

Live-money research queue:
- Reads BTCC-active ↔ Kraken-covered mappings.
- Uses Kraken Futures USD ticker data for research only.
- Holds at most three candidates.
- Requires a five-minute price baseline before ranking.
- Uses Pushover only for admission, drop, and replacement events.
- Never sends orders or calls any BTCC execution endpoint.

Required .env keys:
PUSHOVER_USER_KEY
PUSHOVER_API_TOKEN
TEST_ALERTS=true|false
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"
COVERAGE_PATH = LOG_DIR / "btcc_kraken_coverage_audit.json"
STATE_PATH = LOG_DIR / "kraken_btcc_top3_queue_state.json"
AUDIT_PATH = LOG_DIR / "kraken_btcc_top3_queue_audit.jsonl"
ENV_PATH = ROOT / ".env"

KRAKEN_TICKERS_URL = "https://futures.kraken.com/derivatives/api/v3/tickers"
DATA_VENUE = "KRAKEN_FUTURES"
EXECUTION_VENUE = "BTCC"

WINDOW_SECONDS = 300
MOVE_THRESHOLD_PCT = 1.0
MAX_QUEUE_SIZE = 3
RETENTION_SCORE_FLOOR = 0.70
RETRACE_FROM_FAVORABLE_EXTREME_PCT = 0.50
MAX_CANDIDATE_AGE_SECONDS = 1800
MAX_DATA_AGE_SECONDS = 90
REQUEST_TIMEOUT_SECONDS = 15


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env_keys(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_true(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def append_audit(event: Dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, default=str) + "\n")


def fetch_kraken_tickers() -> Dict[str, Dict[str, Any]]:
    request = urllib.request.Request(
        KRAKEN_TICKERS_URL,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "JHL-KrakenBTCC-Top3Queue/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from Kraken tickers: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Kraken ticker URL error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Kraken ticker JSON parse error: {exc}") from exc

    if payload.get("result") != "success":
        raise RuntimeError(f"Kraken ticker result was {payload.get('result')!r}")

    indexed: Dict[str, Dict[str, Any]] = {}
    for row in payload.get("tickers") or []:
        symbol = str(row.get("symbol") or "").upper()
        try:
            last = float(row.get("last"))
            mark = float(row.get("markPrice"))
            bid = float(row.get("bid"))
            ask = float(row.get("ask"))
        except (TypeError, ValueError):
            continue

        if last <= 0 or mark <= 0 or bid <= 0 or ask <= 0:
            continue
        if row.get("suspended") is True:
            continue

        indexed[symbol] = {
            "symbol": symbol,
            "last": last,
            "mark_price": mark,
            "bid": bid,
            "ask": ask,
            "source_timestamp_utc": row.get("lastTime"),
            "fetched_at_utc": utc_now_iso(),
        }

    return indexed


def load_coverage() -> List[Dict[str, Any]]:
    audit = read_json(COVERAGE_PATH, {})
    rows = audit.get("included") if isinstance(audit, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(
            f"Coverage audit missing or empty: {COVERAGE_PATH}. "
            "Run btcc_kraken_coverage_mapper.py first."
        )
    return rows


def initial_state() -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "created_at_utc": utc_now_iso(),
        "last_run_at_utc": None,
        "price_history": {},
        "queue": [],
    }


def load_state() -> Dict[str, Any]:
    state = read_json(STATE_PATH, initial_state())
    if not isinstance(state, dict):
        return initial_state()
    state.setdefault("schema_version", "1.0")
    state.setdefault("price_history", {})
    state.setdefault("queue", [])
    return state


def epoch_now() -> float:
    return time.time()


def price_history_for(
    state: Dict[str, Any],
    kraken_symbol: str,
) -> Deque[Tuple[float, float]]:
    raw_history = state["price_history"].get(kraken_symbol, [])
    cleaned: Deque[Tuple[float, float]] = deque()

    for row in raw_history:
        try:
            timestamp = float(row[0])
            price = float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        cleaned.append((timestamp, price))

    return cleaned


def candidate_score(
    history: Deque[Tuple[float, float]],
    current_price: float,
    now_epoch: float,
) -> Tuple[float | None, float | None]:
    eligible = [
        (timestamp, price)
        for timestamp, price in history
        if timestamp <= now_epoch - WINDOW_SECONDS
    ]
    if not eligible:
        return None, None

    baseline_timestamp, baseline_price = eligible[-1]
    if baseline_price <= 0:
        return None, None

    move_pct = ((current_price - baseline_price) / baseline_price) * 100.0
    return move_pct, baseline_timestamp


def queue_lookup(queue: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        str(item.get("kraken_symbol") or "").upper(): item
        for item in queue
        if item.get("kraken_symbol")
    }


def alert_text(event_type: str, candidate: Dict[str, Any], reason: str = "") -> Tuple[str, str]:
    direction = candidate.get("direction", "UNKNOWN")
    title = f"TOP-3 {event_type} — {candidate.get('btcc_symbol', '?')} {direction}"

    lines = [
        f"BTCC symbol: {candidate.get('btcc_symbol', '?')}",
        f"Research: Kraken Futures {candidate.get('kraken_symbol', '?')} USD",
        f"Direction: {direction}",
        f"Kraken last: {candidate.get('last_price', '?')}",
        f"5m move: {candidate.get('score_pct', 0.0):+.2f}%",
        f"Reason: {reason or event_type}",
        "",
        "Execution venue: BTCC USDT-M perpetual — MANUAL ONLY.",
        "Before entry: verify BTCC contract active, live price, funding,",
        "spread/depth, and liquidation safety.",
        "Kraken values are research data, not BTCC execution values.",
    ]
    return title, "\n".join(lines)


def send_or_preview(
    env: Dict[str, str],
    event_type: str,
    candidate: Dict[str, Any],
    reason: str,
) -> None:
    title, message = alert_text(event_type, candidate, reason)
    test_mode = env_true(env.get("TEST_ALERTS", "true"))

    if test_mode:
        print(f"\n[TEST ALERT] {title}\n{message}\n")
        return

    user_key = env.get("PUSHOVER_USER_KEY", "")
    api_token = env.get("PUSHOVER_API_TOKEN", "")
    if not user_key or not api_token:
        print(f"[NOT SENT] {title} — missing Pushover key(s).")
        return

    body = urllib.parse.urlencode(
        {
            "token": api_token,
            "user": user_key,
            "title": title,
            "message": message,
            "priority": "0",
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.pushover.net/1/messages.json",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
        if payload.get("status") != 1:
            raise RuntimeError(f"Pushover status={payload.get('status')}")
        print(f"[PUSHOVER SENT] {title}")
    except Exception as exc:
        print(f"[PUSHOVER FAILED] {title}: {exc}")


def make_candidate(
    mapping: Dict[str, Any],
    ticker: Dict[str, Any],
    score_pct: float,
    now_epoch: float,
) -> Dict[str, Any]:
    direction = "UP" if score_pct > 0 else "DOWN"
    last_price = float(ticker["last"])

    return {
        "btcc_symbol": mapping.get("btcc_symbol"),
        "kraken_symbol": mapping.get("kraken_symbol"),
        "data_venue": DATA_VENUE,
        "execution_venue": EXECUTION_VENUE,
        "data_quote_currency": "USD",
        "execution_quote_currency": "USDT",
        "quote_mismatch": "KRAKEN_USD__BTCC_USDT",
        "direction": direction,
        "score_pct": round(score_pct, 6),
        "admission_score_abs_pct": round(abs(score_pct), 6),
        "last_price": last_price,
        "mark_price": float(ticker["mark_price"]),
        "best_bid": float(ticker["bid"]),
        "best_ask": float(ticker["ask"]),
        "admitted_at_epoch": now_epoch,
        "admitted_at_utc": utc_now_iso(),
        "favorable_extreme_price": last_price,
        "last_seen_epoch": now_epoch,
        "last_seen_utc": utc_now_iso(),
    }


def update_candidate(
    candidate: Dict[str, Any],
    ticker: Dict[str, Any],
    score_pct: float,
    now_epoch: float,
) -> Tuple[bool, str]:
    current_price = float(ticker["last"])
    candidate["last_price"] = current_price
    candidate["mark_price"] = float(ticker["mark_price"])
    candidate["best_bid"] = float(ticker["bid"])
    candidate["best_ask"] = float(ticker["ask"])
    candidate["score_pct"] = round(score_pct, 6)
    candidate["last_seen_epoch"] = now_epoch
    candidate["last_seen_utc"] = utc_now_iso()

    direction = candidate.get("direction")
    admission_abs = float(candidate.get("admission_score_abs_pct", 0.0))
    current_abs = abs(score_pct)

    if direction == "UP":
        candidate["favorable_extreme_price"] = max(
            float(candidate.get("favorable_extreme_price", current_price)),
            current_price,
        )
        extreme = float(candidate["favorable_extreme_price"])
        retrace_pct = ((extreme - current_price) / extreme) * 100.0 if extreme > 0 else 0.0
    else:
        candidate["favorable_extreme_price"] = min(
            float(candidate.get("favorable_extreme_price", current_price)),
            current_price,
        )
        extreme = float(candidate["favorable_extreme_price"])
        retrace_pct = ((current_price - extreme) / extreme) * 100.0 if extreme > 0 else 0.0

    age_seconds = now_epoch - float(candidate.get("admitted_at_epoch", now_epoch))

    if current_abs < admission_abs * RETENTION_SCORE_FLOOR:
        return True, "SCORE_DEGRADED_BELOW_70_PERCENT_OF_ADMISSION"
    if retrace_pct >= RETRACE_FROM_FAVORABLE_EXTREME_PCT:
        return True, "RETRACED_0.50_PERCENT_FROM_FAVORABLE_EXTREME"
    if age_seconds >= MAX_CANDIDATE_AGE_SECONDS:
        return True, "CANDIDATE_EXPIRED_30_MINUTES_WITHOUT_MANUAL_ACTION"

    return False, ""


def main() -> int:
    env = load_env_keys(ENV_PATH)
    test_mode = env_true(env.get("TEST_ALERTS", "true"))

    if not ENV_PATH.exists():
        print(f"FAIL: .env not found: {ENV_PATH}")
        return 1

    if not test_mode and (
        not env.get("PUSHOVER_USER_KEY") or not env.get("PUSHOVER_API_TOKEN")
    ):
        print("FAIL: TEST_ALERTS=false but PUSHOVER_USER_KEY or PUSHOVER_API_TOKEN is missing.")
        return 1

    try:
        coverage = load_coverage()
        tickers = fetch_kraken_tickers()
    except Exception as exc:
        print(f"FAIL: input fetch: {type(exc).__name__}: {exc}")
        return 1

    now = epoch_now()
    state = load_state()
    queue: List[Dict[str, Any]] = list(state.get("queue") or [])
    queue_by_symbol = queue_lookup(queue)
    mappings_by_kraken = {
        str(row.get("kraken_symbol") or "").upper(): row
        for row in coverage
        if row.get("kraken_symbol")
    }

    scored: List[Tuple[float, Dict[str, Any], Dict[str, Any]]] = []
    fresh_symbols = 0

    for kraken_symbol, mapping in mappings_by_kraken.items():
        ticker = tickers.get(kraken_symbol)
        if not ticker:
            continue

        fresh_symbols += 1
        history = price_history_for(state, kraken_symbol)
        history.append((now, float(ticker["last"])))

        retention_floor = now - (WINDOW_SECONDS + 90)
        while history and history[0][0] < retention_floor:
            history.popleft()

        state["price_history"][kraken_symbol] = list(history)
        move_pct, _ = candidate_score(history, float(ticker["last"]), now)

        if move_pct is not None and abs(move_pct) >= MOVE_THRESHOLD_PCT:
            scored.append((abs(move_pct), mapping, ticker))
            mapping["_current_score_pct"] = move_pct

    dropped: List[Tuple[Dict[str, Any], str]] = []
    retained: List[Dict[str, Any]] = []

    for candidate in queue:
        kraken_symbol = str(candidate.get("kraken_symbol") or "").upper()
        ticker = tickers.get(kraken_symbol)
        mapping = mappings_by_kraken.get(kraken_symbol)

        if not ticker or not mapping:
            dropped.append((candidate, "DATA_UNAVAILABLE_OR_MAPPING_REMOVED"))
            continue

        history = price_history_for(state, kraken_symbol)
        move_pct, _ = candidate_score(history, float(ticker["last"]), now)

        if move_pct is None:
            age = now - float(candidate.get("last_seen_epoch", now))
            if age > MAX_DATA_AGE_SECONDS:
                dropped.append((candidate, "STALE_PRICE_HISTORY"))
            else:
                retained.append(candidate)
            continue

        should_drop, reason = update_candidate(candidate, ticker, move_pct, now)
        if should_drop:
            dropped.append((candidate, reason))
        else:
            retained.append(candidate)

    for candidate, reason in dropped:
        event = {
            "event_type": "DROP",
            "timestamp_utc": utc_now_iso(),
            "reason": reason,
            "candidate": candidate,
            "test_mode": test_mode,
        }
        append_audit(event)
        send_or_preview(env, "DROP", candidate, reason)

    retained_symbols = {
        str(candidate.get("kraken_symbol") or "").upper()
        for candidate in retained
    }

    scored.sort(key=lambda item: item[0], reverse=True)
    admitted: List[Dict[str, Any]] = []

    for _, mapping, ticker in scored:
        if len(retained) >= MAX_QUEUE_SIZE:
            break

        kraken_symbol = str(mapping.get("kraken_symbol") or "").upper()
        if kraken_symbol in retained_symbols:
            continue

        score_pct = float(mapping.get("_current_score_pct", 0.0))
        candidate = make_candidate(mapping, ticker, score_pct, now)
        retained.append(candidate)
        retained_symbols.add(kraken_symbol)
        admitted.append(candidate)

        event_type = "REPLACEMENT" if dropped else "ADMISSION"
        event = {
            "event_type": event_type,
            "timestamp_utc": utc_now_iso(),
            "reason": "ABS_5M_MOVE_AT_OR_ABOVE_1_PERCENT",
            "candidate": candidate,
            "test_mode": test_mode,
        }
        append_audit(event)
        send_or_preview(env, event_type, candidate, "ABS_5M_MOVE_AT_OR_ABOVE_1_PERCENT")

    state["queue"] = retained
    state["last_run_at_utc"] = utc_now_iso()
    write_json_atomic(STATE_PATH, state)

    print(f"Mode: {'TEST / no Pushover sends' if test_mode else 'LIVE Pushover enabled'}")
    print(f"Mapped assets: {len(mappings_by_kraken)}")
    print(f"Fresh Kraken tickers: {fresh_symbols}")
    print(f"Scored moves >= {MOVE_THRESHOLD_PCT:.2f}%: {len(scored)}")
    print(f"Dropped this run: {len(dropped)}")
    print(f"Admitted this run: {len(admitted)}")
    print(f"Active top-3 queue: {len(retained)}/{MAX_QUEUE_SIZE}")

    if retained:
        print("Queue:")
        for index, candidate in enumerate(retained, start=1):
            print(
                f" {index}. {candidate['btcc_symbol']} <- {candidate['kraken_symbol']} "
                f"{candidate['direction']} {candidate['score_pct']:+.2f}% "
                f"last={candidate['last_price']}"
            )
    else:
        print("Queue: empty — collecting 5-minute baseline or no qualifying moves.")

    print(f"State: {STATE_PATH}")
    print(f"Audit: {AUDIT_PATH}")
    print("RESULT: PASS — observation queue cycle complete; no orders were sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
