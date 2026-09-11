from pathlib import Path
from collections import defaultdict
import pandas as pd
import numpy as np

ROOT = Path(r"C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba")
PRICE_DIR = ROOT / "finance_5m"
LEDGER = ROOT / "corrected_delta_response_ledger.csv"

ATR_LENGTH = 10
ST_MULTIPLIER = 3.0
HORIZON_BARS = 12
ROUND_TRIP_COST_PCT = 0.10

def supertrend(frame, length=10, multiplier=3.0):
    high = frame["high"].to_numpy(float)
    low = frame["low"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    n = len(frame)

    prev_close = np.r_[np.nan, close[:-1]]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = pd.Series(tr).ewm(alpha=1 / length, adjust=False, min_periods=length).mean().to_numpy()

    hl2 = (high + low) / 2
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    direction = np.full(n, np.nan)

    for i in range(length, n):
        if i == length:
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

    out = frame.copy()
    out["st_direction"] = direction
    return out

def load_bars():
    result = {}

    for path in sorted(PRICE_DIR.glob("*_price_history_external_*_5min.csv")):
        symbol = path.name.split("_price_history_external_")[0]
        pair = symbol[:-3] + "/USD"

        x = pd.read_csv(path)
        x["date"] = pd.to_datetime(x["date"], utc=True, errors="coerce")
        x = x.dropna(subset=["date"]).set_index("date").sort_index()

        for col in ["open", "high", "low", "close", "volume"]:
            x[col] = pd.to_numeric(x[col], errors="coerce")

        x = x.dropna(subset=["open", "high", "low", "close"])

        bars = x.resample("15min", label="left", closed="left").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        ).dropna(subset=["open", "high", "low", "close"])

        result[pair] = supertrend(bars, ATR_LENGTH, ST_MULTIPLIER)

    return result

def signed_return(side, entry, exit_price):
    raw = (exit_price / entry - 1.0) * 100.0
    return raw if side == "UP" else -raw

def settle_trade(bars, entry_time, side):
    index = bars.index
    if entry_time not in index:
        pos = index.searchsorted(entry_time)
    else:
        pos = index.get_loc(entry_time)

    entry_pos = pos + 1
    if entry_pos + HORIZON_BARS >= len(bars):
        return None

    entry_price = float(bars["open"].iloc[entry_pos])
    last_pos = entry_pos + HORIZON_BARS

    control_exit_pos = last_pos
    st_exit_pos = last_pos

    entry_st = bars["st_direction"].iloc[entry_pos]
    if not np.isfinite(entry_st):
        return None

    expected = 1 if side == "UP" else -1
    if entry_st != expected:
        return None

    for i in range(entry_pos + 1, last_pos + 1):
        st = bars["st_direction"].iloc[i]
        if np.isfinite(st) and st != expected:
            st_exit_pos = i
            break

    outcomes = {}
    for name, exit_pos in {
        "CONTROL_12_BAR_CLOSE": control_exit_pos,
        "SUPERTREND_10_3": st_exit_pos,
        "HYBRID_ST_OR_12_BAR": st_exit_pos,
    }.items():
        exit_price = float(bars["open"].iloc[exit_pos])
        gross = signed_return(side, entry_price, exit_price)
        net = gross - ROUND_TRIP_COST_PCT
        outcomes[name] = {
            "entry_time": index[entry_pos],
            "entry_price": entry_price,
            "exit_time": index[exit_pos],
            "exit_price": exit_price,
            "hold_bars": exit_pos - entry_pos,
            "gross_pct": gross,
            "net_pct": net,
            "exit_reason": "SUPERTREND_FLIP" if exit_pos != last_pos else "HORIZON_CLOSE",
        }

    return outcomes

def summarize(name, x):
    if x.empty:
        print(f"{name:42} N=0")
        return

    pnl = x["net_pct"].to_numpy()
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) else np.nan

    ordered = x.sort_values("entry_time")
    equity = ordered["net_pct"].cumsum()
    drawdown = (equity.cummax() - equity).max()

    print(
        f"{name:42} "
        f"N={len(x):4} "
        f"Win={100 * (pnl > 0).mean():6.2f}% "
        f"Avg={pnl.mean():8.4f}% "
        f"Med={np.median(pnl):8.4f}% "
        f"PF={pf:6.2f} "
        f"DD={drawdown:8.4f}% "
        f"Hold={x['hold_bars'].mean():5.2f} "
        f"Flip={100 * (x['exit_reason'] == 'SUPERTREND_FLIP').mean():6.2f}%"
    )

bars_by_pair = load_bars()

events = pd.read_csv(LEDGER)
events["entry_time"] = pd.to_datetime(events["entry_time"], utc=True, errors="coerce")
events = events.dropna(subset=["pair", "delta_direction", "entry_time"])
events = events[events["horizon_bars"] == HORIZON_BARS].copy()

events = (
    events.sort_values("observed_at")
    .drop_duplicates(subset=["pair", "delta_direction", "entry_time"])
    .reset_index(drop=True)
)

rows = []
skipped = defaultdict(int)

for _, event in events.iterrows():
    pair = event["pair"]
    side = event["delta_direction"]

    if pair not in bars_by_pair:
        skipped["missing_pair"] += 1
        continue

    settled = settle_trade(bars_by_pair[pair], event["entry_time"], side)
    if settled is None:
        skipped["missing_bars_or_wrong_st_state"] += 1
        continue

    for variant, outcome in settled.items():
        rows.append({
            "variant": variant,
            "pair": pair,
            "side": side,
            **outcome,
        })

out = pd.DataFrame(rows)

if out.empty:
    raise SystemExit("No valid trades settled. Check event-to-bar timestamp alignment.")

print("\nDELTA 15M EXIT ABLATION")
print(f"Cost: {ROUND_TRIP_COST_PCT:.3f}% round trip | Supertrend: {ATR_LENGTH}, {ST_MULTIPLIER} | Horizon: {HORIZON_BARS} bars")
print(f"Input events: {len(events)} | Valid same-entry trades per variant: {len(out) // 3}")
print(f"Skipped: {dict(skipped)}")
print("-" * 175)

for variant, x in out.groupby("variant", sort=True):
    summarize(variant, x)

cutoff = out["entry_time"].drop_duplicates().sort_values().iloc[int(len(out["entry_time"].drop_duplicates()) * 0.70)]

print(f"\nCHRONOLOGICAL HOLDOUT: entries on/after {cutoff.isoformat()}")
for variant, x in out[out["entry_time"] >= cutoff].groupby("variant", sort=True):
    summarize(variant, x)

print("\nBY PAIR — ALL DATA")
for pair, x in out.groupby("pair", sort=True):
    print(f"\n{pair}")
    for variant, y in x.groupby("variant", sort=True):
        summarize(variant, y)

out.to_csv(ROOT / "delta_15m_supertrend_exit_ablation.csv", index=False)
print(f"\nWrote read-only result ledger: {ROOT / 'delta_15m_supertrend_exit_ablation.csv'}")