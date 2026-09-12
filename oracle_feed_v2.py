\"\"\"Oracle Feed v2: High-Performance Systematic Signal Generator
Unified December/April Architecture with Full Prism Terrain & Regime-Aware Multipliers.
\"\"\"
from __future__ import annotations

import json
from datetime import datetime, timezone
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class OracleFeedV2:
    def __init__(self, account_balance: float = 10000.0):
        self.account_balance = account_balance
        # Regime-aware specialist whitelist matching PRISM topographical states
        self.elite_whitelist = {
            "prism_range_mean_reversion_v1": {"multiplier": 1.62, "target_win_rate": 0.58},
            "prism_shelf_absorption_fade_v1": {"multiplier": 2.10, "target_win_rate": 0.52},
            "prism_momentum_expansion_breakout_v1": {"multiplier": 3.50, "target_win_rate": 0.35},
            "sell_absorption_reclaim_v1": {"multiplier": 2.20, "target_win_rate": 0.48},
            "reacceleration_reclaim_continuation_v1": {"multiplier": 2.50, "target_win_rate": 0.44},
            "momentum_expansion_continuation_v1": {"multiplier": 3.00, "target_win_rate": 0.38}
        }
        self.leverage_tiers = {
            "BTCUSD": 20,
            "ETHUSD": 20,
            "SOLUSD": 5,
            "DEFAULT": 5
        }

    def generate_feed(self, raw_market_candidates: list[dict]) -> dict:
        timestamp = datetime.now(timezone.utc).isoformat()
        processed_signals = []
        
        for candidate in raw_market_candidates:
            pair = candidate.get("pair", "UNKNOWN")
            setup = candidate.get("setup_family", "prism_range_mean_reversion_v1")
            stop_dist = candidate.get("stop_distance_pct", 0.01)
            
            if setup not in self.elite_whitelist:
                setup = "prism_range_mean_reversion_v1"
                
            config = self.elite_whitelist[setup]
            leverage = self.leverage_tiers.get(pair, self.leverage_tiers["DEFAULT"])
            
            # 0.75% Equity-Scaled Risk
            risk_amt = self.account_balance * 0.0075
            notional = risk_amt / max(stop_dist, 0.001)
            margin_req = notional / leverage
            
            signal_entry = {
                "pair": pair,
                "setup_family": setup,
                "allocation": {
                    "risk_usd": round(risk_amt, 2),
                    "notional_usd": round(notional, 2),
                    "margin_required_usd": round(margin_req, 2),
                    "leverage": leverage
                },
                "parameters": {
                    "sl_tp_multiplier": config["multiplier"],
                    "target_win_rate": config["target_win_rate"]
                },
                "status": "ARMED_AND_READY"
            }
            processed_signals.append(signal_entry)
            
        feed_payload = {
            "version": "v2.1-PRISM",
            "architecture": "December/April Unified + PRISM Terrain Mainframe",
            "generated_at_utc": timestamp,
            "account_equity": self.account_balance,
            "active_signals_count": len(processed_signals),
            "signals": processed_signals
        }
        
        return feed_payload

if __name__ == "__main__":
    generator = OracleFeedV2(account_balance=10000.0)
    sample_data = [
        {"pair": "BTCUSD", "setup_family": "prism_momentum_expansion_breakout_v1", "stop_distance_pct": 0.008},
        {"pair": "SOLUSD", "setup_family": "prism_range_mean_reversion_v1", "stop_distance_pct": 0.015}
    ]
    feed = generator.generate_feed(sample_data)
    logging.info(json.dumps(feed, indent=2))
