from pair_universe import PROP_SYMBOLS, MarketDataSource

def run_three_tier_phase_backtest():
    mds = MarketDataSource()
    print("📊 Initializing Three-Tier Phase Matrix Backtest...")
    
    total_tested = 0
    
    # Metrics tracking for the 3 Test Branches
    # Test 1: Phase 1 -> 2 (Structural Baseline Entry)
    t1_trades = 0
    t1_pnl = 0.0
    t1_wins = 0
    
    # Test 2: Phase 2 -> 3 (Pure Tape Dominance / Agnostic Winner)
    t2_trades = 0
    t2_pnl = 0.0
    t2_wins = 0
    
    # Test 3: Phase 2 -> 3 (Historical Winner Alignment)
    t3_trades = 0
    t3_pnl = 0.0
    t3_wins = 0
    
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
            
            avg_vol = sum(c["volume"] for c in window[-10:]) / 10
            vol_expansion = current_candle["volume"] / max(1.0, avg_vol)
            
            distance_from_mean = abs(entry - mean_390) / std_390 if std_390 > 0 else 999.0
            if distance_from_mean > 1.0 or vol_expansion < 0.9:
                continue
                
            # Determine historical directional bias (KNN / Mean Deviation context)
            historical_long_bias = entry >= mean_390
            
            # Real-time tape brawl telemetry derived from current candle structure
            body_delta = current_candle["close"] - current_candle["open"]
            tape_green_score = current_candle["volume"] * max(0.01, (current_candle["close"] - current_candle["low"]))
            tape_red_score = current_candle["volume"] * max(0.01, (current_candle["high"] - current_candle["close"]))
            
            is_tape_long_winner = tape_green_score > tape_red_score
            
            future_slice = candles[i+1:i+19]
            if not future_slice:
                continue
                
            # --- TEST 1: Phase 1 -> Phase 2 (Structural Baseline) ---
            t1_trades += 1
            t1_long = historical_long_bias
            t1_resolved = False
            for fc in future_slice:
                stop = lower_band_3 if t1_long else upper_band_3
                target = upper_band_2 if t1_long else lower_band_2
                if t1_long:
                    if fc["low"] <= stop:
                        t1_pnl -= 1.0; t1_resolved = True; break
                    elif fc["high"] >= target:
                        t1_wins += 1; t1_pnl += 1.8; t1_resolved = True; break
                else:
                    if fc["high"] >= stop:
                        t1_pnl -= 1.0; t1_resolved = True; break
                    elif fc["low"] <= target:
                        t1_wins += 1; t1_pnl += 1.8; t1_resolved = True; break
            if not t1_resolved:
                exit_p = future_slice[-1]["close"]
                ret = (exit_p - entry) / entry if t1_long else (entry - exit_p) / entry
                t1_pnl += (ret * 100)

            # --- TEST 2: Phase 2 -> Phase 3 (Agnostic Tape Winner) ---
            t2_trades += 1
            t2_long = is_tape_long_winner
            t2_resolved = False
            for fc in future_slice:
                stop = lower_band_3 if t2_long else upper_band_3
                target = upper_band_2 if t2_long else lower_band_2
                if t2_long:
                    if fc["low"] <= stop:
                        t2_pnl -= 1.0; t2_resolved = True; break
                    elif fc["high"] >= target:
                        t2_wins += 1; t2_pnl += 1.8; t2_resolved = True; break
                else:
                    if fc["high"] >= stop:
                        t2_pnl -= 1.0; t2_resolved = True; break
                    elif fc["low"] <= target:
                        t2_wins += 1; t2_pnl += 1.8; t2_resolved = True; break
            if not t2_resolved:
                exit_p = future_slice[-1]["close"]
                ret = (exit_p - entry) / entry if t2_long else (entry - exit_p) / entry
                t2_pnl += (ret * 100)

            # --- TEST 3: Phase 2 -> Phase 3 (Historical + Tape Winner Alignment) ---
            # Only enter if real-time tape winner matches historical structural bias
            if historical_long_bias == is_tape_long_winner:
                t3_trades += 1
                t3_long = historical_long_bias
                t3_resolved = False
                for fc in future_slice:
                    stop = lower_band_3 if t3_long else upper_band_3
                    target = upper_band_2 if t3_long else lower_band_2
                    if t3_long:
                        if fc["low"] <= stop:
                            t3_pnl -= 1.0; t3_resolved = True; break
                        elif fc["high"] >= target:
                            t3_wins += 1; t3_pnl += 1.8; t3_resolved = True; break
                    else:
                        if fc["high"] >= stop:
                            t3_pnl -= 1.0; t3_resolved = True; break
                        elif fc["low"] <= target:
                            t3_wins += 1; t3_pnl += 1.8; t3_resolved = True; break
                if not t3_resolved:
                    exit_p = future_slice[-1]["close"]
                    ret = (exit_p - entry) / entry if t3_long else (entry - exit_p) / entry
                    t3_pnl += (ret * 100)

    print("\n==================================================")
    print("      THREE-TIER PHASE MATRIX COMPARISON          ")
    print("==================================================")
    print(f"Total Vectors Scanned: {total_tested}")
    print("-" * 50)
    print(f"Test 1 (Structural Baseline):")
    print(f"  - Trades: {t1_trades} | Win Rate: {(t1_wins/max(1,t1_trades))*100:.1f}% | Net R: {t1_pnl:.2f}R")
    print(f"Test 2 (Agnostic Tape Winner):")
    print(f"  - Trades: {t2_trades} | Win Rate: {(t2_wins/max(1,t2_trades))*100:.1f}% | Net R: {t2_pnl:.2f}R")
    print(f"Test 3 (Historical + Tape Aligned):")
    print(f"  - Trades: {t3_trades} | Win Rate: {(t3_wins/max(1,t3_trades))*100:.1f}% | Net R: {t3_pnl:.2f}R")
    print("==================================================")

if __name__ == "__main__":
    run_three_tier_phase_backtest()
