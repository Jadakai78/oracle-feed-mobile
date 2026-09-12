import time
from pair_universe import PROP_SYMBOLS, MarketDataSource

def run_production_master_engine():
    mds = MarketDataSource()
    print("🚀 Initializing Production Master Engine (Bollinger 365 Dev 2/3 + KNN Radar + 90m Hold + Dev-3 Wall Stop)...")
    
    total_scanned = 0
    executed_trades = 0
    wins = 0
    stopped_out = 0
    timed_out = 0
    cumulative_r = 0.0
    
    for base in PROP_SYMBOLS:
        candles = mds.fetch_5m_candles(base, min_candles=100)
        if len(candles) < 50:
            continue
            
        for i in range(40, len(candles) - 18):
            window = candles[i-40:i]
            current_candle = candles[i]
            total_scanned += 1
            
            entry = current_candle["close"]
            price_range = current_candle["high"] - current_candle["low"]
            if price_range == 0:
                continue
                
            # 1. Prism Spatial Map: Bollinger 365 proxy using rolling window
            closes = [c["close"] for c in window]
            mean_390 = sum(closes) / len(closes)
            variance = sum((c - mean_390) ** 2 for c in closes) / len(closes)
            std_390 = variance ** 0.5 if variance > 0 else entry * 0.01
            
            upper_band_3 = mean_390 + (3.0 * std_390)
            lower_band_3 = mean_390 - (3.0 * std_390)
            upper_band_2 = mean_390 + (2.0 * std_390)
            lower_band_2 = mean_390 - (2.0 * std_390)
            
            # 2. KNN Radar / Negative-Space Hostility Filter
            anti_delta = min(100.0, (price_range / entry) * 5000)
            avg_vol = sum(c["volume"] for c in window[-10:]) / 10
            vol_expansion = current_candle["volume"] / max(1.0, avg_vol)
            
            if (anti_delta > 40) or (vol_expansion < 0.8):
                continue
                
            # 3. Fair-Pricing Gate (Within ±1.0 std dev value core)
            distance_from_mean = abs(entry - mean_390) / std_390 if std_390 > 0 else 999.0
            if distance_from_mean > 1.0:
                continue
                
            is_long = entry >= mean_390 and current_candle["close"] > current_candle["open"] and vol_expansion > 1.1
            is_short = entry <= mean_390 and current_candle["close"] < current_candle["open"] and vol_expansion > 1.1
            
            if not is_long and not is_short:
                continue
                
            executed_trades += 1
            
            # 4. Structural Invalidation (Anchored strictly behind Dev-3 walls)
            stop = (lower_band_3 - (std_390 * 0.1)) if is_long else (upper_band_3 + (std_390 * 0.1))
            target = upper_band_2 if is_long else lower_band_2
            
            # 5. Forward Execution Simulation (90-minute / 18-candle max window)
            resolved = False
            future_slice = candles[i+1:i+19]
            
            for step, fc in enumerate(future_slice, start=1):
                if is_long:
                    if fc["low"] <= stop:
                        stopped_out += 1
                        cumulative_r -= 1.0
                        resolved = True
                        break
                    elif fc["high"] >= target:
                        wins += 1
                        cumulative_r += 1.8
                        resolved = True
                        break
                else:
                    if fc["high"] >= stop:
                        stopped_out += 1
                        cumulative_r -= 1.0
                        resolved = True
                        break
                    elif fc["low"] <= target:
                        wins += 1
                        cumulative_r += 1.8
                        resolved = True
                        break
                        
            if not resolved:
                timed_out += 1
                exit_price = future_slice[-1]["close"] if future_slice else entry
                ret = (entry - exit_price) / entry if is_short else (exit_price - entry) / entry
                cumulative_r += (ret * 100)

    print("\n==================================================")
    print("      PRODUCTION MASTER ENGINE EXECUTION REPORT   ")
    print("==================================================")
    print(f"Total Vectors Scanned: {total_scanned}")
    print(f"Total Trades Executed: {executed_trades}")
    if executed_trades > 0:
        win_rate = (wins / executed_trades) * 100
        print(f"Empirical Win Rate: {win_rate:.1f}%")
        print(f"  - Target Hits: {wins}")
        print(f"  - Structural Stop-Outs: {stopped_out}")
        print(f"  - 90m Timeouts: {timed_out}")
        print(f"Net Cumulative R-Expectancy: {cumulative_r:.2f}R")
    print("==================================================")

if __name__ == "__main__":
    run_production_master_engine()
