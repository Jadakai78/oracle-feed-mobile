from __future__ import annotations

from math import isfinite
from typing import Any, Dict, List, Optional, Tuple


def _number(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def unavailable(reason: str, source: str = "unavailable") -> Dict[str, Any]:
    return {
        "ready": False,
        "reason": reason,
        "source": source,
        "volume": None,
        "volume_norm": None,
        "volume_state": "unknown",
        "buy_volume": None,
        "sell_volume": None,
        "delta": None,
        "delta_norm": None,
        "delta_state": "unknown",
        "cvd": None,
        "cvd_slope": None,
    }


def compute_bar_delta(trades: List[Dict[str, Any]]) -> Tuple[float, float, float, int]:
    buy_volume = 0.0
    sell_volume = 0.0
    classified = 0
    for trade in trades:
        side = str(trade.get("side", "")).lower()
        size = _number(trade.get("size"))
        if size is None or size <= 0:
            continue
        if side in {"buy", "b"}:
            buy_volume += size
            classified += 1
        elif side in {"sell", "s"}:
            sell_volume += size
            classified += 1
    return buy_volume, sell_volume, buy_volume - sell_volume, classified


def _volume_state(volume: float, volume_ma: float) -> str:
    ratio = volume / volume_ma
    if ratio < 0.5:
        return "thin"
    if ratio > 1.5:
        return "high"
    return "normal"


def _delta_state(delta: float, volume: float, threshold_ratio: float = 0.2) -> str:
    relative_delta = delta / volume
    if relative_delta >= threshold_ratio:
        return "buy"
    if relative_delta <= -threshold_ratio:
        return "sell"
    return "balanced"


def volume_specialist(
    trades_bar: List[Dict[str, Any]],
    ohlcv: Dict[str, Any],
    vol_ma: Any,
    prev_cvd: Any,
    prev_cvd_window: List[float],
    cvd_window_size: int = 20,
    source: str = "trade_executions",
) -> Dict[str, Any]:
    """Return pressure fields for one completed pair/timeframe candle.

    `trades_bar` must contain only executions in that completed candle and each
    execution must have a trustworthy aggressor `side` and positive `size`.
    Missing input returns an explicit unavailable state; it is never represented
    as balanced delta or normal volume.
    """
    if not isinstance(trades_bar, list) or not trades_bar:
        return unavailable("no_trade_executions", source)

    volume = _number(ohlcv.get("volume")) if isinstance(ohlcv, dict) else None
    baseline = _number(vol_ma)
    prior_cvd = _number(prev_cvd)
    if volume is None or volume <= 0:
        return unavailable("missing_or_zero_ohlcv_volume", source)
    if baseline is None or baseline <= 0:
        return unavailable("missing_or_zero_volume_ma", source)
    if prior_cvd is None:
        return unavailable("missing_previous_cvd", source)

    buy_volume, sell_volume, delta, classified = compute_bar_delta(trades_bar)
    if classified == 0:
        return unavailable("no_classified_trade_sides", source)

    classified_volume = buy_volume + sell_volume
    if classified_volume <= 0:
        return unavailable("zero_classified_trade_volume", source)

    cvd = prior_cvd + delta
    window = [float(value) for value in prev_cvd_window if _number(value) is not None]
    window = (window + [cvd])[-max(2, int(cvd_window_size)):]
    cvd_slope = (window[-1] - window[0]) / (len(window) - 1) if len(window) >= 2 else 0.0

    return {
        "ready": True,
        "reason": None,
        "source": source,
        "volume": volume,
        "volume_norm": min(volume / (baseline * 3.0), 1.0),
        "volume_state": _volume_state(volume, baseline),
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "classified_trade_count": classified,
        "classified_volume_ratio": classified_volume / volume,
        "delta": delta,
        "delta_norm": delta / volume,
        "delta_state": _delta_state(delta, volume),
        "cvd": cvd,
        "cvd_slope": cvd_slope / baseline,
    }
