import random

def test_clash_health_decay(entry_price, current_price, is_long, initial_health=100):
    """
    Simulates a clash-weighted health score penalty based on delta vs anti-delta aggression.
    """
    # Simulate real-time tape aggression scores
    green_aggression = random.randint(50, 500) # Buying pressure
    red_aggression = random.randint(50, 500)   # Selling pressure
    
    # Calculate price movement delta
    price_delta_pct = ((current_price - entry_price) / entry_price) * 100 if is_long else ((entry_price - current_price) / entry_price) * 100
    
    # Determine dominance penalty
    dominant_side_score = green_aggression if is_long else red_aggression
    opposing_side_score = red_aggression if is_long else green_aggression
    
    # If the opposing side's aggression outpaces our side, or price is negative, apply heavy penalties
    penalty = 0
    if price_delta_pct < 0:
        # Scale penalty directly by how far underwater we are and opposing pressure
        penalty += abs(price_delta_pct) * 15
        
    if opposing_side_score > dominant_side_score:
        # The enemy is winning the fight at the wall
        dominance_ratio = opposing_side_score / max(1, dominant_side_score)
        penalty += (dominance_ratio - 1.0) * 25
        
    current_health = max(0, int(initial_health - penalty))
    
    print(f"Entry: {entry_price} | Current: {current_price} ({price_delta_pct:+.2f}%)")
    print(f"Green Aggression: {green_aggression} | Red Aggression: {red_aggression}")
    print(f"Clash Penalty Applied: -{penalty:.1f} | Adjusted Health Score: {current_health}/100")
    print("-" * 50)
    return current_health

if __name__ == "__main__":
    print("📊 Testing Clash-Weighted Health Decay Model...")
    # Simulate a long position currently underwater by $3 (-0.3%) with opposing pressure winning
    test_clash_health_decay(entry_price=1000.0, current_price=997.0, is_long=True)
    # Simulate a winning long position (+0.5%) with dominant green aggression
    test_clash_health_decay(entry_price=1000.0, current_price=1005.0, is_long=True)
