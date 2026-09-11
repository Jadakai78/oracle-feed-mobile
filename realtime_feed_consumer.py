"""
Real-Time Feed Consumer Module
--------------------------------
Ingests live orderbook updates, maintains real-time CVD (Cumulative Volume Delta)
and L2 depth state, enriches candidate cards, and evaluates postures via offensive_review_v1.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from offensive_review_v1 import build_offensive_review


class OrderbookState:
    """Maintains L2 orderbook depth and rolling CVD for a single trading pair."""

    def __init__(self, pair: str, max_cvd_bars: int = 10):
        self.pair = pair
        self.bids: Dict[float, float] = {}  # price -> size
        self.asks: Dict[float, float] = {}  # price -> size
        self.current_delta: float = 0.0
        self.cvd_series: List[float] = [0.0]
        self.max_cvd_bars = max_cvd_bars

    def update_orderbook(
        self,
        bids: List[List[float]],
        asks: List[List[float]],
        trade_delta: Optional[float] = None,
    ) -> None:
        """Updates internal orderbook state and appends trade delta to CVD series."""
        for price, size in bids:
            if size == 0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = size

        for price, size in asks:
            if size == 0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = size

        if trade_delta is not None:
            self.current_delta = trade_delta
            new_cvd = self.cvd_series[-1] + trade_delta
            self.cvd_series.append(round(new_cvd, 4))
            if len(self.cvd_series) > self.max_cvd_bars:
                self.cvd_series.pop(0)

    def get_delta_cvd_payload(self) -> Dict[str, Any]:
        """Returns delta and CVD series formatted for offensive review engine."""
        return {
            "delta_value": self.current_delta,
            "cvd_series": list(self.cvd_series),
        }


class RealTimeFeedConsumer:
    """
    Consumer pipeline bridging candidate cards, orderbook streams,
    and the quantitative offensive review engine.
    """

    def __init__(
        self, expectancy_report: Optional[Dict[str, Dict[str, Any]]] = None
    ):
        self.orderbooks: Dict[str, OrderbookState] = {}
        self.expectancy_report = expectancy_report

    def get_or_create_orderbook(self, pair: str) -> OrderbookState:
        if pair not in self.orderbooks:
            self.orderbooks[pair] = OrderbookState(pair)
        return self.orderbooks[pair]

    def ingest_orderbook_tick(
        self,
        pair: str,
        bids: List[List[float]],
        asks: List[List[float]],
        trade_delta: Optional[float] = None,
    ) -> None:
        """Processes incoming market depth and trade delta stream."""
        ob = self.get_or_create_orderbook(pair)
        ob.update_orderbook(bids, asks, trade_delta)

    def process_candidate_card(
        self, candidate_card: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enriches incoming card with real-time CVD data and evaluates posture via offensive_review_v1.
        """
        pair = candidate_card.get("pair", "UNKNOWN")
        ob = self.get_or_create_orderbook(pair)

        # Inject real-time orderbook/CVD state
        delta_cvd_input = ob.get_delta_cvd_payload()
        now_utc = datetime.now(timezone.utc).isoformat()

        # Run evaluation through Offensive Review v1 engine
        review = build_offensive_review(
            card=candidate_card,
            now_utc_str=now_utc,
            delta_cvd_input=delta_cvd_input,
            expectancy_report=self.expectancy_report,
        )

        candidate_card["offensive_review"] = review
        return review


# Self-Test Pipeline Demo
async def main():
    print("Initializing Real-Time Feed Consumer Pipeline...")

    # Optional Expectancy Report Overrides
    sample_expectancy_report = {
        "PRISM:AVAILABLE|SPEED:REACCELERATION|RECLAIM:True|CVD_SLOPE:EXPANDING": {
            "sample_size": 35,
            "win_rate_pct": 68.5,
            "profit_factor": 3.2,
            "expected_value_r": 0.85,
            "confidence_status": "STATISTICALLY_VALIDATED",
            "recommended_posture": "PRIORITY_REVIEW",
        }
    }

    consumer = RealTimeFeedConsumer(expectancy_report=sample_expectancy_report)

    # 1. Simulate orderbook ticks & volume delta streaming for BTC/USD
    pair = "BTC/USD"
    print(f"\n[1] Streaming L2 Orderbook ticks for {pair}...")

    consumer.ingest_orderbook_tick(
        pair,
        bids=[[65000.0, 1.5], [64990.0, 3.0]],
        asks=[[65010.0, 2.0]],
        trade_delta=12.5,
    )
    consumer.ingest_orderbook_tick(
        pair, bids=[[65005.0, 2.0]], asks=[[65015.0, 1.0]], trade_delta=18.2
    )
    consumer.ingest_orderbook_tick(
        pair, bids=[[65010.0, 4.0]], asks=[[65020.0, 0.5]], trade_delta=25.0
    )

    # 2. Simulate raw incoming Candidate Card
    raw_card = {
        "pair": pair,
        "oracle_context": {
            "location": "HIGH_CONFLUENCE_SUPPORT",
            "structure": "BULLISH_CONTINUATION",
            "flow": "CONFIRMS",
            "tempo": "EXPANDING",
        },
        "prism": {"state": "AVAILABLE"},
        "delta_tempo_timing": {
            "lifecycle_state": "REACCELERATION",
            "reclaim_confirmed": True,
            "direction": "LONG",
        },
    }

    # 3. Process candidate card through real-time review engine
    print("[2] Processing candidate card through Offensive Review...")
    review = consumer.process_candidate_card(raw_card)

    print("\n" + "=" * 60)
    print("             LIVE OFFENSIVE REVIEW EVALUATION              ")
    print("=" * 60)
    print(f"Pair                 : {review['pair']}")
    print(f"Speed Phase          : {review['speed_phase']}")
    print(f"CVD Slope State      : {review['cvd_slope_state']}")
    print(f"Reclaim Confirmed    : {review['reclaim_confirmed']}")
    print(f"Offensive Posture    : {review['offensive_posture']}")
    print(f"Summary              : {review['summary']}")
    print(f"Manual Review Only   : {review['manual_review_only']}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
