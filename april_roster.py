"""april_roster.py — Dynamic Top-12 Pair Selector

Builds the April roster from signals.json so scanner, read.py,
and market_reader.py can all show the same best 12 pairs.

Usage:
    from april_roster import top_12_pairs, filter_rows_to_top12

Scoring philosophy:
- Reward clean structure
- Reward live / building tempo
- Reward active watch states and aligned conviction
- Penalize veto / trap risk / dead structure
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

SIGNALS_FILE = Path(__file__).parent / "signals.json"

BOT_KEYS = [
    "gimba_volatile",
    "gimba_range",
    "rts_liq",
    "gimba_trend",
]


# ── IO ─────────────────────────────────────────────────────────────────────

def load_signals() -> dict:
    if not SIGNALS_FILE.exists():
        return {"ts": "unknown", "cycle": "?", "signals": []}
    try:
        return json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"ts": "read_error", "cycle": "?", "signals": []}


# ── Scoring helpers ────────────────────────────────────────────────────────

def _structure_score(row: dict) -> float:
    strx = row.get("structure", {}) or {}
    state = str(strx.get("state", "STRUCTURE_UNCLEAR")).upper()
    zone = str(strx.get("zone", "neutral")).lower()
    bos = bool(strx.get("bos", False))

    score = 0.0

    if state.startswith("TRENDING_UP") or state.startswith("TRENDING_DOWN"):
        score += 36.0
    elif state == "RANGING_NEUTRAL":
        score += 22.0
    elif state == "STRUCTURE_UNCLEAR":
        score -= 18.0
    else:
        score += 10.0

    if zone in ("discount", "premium"):
        score += 6.0
    elif zone == "neutral":
        score += 2.0

    if bos:
        score += 5.0

    return score


def _tempo_points(label: str) -> float:
    t = str(label or "DEAD").upper()
    if t == "LIVE":
        return 14.0
    if t == "BUILDING":
        return 11.0
    if t == "EARLY":
        return 8.0
    if t == "LATE":
        return 3.0
    return -4.0


def _tempo_score(row: dict) -> float:
    score = 0.0

    strx = row.get("structure", {}) or {}
    score += _tempo_points(strx.get("market_tempo") or strx.get("h1_tempo") or "DEAD")

    for bot_key in BOT_KEYS:
        bot = row.get(bot_key, {}) or {}
        score += _tempo_points(bot.get("tempo", "DEAD")) * 0.75

    return score


def _watch_score(row: dict) -> float:
    score = 0.0
    long_count = 0
    short_count = 0
    watch_count = 0
    conviction_sum = 0.0

    for bot_key in BOT_KEYS:
        bot = row.get(bot_key, {}) or {}
        if bot.get("action_state") != "watch":
            continue

        bias = bot.get("bias", "NONE")
        conv = float(bot.get("conviction", 0.0))

        watch_count += 1
        conviction_sum += conv
        score += 8.0 + conv * 12.0

        if bias == "LONG":
            long_count += 1
        elif bias == "SHORT":
            short_count += 1

    if watch_count == 0:
        score -= 4.0
    elif long_count == watch_count or short_count == watch_count:
        if watch_count >= 3:
            score += 14.0
        elif watch_count == 2:
            score += 9.0
        else:
            score += 3.0
    elif long_count > 0 and short_count > 0:
        score -= 7.0

    return score


def _volatility_score(row: dict) -> float:
    vol = row.get("gimba_volatile", {}) or {}
    rng = row.get("gimba_range", {}) or {}

    vind = vol.get("indicators", {}) or {}
    rind = rng.get("indicators", {}) or {}

    rvol = float(vind.get("rvol", 1.0))
    speed_pct = float(vind.get("speed_pct", 0.0))
    dispq = float(vind.get("disp_quality", 0.5))
    expansion_active = bool(rind.get("expansion_active", False))

    score = 0.0

    if rvol >= 1.4:
        score += 8.0
    elif rvol >= 1.1:
        score += 5.0
    elif rvol < 0.8:
        score -= 3.0

    if speed_pct >= 0.60:
        score += 6.0
    elif speed_pct >= 0.30:
        score += 3.0

    if dispq >= 0.60:
        score += 5.0
    elif dispq < 0.40:
        score -= 2.0

    if expansion_active:
        score += 4.0

    return score


def _trap_penalty(row: dict) -> float:
    rts = row.get("rts_liq", {}) or {}
    ind = rts.get("indicators", {}) or {}

    score = 0.0

    trap_score = float(rts.get("trap_score", 0.0))
    veto = bool(rts.get("veto", False))
    swept_high = bool(ind.get("swept_high", False))
    swept_low = bool(ind.get("swept_low", False))
    reclaim_high = bool(ind.get("reclaim_high", False))
    reclaim_low = bool(ind.get("reclaim_low", False))
    strong_wick = bool(ind.get("strong_wick", False))

    if veto:
        score -= 16.0

    if trap_score >= 0.80:
        score -= 10.0
    elif trap_score >= 0.60:
        score -= 6.0
    elif trap_score >= 0.40:
        score -= 2.0

    if strong_wick:
        score -= 2.0

    if (swept_high or swept_low) and not (reclaim_high or reclaim_low):
        score -= 3.0

    return score


def _freshness_bonus(row: dict) -> float:
    """
    Small bonus for non-dead structure + at least one active engine.
    Helps avoid dead placeholders making the roster.
    """
    strx = row.get("structure", {}) or {}
    stempo = str(strx.get("market_tempo") or strx.get("h1_tempo") or "DEAD").upper()

    active_tempo = 0
    for bot_key in BOT_KEYS:
        t = str((row.get(bot_key, {}) or {}).get("tempo", "DEAD")).upper()
        if t in ("LIVE", "BUILDING", "EARLY"):
            active_tempo += 1

    bonus = 0.0
    if stempo in ("LIVE", "BUILDING", "EARLY"):
        bonus += 6.0
    if active_tempo >= 2:
        bonus += 6.0
    elif active_tempo == 1:
        bonus += 3.0

    return bonus


# ── Public API ────────────────────────────────────────────────────────────

def score_pair(row: dict) -> float:
    total = 0.0
    total += _structure_score(row)
    total += _tempo_score(row)
    total += _watch_score(row)
    total += _volatility_score(row)
    total += _trap_penalty(row)
    total += _freshness_bonus(row)
    return round(total, 3)


def ranked_rows(data: dict | None = None) -> List[Tuple[float, dict]]:
    if data is None:
        data = load_signals()

    rows = data.get("signals", []) or []
    ranked = [(score_pair(row), row) for row in rows]
    ranked.sort(key=lambda x: (-x[0], x[1].get("pair", "")))
    return ranked


def top_12_pairs(data: dict | None = None) -> List[str]:
    ranked = ranked_rows(data)
    return [row.get("pair", "?") for score, row in ranked[:12]]


def filter_rows_to_top12(rows: List[dict], data: dict | None = None) -> List[dict]:
    top = set(top_12_pairs(data))
    kept = [row for row in rows if row.get("pair") in top]
    kept.sort(key=lambda row: top_12_pairs(data).index(row.get("pair")))
    return kept


def debug_print(data: dict | None = None) -> None:
    ranked = ranked_rows(data)
    print("\nAPRIL ROSTER — TOP 12\n" + "─" * 72)
    for i, (score, row) in enumerate(ranked[:12], start=1):
        pair = row.get("pair", "?")
        strx = (row.get("structure", {}) or {}).get("state", "STRUCTURE_UNCLEAR")
        print(f"{i:>2}. {pair:<12} score={score:>6.2f}   {strx}")
    print()


if __name__ == "__main__":
    debug_print()
