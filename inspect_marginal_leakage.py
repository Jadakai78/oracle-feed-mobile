import random

def audit_entry_distribution():
    print("🔍 Inspecting Entry Frequency & Marginal Leakage Zones...")
    random.seed(42)
    
    marginal_count = 0
    elite_count = 0
    vetoed_count = 0
    
    for i in range(1, 501):
        score = random.randint(75, 98)
        anti_delta = random.randint(20, 90)
        cvd_divergent = random.choice([True, False])
        
        if score < 85 or not cvd_divergent:
            marginal_count += 1
        elif score >= 90 and cvd_divergent and anti_delta < 50:
            elite_count += 1
        else:
            vetoed_count += 1
            
    print(f"\n📊 SIGNAL DISTRIBUTION AUDIT (Out of 500 Raw Candidates):")
    print(f" - Elite Sniper Entries (Score 90+, Divergent CVD, Low Anti-Delta): {elite_count} ({(elite_count/500)*100:.1f}%)")
    print(f" - Marginal 'Borderline' Entries (The Leakage Zone):             {marginal_count} ({(marginal_count/500)*100:.1f}%)")
    print(f" - Sentinel Vetoed / Blocked:                                   {vetoed_count} ({(vetoed_count/500)*100:.1f}%)")
    print("\n💡 INSIGHT: If marginal entries are bypassing the gate, account equity will bleed.")
    print("   Action required: Restrict sizing to ZERO for anything outside the Elite bucket.")

if __name__ == "__main__":
    audit_entry_distribution()
