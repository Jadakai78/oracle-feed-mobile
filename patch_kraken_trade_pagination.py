from __future__ import annotations

import py_compile
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "scanner.py"

if not TARGET.exists():
    raise SystemExit(f"scanner.py not found beside this patch script: {TARGET}")

source = TARGET.read_text(encoding="utf-8")

if "_fetch_completed_bar_trades_paginated" in source:
    raise SystemExit("Kraken completed-bar trade pagination already appears to be installed. Nothing changed.")

helper = r'''

def _fetch_completed_bar_trades_paginated(
    kraken_pair: str,
    start: int,
    end: int,
    max_pages: int = 20,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Collect Kraken public trades for one completed bar using cursor pagination.

    Fails closed on a repeated/missing cursor or page-cap exhaustion. The final
    result is de-duplicated by Kraken trade id before it is used for pressure.
    """
    since = str(start)
    seen_cursors: set[str] = set()
    trades_by_id: Dict[str, Dict[str, Any]] = {}

    try:
        for _ in range(max_pages):
            result = _request("/Trades", {"pair": kraken_pair, "since": since, "count": 1000})
            raw_trades = _result_rows(result)
            next_cursor = str(result.get("last") or "")

            for raw in raw_trades:
                if len(raw) < 7:
                    continue
                trade_time = float(raw[2])
                if start <= trade_time < end:
                    trade_id = str(raw[6])
                    trades_by_id[trade_id] = {
                        "price": float(raw[0]),
                        "size": float(raw[1]),
                        "side": str(raw[3]).lower(),
                        "timestamp": trade_time,
                        "trade_id": trade_id,
                    }

            # A short page means Kraken has exhausted currently available rows.
            if len(raw_trades) < 1000:
                return list(trades_by_id.values()), None

            # At 1,000 rows we must advance with Kraken's cursor; never use a capped page.
            if not next_cursor or next_cursor == since or next_cursor in seen_cursors:
                return [], "trade_pagination_cursor_stalled"
            seen_cursors.add(since)
            since = next_cursor

        return [], f"trade_pagination_page_limit_{max_pages}"
    except Exception as exc:
        return [], f"kraken_trade_pagination_error:{type(exc).__name__}"
'''

function_anchor = "\ndef fetch_bar_data("
if function_anchor not in source:
    raise SystemExit("Could not find fetch_bar_data() to insert the pagination helper. Nothing changed.")
source = source.replace(function_anchor, helper + "\n\ndef fetch_bar_data(", 1)

old_block = '''        trades_result = _request("/Trades", {"pair": kraken_pair, "since": str(start), "count": 1000})
        raw_trades = _result_rows(trades_result)
        if len(raw_trades) >= 1000:
            return [], ohlcv, "trade_response_at_limit"

        trades: List[Dict[str, Any]] = []
        for raw in raw_trades:
            if len(raw) < 7:
                continue
            trade_time = float(raw[2])
            if start <= trade_time < end:
                trades.append({
                    "price": float(raw[0]), "size": float(raw[1]), "side": str(raw[3]).lower(),
                    "timestamp": trade_time, "trade_id": str(raw[6]),
                })
        return trades, ohlcv, None
'''
new_block = '''        trades, trade_error = _fetch_completed_bar_trades_paginated(
            kraken_pair=kraken_pair,
            start=start,
            end=end,
        )
        if trade_error:
            return [], ohlcv, trade_error
        return trades, ohlcv, None
'''

if old_block not in source:
    raise SystemExit(
        "Could not find the original Kraken trade-fetch block in fetch_bar_data(). "
        "Nothing changed."
    )
source = source.replace(old_block, new_block, 1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"scanner.pre_kraken_pagination_{stamp}.py")
shutil.copy2(TARGET, backup)
TARGET.write_text(source, encoding="utf-8")

try:
    py_compile.compile(str(TARGET), doraise=True)
except Exception:
    shutil.copy2(backup, TARGET)
    raise

print(f"Patched: {TARGET.name}")
print(f"Backup:  {backup.name}")
print("Syntax check: PASS")
print("Kraken completed-bar trade pagination is active: 20-page cap, cursor-stall detection, fail-closed behavior.")
