from pair_universe import PROP_SYMBOLS, MarketDataSource

def run_bleed_filter_backtest():
    mds = MarketDataSource()
    print("📊 Initializing Clean-Bleed Filter Optimization Test...")
    
    base_trades = 0
    base_wins = 0
    base_pnl = 0.0
    
    filt_trades = 0
    filt_wins = 0
    filt_pnl = 0.0
    
    for symbol in PROP_SYMBOLS:
        candles = mds.fetch_5m_candles(symbol, min_candles=100)
        if len(candles) < 50:
            continue
            
        for i in range(40, len(candles) - 18):
            window = candles[i-40:i]
            current_candle = candles[i]
            
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
            
            avg_vol = sum(c["volume"] for c in window[-10:]) / 10
            vol_expansion = current_candle["volume"] / max(1.0, avg_vol)
            
            distance_from_mean = abs(entry - mean_390) / std_390 if std_390 > 0 else 999.0
            if distance_from_mean > 1.0 or vol_expansion < 0.9:
                continue
                
            t1_long = entry >= mean_390
            future_slice = candles[i+1:i+19]
            if not future_slice:
                continue
                
            # Simulate baseline outcome
            b_res = simulate_trade(future_slice, t1_long, lower_band_3, upper_band_3, upper_band_2, lower_band_2, entry)
            base_trades += 1
            if b_res["won"]:
                base_wins += 1
            base_pnl += b_res["pnl"]
            
            # Filtered run: Enforce minimum body commitment and stronger volume expansion to starve clean bleeds
            body = abs(current_candle["close"] - current_candle["open"])
            is_choppy = body < (price_range * 0.35)
            is_weak_vol = vol_expansion < 1.15
            
            if not is_choppy and not is_weak_vol:
                filt_trades += 1
                if b_res["won"]:
                    filt_wins += 1
                filt_pnl += b_res["pnl"]

    print("\n==================================================")
    print("      CLEAN-BLEED FILTER COMPARISON REPORT        ")
    print("==================================================")
    print(f"Baseline (Test 1):")
    print(f"  - Trades: {base_trades} | Win Rate: {(base_wins/max(1,base_trades))*100:.1f}% | Net R: {base_pnl:.2f}R")
    print(f"Filtered (Anti-Bleed Gate):")
    print(f"  - Trades: {filt_trades} | Win Rate: {(filt_wins/max(1,filt_trades))*100:.1f}% | Net R: {filt_pnl:.2f}R")
    print("==================================================")

def simulate_trade(future_slice, is_long, stop_long, stop_short, target_long, target_short, entry):
    stop = stop_long if is_long else stop_short
    target = target_long if is_long else target_short
    resolved = False
    won = False
    pnl = 0.0
    
    for fc in future_slice:
        if is_long:
            if fc["low"] <= stop:
                pnl = -1.0; resolved = True; break
            elif fc["high"] >= target:
                won = True; pnl = 1.8; resolved = True; break
        else:
            if fc["high"] >= stop:
                pnl = -1.0; resolved = True; break
            elif fc["low"] <= target:
                won = True; pnl = 1.8; resolved = True; break
                
    if not resolved:
        exit_p = future_slice[-1]["close"]
        ret = (exit_p - entry) / entry if is_long else (entry - exit_p) / entry
        pnl = (ret * 100)
        if pnl > 0:
            won = True
            
    return {"won": won, "pnl": pnl}

if __name__ == "__main__":
    run_bleed_filter_backtest()
