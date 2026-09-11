"""
oracle_prism_bar_snapshot_producer_v1.py — standalone, finite, run-once
Oracle-to-PRISM bar snapshot bridge.

This is the ONLY network-facing component in this chain. It fetches Kraken
public 15-minute OHLC data for a fixed (or explicitly supplied) canonical
pair universe, converts it to the exact ORACLE_PRISM_BAR_SNAPSHOT contract,
and atomically writes it to an explicitly supplied output path.

It does not import any Oracle scanner code and does not import any PRISM
clean-room code (no shared forbidden-key list, no shared bar-validation
helper -- this module owns its own copies so it has zero import coupling to
either). It runs once and exits; it is never an infinite loop, never
publishes, never touches GitHub/hosting/broker/exchange-account/alert/
execution code.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
INTERVAL_MINUTES = 15
BAR_INTERVAL_SECONDS = INTERVAL_MINUTES * 60
REQUIRED_BAR_COUNT = 390
TIMEFRAME = "15m"

OUTPUT_RECORDTYPE = "ORACLE_PRISM_BAR_SNAPSHOT"
OUTPUT_SCHEMA_VERSION = "oracle_prism_bar_snapshot_v1"

TOP_LEVEL_KEYS = {"recordtype", "schema_version", "generated_at_utc", "timeframe", "pairs"}
PAIR_ENTRY_KEYS = {"pair", "bars"}
BAR_KEYS = {"timestamp", "open", "high", "low", "close", "volume"}

# Only verified aliases. No guessed alias for any other pair.
VERIFIED_ALIASES = {"BTC": "XBT", "DOGE": "XDG"}

# Fixed default Oracle pair universe (duplicated here intentionally -- this
# module does not import oracle_prop_context_scanner.py).
DEFAULT_PAIR_UNIVERSE: tuple[str, ...] = (
    "AAVE/USD", "ADA/USD", "ALGO/USD", "ARB/USD", "ATOM/USD", "AVAX/USD",
    "BTC/USD", "BCH/USD", "BONK/USD", "DOGE/USD", "DOT/USD", "ETH/USD",
    "ETC/USD", "FET/USD", "FIL/USD", "INJ/USD", "LINK/USD", "LTC/USD",
    "MATIC/USD", "NEAR/USD", "OP/USD", "PEPE/USD", "POL/USD", "RNDR/USD",
    "SEI/USD", "SHIB/USD", "SOL/USD", "SUI/USD", "TIA/USD", "TON/USD",
    "TRX/USD", "UNI/USD", "WIF/USD", "XLM/USD", "XRP/USD", "XTZ/USD",
    "APT/USD", "CRV/USD", "DYDX/USD", "EGLD/USD", "ICP/USD", "IMX/USD",
    "KAS/USD", "LDO/USD", "RUNE/USD", "STX/USD", "TAO/USD", "WLD/USD",
    "ZRX/USD",
)


class BridgeConfigError(ValueError):
    """Raised for a whole-run/config/output failure. Distinct from a single
    pair's fetch/validation failure, which never raises -- it always
    resolves to an explicit empty-bars pair record instead."""


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_canonical_pair(pair: object) -> str | None:
    """Strictly validate a canonical 'BASE/QUOTE' pair string. Performs NO
    normalization or repair. Returns the original string unchanged if valid,
    else None."""
    if not isinstance(pair, str) or not pair:
        return None
    if pair != pair.strip():
        return None
    for char in ("\r", "\n", "|"):
        if char in pair:
            return None
    parts = pair.split("/")
    if len(parts) != 2:
        return None
    base, quote = parts[0], parts[1]
    if not base or not quote:
        return None
    if base != base.strip() or quote != quote.strip():
        return None
    return pair


def kraken_symbol(pair: str) -> str:
    """Map a canonical 'BASE/QUOTE' pair to a Kraken pair symbol using only
    verified aliases (BTC->XBT, DOGE->XDG). Any other base/quote is passed
    through unchanged and concatenated."""
    base, quote = pair.split("/")
    return f"{VERIFIED_ALIASES.get(base, base)}{VERIFIED_ALIASES.get(quote, quote)}"


def default_fetch(pair: str) -> Any:
    """The only function in this module that performs a live network call.
    Never invoked by tests -- tests always inject a mock fetcher."""
    query = urllib.parse.urlencode({"pair": kraken_symbol(pair), "interval": INTERVAL_MINUTES})
    request = urllib.request.Request(
        f"{KRAKEN_OHLC_URL}?{query}",
        headers={"User-Agent": "oracle-prism-bar-snapshot-producer/1.0"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_completed_rows(raw_payload: Any) -> list | None:
    """Return the completed (final in-progress row dropped) raw Kraken OHLC
    rows, or None if the payload is malformed in any way."""
    if not isinstance(raw_payload, dict):
        return None
    if raw_payload.get("error"):
        return None
    result = raw_payload.get("result")
    if not isinstance(result, dict):
        return None
    series_key = next((key for key in result if key != "last"), None)
    if series_key is None:
        return None
    rows = result.get(series_key)
    if not isinstance(rows, list) or len(rows) < 2:
        return None
    return rows[:-1]  # drop the final in-progress row


def _row_to_bar(row: Any) -> dict | None:
    """Convert one raw Kraken OHLC row to a bar dict. Returns None if the
    row shape is invalid. Never mutates `row`."""
    if not isinstance(row, (list, tuple)) or len(row) < 7:
        return None
    try:
        start_epoch = float(row[0])
        open_ = float(row[1])
        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
        volume = float(row[6])
    except (TypeError, ValueError):
        return None
    close_time = datetime.fromtimestamp(start_epoch + BAR_INTERVAL_SECONDS, timezone.utc)
    return {
        "timestamp": _format_utc(close_time),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _is_finite_positive(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and value > 0


def _bar_shape_valid(bar: dict) -> bool:
    for key in ("open", "high", "low", "close", "volume"):
        if not _is_finite_positive(bar.get(key)):
            return False
    open_, high, low, close = bar["open"], bar["high"], bar["low"], bar["close"]
    if low > min(open_, close):
        return False
    if high < max(open_, close):
        return False
    if high < low:
        return False
    return True


def _sequence_valid(bars: list[dict]) -> bool:
    """Ascending timestamps, exactly BAR_INTERVAL_SECONDS apart, using the
    same ISO-8601 'Z' format this module always produces."""
    if len(bars) < 2:
        return True
    parsed = []
    for bar in bars:
        text = bar["timestamp"]
        if not isinstance(text, str) or not text.endswith("Z"):
            return False
        try:
            parsed.append(datetime.fromisoformat(text[:-1] + "+00:00"))
        except ValueError:
            return False
    for earlier, later in zip(parsed, parsed[1:]):
        if later - earlier != timedelta(seconds=BAR_INTERVAL_SECONDS):
            return False
    return True


def build_pair_snapshot(pair: str, fetch: Callable[[str], Any]) -> dict:
    """Build one pair entry. Never raises -- any fetch/parse/validation
    failure resolves to an explicit {"pair": pair, "bars": []} record.
    Never retries, interpolates, pads, merges, or fabricates bars."""
    try:
        raw_payload = fetch(pair)
        rows = _extract_completed_rows(raw_payload)
        if rows is None:
            return {"pair": pair, "bars": []}

        bars: list[dict] = []
        for row in rows:
            bar = _row_to_bar(row)
            if bar is None:
                return {"pair": pair, "bars": []}
            bars.append(bar)

        for bar in bars:
            if not _bar_shape_valid(bar):
                return {"pair": pair, "bars": []}

        if not _sequence_valid(bars):
            return {"pair": pair, "bars": []}

        if len(bars) < REQUIRED_BAR_COUNT:
            return {"pair": pair, "bars": []}

        newest = bars[-REQUIRED_BAR_COUNT:]
        return {"pair": pair, "bars": newest}
    except Exception:
        return {"pair": pair, "bars": []}


def build_snapshot(
    pairs: list[str],
    fetch: Callable[[str], Any] = default_fetch,
    generated_at: datetime | None = None,
) -> dict:
    """Pure-ish payload builder (network happens only inside `fetch`, which
    tests always replace). `generated_at` is injectable for deterministic
    tests. A single pair's failure never aborts the run."""
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)

    pair_records = []
    for pair in pairs:
        try:
            pair_records.append(build_pair_snapshot(pair, fetch))
        except Exception:
            pair_records.append({"pair": pair, "bars": []})

    return {
        "recordtype": OUTPUT_RECORDTYPE,
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "generated_at_utc": _format_utc(generated_at),
        "timeframe": TIMEFRAME,
        "pairs": pair_records,
    }


def write_snapshot_atomic(payload: dict, output_path: str | Path) -> None:
    """Atomically write `payload` as JSON to `output_path`."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=output_path.name + ".",
        suffix=".tmp",
        dir=str(output_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(tmp_name, output_path)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def _parse_pairs_arg(raw_pairs: list[str] | None) -> list[str]:
    if raw_pairs is None:
        return list(DEFAULT_PAIR_UNIVERSE)
    validated = []
    for pair in raw_pairs:
        canonical = validate_canonical_pair(pair)
        if canonical is None:
            raise BridgeConfigError(f"invalid or noncanonical --pairs entry: {pair!r}")
        validated.append(canonical)
    return validated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Finite, run-once bridge: fetches Kraken public 15-minute OHLC data "
            "and writes an ORACLE_PRISM_BAR_SNAPSHOT. Network-facing but "
            "public-data-only; no publishing, no scanning loop, no execution."
        )
    )
    parser.add_argument("--output", required=True, help="Path to write the ORACLE_PRISM_BAR_SNAPSHOT JSON output.")
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=None,
        help="Explicit canonical BASE/QUOTE pairs to fetch. Defaults to the fixed 49-pair Oracle universe.",
    )
    args = parser.parse_args(argv)

    try:
        pairs = _parse_pairs_arg(args.pairs)
    except BridgeConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = build_snapshot(pairs, fetch=default_fetch)

    try:
        write_snapshot_atomic(payload, args.output)
    except OSError as exc:
        print(f"ERROR: could not write output file: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote ORACLE_PRISM_BAR_SNAPSHOT with {len(payload['pairs'])} pair record(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
