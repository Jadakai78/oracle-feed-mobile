"""feed.py — JHL Live Feed
Auto-refreshing signal feed for Gimba.
Shows active signals first, idle market below.

Usage:
    python feed.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

SIGNALS_FILE = Path(__file__).parent / "signals.json"
REFRESH_SECONDS = 3

BOT_LABELS = [
    ("gimba_volatile", "VOL"),
    ("gimba_range", "RNG"),
    ("rts_liq", "RTS"),
]


def _load() -> dict:
    if not SIGNALS_FILE.exists():
        return {"ts": "waiting...", "cycle": "?", "signals": []}
    try:
        return json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"ts": "read error", "cycle": "?", "signals": []}


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _alignment(row: dict) -> str:
    active = []
    for bot_key, short_label in BOT_LABELS:
        s = row.get(bot_key, {})
        if s.get("action_state") == "watch" and s.get("bias") in ("LONG", "SHORT"):
            active.append((short_label, s.get("bias")))

    if not active:
        return "----"

    long_count = sum(1 for _, bias in active if bias == "LONG")
    short_count = sum(1 for _, bias in active if bias == "SHORT")
    total = len(active)

    if total == 3 and long_count == 3:
        return "ALL 3 ▲"
    if total == 3 and short_count == 3:
        return "ALL 3 ▼"
    if total >= 2 and long_count >= 2:
        return "2 of 3 ▲"
    if total >= 2 and short_count >= 2:
        return "2 of 3 ▼"
    if long_count > 0 and short_count > 0:
        return "SPLIT ⚠"
    if total == 1:
        label, bias = active[0]
        arrow = "▲" if bias == "LONG" else "▼"
        return f"SOLO({label}{arrow})"
    return "----"


def _alignment_rank(tag: str) -> int:
    if tag.startswith("ALL 3"):
        return 0
    if tag.startswith("2 of 3"):
        return 1
    if tag.startswith("SOLO"):
        return 2
    if tag.startswith("SPLIT"):
        return 3
    return 4


def _veto_active(row: dict) -> str:
    rts = row.get("rts_liq", {})
    if rts.get("veto") and rts.get("veto_direction") not in ("none", None):
        return f" ⚠ VETO:{rts['veto_direction'].upper()}"
    return ""


def _structure_meta(row: dict) -> str:
    strx = row.get("structure", {})
    market_condition = strx.get("market_condition") or strx.get("state") or "STRUCTURE_UNCLEAR"
    market_tempo = strx.get("market_tempo") or strx.get("h1_tempo") or ""
    zone = strx.get("zone", "unknown")
    alignment = strx.get("alignment", "unaligned")
    bos = " BOS" if strx.get("bos") else ""

    details = []
    if market_tempo:
        details.append(market_tempo)
    if zone:
        details.append(zone)
    if alignment:
        details.append(alignment)

    suffix = f" ({' | '.join(details)})" if details else ""
    raw = f"{market_condition}{bos}{suffix}"

    upper = market_condition.upper()
    if ("DOWN" in upper and zone == "premium") or ("UP" in upper and zone == "discount"):
        return f"\033[92m{raw}\033[0m"
    if ("UP" in upper and zone == "premium") or ("DOWN" in upper and zone == "discount"):
        return f"\033[93m{raw}\033[0m"
    if "RANGING" in upper or zone == "neutral":
        return f"\033[90m{raw}\033[0m"
    return raw


def _bot_tempo_summary(row: dict) -> str:
    tempos = []
    for bot_key, short_label in BOT_LABELS:
        tempo = row.get(bot_key, {}).get("tempo")
        if tempo:
            tempos.append(f"{short_label}:{tempo}")
    return f"  Tempo[{ ' | '.join(tempos) }]" if tempos else ""


def _watch_lines(row: dict) -> list[str]:
    pair = row.get("pair", "?")
    lines = []
    for bot_key, short_label in BOT_LABELS:
        s = row.get(bot_key, {})
        act = s.get("action_state", "idle")
        bias = s.get("bias", "NONE")
        if act != "watch" or bias not in ("LONG", "SHORT"):
            continue

        conv = s.get("conviction", 0.0)
        entry = s.get("entry")
        sl = s.get("sl")
        tp = s.get("tp")
        knn_n = s.get("knn_samples", 0)
        knn_a = s.get("knn_adj", 0.0)
        tempo_val = s.get("tempo", "")
        setup = s.get("setup_type", "")

        if knn_n >= 30:
            adj_str = f"+{knn_a:.3f}" if knn_a >= 0 else f"{knn_a:.3f}"
            knn_str = f"  KNN{adj_str}"
        else:
            knn_str = f"  KNN({knn_n}/30)"

        geo_str = ""
        if entry is not None and sl is not None and tp is not None:
            geo_str = f"  Entry:{entry}  SL:{sl}  TP:{tp}"

        tempo_str = f"  [{tempo_val}]" if tempo_val else ""
        setup_str = f"  {setup}" if setup else ""

        lines.append(
            f"  {pair:<12}  {bias:<6}  {short_label}  conv:{conv:.2f}{tempo_str}{geo_str}{knn_str}{setup_str}"
        )
    return lines


def _row_bucket(row: dict) -> tuple[int, float]:
    tag = _alignment(row)
    lines = _watch_lines(row)

    best_conv = 0.0
    for bot_key, _ in BOT_LABELS:
        s = row.get(bot_key, {})
        if s.get("action_state") == "watch":
            best_conv = max(best_conv, float(s.get("conviction", 0.0)))

    return (_alignment_rank(tag), -best_conv)


def _print_section(title: str) -> None:
    print(f"\n  {title}")
    print(f"  {'─' * 86}")


def main() -> None:
    while True:
        data = _load()
        ts = data.get("ts", "unknown")
        cycle = data.get("cycle", "?")
        signals = data.get("signals", [])

        _clear()
        print(f"\n  JHL LIVE FEED  │  Cycle {cycle}  │  {ts}")
        print(f"  {'═' * 86}")

        ranked = sorted(signals, key=_row_bucket)

        active_aligned = []
        active_caution = []
        idle_rows = []

        for row in ranked:
            alignment = _alignment(row)
            watch_lines = _watch_lines(row)

            if alignment in ("ALL 3 ▲", "ALL 3 ▼", "2 of 3 ▲", "2 of 3 ▼"):
                active_aligned.append((row, alignment, watch_lines))
            elif watch_lines:
                active_caution.append((row, alignment, watch_lines))
            else:
                idle_rows.append((row, alignment))

        if active_aligned:
            _print_section("ACTIVE ALIGNED")
            for row, alignment, watch_lines in active_aligned:
                veto = _veto_active(row)
                strx_tag = _structure_meta(row)
                tempo_summary = _bot_tempo_summary(row)
                print(f"\n  [{alignment}{veto}]  {strx_tag}{tempo_summary}")
                for line in watch_lines:
                    print(line)

        if active_caution:
            _print_section("ACTIVE CAUTION")
            for row, alignment, watch_lines in active_caution:
                veto = _veto_active(row)
                strx_tag = _structure_meta(row)
                tempo_summary = _bot_tempo_summary(row)
                print(f"\n  [{alignment}{veto}]  {strx_tag}{tempo_summary}")
                for line in watch_lines:
                    print(line)

        _print_section("IDLE MARKET")
        if idle_rows:
            for row, alignment in idle_rows:
                pair = row.get("pair", "?")
                strx_tag = _structure_meta(row)
                tempo_summary = _bot_tempo_summary(row)
                print(f"  {pair:<12}  --     {alignment:<10}  {strx_tag}{tempo_summary}")
        else:
            print("  None. Everything active.")

        print(f"\n  {'═' * 86}")
        print(f"  Refreshing every {REFRESH_SECONDS}s  │  Ctrl+C to stop")
        print("  Highest priority = ALL 3 / 2 of 3 aligned at top.\n")

        time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nFeed stopped.")
