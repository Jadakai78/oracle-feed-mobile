"""read.py — JHL Live Signal Panel
Reads signals.json and prints only what matters, in a loop.

Shows per pair:
- Alignment across VOL / RNG / RTS / TRD
- Structure state + why (for STRUCTURE_UNCLEAR)
- Shadow (Shield) verdict and score
- Offense MODE: TREND / RANGE / TRAP / DEAD / MIXED

Usage:
    python read.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, Any

SIGNALS_FILE = Path(__file__).parent / "signals.json"
REFRESH_INTERVAL = 10  # seconds between refreshes

BOT_LABELS = [
    ("gimba_volatile", "VOL"),
    ("gimba_range", "RNG"),
    ("rts_liq", "RTS"),
    ("gimba_trend", "TRD"),
]


def _load() -> dict:
    if not SIGNALS_FILE.exists():
        print("signals.json not found. Is scanner.py running?")
        time.sleep(3)
        return {}
    try:
        return json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # If scanner is mid-write, wait and try again next loop
        return {}


def _alignment(row: dict) -> str:
    """Alignment tag across four bots."""
    watch_biases = []
    for bot_key, _ in BOT_LABELS:
        s = row.get(bot_key, {}) or {}
        if s.get("action_state") == "watch" and s.get("bias") not in ("NONE", None):
            watch_biases.append(s["bias"])

    if not watch_biases:
        return "----"

    long_count = watch_biases.count("LONG")
    short_count = watch_biases.count("SHORT")
    total = len(watch_biases)

    if total == 4 and long_count == 4:
        return "ALL 4 ▲"
    if total == 4 and short_count == 4:
        return "ALL 4 ▼"
    if total >= 3 and long_count >= 3:
        return "3 of 4 ▲"
    if total >= 3 and short_count >= 3:
        return "3 of 4 ▼"
    if total >= 2 and long_count >= 2:
        return "2 of 4 ▲"
    if total >= 2 and short_count >= 2:
        return "2 of 4 ▼"
    if long_count > 0 and short_count > 0:
        return "SPLIT ⚠"
    if total == 1:
        which = [
            BOT_LABELS[i][0]
            for i, (bk, _) in enumerate(BOT_LABELS)
            if row.get(bk, {}).get("action_state") == "watch"
            and row.get(bk, {}).get("bias") not in ("NONE", None)
        ]
        label = which[0].replace("gimba_volatile", "VOL").replace(
            "gimba_range", "RNG"
        ).replace("rts_liq", "RTS").replace("gimba_trend", "TRD")
        return f"SOLO({label})"
    return "----"


def _veto_active(row: dict) -> str:
    rts = row.get("rts_liq", {}) or {}
    if rts.get("veto") and rts.get("veto_direction") not in ("none", None):
        return f" ⚠ VETO:{rts['veto_direction'].upper()}"
    return ""


def _shadow_pill(row: dict) -> str:
    """Render Shadow (shield) verdict as a colored pill: SHD:CLAIM / WATCH / VETO / NEUTR plus score."""
    diag = row.get("diagnostics") or {}
    shadow = diag.get("shadow_sentinel") or {}
    verdict = str(shadow.get("verdict") or "unavailable")
    score = shadow.get("score")

    if verdict == "shadow_claim":
        tag = "\033[92mSHD:CLAIM\033[0m"
    elif verdict == "shadow_watch":
        tag = "\033[93mSHD:WATCH\033[0m"
    elif verdict == "shadow_veto":
        tag = "\033[91mSHD:VETO \033[0m"
    elif verdict == "shadow_neutral":
        tag = "\033[90mSHD:NEUTR\033[0m"
    else:
        tag = "\033[90mSHD:NA   \033[0m"

    if isinstance(score, (int, float)):
        return f"{tag} s:{score:>4}"
    return tag


def _offense_mode(row: Dict[str, Any]) -> str:
    """Mirror of scanner offense mode for display only."""
    strx = row.get("structure") or {}
    state = strx.get("state", "STRUCTURE_UNCLEAR")
    trap = float(row.get("rts_liq", {}).get("trap_score") or 0.5)

    tempos = [
        (strx.get("tempo") or "").upper(),
        (row.get("gimba_volatile", {}).get("tempo") or "").upper(),
        (row.get("gimba_range", {}).get("tempo") or "").upper(),
        (row.get("rts_liq", {}).get("tempo") or "").upper(),
        (row.get("gimba_trend", {}).get("tempo") or "").upper(),
    ]
    dead_count = sum(1 for t in tempos if t == "DEAD")

    vol_ind = row.get("gimba_volatile", {}).get("indicators") or {}
    rvol = float(vol_ind.get("rvol") or 1.0)

    if state == "STRUCTURE_UNCLEAR":
        if dead_count >= 3:
            return "DEAD"
        return "MIXED"

    if trap >= 0.75 or rvol < 0.3:
        return "TRAP"

    if state.startswith("TRENDING_"):
        return "TREND"

    if state == "RANGING_NEUTRAL":
        return "RANGE"

    return "MIXED"


def _header(ts: str, cycle: str) -> None:
    os.system("cls" if os.name == "nt" else "clear")
    print(f"\n JHL GIMBA │ Cycle {cycle} │ {ts}")
    print(f" {'─'*62}")


def _render_panel(data: dict) -> None:
    ts = data.get("ts", "unknown")
    cycle = data.get("cycle", "?")
    signals = data.get("signals", [])

    _header(ts, cycle)
    any_watch = False

    for row in signals:
        pair = row.get("pair", "?")
        alignment = _alignment(row)
        veto = _veto_active(row)
        strx = row.get("structure", {}) or {}
        strx_state = strx.get("state", "STRUCTURE_UNCLEAR")
        strx_zone = strx.get("zone", "")
        strx_bos = " BOS" if strx.get("bos") else ""
        strx_why = str(strx.get("why") or "").strip()

        # Append why for unclear structure
        if strx_state == "STRUCTURE_UNCLEAR" and strx_why:
            display_state = f"{strx_state} [{strx_why}]"
        else:
            display_state = strx_state

        # Color structure state
        if "DISCOUNT" in strx_state and "UP" in strx_state:
            strx_tag = f"\033[92m{display_state}{strx_bos}\033[0m"  # green
        elif "PREMIUM" in strx_state and "DOWN" in strx_state:
            strx_tag = f"\033[92m{display_state}{strx_bos}\033[0m"  # green
        elif "PREMIUM" in strx_state and "UP" in strx_state:
            strx_tag = f"\033[93m{display_state}{strx_bos}\033[0m"  # yellow
        elif "DISCOUNT" in strx_state and "DOWN" in strx_state:
            strx_tag = f"\033[93m{display_state}{strx_bos}\033[0m"  # yellow
        elif strx_state == "RANGING_NEUTRAL":
            strx_tag = f"\033[90m{display_state}\033[0m"  # gray
        else:
            strx_tag = display_state

        shd_tag = _shadow_pill(row)
        mode_str = _offense_mode(row)
        mode_tag = f"MODE:{mode_str}"

        # Collect all WATCH signals for this pair
        watch_lines = []
        for bot_key, short_label in BOT_LABELS:
            s = row.get(bot_key, {}) or {}
            act = s.get("action_state", "idle")
            bias = s.get("bias", "NONE")
            if act != "watch" or bias in ("NONE", None):
                continue

            conv = s.get("conviction", 0.0)
            entry = s.get("entry")
            sl = s.get("sl")
            tp = s.get("tp")
            knn_n = s.get("knn_samples", 0)
            knn_a = s.get("knn_adj", 0.0)

            # KNN note
            if knn_n >= 30:
                adj_str = f"+{knn_a:.3f}" if knn_a >= 0 else f"{knn_a:.3f}"
                knn_str = f" KNN{adj_str}"
            else:
                knn_str = f" KNN({knn_n}/30)"

            geo_str = ""
            if entry and sl and tp:
                geo_str = f" Entry:{entry} SL:{sl} TP:{tp}"

            tempo_val = s.get("tempo", "")
            tempo_str = f" [{tempo_val}]" if tempo_val else ""

            watch_lines.append(
                f" {pair:<12} {bias:<6} {short_label} conv:{conv:.2f}"
                f"{tempo_str}{geo_str}{knn_str}"
            )

        if watch_lines:
            any_watch = True
            align_tag = f"[{alignment}{veto}]"
            print(f"\n {align_tag} {strx_tag} {shd_tag} {mode_tag}")
            for line in watch_lines:
                print(line)
        else:
            # idle pairs: print one quiet line
            align_tag = f"[{alignment}{veto}]"
            print(f"\n {align_tag} {pair:<12} -- {strx_tag} {shd_tag} {mode_tag}")

    print(f"\n {'─'*62}")
    if not any_watch:
        print(" No active signals. Market idle.")
    else:
        print(" CAUTION: SOLO or SPLIT signals are lower confidence.")
        print(" ALL 4 or 3 of 4 aligned = highest conviction.")
    print(f"\n Refreshing in {REFRESH_INTERVAL}s...")


def main() -> None:
    while True:
        data = _load()
        if data:
            _render_panel(data)
        else:
            os.system("cls" if os.name == "nt" else "clear")
            print("Waiting for signals.json ...")

        time.sleep(REFRESH_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nReader stopped.")
