def calculate_live_health_score(entry_price, current_price, is_long, minutes_remaining, max_minutes=90):
    """
    Calculates a strict, bounded live health score (0-100).
    Penalizes dollar/percentage drawdown and decays rapidly as time expires while underwater.
    """
    health = 100.0
    
    if is_long:
        price_delta_pct = ((current_price - entry_price) / entry_price) * 100
    else:
        price_delta_pct = ((entry_price - current_price) / entry_price) * 100
        
    if price_delta_pct < 0:
        drawdown_penalty = abs(price_delta_pct) * 35.0
        health -= drawdown_penalty
        
    time_elapsed_pct = max(0.0, min(1.0, (max_minutes - minutes_remaining) / max_minutes))
    if price_delta_pct < 0:
        time_urgency_penalty = time_elapsed_pct * 50.0 * abs(price_delta_pct)
        health -= time_urgency_penalty
    else:
        health += min(20.0, price_delta_pct * 10.0)
        
    return round(max(0.0, min(100.0, health)), 1)
