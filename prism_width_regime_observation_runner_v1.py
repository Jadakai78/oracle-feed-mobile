from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from prism_kraken_spot_15m_fetch_v1 import (
    fetch_prism_kraken_spot_15m,
)
from prism_width_regime_ledger_v1 import append_observation
from prism_width_regime_observer_v1 import (
    build_prism_width_regime_observation,
)


FetchRawCandles = Callable[[str], tuple[str, list[list[Any]]]]


def run_observation_cycle(
    canonical_pair: str,
    *,
    audit_path: Path,
    observations_path: Path,
    state_path: Path,
    fetch_raw_candles: FetchRawCandles,
    fetched_at_utc: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one explicit-pair, observation-only PRISM research cycle.

    This function does not loop, request future bars, resolve outcomes, emit
    alerts, change signals, rank routes, or authorize/simulate a trade.
    """
    fetched = fetch_prism_kraken_spot_15m(
        canonical_pair,
        audit_path=audit_path,
        fetch_raw_candles=fetch_raw_candles,
        fetched_at_utc=fetched_at_utc,
    )

    pair = fetched.get("pair", "")
    fetch_state = fetched.get("state", "UNAVAILABLE")
    fetch_reason = fetched.get("reason")

    base_result = {
        "pair": pair,
        "fetch_state": fetch_state,
        "fetch_reason": fetch_reason,
        "observation_id": None,
        "ledger_status": "NO_OBSERVATION",
        "manual_review_only": True,
        "does_not_authorize_trade": True,
        "does_not_simulate_order": True,
    }

    if fetch_state != "AVAILABLE":
        return base_result

    observation = build_prism_width_regime_observation(
        pair=pair,
        bars=fetched.get("bars", []),
        timeframe=fetched.get("timeframe", "15m"),
    )

    if observation is None:
        return base_result

    ledger = append_observation(
        observation,
        observations_path=observations_path,
        state_path=state_path,
        dry_run=dry_run,
    )

    return {
        **base_result,
        "observation_id": observation["observation_id"],
        "ledger_status": ledger["status"],
    }
