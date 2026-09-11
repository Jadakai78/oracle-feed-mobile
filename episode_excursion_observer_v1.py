from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"

EPISODES_PATH = LOG_DIR / "episode_context_events.jsonl"
BARS_PATH = LOG_DIR / "episode_5m_bars_v1.jsonl"
OUTCOMES_PATH = LOG_DIR / "episode_excursion_outcomes_v1.jsonl"

HORIZONS = (12, 24)  # 5m bars: 60m and 120m
BRACKETS = (
    {"name": "FWD_1.0_BACK_0.5", "forward_pct": 1.0, "backward_pct": 0.5},
    {"name": "FWD_1.5_BACK_0.5", "forward_pct": 1.5, "backward_pct": 0.5},
)


def parse_time(value):
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_symbol(value):
    return str(value or "").upper().replace("-", "").replace("_", "").replace("/", "")


def load_jsonl(path):
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


def episode_opens(rows):
    opened = {}
    for row in rows:
        if str(row.get("eventtype", "")).upper() != "EPISODEOPEN":
            continue

        episode = row.get("episode") or {}
        episode_id = episode.get("episodeid") or row.get("episodeid")
        symbol = episode.get("krakensymbol") or row.get("krakensymbol")
        direction = episode.get("direction") or row.get("direction")
        reference = episode.get("referenceprice") or row.get("referenceprice")
        started = episode.get("startedatutc") or row.get("timestamputc")

        reference = number(reference)
        started = parse_time(started)

        if not episode_id or not symbol or direction not in ("UP", "DOWN"):
            continue
        if reference is None or reference <= 0 or started is None:
            continue

        opened[str(episode_id)] = {
            "episode_id": str(episode_id),
            "symbol": normalize_symbol(symbol),
            "direction": str(direction).upper(),
            "reference_price": reference,
            "started_at": started,
        }
    return opened


def load_bars(rows):
    bars_by_symbol = defaultdict(list)

    for row in rows:
        symbol = normalize_symbol(row.get("symbol") or row.get("pair") or row.get("krakensymbol"))
        start = parse_time(row.get("barstart") or row.get("bar_start") or row.get("start"))
        end = parse_time(row.get("barend") or row.get("bar_end") or row.get("end"))
        high = number(row.get("high"))
        low = number(row.get("low"))
        close = number(row.get("close"))

        if not symbol or start is None or end is None:
            continue
        if high is None or low is None or close is None:
            continue

        bars_by_symbol[symbol].append(
            {"start": start, "end": end, "high": high, "low": low, "close": close}
        )

    for symbol in bars_by_symbol:
        deduped = {bar["end"]: bar for bar in bars_by_symbol[symbol]}
        bars_by_symbol[symbol] = sorted(deduped.values(), key=lambda bar: bar["end"])

    return bars_by_symbol


def bars_after_open(bars, opened_at, horizon):
    future = [bar for bar in bars if bar["end"] > opened_at]
    if len(future) < horizon:
        return None
    return future[:horizon]


def bracket_outcome(path, direction, entry, forward_pct, backward_pct):
    if direction == "UP":
        forward_price = entry * (1 + forward_pct / 100)
        backward_price = entry * (1 - backward_pct / 100)
    else:
        forward_price = entry * (1 - forward_pct / 100)
        backward_price = entry * (1 + backward_pct / 100)

    for bar in path:
        if direction == "UP":
            forward_hit = bar["high"] >= forward_price
            backward_hit = bar["low"] <= backward_price
        else:
            forward_hit = bar["low"] <= forward_price
            backward_hit = bar["high"] >= backward_price

        if forward_hit and backward_hit:
            return "AMBIGUOUS_SAME_5M_BAR", bar["end"]
        if forward_hit:
            return "FORWARD_FIRST", bar["end"]
        if backward_hit:
            return "BACKWARD_FIRST", bar["end"]

    return "UNRESOLVED", None


def calculate_outcome(episode, path, horizon):
    entry = episode["reference_price"]
    direction = episode["direction"]

    favorable = 0.0
    adverse = 0.0

    for bar in path:
        if direction == "UP":
            favorable = max(favorable, (bar["high"] / entry - 1) * 100)
            adverse = min(adverse, (bar["low"] / entry - 1) * 100)
        else:
            favorable = max(favorable, (entry / bar["low"] - 1) * 100)
            adverse = min(adverse, (entry / bar["high"] - 1) * 100)

    final_close = path[-1]["close"]
    terminal_return = (
        (final_close / entry - 1) * 100
        if direction == "UP"
        else (entry / final_close - 1) * 100
    )

    if direction == "UP":
        favorable_extreme_price = max(bar["high"] for bar in path)
        retracement = (favorable_extreme_price / final_close - 1) * 100
    else:
        favorable_extreme_price = min(bar["low"] for bar in path)
        retracement = (final_close / favorable_extreme_price - 1) * 100

    brackets = []
    for bracket in BRACKETS:
        result, resolved_at = bracket_outcome(
            path,
            direction,
            entry,
            bracket["forward_pct"],
            bracket["backward_pct"],
        )
        brackets.append(
            {
                **bracket,
                "result": result,
                "resolved_at_utc": resolved_at.isoformat() if resolved_at else None,
            }
        )

    return {
        "recordtype": "EPISODEEXCURSIONOUTCOME",
        "schemaversion": "episodeexcursionsettlev1",
        "observationonly": True,
        "doesnotauthorizetrade": True,
        "doesnotchangequeue": True,
        "episodeid": episode["episode_id"],
        "krakensymbol": episode["symbol"],
        "episodedirection": direction,
        "referenceprice": entry,
        "episodeopenedatutc": episode["started_at"].isoformat(),
        "horizonbars": horizon,
        "horizonminutes": horizon * 5,
        "horizonendutc": path[-1]["end"].isoformat(),
        "maxfavorableexcursionpct": round(favorable, 6),
        "maxadverseexcursionpct": round(adverse, 6),
        "terminalreturnpct": round(terminal_return, 6),
        "retracementfromfavorableextremepct": round(retracement, 6),
        "finalclose": final_close,
        "brackets": brackets,
        "settledatutc": datetime.now(timezone.utc).isoformat(),
        "barsource": BARS_PATH.name,
    }


def existing_keys(rows):
    return {
        (str(row.get("episodeid")), int(row.get("horizonbars", 0)))
        for row in rows
        if row.get("recordtype") == "EPISODEEXCURSIONOUTCOME"
    }


def main():
    if not EPISODES_PATH.exists():
        sys.exit(f"Missing episode event log: {EPISODES_PATH}")

    if not BARS_PATH.exists():
        sys.exit(
            f"Missing 5-minute bar log: {BARS_PATH}\n"
            "Create/run the episode bar collector before settling outcomes."
        )

    episodes = episode_opens(load_jsonl(EPISODES_PATH))
    bars_by_symbol = load_bars(load_jsonl(BARS_PATH))
    settled = existing_keys(load_jsonl(OUTCOMES_PATH))

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    new_records = []

    for episode in episodes.values():
        bars = bars_by_symbol.get(episode["symbol"], [])

        for horizon in HORIZONS:
            key = (episode["episode_id"], horizon)
            if key in settled:
                continue

            path = bars_after_open(bars, episode["started_at"], horizon)
            if path is None:
                continue

            new_records.append(calculate_outcome(episode, path, horizon))

    if new_records:
        with OUTCOMES_PATH.open("a", encoding="utf-8") as handle:
            for record in new_records:
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    print(f"Episodes found: {len(episodes)}")
    print(f"Symbols with bars: {len(bars_by_symbol)}")
    print(f"New outcome records: {len(new_records)}")
    print(f"Outcome ledger: {OUTCOMES_PATH}")


if __name__ == "__main__":
    main()
