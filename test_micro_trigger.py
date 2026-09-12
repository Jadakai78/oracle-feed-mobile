import time
from pair_universe import PROP_SYMBOLS, MarketDataSource

def run_delta_micro_trigger_backtest():
    mds = MarketDataSource()
    print(f"📊 Initializing Delta Micro-Trigger Backtest across {len(PROP_SYMBOLS)} symbols...")
    
    total_tested = 0
    trades_executed = 0
    hits = 0
    stopped = 0
    timed_out = 0
    pnl_accumulator = 0.0
    
    for symbol in PROP_SYMBOLS:
        candles = mds.fetch_5m_candles(symbol, min_candles=100)
        if len(candles) < 50:
            continue
            
        for i in range(42, len(candles) - 18):
            window = candles[i-40:i]
            current_candle = candles[i]
            prev_candle_1 = candles[i-1]
            prev_candle_2 = candles[i-2]
            total_tested += 1
            
            entry = current_candle["close"]
            price_range = current_candle["high"] - current_candle["low"]
            if price_range == 0:
                continue
                
            closes = [c["close"] for c in window]
            mean_390 = sum(closes) / len(closes)
            variance = sum((c - mean_390) ** 2 for c in closes) / len(closes)
            std_390 = variance ** 0.5 if variance > 0 else entry * 0.01
            
            upper_band_3 = mean_390 + (3.0 * std_390)
            lower_band_3 = mean_390 - (3.0 * std_390)
            upper_band_2 = mean_390 + (2.0 * std_390)
            lower_band_2 = mean_390 - (2.0 * std_390)
            
            anti_delta = min(100.0, (price_range / entry) * 5000)
            avg_vol = sum(c["volume"] for c in window[-10:]) / 10
            vol_expansion = current_candle["volume"] / max(1.0, avg_vol)
            
            if (anti_delta > 40) or (vol_expansion < 0.8):
                continue
                
            distance_from_mean = abs(entry - mean_390) / std_390 if std_390 > 0 else 999.0
            if distance_from_mean > 1.0:
                continue
                
            # Relaxed micro-compression threshold for realistic fill frequencies
            prev_range_1 = prev_candle_1["high"] - prev_candle_1["low"]
            prev_range_2 = prev_candle_2["high"] - prev_candle_2["low"]
            avg_recent_range = (prev_range_1 + prev_range_2) / 2.0
            is_compressed = avg_recent_range < (std_390 * 0.50) 
            
            candle_span = current_candle["high"] - current_candle["low"]
            if candle_span == 0:
                continue
                
            close_loc_long = (current_candle["close"] - current_candle["low"]) / candle_span
            close_loc_short = (current_candle["high"] - current_candle["close"]) / candle_span
            
            is_long_trigger = (
                entry >= mean_390 and 
                is_compressed and 
                vol_expansion > 1.15 and 
                close_loc_long >= 0.65 and 
                current_candle["close"] > prev_candle_1["high"]
            )
            
            is_short_trigger = (
                entry <= mean_390 and 
                is_compressed and 
                vol_expansion > 1.15 and 
                close_loc_short >= 0.65 and 
                current_candle["close"] < prev_candle_1["low"]
            )
            
            if not is_long_trigger and not is_short_trigger:
                continue
                
            trades_executed += 1
            
            stop = (lower_band_3 - (std_390 * 0.1)) if is_long_trigger else (upper_band_3 + (std_390 * 0.1))
            target = upper_band_2 if is_long_trigger else lower_band_2
            
            resolved = False
            future_slice = candles[i+1:i+19]
            
            for step, fc in enumerate(future_slice, start=1):
                if is_long_trigger:
                    if fc["low"] <= stop:
                        stopped += 1
                        pnl_accumulator -= 1.0
                        resolved = True
                        break
                    elif fc["high"] >= target:
                        hits += 1
                        pnl_accumulator += 1.8
                        resolved = True
                        break
                else:
                    if fc["high"] >= stop:
                        stopped += 1
                        pnl_accumulator -= 1.0
                        resolved = True
                        break
                    elif fc["low"] <= target:
                        hits += 1
                        pnl_accumulator += 1.8
                        resolved = True
                        break
                        
            if not resolved:
                timed_out += 1
                exit_price = future_slice[-1]["close"] if future_slice else entry
                ret = (entry - exit_price) / entry if is_short_trigger else (exit_price - entry) / entry
                pnl_accumulator += (ret * 100)

    print("\n==================================================")
    print("      DELTA MICRO-TRIGGER BACKTEST REPORT         ")
    print("==================================================")
    print(f"Total Vectors Scanned: {total_tested}")
    print(f"Total Trades Executed: {trades_executed}")
    if trades_executed > 0:
        win_rate = (hits / trades_executed) * 100
        print(f"Empirical Win Rate: {win_rate:.1f}%")
        print(f"  - Target Hits: {hits}")
        print(f"  - Stopped Out: {stopped}")
        print(f"  - Timed Out (90m Window): {timed_out}")
        print(f"Cumulative R-Expectancy Proxy: {pnl_accumulator:.2f}R")
    else:
        print("No trades cleared the tight micro-trigger compression gate.")
    print("==================================================")

if __name__ == "__main__":
    run_delta_micro_trigger_backtest()
