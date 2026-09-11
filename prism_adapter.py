"""
PRISM Execution Schema Adapter
Translates high-speed Delta/Tempo scanner ticks into PRISM-compliant payloads.
"""
from typing import Dict, Any, Callable

class DeltaTempoPRISMAdapter:
    REQUIRED_INPUT_KEYS = {"sym", "msg_type", "bid", "ask", "sz"}

    @classmethod
    def transform(cls, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        """Validates and converts scanner dict to PRISM execution schema."""
        missing = cls.REQUIRED_INPUT_KEYS - raw_event.keys()
        if missing:
            raise KeyError(f"Missing required fields from scanner feed: {missing}")

        return {
            "venue": "PROP",
            "recordtype": str(raw_event["msg_type"]).upper(),
            "symbol": str(raw_event["sym"]).upper(),
            "bid_price": float(raw_event["bid"]),
            "ask_price": float(raw_event["ask"]),
            "qty": int(raw_event["sz"]),
            "manual_review_only": bool(raw_event.get("flag_manual", False)),
            "universe": raw_event.get("universe", "GLOBAL")
        }

    @classmethod
    def process_and_send(cls, raw_event: Dict[str, Any], publisher_func: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
        """Transforms and immediately forwards payload to the target publisher function."""
        prism_payload = cls.transform(raw_event)
        publisher_func(prism_payload)
        return prism_payload
