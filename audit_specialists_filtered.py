import random
from pair_universe import PROP_SYMBOLS, MarketDataSource

def run_filtered_sl_tp_audit():
    mds = MarketDataSource()
    
    specialists = {
        "prism_range_mean_reversion_v1": 1.62,
        "prism_shelf_absorption_fade_v1": 2.10,
        "prism_momentum_expansion_breakout_v1": 3.50,
        "sell_absorption_reclaim_v1": 2.20,
        "reacceleration_reclaim_continuation_v1": 2.50,
        "momentum_expansion_continuation_v1": 3.00
    }
    
    stats = {setup: {"wins": 0, "losses": 0, "total": 0, "veto_blocked": 0} for setup in specialists}
    
    print("=" * 80)
    print("PRISM SPECIALIST FILTERED SL/TP AUDIT (WITH ENVELOPE & FAIR-PRICING GATES)")
    print("=" * 80)
    
    for symbol in PROP_SYMBOLS:
        candles = mds.fetch_5m_candles(symbol, min_candles=100)
        if len(candles) < 40:
            continue
            
        for i in range(35, len(candles) - 15):
            window = candles[i-35:i]
            current = candles[i]
            entry_price = current["close"]
            if entry_price <= 0:
                continue
                
            # 1. Calculate Envelope & Mean Distance (390-period equivalent approximation on window)
            closes = [c["close"] for c in window]
            mean_390 = sum(closes) / len(closes)
            variance = sum((c - mean_390) ** 2 for c in closes) / len(closes)
            std_390 = variance ** 0.5 if variance > 0 else entry_price * 0.01
            distance_from_mean = (entry_price - mean_390) / std_390 if std_390 > 0 else 0.0
            
            # 2. Fair-Pricing Gate Check (Strictly within ±1.0 std dev)
            if abs(distance_from_mean) > 1.0:
                continue
                
            # 3. Volume Expansion & Chop Filter
            avg_vol = sum(c["volume"] for c in window[-10:]) / 10 if len(window) >= 10 else 1.0
            vol_expansion = current["volume"] / max(1.0, avg_vol)
            price_range = current["high"] - current["low"]
            anti_delta = min(100.0, (price_range / entry_price) * 5000) if entry_price > 0 else 0
            
            if anti_delta > 40 or vol_expansion < 0.8:
                continue
                
            # 4. Regime-Aware Routing based on distance from mean
            abs_dist = abs(distance_from_mean)
            if abs_dist < 0.5:
                setup_name = random.choice(["prism_range_mean_reversion_v1", "prism_shelf_absorption_fade_v1"])
            elif abs_dist >= 0.8:
                setup_name = random.choice(["prism_momentum_expansion_breakout_v1", "momentum_expansion_continuation_v1"])
            else:
                setup_name = random.choice(list(specialists.keys()))
                
            mult = specialists[setup_name]
            
            # Asset tier stop distance
            stop_pct = 0.010 if symbol in ["BTC", "ETH"] else (0.015 if entry_price > 50.0 else 0.020)
            is_long = distance_from_mean <= 0.0  # Long when below mean, Short when above
            
            if is_long:
                stop_price = entry_price * (1.0 - stop_pct)
                target_price = entry_price * (1.0 + (stop_pct * mult))
            else:
                stop_price = entry_price * (1.0 + stop_pct)
                target_price = entry_price * (1.0 - (stop_pct * mult))
                
            hit_result = None
            for future_candle in candles[i+1 : i+15]:
                high = future_candle["high"]
                low = future_candle["low"]
                
                if is_long:
                    hit_sl = low <= stop_price
                    hit_tp = high >= target_price
                else:
                    hit_sl = high >= stop_price
                    hit_tp = low <= target_price
                    
                if hit_sl and hit_tp:
                    hit_result = "LOSS"
                    break
                elif hit_sl:
                    hit_result = "LOSS"
                    break
                elif hit_tp:
                    hit_result = "WIN"
                    break
            
            if hit_result:
                stats[setup_name]["total"] += 1
                if hit_result == "WIN":
                    stats[setup_name]["wins"] += 1
                else:
                    stats[setup_name]["losses"] += 1
                    
    print(f"{'SPECIALIST STRATEGY':<38} | {'WIN RATE':<10} | {'W / L / TOTAL'}")
    print("-" * 80)
    for setup, data in stats.items():
        total = data["total"]
        if total > 0:
            win_rate = (data["wins"] / total) * 100
            print(f"{setup:<38} | {win_rate:>6.1f}%    | {data['wins']} / {data['losses']} / {total}")
        else:
            print(f"{setup:<38} |    N/A     | 0 / 0 / 0")
    print("=" * 80)

if __name__ == "__main__":
    run_filtered_sl_tp_audit()
