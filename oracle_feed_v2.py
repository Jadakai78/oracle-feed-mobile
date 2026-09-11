"""Oracle Feed v2: High-Performance Systematic Signal Generator
Unified December/April Architecture with Elite Whitelist & Margin Scaling.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class OracleFeedV2:
    def __init__(self, account_balance: float = 10000.0):
        self.account_balance = account_balance
        self.elite_whitelist = {
            "sell_absorption_reclaim_v1": {"multiplier": 3.5, "target_win_rate": 0.44},
            "reacceleration_reclaim_continuation_v1": {"multiplier": 4.0, "target_win_rate": 0.39},
            "momentum_expansion_continuation_v1": {"multiplier": 4.5, "target_win_rate": 0.29}
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
            setup = candidate.get("setup_family", "sell_absorption_reclaim_v1")
            stop_dist = candidate.get("stop_distance_pct", 0.01)
            
            if setup not in self.elite_whitelist:
                continue
                
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
            "version": "v2.0",
            "architecture": "December/April Unified",
            "generated_at_utc": timestamp,
            "account_equity": self.account_balance,
            "active_signals_count": len(processed_signals),
            "signals": processed_signals
        }
        
        return feed_payload

if __name__ == "__main__":
    generator = OracleFeedV2(account_balance=10000.0)
    sample_data = [
        {"pair": "BTCUSD", "setup_family": "momentum_expansion_continuation_v1", "stop_distance_pct": 0.008},
        {"pair": "SOLUSD", "setup_family": "sell_absorption_reclaim_v1", "stop_distance_pct": 0.015},
        {"pair": "ADA/USD", "setup_family": "reacceleration_reclaim_continuation_v1", "stop_distance_pct": 0.012}
    ]
    feed = generator.generate_feed(sample_data)
    logging.info(json.dumps(feed, indent=2))
