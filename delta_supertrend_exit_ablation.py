from pathlib import Path
from datetime import datetime, timezone
import json
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba")
CANDIDATES = ROOT / "delta_corrected_tempo_candidates.csv"
OUTPUT = ROOT / "delta_15m_supertrend_exit_ablation.csv"

KRAKEN_API = "https://api.kraken.com/0/public/OHLC"
PAIR_MAP = {
    "SOL/USD": "SOLUSD",
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
    "XRP/USD": "XRPUSD",
    "ADA/USD": "ADAUSD",
    "DOGE/USD": "XDGUSD",
    "LINK/USD": "LINKUSD",
    "AVAX/USD": "AVAXUSD",
    "DOT/USD": "DOTUSD",
    "AAVE/USD": "AAVEUSD",
    "LTC/USD": "XLTCZUSD",
}

INTERVAL_MINUTES = 15
HORIZON_BARS = 12
ATR_LENGTH = 10
ST_MULTIPLIER = 3.0
ROUND_TRIP_COST_PCT = 0.10
REQUEST_PAUSE_SECONDS = 0.15

def kraken_ohlc(pair, since_epoch):
    params = urllib.parse.urlencode({
        "pair": PAIR_MAP[pair],
        "interval": INTERVAL_MINUTES,
        "since": int(since_epoch),
    })

    with urllib.request.urlopen(f"{KRAKEN_API}?{params}", timeout=20) as response:
        payload = json.loads(response.read())

    if payload.get("error"):
        raise RuntimeError("; ".join(payload["error"]))

    result = payload.get("result", {})
    rows = next((value for key, value in result.items() if key != "last"), None)

    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close"])

    x = pd.DataFrame(rows, columns=[
        "timestamp", "open", "high", "low", "close", "vwap", "volume", "count"
    ])

    x["timestamp"] = pd.to_datetime(x["timestamp"], unit="s", utc=True)
    for col in ["open", "high", "low", "close"]:
        x[col] = pd.to_numeric(x[col], errors="coerce")

    return (
        x.dropna(subset=["timestamp", "open", "high", "low", "close"])
         .drop_duplicates("timestamp")
         .sort_values("timestamp")
         .reset_index(drop=True)
    )

def add_supertrend(x):
    x = x.copy()
    high = x["high"].to_numpy(float)
    low = x["low"].to_numpy(float)
    close = x["close"].to_numpy(float)
    prev_close = np.r_[np.nan, close[:-1]]

    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
    )

    atr = (
        pd.Series(tr)
        .ewm(alpha=1 / ATR_LENGTH, adjust=False, min_periods=ATR_LENGTH)
        .mean()
        .to_numpy()
    )

    hl2 = (high + low) / 2
    upper = hl2 + ST_MULTIPLIER * atr
    lower = hl2 - ST_MULTIPLIER * atr

    final_upper = np.full(len(x), np.nan)
    final_lower = np.full(len(x), np.nan)
    direction = np.full(len(x), np.nan)

    for i in range(ATR_LENGTH, len(x)):
        if i == ATR_LENGTH:
            final_upper[i] = upper[i]
            final_lower[i] = lower[i]
            direction[i] = 1 if close[i] >= lower[i] else -1
            continue

        final_upper[i] = (
            upper[i]
            if upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]
            else final_upper[i - 1]
        )
        final_lower[i] = (
            lower[i]
            if lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]
            else final_lower[i - 1]
        )

        if direction[i - 1] == 1:
            direction[i] = -1 if close[i] < final_lower[i] else 1
        else:
            direction[i] = 1 if close[i] > final_upper[i] else -1

    x["st_direction"] = direction
    return x

def side_return_pct(side, entry, exit_price):
    raw = 100.0 * (exit_price / entry - 1.0)
    return raw if side == "UP" else -raw

def settle_candidate(row):
    pair = row["pair"]
    side = row["delta_direction"]
    signal_end = int(row["bar_end"])

    warmup_start = signal_end - (ATR_LENGTH + 15) * INTERVAL_MINUTES * 60
    bars = add_supertrend(kraken_ohlc(pair, warmup_start))

    future = bars[
        bars["timestamp"].astype("int64") // 1_000_000_000 > signal_end
    ].copy()

    if len(future) < HORIZON_BARS:
        return None, "insufficient_completed_15m_bars"

    future = future.iloc[:HORIZON_BARS].reset_index(drop=True)

    entry_price = float(row["close"])
    if not np.isfinite(entry_price) or entry_price <= 0:
        return None, "invalid_reference_price"

    expected_direction = 1 if side == "UP" else -1
    control_exit_index = HORIZON_BARS - 1
    st_exit_index = control_exit_index

    for i in range(len(future)):
        current_direction = future["st_direction"].iloc[i]
        if np.isfinite(current_direction) and current_direction != expected_direction:
            st_exit_index = i
            break

    outcomes = []
    for variant, exit_index in [
        ("CONTROL_12_BAR_CLOSE", control_exit_index),
        ("SUPERTREND_10_3", st_exit_index),
    ]:
        exit_row = future.iloc[exit_index]
        exit_price = float(exit_row["close"])
        gross = side_return_pct(side, entry_price, exit_price)

        outcomes.append({
            "variant": variant,
            "pair": pair,
            "side": side,
            "signal_bar_end": pd.to_datetime(signal_end, unit="s", utc=True),
            "entry_time": pd.to_datetime(signal_end, unit="s", utc=True),
            "entry_price": entry_price,
            "exit_time": exit_row["timestamp"],
            "exit_price": exit_price,
            "hold_bars": exit_index + 1,
            "exit_reason": (
                "SUPERTREND_OPPOSITE"
                if variant == "SUPERTREND_10_3" and exit_index != control_exit_index
                else "HORIZON_CLOSE"
            ),
            "gross_pct": gross,
            "net_pct": gross - ROUND_TRIP_COST_PCT,
        })

    return outcomes, None

def summarize(name, x):
    if x.empty:
        print(f"{name:42} N=0")
        return

    pnl = x["net_pct"].to_numpy(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) else np.nan

    chronological = x.sort_values(["entry_time", "pair", "side"])
    equity = chronological["net_pct"].cumsum()
    max_dd = float((equity.cummax() - equity).max())

    print(
        f"{name:42} "
        f"N={len(x):4} "
        f"Win={100 * (pnl > 0).mean():6.2f}% "
        f"Avg={pnl.mean():8.4f}% "
        f"Med={np.median(pnl):8.4f}% "
        f"PF={pf:6.2f} "
        f"DD={max_dd:8.4f}% "
        f"Hold={x['hold_bars'].mean():5.2f} "
        f"STexit={100 * (x['exit_reason'] == 'SUPERTREND_OPPOSITE').mean():6.2f}%"
    )

events = pd.read_csv(CANDIDATES)
events = events.dropna(subset=["pair", "delta_direction", "bar_end", "close"]).copy()
events["bar_end"] = pd.to_numeric(events["bar_end"], errors="coerce")
events["close"] = pd.to_numeric(events["close"], errors="coerce")
events = events.dropna(subset=["bar_end", "close"])
events = events[events["pair"].isin(PAIR_MAP)].copy()

events = (
    events.sort_values(["bar_end", "pair", "delta_direction"])
          .drop_duplicates(["pair", "delta_direction", "bar_end"])
          .reset_index(drop=True)
)

records = []
skipped = {}

for number, (_, event) in enumerate(events.iterrows(), start=1):
    try:
        settled, reason = settle_candidate(event)
    except Exception as exc:
        settled, reason = None, f"fetch_or_parse_error:{type(exc).__name__}"

    if settled is None:
        skipped[reason] = skipped.get(reason, 0) + 1
    else:
        records.extend(settled)

    if number % 25 == 0 or number == len(events):
        print(f"Processed {number}/{len(events)} candidates")

    time.sleep(REQUEST_PAUSE_SECONDS)

out = pd.DataFrame(records)

if out.empty:
    raise SystemExit(f"No candidates settled. Skipped: {skipped}")

out.to_csv(OUTPUT, index=False)

print("\nDELTA 15M SUPERTREND EXIT ABLATION")
print(
    f"Candidates={len(events)} | "
    f"Valid same-entry trades/variant={len(out) // 2} | "
    f"Skipped={skipped}"
)
print(
    f"Reference entry=5m signal close | "
    f"Max hold={HORIZON_BARS} completed 15m bars | "
    f"Cost={ROUND_TRIP_COST_PCT:.3f}% round trip | "
    f"ST=({ATR_LENGTH}, {ST_MULTIPLIER})"
)
print("-" * 175)

for variant, group in out.groupby("variant", sort=True):
    summarize(variant, group)

unique_entries = out[["entry_time"]].drop_duplicates().sort_values("entry_time").reset_index(drop=True)
cut = unique_entries.iloc[int(len(unique_entries) * 0.70), 0]
holdout = out[out["entry_time"] >= cut]

print(f"\nCHRONOLOGICAL HOLDOUT: entry_time >= {cut.isoformat()}")
for variant, group in holdout.groupby("variant", sort=True):
    summarize(variant, group)

print("\nBY PAIR — ALL DATA")
for pair, pair_rows in out.groupby("pair", sort=True):
    print(f"\n{pair}")
    for variant, group in pair_rows.groupby("variant", sort=True):
        summarize(variant, group)

print(f"\nWrote: {OUTPUT}")