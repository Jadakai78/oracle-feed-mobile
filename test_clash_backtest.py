import random
from pair_universe import PROP_SYMBOLS, MarketDataSource

def run_clash_health_backtest():
    mds = MarketDataSource()
    print("📊 Initializing Clash-Weighted Health Decay & Early-Exit Backtest...")
    
    total_tested = 0
    trades_executed = 0
    hits = 0
    stopped = 0
    timed_out = 0
    clash_cut_exits = 0
    pnl_accumulator = 0.0
    
    for symbol in PROP_SYMBOLS:
        candles = mds.fetch_5m_candles(symbol, min_candles=100)
        if len(candles) < 50:
            continue
            
        for i in range(40, len(candles) - 18):
            window = candles[i-40:i]
            current_candle = candles[i]
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
                
            is_long = entry >= mean_390 and current_candle["close"] > current_candle["open"] and vol_expansion > 1.1
            is_short = entry <= mean_390 and current_candle["close"] < current_candle["open"] and vol_expansion > 1.1
            
            if not is_long and not is_short:
                continue
                
            trades_executed += 1
            stop = (lower_band_3 - (std_390 * 0.1)) if is_long else (upper_band_3 + (std_390 * 0.1))
            target = upper_band_2 if is_long else lower_band_2
            
            # Forward Execution Simulation with Clash Health Monitoring
            resolved = False
            future_slice = candles[i+1:i+19]
            health_score = 100
            
            for step, fc in enumerate(future_slice, start=1):
                current_price = fc["close"]
                price_delta_pct = ((current_price - entry) / entry) * 100 if is_long else ((entry - current_price) / entry) * 100
                
                # Simulate tape aggression for this candle step
                green_agg = random.randint(50, 400)
                red_agg = random.randint(50, 400)
                
                dominant_agg = green_agg if is_long else red_agg
                opposing_agg = red_agg if is_long else green_agg
                
                penalty = 0
                if price_delta_pct < 0:
                    penalty += abs(price_delta_pct) * 20
                if opposing_agg > dominant_agg:
                    dominance_ratio = opposing_agg / max(1, dominant_agg)
                    penalty += (dominance_ratio - 1.0) * 30
                    
                health_score = max(0, int(health_score - penalty))
                
                # Check for Clash-Health Early Exit (Cut trade before hard stop if tape flips completely)
                if health_score <= 15:
                    clash_cut_exits += 1
                    # Small realized loss or scratch instead of full -1.0R stop out
                    pnl_accumulator -= 0.35
                    resolved = True
                    break
                
                if is_long:
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
                ret = (entry - exit_price) / entry if is_short else (exit_price - entry) / entry
                pnl_accumulator += (ret * 100)

    print("\n==================================================")
    print("      CLASH-WEIGHTED HEALTH BACKTEST REPORT       ")
    print("==================================================")
    print(f"Total Vectors Scanned: {total_tested}")
    print(f"Total Trades Executed: {trades_executed}")
    if trades_executed > 0:
        win_rate = (hits / trades_executed) * 100
        print(f"Empirical Win Rate: {win_rate:.1f}%")
        print(f"  - Target Hits: {hits}")
        print(f"  - Structural Stop-Outs: {stopped}")
        print(f"  - Clash-Health Early Cuts: {clash_cut_exits}")
        print(f"  - 90m Timeouts: {timed_out}")
        print(f"Net Cumulative R-Expectancy: {pnl_accumulator:.2f}R")
    print("==================================================")

if __name__ == "__main__":
    run_clash_health_backtest()
