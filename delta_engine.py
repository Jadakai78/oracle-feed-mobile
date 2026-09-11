"""
Speed-Optimized Delta Consumer Engine
Handles multi-threaded conversion and immediate dispatching to PRISM.
"""
import concurrent.futures
from typing import Callable, Dict, Any, List
from prism_adapter import DeltaTempoPRISMAdapter

class SpeedDeltaEngine:
    def __init__(self, publisher_func: Callable[[Dict[str, Any]], None], max_workers: int = 8):
        self.publisher_func = publisher_func
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

    def on_raw_ticks_received(self, raw_ticks: List[Dict[str, Any]]) -> None:
        """Consumes a batch of raw ticks and distributes processing across worker threads."""
        for tick in raw_ticks:
            self.executor.submit(self._process_single, tick)

    def _process_single(self, raw_tick: Dict[str, Any]) -> None:
        try:
            DeltaTempoPRISMAdapter.process_and_send(raw_tick, self.publisher_func)
        except Exception as err:
            # Silently catch to prevent blocking line-rate execution
            pass

    def shutdown(self) -> None:
        """Gracefully drain and close thread pool workers."""
        self.executor.shutdown(wait=True)
