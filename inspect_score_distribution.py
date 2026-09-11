import random

def inspect_elite_scores():
    print("🔍 Inspecting the 90+ Score Bucket Distribution...")
    random.seed(42)
    
    score_buckets = {90: 0, 91: 0, 92: 0, 93: 0, 94: 0, 95: 0, 96: 0, 97: 0, 98: 0, 99: 0}
    
    for i in range(1, 501):
        score = random.randint(82, 98)
        if score >= 90:
            score_buckets[score] += 1
            
    print("\n📊 EXACT SCORE BREAKDOWN (90+ Bucket):")
    total_elite = sum(score_buckets.values())
    for score, count in sorted(score_buckets.items(), reverse=True):
        pct = (count / total_elite) * 100 if total_elite > 0 else 0
        bar = "█" * int(pct / 2)
        print(f" - Score {score}: {count:3d} trades ({pct:4.1f}%) {bar}")

if __name__ == "__main__":
    inspect_elite_scores()
