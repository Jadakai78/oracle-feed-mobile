"""Kraken Pro 10k Prop Simulator with Full Setup & Sizing Analytics."""
from __future__ import annotations

import pandas as pd
import numpy as np
from exit_engine import apply_setup_specific_exits

def simulate_kraken_prop_evaluation():
    print("="*80)
    print(" KRAKEN PROP 10K EVALUATION SIMULATOR — ELITE PIPELINE TELEMETRY")
    print("="*80)
    
    # Account Parameters for $10k Kraken Pro tier
    initial_balance = 10000.0
    profit_target = initial_balance * 0.09   # $900.00
    max_daily_loss = initial_balance * 0.03  # $300.00
    max_total_dd = initial_balance * 0.03    # $300.00 (Fixed floor from high-water mark)
    
    # Generate test population across our elite 3 setup families
    np.random.seed(42)
    n = 1500
    families = [
        "sell_absorption_reclaim_v1",
        "reacceleration_reclaim_continuation_v1",
        "momentum_expansion_continuation_v1"
    ]
    
    df_raw = pd.DataFrame({
        "setup_family": np.random.choice(families, size=n, p=[0.4, 0.35, 0.25]),
        "direction": np.random.choice(["LONG", "SHORT"], size=n),
        "entry_price": np.random.uniform(2000, 3000, size=n),
        "atr": np.random.uniform(15, 40, size=n),
        "structural_wick_distance": np.random.uniform(20, 30, size=n),
        "structural_pivot_buffer": np.random.uniform(10, 20, size=n)
    })

    # Pass through elite exit engine to get custom SL/TP brackets
    df_evaluated = apply_setup_specific_exits(df_raw)
    
    trade_history = []
    balance = initial_balance
    peak_balance = initial_balance
    daily_balance_start = initial_balance
    max_observed_dd = 0.0
    
    passed = False
    failed = False
    fail_reason = ""
    
    for idx, row in df_evaluated.iterrows():
        sf = row["setup_family"]
        
        # Determine win probability & R-multiple profile based on setup architecture
        if sf == "sell_absorption_reclaim_v1":
            is_win = np.random.rand() < 0.44
            r_multiple = 3.5 if is_win else -1.0
        elif sf == "reacceleration_reclaim_continuation_v1":
            is_win = np.random.rand() < 0.39
            r_multiple = 4.0 if is_win else -1.0
        else:  # momentum_expansion_continuation_v1
            is_win = np.random.rand() < 0.29
            r_multiple = 4.5 if is_win else -1.0
            
        # Sizing Rule: Risk 0.75% of current equity per trade to insulate against the 3% DD window
        risk_pct = 0.0075
        risk_amount = balance * risk_pct
        pnl = r_multiple * risk_amount
        
        balance += pnl
        
        # Track High-Water Mark & Drawdowns
        if balance > peak_balance:
            peak_balance = balance
            
        total_drawdown_from_peak = peak_balance - balance
        if total_drawdown_from_peak > max_observed_dd:
            max_observed_dd = total_drawdown_from_peak
            
        daily_loss = daily_balance_start - balance
        
        # Check Kraken Pro Rules
        if total_drawdown_from_peak >= max_total_dd:
            failed = True
            fail_reason = f"Max Total Drawdown Breached ({total_drawdown_from_peak:.2f} >= ${max_total_dd})"
            break
            
        if daily_loss >= max_daily_loss:
            failed = True
            fail_reason = f"Max Daily Loss Breached ({daily_loss:.2f} >= ${max_daily_loss})"
            break
            
        trade_history.append({
            "trade_id": idx + 1,
            "setup_family": sf,
            "direction": row["direction"],
            "risk_amount": risk_amount,
            "r_multiple": r_multiple,
            "pnl": pnl,
            "balance": balance,
            "win": is_win
        })
        
        # Check Profit Target (9% = $900 profit)
        if balance >= (initial_balance + profit_target):
            passed = True
            break

    # Convert results to DataFrame for macro telemetry breakdown
    df_trades = pd.DataFrame(trade_history)

    print("\n" + "="*80)
    print(" SIMULATION OUTCOME & PERFORMANCE SUMMARY")
    print("="*80)
    if passed:
        print(f" Status          : [PASSED EVALUATION]")
        print(f" Final Balance   : ${balance:,.2f} (+${balance - initial_balance:,.2f})")
        print(f" Total Trades    : {len(df_trades)}")
        print(f" Max Peak DD     : ${max_observed_dd:.2f} (Limit: ${max_total_dd:.2f})")
    elif failed:
        print(f" Status          : [FAILED EVALUATION]")
        print(f" Reason          : {fail_reason}")
        print(f" Balance at Fail : ${balance:,.2f}")
    else:
        print(f" Status          : [INCOMPLETE / MAX TRADES REACHED]")
        print(f" Final Balance   : ${balance:,.2f}")

    print("\n" + "-"*80)
    print(" SETUP FAMILY BREAKDOWN & SIZING ATTRIBUTION")
    print("-"*80)
    
    if not df_trades.empty:
        summary_rows = []
        for family, group in df_trades.groupby("setup_family"):
            total_t = len(group)
            wins = group[group["win"] == True]
            win_rate = (len(wins) / total_t) * 100 if total_t > 0 else 0.0
            total_pnl = group["pnl"].sum()
            avg_risk = group["risk_amount"].mean()
            gross_profit = group[group["pnl"] > 0]["pnl"].sum()
            gross_loss = abs(group[group["pnl"] < 0]["pnl"].sum())
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
            
            summary_rows.append({
                "Setup Family": family,
                "Count": total_t,
                "Win Rate": f"{win_rate:.1f}%",
                "Avg Risk ($)": f"${avg_risk:.2f}",
                "Net PnL ($)": f"${total_pnl:,.2f}",
                "Profit Factor": f"{profit_factor:.2f}"
            })
            
        df_summary = pd.DataFrame(summary_rows)
        print(df_summary.to_string(index=False))
    
    print("="*80 + "\n")

if __name__ == "__main__":
    simulate_kraken_prop_evaluation()
