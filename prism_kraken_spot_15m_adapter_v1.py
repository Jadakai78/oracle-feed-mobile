from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


DATA_VENUE = "KRAKEN_SPOT"
TIMEFRAME = "15m"
INTERVAL_SECONDS = 15 * 60
REQUIRED_COMPLETED_BARS = 390


def _payload(
    *,
    state: str,
    reason: str | None,
    canonical_pair: str,
    kraken_api_pair: str,
    kraken_altname: str | None,
    kraken_wsname: str | None,
    fetched_at_utc: str,
    completed_bar_count: int,
    bars: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "reason": reason,
        "data_venue": DATA_VENUE,
        "pair": canonical_pair,
        "timeframe": TIMEFRAME,
        "kraken_api_pair": kraken_api_pair,
        "kraken_altname": kraken_altname,
        "kraken_wsname": kraken_wsname,
        "fetched_at_utc": fetched_at_utc,
        "completed_bar_count": completed_bar_count,
        "required_completed_bar_count": REQUIRED_COMPLETED_BARS,
        "bars": list(bars or []),
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
    }


def _iso_from_epoch(value: Any) -> str:
    epoch = int(float(value))

    if epoch <= 0:
        raise ValueError("timestamp must be positive")

    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _finite_positive(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not numeric")

    number = float(value)

    if not math.isfinite(number) or number <= 0.0:
        raise ValueError("value must be finite and positive")

    return number


def _parse_completed_row(row: Any) -> tuple[int, dict[str, Any]]:
    if not isinstance(row, (list, tuple)) or len(row) < 7:
        raise ValueError("malformed OHLC row")

    start_epoch = int(float(row[0]))

    if start_epoch <= 0:
        raise ValueError("timestamp must be positive")

    open_price = _finite_positive(row[1])
    high_price = _finite_positive(row[2])
    low_price = _finite_positive(row[3])
    close_price = _finite_positive(row[4])
    volume = _finite_positive(row[6])

    if high_price < low_price:
        raise ValueError("high below low")

    if low_price > min(open_price, close_price):
        raise ValueError("open or close below low")

    if high_price < max(open_price, close_price):
        raise ValueError("open or close above high")

    end_epoch = start_epoch + INTERVAL_SECONDS

    return (
        start_epoch,
        {
            "timestamp": _iso_from_epoch(end_epoch),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
        },
    )


def build_completed_15m_bars(
    *,
    canonical_pair: str,
    kraken_api_pair: str,
    kraken_altname: str | None,
    kraken_wsname: str | None,
    raw_candles: list[list[Any]],
    fetched_at_utc: str,
) -> dict[str, Any]:
    """Build a validated PRISM-ready payload from Kraken native 15m OHLC rows.

    The final raw candle is always treated as active and discarded. This is a
    pure parser; it performs no HTTP request, file write, or trading action.
    """
    pair = canonical_pair.strip() if isinstance(canonical_pair, str) else ""
    api_pair = kraken_api_pair.strip() if isinstance(kraken_api_pair, str) else ""
    fetched = fetched_at_utc.strip() if isinstance(fetched_at_utc, str) else ""

    raw_list = raw_candles if isinstance(raw_candles, list) else []

    if not pair or "/" not in pair or not api_pair or not fetched:
        return _payload(
            state="UNAVAILABLE",
            reason="invalid_adapter_metadata",
            canonical_pair=pair,
            kraken_api_pair=api_pair,
            kraken_altname=kraken_altname,
            kraken_wsname=kraken_wsname,
            fetched_at_utc=fetched,
            completed_bar_count=0,
        )

    completed_rows = raw_list[:-1] if len(raw_list) > 1 else []
    completed_count = len(completed_rows)

    parsed: list[tuple[int, dict[str, Any]]] = []

    try:
        for row in completed_rows:
            parsed.append(_parse_completed_row(row))
    except (TypeError, ValueError, OverflowError):
        return _payload(
            state="UNAVAILABLE",
            reason="invalid_ohlcv",
            canonical_pair=pair,
            kraken_api_pair=api_pair,
            kraken_altname=kraken_altname,
            kraken_wsname=kraken_wsname,
            fetched_at_utc=fetched,
            completed_bar_count=completed_count,
        )

    previous_start: int | None = None

    for start_epoch, _ in parsed:
        if (
            previous_start is not None
            and start_epoch - previous_start != INTERVAL_SECONDS
        ):
            return _payload(
                state="UNAVAILABLE",
                reason="noncontinuous_completed_bars",
                canonical_pair=pair,
                kraken_api_pair=api_pair,
                kraken_altname=kraken_altname,
                kraken_wsname=kraken_wsname,
                fetched_at_utc=fetched,
                completed_bar_count=completed_count,
            )
        previous_start = start_epoch

    if completed_count < REQUIRED_COMPLETED_BARS:
        return _payload(
            state="UNAVAILABLE",
            reason="insufficient_completed_history",
            canonical_pair=pair,
            kraken_api_pair=api_pair,
            kraken_altname=kraken_altname,
            kraken_wsname=kraken_wsname,
            fetched_at_utc=fetched,
            completed_bar_count=completed_count,
        )

    return _payload(
        state="AVAILABLE",
        reason=None,
        canonical_pair=pair,
        kraken_api_pair=api_pair,
        kraken_altname=kraken_altname,
        kraken_wsname=kraken_wsname,
        fetched_at_utc=fetched,
        completed_bar_count=completed_count,
        bars=[bar for _, bar in parsed],
    )
