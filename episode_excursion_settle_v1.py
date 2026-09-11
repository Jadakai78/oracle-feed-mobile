from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import json
import math

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs"

EPISODES_PATH = LOG_DIR / "episode_context_events.jsonl"
BARS_PATH = LOG_DIR / "episode_5m_bars_v1.jsonl"
OUTCOMES_PATH = LOG_DIR / "episode_excursion_outcomes_v1.jsonl"

HORIZONS = (12, 24)

BRACKETS = (
    {"name": "FWD_1.0_BACK_0.5", "forward_pct": 1.0, "backward_pct": 0.5},
    {"name": "FWD_1.5_BACK_0.5", "forward_pct": 1.5, "backward_pct": 0.5},
)


def now_utc():
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
        parsed = datetime.fromisoformat(
            str(value).strip().replace("Z", "+00:00")
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def finite_number(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    return parsed if math.isfinite(parsed) else None


def normalize_symbol(value):
    return (
        str(value or "")
        .upper()
        .replace("-", "")
        .replace("/", "")
        .strip()
    )


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


def row_event_type(row):
    return str(
        row.get("event_type")
        or row.get("eventtype")
        or ""
    ).upper()


def get_episode_value(row, episode, *names):
    for name in names:
        value = episode.get(name)
        if value is not None:
            return value

        value = row.get(name)
        if value is not None:
            return value

    return None


def episode_opens(rows):
    """
    Creates one immutable opening reference per episode.
    Supports both current snake_case and older compact schemas.
    The earliest valid EPISODEOPEN or EPISODE_UPDATE becomes the reference.
    """
    opened = {}

    for row in rows:
        kind = row_event_type(row)

        if kind not in {"EPISODEOPEN", "EPISODE_UPDATE"}:
            continue

        episode = row.get("episode") or {}

        identifier = str(
            get_episode_value(
                row,
                episode,
                "episode_id",
                "episodeid",
            )
            or ""
        ).strip()

        pair = normalize_symbol(
            get_episode_value(
                row,
                episode,
                "kraken_symbol",
                "krakensymbol",
            )
        )

        direction = str(
            get_episode_value(
                row,
                episode,
                "direction",
            )
            or ""
        ).upper()

        reference = finite_number(
            get_episode_value(
                row,
                episode,
                "reference_price",
                "referenceprice",
            )
        )

        started_at = parse_time(
            get_episode_value(
                row,
                episode,
                "started_at_utc",
                "startedatutc",
                "timestamp_utc",
                "timestamputc",
            )
        )

        if not identifier or not pair:
            continue

        if direction not in {"UP", "DOWN"}:
            continue

        if reference is None or reference <= 0:
            continue

        if started_at is None:
            continue

        if identifier not in opened:
            opened[identifier] = {
                "episode_id": identifier,
                "kraken_symbol": pair,
                "direction": direction,
                "reference_price": reference,
                "started_at": started_at,
            }

    return opened


def load_bars(rows):
    bars_by_symbol = defaultdict(list)

    for row in rows:
        pair = normalize_symbol(
            row.get("kraken_symbol")
            or row.get("krakensymbol")
            or row.get("symbol")
        )

        bar_start = parse_time(
            row.get("bar_start")
            or row.get("barstart")
        )

        bar_end = parse_time(
            row.get("bar_end")
            or row.get("barend")
        )

        opened = finite_number(row.get("open"))
        high = finite_number(row.get("high"))
        low = finite_number(row.get("low"))
        close = finite_number(row.get("close"))

        if not pair or bar_start is None or bar_end is None:
            continue

        if None in {opened, high, low, close}:
            continue

        if min(opened, high, low, close) <= 0:
            continue

        bars_by_symbol[pair].append(
            {
                "start": bar_start,
                "end": bar_end,
                "open": opened,
                "high": high,
                "low": low,
                "close": close,
            }
        )

    for pair, bars in bars_by_symbol.items():
        deduped = {bar["end"]: bar for bar in bars}
        bars_by_symbol[pair] = sorted(
            deduped.values(),
            key=lambda bar: bar["end"],
        )

    return bars_by_symbol


def future_bars(bars, episode_opened_at, horizon_bars):
    path = [
        bar
        for bar in bars
        if bar["end"] > episode_opened_at
    ]

    if len(path) < horizon_bars:
        return None

    return path[:horizon_bars]


def bracket_outcome(
    path,
    direction,
    entry,
    forward_pct,
    backward_pct,
):
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


def settle_episode(episode, path, horizon_bars):
    entry = episode["reference_price"]
    direction = episode["direction"]

    if direction == "UP":
        mfe = max(
            (bar["high"] / entry - 1) * 100
            for bar in path
        )
        mae = min(
            (bar["low"] / entry - 1) * 100
            for bar in path
        )
        favorable_extreme = max(bar["high"] for bar in path)
        terminal_return = (path[-1]["close"] / entry - 1) * 100
        retracement = (
            favorable_extreme / path[-1]["close"] - 1
        ) * 100

    else:
        mfe = max(
            (entry / bar["low"] - 1) * 100
            for bar in path
        )
        mae = min(
            (entry / bar["high"] - 1) * 100
            for bar in path
        )
        favorable_extreme = min(bar["low"] for bar in path)
        terminal_return = (
            entry / path[-1]["close"] - 1
        ) * 100
        retracement = (
            path[-1]["close"] / favorable_extreme - 1
        ) * 100

    brackets = []

    for bracket in BRACKETS:
        result, resolved_at = bracket_outcome(
            path=path,
            direction=direction,
            entry=entry,
            forward_pct=bracket["forward_pct"],
            backward_pct=bracket["backward_pct"],
        )

        brackets.append(
            {
                **bracket,
                "result": result,
                "resolved_at_utc": (
                    resolved_at.isoformat()
                    if resolved_at
                    else None
                ),
            }
        )

    return {
        "recordtype": "EPISODEEXCURSIONOUTCOME",
        "schemaversion": "episodeexcursionsettlev1",
        "observationonly": True,
        "doesnotauthorizetrade": True,
        "doesnotchangequeue": True,
        "episode_id": episode["episode_id"],
        "kraken_symbol": episode["kraken_symbol"],
        "episode_direction": direction,
        "reference_price": entry,
        "episode_opened_at_utc": (
            episode["started_at"].isoformat()
        ),
        "horizon_bars": horizon_bars,
        "horizon_minutes": horizon_bars * 5,
        "horizon_end_utc": path[-1]["end"].isoformat(),
        "max_favorable_excursion_pct": round(mfe, 6),
        "max_adverse_excursion_pct": round(mae, 6),
        "terminal_return_pct": round(terminal_return, 6),
        "retracement_from_favorable_extreme_pct": round(
            retracement,
            6,
        ),
        "final_close": path[-1]["close"],
        "brackets": brackets,
        "bar_source": BARS_PATH.name,
        "settled_at_utc": now_utc().isoformat(),
    }


def existing_settlement_keys(rows):
    return {
        (
            str(row.get("episode_id")),
            int(row.get("horizon_bars", 0)),
        )
        for row in rows
        if row.get("recordtype") == "EPISODEEXCURSIONOUTCOME"
    }


def main():
    if not EPISODES_PATH.exists():
        raise SystemExit(
            f"Missing episode event log: {EPISODES_PATH}"
        )

    if not BARS_PATH.exists():
        raise SystemExit(
            f"Missing 5-minute bar log: {BARS_PATH}"
        )

    episode_rows = load_jsonl(EPISODES_PATH)
    bar_rows = load_jsonl(BARS_PATH)
    outcome_rows = load_jsonl(OUTCOMES_PATH)

    episodes = episode_opens(episode_rows)
    bars_by_symbol = load_bars(bar_rows)
    existing = existing_settlement_keys(outcome_rows)

    new_rows = []
    pending = 0

    for episode in episodes.values():
        bars = bars_by_symbol.get(
            episode["kraken_symbol"],
            [],
        )

        for horizon_bars in HORIZONS:
            key = (
                episode["episode_id"],
                horizon_bars,
            )

            if key in existing:
                continue

            path = future_bars(
                bars,
                episode["started_at"],
                horizon_bars,
            )

            if path is None:
                pending += 1
                continue

            new_rows.append(
                settle_episode(
                    episode,
                    path,
                    horizon_bars,
                )
            )

    if new_rows:
        with OUTCOMES_PATH.open(
            "a",
            encoding="utf-8",
        ) as handle:
            for row in new_rows:
                handle.write(
                    json.dumps(
                        row,
                        separators=(",", ":"),
                    )
                    + "\n"
                )

    print(f"Episode rows read: {len(episode_rows)}")
    print(f"Episodes found: {len(episodes)}")
    print(f"Symbols with bars: {len(bars_by_symbol)}")
    print(f"New outcome records: {len(new_rows)}")
    print(f"Pending horizon records: {pending}")
    print(f"Outcome ledger: {OUTCOMES_PATH}")


if __name__ == "__main__":
    main()
