from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"
EPISODES_PATH = LOG_DIR / "episode_context_events.jsonl"
BARS_PATH = LOG_DIR / "episode_5m_bars_v1.jsonl"

KRAKEN_FUTURES_OHLC_URL = "https://futures.kraken.com/api/charts/v1"
TIMEFRAME_MINUTES = 5
LOOKBACK_MINUTES = 180
REQUEST_TIMEOUT_SECONDS = 15


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 10_000_000_000:
            stamp /= 1000
        try:
            return datetime.fromtimestamp(stamp, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None

    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def positive_number(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    return parsed if parsed > 0 else None


def normalize_symbol(value) -> str:
    return str(value or "").upper().replace("-", "").replace("/", "").strip()


def load_jsonl(path: Path):
    rows = []

    if not path.exists():
        return rows

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()

            if not line:
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(row, dict):
                rows.append(row)

    return rows


def event_type(row) -> str:
    return str(
        row.get("event_type")
        or row.get("eventtype")
        or ""
    ).upper()


def episode_id(row, episode) -> str:
    return str(
        episode.get("episode_id")
        or episode.get("episodeid")
        or row.get("episode_id")
        or row.get("episodeid")
        or ""
    ).strip()


def episode_symbol(row, episode) -> str:
    return normalize_symbol(
        episode.get("kraken_symbol")
        or episode.get("krakensymbol")
        or row.get("kraken_symbol")
        or row.get("krakensymbol")
    )


def episode_status(row, episode) -> str:
    return str(
        episode.get("status")
        or row.get("status")
        or ""
    ).upper()


def active_symbols(rows):
    latest = {}

    for row in rows:
        episode = row.get("episode") or {}
        kind = event_type(row)
        identifier = episode_id(row, episode)

        if not identifier:
            continue

        pair = episode_symbol(row, episode)
        status = episode_status(row, episode)

        if kind == "EPISODECLOSE":
            latest[identifier] = {
                "pair": pair,
                "status": "CLOSED",
            }
            continue

        if kind in {"EPISODEOPEN", "EPISODE_UPDATE"} and pair:
            latest[identifier] = {
                "pair": pair,
                "status": status,
            }

    return sorted(
        {
            record["pair"]
            for record in latest.values()
            if record["pair"] and record["status"] == "ACTIVE"
        }
    )


def existing_bar_keys(rows):
    keys = set()

    for row in rows:
        pair = normalize_symbol(
            row.get("kraken_symbol")
            or row.get("krakensymbol")
            or row.get("symbol")
        )
        bar_end = parse_time(
            row.get("bar_end")
            or row.get("barend")
        )

        if pair and bar_end:
            keys.add((pair, bar_end.isoformat()))

    return keys


def fetch_candles(pair: str):
    url = (
        f"https://futures.kraken.com/api/charts/v1/"
        f"trade/{pair}/5m"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "JHL-Episode-Observer/1.0"},
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))

    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        print(f"{pair}: fetch failed: {exc}")
        return []

    candles = (
        payload.get("candles")
        or payload.get("data")
        or payload.get("result")
        or []
    )

    if isinstance(candles, dict):
        candles = (
            candles.get("candles")
            or candles.get("data")
            or []
        )

    return candles if isinstance(candles, list) else []

def candle_to_bar(pair: str, candle):
    if isinstance(candle, dict):
        stamp = (
            candle.get("time")
            or candle.get("timestamp")
            or candle.get("t")
            or candle.get("startTime")
        )
        opened = candle.get("open") or candle.get("o")
        high = candle.get("high") or candle.get("h")
        low = candle.get("low") or candle.get("l")
        close = candle.get("close") or candle.get("c")
        volume = candle.get("volume") or candle.get("v")

    elif isinstance(candle, (list, tuple)) and len(candle) >= 5:
        stamp, opened, high, low, close = candle[:5]
        volume = candle[5] if len(candle) > 5 else None

    else:
        return None

    bar_start = parse_time(stamp)
    opened = positive_number(opened)
    high = positive_number(high)
    low = positive_number(low)
    close = positive_number(close)

    if not bar_start or None in (opened, high, low, close):
        return None

    bar_end = datetime.fromtimestamp(
        bar_start.timestamp() + TIMEFRAME_MINUTES * 60,
        tz=timezone.utc,
    )

    return {
        "recordtype": "EPISODE5MBAR",
        "schemaversion": "episode5mbarv1",
        "observationonly": True,
        "doesnotauthorizetrade": True,
        "doesnotchangequeue": True,
        "kraken_symbol": pair,
        "krakensymbol": pair,
        "symbol": pair,
        "bar_start": bar_start.isoformat(),
        "barstart": bar_start.isoformat(),
        "bar_end": bar_end.isoformat(),
        "barend": bar_end.isoformat(),
        "open": opened,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "source": "kraken_futures_ohlc",
        "written_at_utc": now_utc().isoformat(),
    }


def main():
    if not EPISODES_PATH.exists():
        raise SystemExit(f"Missing episode event log: {EPISODES_PATH}")

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    episode_rows = load_jsonl(EPISODES_PATH)
    pairs = active_symbols(episode_rows)

    print(f"Episode log: {EPISODES_PATH}")
    print(f"Rows read: {len(episode_rows)}")
    print(f"Active episode symbols: {len(pairs)}")

    if not pairs:
        print("No active episode symbols found. Nothing to collect.")
        return

    existing = existing_bar_keys(load_jsonl(BARS_PATH))
    cutoff_epoch = now_utc().timestamp() - LOOKBACK_MINUTES * 60
    current_time = now_utc()

    new_rows = []
    seen_this_run = set()

    for pair in pairs:
        candles = fetch_candles(pair)
        print(f"{pair}: candles received {len(candles)}")

        for candle in candles:
            row = candle_to_bar(pair, candle)

            if not row:
                continue

            bar_start = parse_time(row["bar_start"])
            bar_end = parse_time(row["bar_end"])
            key = (pair, bar_end.isoformat())

            if bar_start.timestamp() < cutoff_epoch:
                continue

            if bar_end > current_time:
                continue

            if key in existing or key in seen_this_run:
                continue

            seen_this_run.add(key)
            new_rows.append(row)

        time.sleep(0.25)

    new_rows.sort(
        key=lambda row: (
            row["kraken_symbol"],
            row["bar_end"],
        )
    )

    if new_rows:
        with BARS_PATH.open("a", encoding="utf-8") as handle:
            for row in new_rows:
                handle.write(
                    json.dumps(row, separators=(",", ":")) + "\n"
                )

    print(f"New completed 5m bars written: {len(new_rows)}")
    print(f"Bar ledger: {BARS_PATH}")


if __name__ == "__main__":
    main()

