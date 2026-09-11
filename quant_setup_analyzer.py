"""
Quantitative Setup Analyzer & Statistical Edge Engine
------------------------------------------------------
Evaluates historical candidate cards against forward outcome data
to compute Win Rate, Expected Value (EV), and Profit Factor across setup clusters.

Includes exporter methods for JSON and CSV disk persistence.
"""

import csv
import json
from typing import Any, Dict, List, Optional


class QuantSetupAnalyzer:

    def __init__(
        self,
        min_sample_size: int = 30,
        min_ev_r: float = 0.50,
        min_win_rate_pct: float = 55.0,
    ):
        self.trades: List[Dict[str, Any]] = []
        self.min_sample_size = min_sample_size
        self.min_ev_r = min_ev_r
        self.min_win_rate_pct = min_win_rate_pct

    def record_snapshot_outcome(
        self, candidate_card: Dict[str, Any], forward_return_r: float
    ) -> None:
        """
        Record a candidate card's setup characteristics and its eventual R-multiple return.
        """
        review = candidate_card.get("offensive_review", {})

        feature_key = (
            f"PRISM:{review.get('prism_state', 'UNAVAILABLE')}|"
            f"SPEED:{review.get('speed_phase', 'UNKNOWN')}|"
            f"RECLAIM:{review.get('reclaim_confirmed', False)}|"
            f"CVD_SLOPE:{review.get('cvd_slope_state', 'FLAT')}"
        )

        self.trades.append(
            {
                "pair": candidate_card.get("pair", "UNKNOWN"),
                "feature_key": feature_key,
                "posture": review.get("offensive_posture", "UNKNOWN"),
                "r_return": forward_return_r,
                "win": forward_return_r > 0,
            }
        )

    def generate_expectancy_report(self) -> Dict[str, Dict[str, Any]]:
        """
        Groups outcomes by setup feature key and calculates quantitative performance metrics.
        Enforces statistical confidence thresholds (N >= 30, EV >= +0.50R).
        """
        clusters: Dict[str, List[float]] = {}
        for trade in self.trades:
            key = trade["feature_key"]
            if key not in clusters:
                clusters[key] = []
            clusters[key].append(trade["r_return"])

        report = {}
        for key, returns in clusters.items():
            total_trades = len(returns)
            wins = [r for r in returns if r > 0]
            losses = [r for r in returns if r <= 0]

            win_rate = (len(wins) / total_trades) * 100 if total_trades > 0 else 0.0
            gross_gains = sum(wins)
            gross_losses = abs(sum(losses)) if losses else 1e-6
            profit_factor = gross_gains / gross_losses
            ev_per_trade = sum(returns) / total_trades if total_trades > 0 else 0.0

            # Quant Rule: Must pass Sample Size AND EV AND Win Rate thresholds
            has_sample_size = total_trades >= self.min_sample_size
            has_positive_ev = ev_per_trade >= self.min_ev_r
            has_win_rate = win_rate >= self.min_win_rate_pct

            if has_sample_size and has_positive_ev and has_win_rate:
                recommended_posture = "PRIORITY_REVIEW"
                confidence_status = "STATISTICALLY_VALIDATED"
            elif not has_sample_size:
                recommended_posture = "OBSERVE"
                confidence_status = f"INSUFFICIENT_DATA (N={total_trades}/{self.min_sample_size})"
            else:
                recommended_posture = "STAND_DOWN"
                confidence_status = "NEGATIVE_OR_WEAK_EV"

            report[key] = {
                "sample_size": total_trades,
                "win_rate_pct": round(win_rate, 2),
                "profit_factor": round(profit_factor, 2),
                "expected_value_r": round(ev_per_trade, 3),
                "confidence_status": confidence_status,
                "recommended_posture": recommended_posture,
            }

        return report

    def export_report_to_json(self, filepath: str) -> None:
        """
        Exports the setup expectancy report as formatted JSON to disk.
        """
        report = self.generate_expectancy_report()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    def export_report_to_csv(self, filepath: str) -> None:
        """
        Exports the setup expectancy report as tabular CSV data to disk.
        """
        report = self.generate_expectancy_report()
        headers = [
            "feature_key",
            "sample_size",
            "win_rate_pct",
            "profit_factor",
            "expected_value_r",
            "confidence_status",
            "recommended_posture",
        ]

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for key, metrics in report.items():
                row = {"feature_key": key}
                row.update(metrics)
                writer.writerow(row)
