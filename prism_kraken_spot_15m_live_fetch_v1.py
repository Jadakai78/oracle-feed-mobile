import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta

OUTPUT_FILE = r"C:\Users\jason\OneDrive\Desktop\jhl_v2\oracle-feed-mobile\prism_kraken_spot_15m_latest.json"

PAIRS = [
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "ADAUSD", 
    "AVAXUSD", "LTCUSD", "LINKUSD", "DOTUSD", "BCHUSD"
]

def fetch_live_kraken_ohlc():
    bars_by_symbol = {}

    for pair in PAIRS:
        url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=15"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    result = data.get("result", {})
                    
                    for k, v in result.items():
                        if k != "last":
                            parsed_bars = []
                            for bar in v[-10:]:
                                interval_start_sec = int(bar[0])
                                # Kraken interval start + 900s = completed 15m bar close UTC
                                bar_close_sec = interval_start_sec + 900
                                bar_close_utc = datetime.fromtimestamp(bar_close_sec, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                                
                                parsed_bars.append({
                                    "timestamp_interval_start": datetime.fromtimestamp(interval_start_sec, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "reference_bar_close_utc": bar_close_utc,
                                    "open": float(bar[1]),
                                    "high": float(bar[2]),
                                    "low": float(bar[3]),
                                    "close": float(bar[4]),
                                    "volume": float(bar[6])
                                })
                            bars_by_symbol[pair] = parsed_bars
        except Exception as e:
            print(f"[-] Failed fetch for {pair}: {e}")

    payload = {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bars": bars_by_symbol
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(payload, f, indent=2)

if __name__ == "__main__":
    fetch_live_kraken_ohlc()
