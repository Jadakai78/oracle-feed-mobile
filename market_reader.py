"""market_reader.py — JHL Market State Radar (APRIL Top-12)

Panel 3: battlefield overview, not bot signals.
Shows structure, tempo, volatility, and liquidation regime
for the APRIL roster (dynamic top 12 pairs).

Usage:
    python market_reader.py
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from april_roster import top_12_pairs

SIGNALS_FILE = Path(__file__).parent / "signals.json"
REFRESH_INTERVAL = 15  # seconds between panel refreshes


BOT_LABELS = [
    ("gimba_volatile", "VOL"),
    ("gimba_range", "RNG"),
    ("rts_liq", "RTS"),
    ("gimba_trend", "TRD"),
]


def _load() -> dict:
    if not SIGNALS_FILE.exists():
        print("signals.json not found. Is scanner.py running?")
        return {"ts": "waiting...", "cycle": "?", "signals": []}
    try:
        return json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        print("Error reading signals.json.")
        return {"ts": "read_error", "cycle": "?", "signals": []}


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


# ── Structure classification ──────────────────────────────────────────────

def _structure_state(row: dict) -> tuple[str, str]:
    strx = row.get("structure", {}) or {}

    market_condition = (
        strx.get("market_condition")
        or strx.get("state")
        or "STRUCTURE_UNCLEAR"
    )
    market_tempo = strx.get("market_tempo") or strx.get("h1_tempo") or ""
    zone = strx.get("zone", "neutral")
    alignment = strx.get("alignment", "unknown")
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
        styled = f"\033[92m{raw}\033[0m"
    elif ("UP" in upper and zone == "premium") or ("DOWN" in upper and zone == "discount"):
        styled = f"\033[93m{raw}\033[0m"
    elif "RANGING" in upper or zone == "neutral":
        styled = f"\033[90m{raw}\033[0m"
    else:
        styled = raw

    return raw, styled


# ── Tempo classification ──────────────────────────────────────────────────

def _tempo_state(row: dict) -> str:
    strx = row.get("structure", {}) or {}
    str_tempo = strx.get("market_tempo") or strx.get("h1_tempo") or ""

    bot_tempos = []
    for bot_key, short_label in BOT_LABELS:
        tempo = row.get(bot_key, {}).get("tempo")
        if tempo:
            bot_tempos.append(f"{short_label}:{tempo}")

    parts = []
    if str_tempo:
        parts.append(f"STR:{str_tempo}")
    if bot_tempos:
        parts.append(" | ".join(bot_tempos))

    return "Tempo[" + " | ".join(parts) + "]" if parts else "Tempo[DEAD]"


# ── Volatility classification ─────────────────────────────────────────────

def _volatility_state(row: dict) -> str:
    vol = row.get("gimba_volatile", {}) or {}
    rng = row.get("gimba_range", {}) or {}

    v_ind = vol.get("indicators", {}) or {}
    r_ind = rng.get("indicators", {}) or {}

    rvol = float(v_ind.get("rvol", v_ind.get("rvol", 1.0)))
    atr = float(v_ind.get("atr", r_ind.get("atr", 0.0)))
    speed = float(v_ind.get("speed_pct", v_ind.get("speed_pct", 0.0)))
    knn_n = int(vol.get("knn_samples", 0))
    dispq = float(v_ind.get("disp_quality", v_ind.get("disp_quality", 0.5)))
    maturity = float(v_ind.get("maturity", v_ind.get("maturity", 0.5)))
    expansion_active = bool(r_ind.get("expansion_active", False))

    if atr == 0.0 and rvol <= 0.8:
        regime = "QUIET"
    elif rvol < 1.2 and not expansion_active and speed < 0.5:
        regime = "NORMAL"
    elif (rvol >= 1.2 or speed >= 0.5) and dispq >= 0.55:
        regime = "ACTIVE"
    else:
        regime = "MIXED"

    if expansion_active:
        if regime == "ACTIVE":
            regime = "EXPANDING"
        else:
            regime = "EXPANSION_RISK"

    return (
        f"Vol[{regime} | rvol={rvol:.2f} | atr={atr:.4f} | "
        f"dispq={dispq:.3f} | mat={maturity:.2f} | KNN={knn_n}]"
    )


# ── Liquidation / trap classification ─────────────────────────────────────

def _liquidation_state(row: dict) -> str:
    rts = row.get("rts_liq", {}) or {}
    ind = rts.get("indicators", {}) or {}

    trap_score = float(rts.get("trap_score", 0.0))
    swept_high = bool(ind.get("swept_high", False))
    swept_low = bool(ind.get("swept_low", False))
    reclaim_high = bool(ind.get("reclaim_high", False))
    reclaim_low = bool(ind.get("reclaim_low", False))
    strong_wick = bool(ind.get("strong_wick", False))
    sweep_size = float(ind.get("sweep_size", 0.0))
    veto = bool(rts.get("veto", False))
    veto_dir = rts.get("veto_direction", "none") or "none"

    if not swept_high and not swept_low and not strong_wick and trap_score < 0.5:
        regime = "CALM"
    elif strong_wick and sweep_size == 0.0 and trap_score < 0.6:
        regime = "WICKY"
    elif (swept_high or swept_low) and not (reclaim_high or reclaim_low) and trap_score < 0.7:
        regime = "SWEEP"
    elif trap_score >= 0.7 and (reclaim_high or reclaim_low):
        regime = "FULL_TRAP"
    elif trap_score >= 0.5:
        regime = "TRAP_RISK"
    else:
        regime = "MIXED"

    veto_str = ""
    if veto and veto_dir not in ("none", None):
        veto_str = f" | VETO:{veto_dir.upper()}"

    return (
        f"Liq[{regime} | trap={trap_score:.2f} | "
        f"sweep={swept_high or swept_low} | reclaim={reclaim_high or reclaim_low}{veto_str}]"
    )


def _summary_sentence(struct_raw: str, tempo: str, vol_state: str, liq_state: str) -> str:
    parts = []

    if struct_raw.startswith("TRENDING_UP"):
        parts.append("Uptrend environment")
    elif struct_raw.startswith("TRENDING_DOWN"):
        parts.append("Downtrend environment")
    elif struct_raw.startswith("RANGING_NEUTRAL"):
        parts.append("Range/chop environment")
    elif "STRUCTURE_UNCLEAR" in struct_raw:
        parts.append("Structure unclear")

    if "LIVE" in tempo:
        parts.append("move live now")
    elif "BUILDING" in tempo:
        parts.append("move building")
    elif "EARLY" in tempo:
        parts.append("early move forming")
    elif "LATE" in tempo:
        parts.append("move aging")
    elif "DEAD" in tempo:
        parts.append("market dead")

    if "EXPANDING" in vol_state:
        parts.append("real expansion")
    elif "ACTIVE" in vol_state:
        parts.append("volatility active")
    elif "QUIET" in vol_state:
        parts.append("volatility quiet")

    if "FULL_TRAP" in liq_state:
        parts.append("trap fully active")
    elif "TRAP_RISK" in liq_state:
        parts.append("trap risk elevated")
    elif "SWEEP" in liq_state:
        parts.append("recent liquidity sweep")

    if not parts:
        return "Mixed environment; no dominant regime."

    return "; ".join(parts) + "."


def _render_once() -> None:
    data = _load()
    ts = data.get("ts", "unknown")
    cycle = data.get("cycle", "?")
    signals = data.get("signals", [])

    roster = top_12_pairs(data)
    roster_set = set(roster)
    signals = [row for row in signals if row.get("pair") in roster_set]
    signals.sort(key=lambda row: roster.index(row.get("pair")))

    _clear()
    print(f"\n  JHL MARKET READER  │  Cycle {cycle}  │  {ts}")
    print(f"  APRIL ROSTER TOP 12")
    print(f"  {'═' * 110}")

    for row in signals:
        pair = row.get("pair", "?")

        struct_raw, struct_tag = _structure_state(row)
        tempo = _tempo_state(row)
        vol_state = _volatility_state(row)
        liq_state = _liquidation_state(row)
        sentence = _summary_sentence(struct_raw, tempo, vol_state, liq_state)

        print(f"\n  {pair}")
        print(f"    Structure:   {struct_tag}")
        print(f"    {tempo}")
        print(f"    {vol_state}")
        print(f"    {liq_state}")
        print(f"    Read:        {sentence}")

    print(f"\n  {'═' * 110}")
    print(f"  Panel 3: market state for APRIL roster — auto-refresh every {REFRESH_INTERVAL}s.")
    print("  Ctrl+C to stop.\n")


def main() -> None:
    print("Starting JHL Market Reader loop (APRIL roster)...")
    time.sleep(1.5)
    try:
        while True:
            _render_once()
            time.sleep(REFRESH_INTERVAL)
    except KeyboardInterrupt:
        print("\nMarket reader stopped.")


if __name__ == "__main__":
    main()
