"""Kraken Pro Master Execution Engine (December/April Unified Architecture).
Supports dynamic account sizing (10k / 50k), 9/3/3 Guardrails, Elite Whitelist, 
and Tiered Leverage Margin Validation (5x - 20x).
"""
from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class MasterEngine:
    def __init__(self, initial_balance: float = 10000.0, leverage_tiers: dict | None = None):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.peak_balance = initial_balance
        self.daily_balance_start = initial_balance
        
        # Prop Firm Thresholds (9% Target, 3% Daily DD, 3% Total DD)
        self.profit_target = initial_balance * 0.09   # $900 for 10k, $4500 for 50k
        self.max_daily_loss = initial_balance * 0.03  # $300 for 10k, $1500 for 50k
        self.max_total_dd = initial_balance * 0.03    # $300 for 10k, $1500 for 50k
        
        # Elite Setup Whitelist & Risk Multipliers
        self.elite_whitelist = {
            "sell_absorption_reclaim_v1": {"target_win_rate": 0.44, "sl_tp_mult": 3.5},
            "reacceleration_reclaim_continuation_v1": {"target_win_rate": 0.39, "sl_tp_mult": 4.0},
            "momentum_expansion_continuation_v1": {"target_win_rate": 0.29, "sl_tp_mult": 4.5}
        }
        
        # Dynamic Risk Allocation (0.75% equity-scaled risk per trade)
        self.base_risk_pct = 0.0075  
        
        # Asset Leverage Tiers (Kraken Pro Standards)
        # BTC/ETH: 20x (5% initial margin), Alts/Others: 5x (20% margin) or 2x
        self.leverage_tiers = leverage_tiers or {
            "BTCUSD": 20,
            "ETHUSD": 20,
            "SOLUSD": 5,
            "XRPUSD": 5,
            "DEFAULT": 5
        }

    def evaluate_guardrails(self) -> tuple[bool, str]:
        total_dd = self.peak_balance - self.balance
        daily_loss = self.daily_balance_start - self.balance
        
        if total_dd >= self.max_total_dd:
            return False, f"Max Total Drawdown Breached (${total_dd:.2f} >= ${self.max_total_dd})"
        if daily_loss >= self.max_daily_loss:
            return False, f"Max Daily Loss Breached (${daily_loss:.2f} >= ${self.max_daily_loss})"
        if self.balance >= (self.initial_balance + self.profit_target):
            return True, f"Profit Target Reached (${self.profit_target:.2f})"
            
        return True, "Within Limits"

    def validate_margin(self, asset: str, notional_value: float) -> tuple[bool, str]:
        leverage = self.leverage_tiers.get(asset, self.leverage_tiers["DEFAULT"])
        required_margin = notional_value / leverage
        
        if required_margin > self.balance:
            return False, f"Required margin ${required_margin:.2f} exceeds balance"
        return True, f"Margin OK (Req: ${required_margin:.2f} at {leverage}x)"

    def execute_signal(self, setup_family: str, asset: str, stop_distance_pct: float) -> dict:
        if setup_family not in self.elite_whitelist:
            logging.warning(f"Rejected setup {setup_family}: Not in elite whitelist.")
            return {"status": "REJECTED", "reason": "Not Whitelisted"}
            
        active, status_msg = self.evaluate_guardrails()
        if not active:
            logging.error(f"Execution halted: {status_msg}")
            return {"status": "HALTED", "reason": status_msg}
            
        risk_amount = self.balance * self.base_risk_pct
        position_notional = risk_amount / max(stop_distance_pct, 0.001)
        
        margin_ok, margin_msg = self.validate_margin(asset, position_notional)
        if not margin_ok:
            logging.error(f"Margin rejection for {asset}: {margin_msg}")
            return {"status": "REJECTED", "reason": f"Margin Constraint: {margin_msg}"}
            
        logging.info(f"EXECUTING {setup_family} on {asset} | Risk: ${risk_amount:.2f} | Notional: ${position_notional:.2f} | {margin_msg}")
        return {
            "status": "EXECUTED",
            "setup_family": setup_family,
            "asset": asset,
            "allocated_risk": risk_amount,
            "position_notional": position_notional,
            "current_balance": self.balance
        }

if __name__ == "__main__":
    engine = MasterEngine(initial_balance=10000.0)
    logging.info("Master Engine (Unified December/April Mode) initialized successfully.")
