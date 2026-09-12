import random
from pair_universe import PROP_SYMBOLS, MarketDataSource

def run_pure_sl_tp_audit():
    mds = MarketDataSource()
    
    # PRISM Specialist multipliers we established
    specialists = {
        "prism_range_mean_reversion_v1": 1.62,
        "prism_shelf_absorption_fade_v1": 2.10,
        "prism_momentum_expansion_breakout_v1": 3.50,
        "sell_absorption_reclaim_v1": 2.20,
        "reacceleration_reclaim_continuation_v1": 2.50,
        "momentum_expansion_continuation_v1": 3.00
    }
    
    stats = {setup: {"wins": 0, "losses": 0, "total": 0} for setup in specialists}
    
    print("=" * 70)
    print("PRISM SPECIALIST RAW SL/TP HIT-RATE AUDIT (TIMELINE-AGNOSTIC)")
    print("=" * 70)
    
    for symbol in PROP_SYMBOLS:
        candles = mds.fetch_5m_candles(symbol, min_candles=100)
        if len(candles) < 30:
            continue
            
        # Simulate trades across historical windows
        for i in range(20, len(candles) - 15):
            entry_candle = candles[i]
            entry_price = entry_candle["close"]
            if entry_price <= 0:
                continue
                
            # Determine stop distance based on asset tier
            stop_pct = 0.010 if symbol in ["BTC", "ETH"] else (0.015 if entry_price > 50.0 else 0.020)
            
            # Pick a specialist regime
            setup_name = random.choice(list(specialists.keys()))
            mult = specialists[setup_name]
            
            # Test both Long and Short edge
            for is_long in [True, False]:
                if is_long:
                    stop_price = entry_price * (1.0 - stop_pct)
                    target_price = entry_price * (1.0 + (stop_pct * mult))
                else:
                    stop_price = entry_price * (1.0 + stop_pct)
                    target_price = entry_price * (1.0 - (stop_pct * mult))
                
                hit_result = None
                # Walk forward through subsequent candles until SL or TP is breached
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
                        # Ambiguous intra-candle crossover: conservative tie-breaker to SL
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
    print("-" * 70)
    for setup, data in stats.items():
        total = data["total"]
        if total > 0:
            win_rate = (data["wins"] / total) * 100
            print(f"{setup:<38} | {win_rate:>6.1f}%    | {data['wins']} / {data['losses']} / {total}")
        else:
            print(f"{setup:<38} |    N/A     | 0 / 0 / 0")
    print("=" * 70)

if __name__ == "__main__":
    run_pure_sl_tp_audit()
