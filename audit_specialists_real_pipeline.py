from pair_universe import PROP_SYMBOLS, MarketDataSource
from speed_phase import analyze_completed_candles
from hostile_sentinel_analyzer import HostileActivitySentinel

def run_real_pipeline_sl_tp_audit():
    mds = MarketDataSource()
    sentinel = HostileActivitySentinel(hostility_threshold=0.80)
    
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
    print("PRISM SPECIALIST REAL-PIPELINE SL/TP AUDIT (DETERMINISTIC SPEED & SENTINEL)")
    print("=" * 80)
    
    for symbol in PROP_SYMBOLS:
        candles = mds.fetch_5m_candles(symbol, min_candles=60)
        if len(candles) < 45:
            continue
            
        for i in range(40, len(candles) - 15):
            window = candles[:i+1]
            current = candles[i]
            entry_price = current["close"]
            if entry_price <= 0:
                continue
                
            # 1. Deterministic Speed Phase Check
            speed_result = analyze_completed_candles(window)
            speed_phase = speed_result.get("phase", "NONE")
            if speed_phase == "NONE" or speed_phase == "DECAY":
                continue
                
            # 2. Derive CVD slope & RTS state from speed phase
            if speed_phase == "REACCELERATION":
                cvd_slope = "DIVERGENT"
                rts_state = "ALIGNED"
            elif speed_phase == "CONTROLLED_PULLBACK":
                cvd_slope = "EXPANDING"
                rts_state = "ALIGNED"
            else:
                cvd_slope = "FLAT"
                rts_state = "NEUTRAL"
                
            # 3. Spatial Envelope & Fair-Pricing Gate (±1.0 std dev from 390-period mean)
            sub_window = window[-40:]
            closes = [c["close"] for c in sub_window]
            mean_390 = sum(closes) / len(closes)
            variance = sum((c - mean_390) ** 2 for c in closes) / len(closes)
            std_390 = variance ** 0.5 if variance > 0 else entry_price * 0.01
            distance_from_mean = (entry_price - mean_390) / std_390 if std_390 > 0 else 0.0
            
            if abs(distance_from_mean) > 1.0:
                continue
                
            # 4. Volume & Anti-Delta Gate
            price_range = current["high"] - current["low"]
            anti_delta_score = int(min(100.0, (price_range / entry_price) * 5000))
            avg_vol = sum(c["volume"] for c in sub_window[-10:]) / 10 if len(sub_window) >= 10 else 1.0
            vol_expansion = current["volume"] / max(1.0, avg_vol)
            
            if anti_delta_score > 75 or vol_expansion < 0.8:
                continue
                
            # 5. Hostile Activity Sentinel Veto Check
            is_hostile, _, _ = sentinel.evaluate_hostility({
                "offensive_review": {
                    "speed_phase": speed_phase,
                    "cvd_slope_state": cvd_slope,
                    "anti_delta_score": anti_delta_score,
                    "rts_state": rts_state
                }
            })
            if is_hostile:
                continue
                
            # 6. Regime Specialist Routing
            abs_dist = abs(distance_from_mean)
            if abs_dist < 0.5:
                setup_name = "prism_range_mean_reversion_v1" if speed_phase != "REACCELERATION" else "prism_shelf_absorption_fade_v1"
            elif abs_dist >= 0.8:
                setup_name = "prism_momentum_expansion_breakout_v1"
            else:
                setup_name = "reacceleration_reclaim_continuation_v1" if speed_phase == "REACCELERATION" else "momentum_expansion_continuation_v1"
                
            mult = specialists[setup_name]
            stop_pct = 0.010 if symbol in ["BTC", "ETH"] else (0.015 if entry_price > 50.0 else 0.020)
            is_long = distance_from_mean <= 0.0
            
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
    run_real_pipeline_sl_tp_audit()
