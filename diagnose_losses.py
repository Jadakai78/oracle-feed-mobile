from pair_universe import PROP_SYMBOLS, MarketDataSource

def diagnose_losing_vectors():
    mds = MarketDataSource()
    print("🔍 Dissecting Test 1 Failure Modes & No-Trade Signatures...")
    
    total_losses = 0
    failure_profiles = {
        "low_vol_drift": 0,    # Entered on weak volume expansion (vacuum traps)
        "overextended": 0,     # Too far from mean (chasing extremes)
        "choppy_range": 0,     # Tight prior ranges leading to immediate chop
        "clean_bleed": 0       # Timed out into a stagnant grid
    }
    
    for symbol in PROP_SYMBOLS:
        candles = mds.fetch_5m_candles(symbol, min_candles=100)
        if len(candles) < 50:
            continue
            
        for i in range(40, len(candles) - 18):
            window = candles[i-40:i]
            current_candle = candles[i]
            prev_candle = candles[i-1]
            
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
                
            # Simulate Test 1 outcome
            resolved = False
            trade_lost = False
            for fc in future_slice:
                stop = lower_band_3 if t1_long else upper_band_3
                target = upper_band_2 if t1_long else lower_band_2
                if t1_long:
                    if fc["low"] <= stop:
                        trade_lost = True; resolved = True; break
                    elif fc["high"] >= target:
                        resolved = True; break
                else:
                    if fc["high"] >= stop:
                        trade_lost = True; resolved = True; break
                    elif fc["low"] <= target:
                        resolved = True; break
                        
            if not resolved or trade_lost:
                total_losses += 1
                # Categorize the exact structural failure signature
                if vol_expansion < 1.05:
                    failure_profiles["low_vol_drift"] += 1
                elif distance_from_mean > 0.85:
                    failure_profiles["overextended"] += 1
                elif abs(current_candle["close"] - current_candle["open"]) < (price_range * 0.3):
                    failure_profiles["choppy_range"] += 1
                else:
                    failure_profiles["clean_bleed"] += 1

    print("\n==================================================")
    print("      LOSING VECTORS FAILURE PROFILE (TEST 1)     ")
    print("==================================================")
    print(f"Total Losing / Non-Target Vectors: {total_losses}")
    for profile, count in failure_profiles.items():
        pct = (count / max(1, total_losses)) * 100
        print(f"  - {profile.replace('_', ' ').title()}: {count} ({pct:.1f}%)")
    print("==================================================")

if __name__ == "__main__":
    diagnose_losing_vectors()
