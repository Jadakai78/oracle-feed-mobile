from pathlib import Path
import json
import urllib.parse
import urllib.request
import pandas as pd

ROOT = Path(r"C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba")
EVENTS = pd.read_csv(ROOT / "delta_corrected_tempo_candidates.csv")

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

for pair, x in EVENTS.groupby("pair", sort=True):
    row = x.iloc[0]
    query = urllib.parse.urlencode({
        "pair": PAIR_MAP[pair],
        "interval": 15,
        "since": int(row["bar_end"]) - 7200,
    })
    url = f"https://api.kraken.com/0/public/OHLC?{query}"

    print(f"\n{pair} -> {PAIR_MAP[pair]}")
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read())

        print("API ERRORS:", payload.get("error"))
        result = payload.get("result", {})
        keys = list(result.keys())
        print("RESULT KEYS:", keys)

        candles = next((v for k, v in result.items() if k != "last"), [])
        if candles:
            times = pd.to_datetime(
                [int(float(c[0])) for c in candles],
                unit="s",
                utc=True,
            )
            print(f"CANDLES={len(candles)} RANGE={times.min()} to {times.max()}")
        else:
            print("CANDLES=0")

    except Exception as exc:
        print(f"REQUEST ERROR: {type(exc).__name__}: {exc}")