from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from prism_kraken_spot_15m_adapter_v1 import build_completed_15m_bars


FetchRawCandles = Callable[[str], tuple[str, list[list[Any]]]]


def _unavailable(
    *,
    reason: str,
    pair: str,
    fetched_at_utc: str,
    kraken_api_pair: str = "",
    kraken_altname: str | None = None,
    kraken_wsname: str | None = None,
) -> dict[str, Any]:
    return {
        "state": "UNAVAILABLE",
        "reason": reason,
        "data_venue": "KRAKEN_SPOT",
        "pair": pair,
        "timeframe": "15m",
        "kraken_api_pair": kraken_api_pair,
        "kraken_altname": kraken_altname,
        "kraken_wsname": kraken_wsname,
        "fetched_at_utc": fetched_at_utc,
        "completed_bar_count": 0,
        "required_completed_bar_count": 390,
        "bars": [],
        "manual_review_only": True,
        "trade_authority": False,
        "entry_authority": False,
    }


def _canonical_pair(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    pair = value.strip().upper()

    if not pair or "/" not in pair:
        return None

    base, quote = pair.split("/", 1)

    if not base or quote != "USD":
        return None

    return pair


def _load_audit_rows(audit_path: Path) -> list[dict[str, Any]] | None:
    if not isinstance(audit_path, Path) or not audit_path.exists():
        return None

    try:
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    rows = payload.get("rows") if isinstance(payload, dict) else None

    if not isinstance(rows, list):
        return None

    return [row for row in rows if isinstance(row, dict)]


def _find_pair(
    rows: list[dict[str, Any]],
    canonical_pair: str,
) -> dict[str, Any] | None:
    for row in rows:
        candidate = str(row.get("context_pair") or "").upper().strip()

        if candidate == canonical_pair:
            return row

    return None


def fetch_prism_kraken_spot_15m(
    canonical_pair: str,
    *,
    audit_path: Path,
    fetch_raw_candles: FetchRawCandles,
    fetched_at_utc: str,
) -> dict[str, Any]:
    """Resolve, fetch through an injected source, and parse Kraken native 15m bars.

    This function performs no network access itself. The caller owns the
    injected fetch function. It does not write artifacts or open observations.
    """
    pair = _canonical_pair(canonical_pair)

    if pair is None:
        return _unavailable(
            reason="invalid_canonical_pair",
            pair="",
            fetched_at_utc=fetched_at_utc,
        )

    rows = _load_audit_rows(audit_path)

    if rows is None:
        return _unavailable(
            reason="audit_unavailable",
            pair=pair,
            fetched_at_utc=fetched_at_utc,
        )

    market = _find_pair(rows, pair)

    if market is None:
        return _unavailable(
            reason="pair_not_found_in_audit",
            pair=pair,
            fetched_at_utc=fetched_at_utc,
        )

    altname = market.get("kraken_altname")
    wsname = market.get("kraken_wsname")
    api_pair = str(
        market.get("kraken_altname")
        or market.get("api_pair_key")
        or ""
    ).upper().strip()

    if str(market.get("resolution_state") or "").upper() != "RESOLVED":
        return _unavailable(
            reason="pair_not_resolved_in_audit",
            pair=pair,
            fetched_at_utc=fetched_at_utc,
            kraken_api_pair=api_pair,
            kraken_altname=altname,
            kraken_wsname=wsname,
        )

    if not api_pair:
        return _unavailable(
            reason="missing_kraken_api_pair",
            pair=pair,
            fetched_at_utc=fetched_at_utc,
            kraken_altname=altname,
            kraken_wsname=wsname,
        )

    try:
        fetched = fetch_raw_candles(api_pair)

        if (
            not isinstance(fetched, tuple)
            or len(fetched) != 2
            or not isinstance(fetched[0], str)
            or not isinstance(fetched[1], list)
        ):
            raise ValueError("fetcher must return (candle_key, raw_candles)")

        candle_key, raw_candles = fetched
    except Exception as exc:
        return _unavailable(
            reason=f"fetch_error:{type(exc).__name__}",
            pair=pair,
            fetched_at_utc=fetched_at_utc,
            kraken_api_pair=api_pair,
            kraken_altname=altname,
            kraken_wsname=wsname,
        )

    return build_completed_15m_bars(
        canonical_pair=pair,
        kraken_api_pair=api_pair,
        kraken_altname=altname,
        kraken_wsname=wsname,
        raw_candles=raw_candles,
        fetched_at_utc=fetched_at_utc,
    )
