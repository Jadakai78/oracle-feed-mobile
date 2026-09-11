from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

SRC = Path(r"C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl-market-edge-drive\gimba")
DST = Path(r"C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba")

COPY_FILES = (
    "market_noise.py",
    "shadow_scoreboard.py",
    "test_market_noise.py",
    "test_shadow_candidates.py",
    "JHL-Market-Edge-Shell.html",
)


def backup(path: Path) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, path.with_name(f"{path.name}.{stamp}.bak"))


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Patch anchor not found: {label}. No files were changed.")
    return text.replace(old, new, 1)


def patch_scanner(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "import market_noise" in text or '"market_noise":' in text:
        raise RuntimeError("scanner.py already appears to contain market-noise integration.")

    text = replace_once(
        text,
        "import gimba_pulse\n",
        "import gimba_pulse\nimport market_noise\n",
        "market_noise import",
    )
    text = replace_once(
        text,
        '        "volume_flow": volume_flow,\n        "outcome": {"status": "pending", "label": None},\n',
        '        "volume_flow": volume_flow,\n        "market_noise": signal.get("market_noise") or market_noise.unavailable("market_noise_missing"),\n        "outcome": {"status": "pending", "label": None},\n',
        "training-log market_noise field",
    )
    text = replace_once(
        text,
        '        "volume_flow": volume_flow,\n        "outcome": {"status": "pending", "label": None},\n',
        '        "volume_flow": volume_flow,\n        "market_noise": signal.get("market_noise") or market_noise.unavailable("market_noise_missing"),\n        "outcome": {"status": "pending", "label": None},\n',
        "shadow-log market_noise field",
    )
    text = replace_once(
        text,
        '        status = "READY" if pressure.get("ready") else f"OFF:{pressure.get(\'reason\', \'unknown\')}"\n        print(f"║ ── {pair} │ PRESSURE {status}")\n',
        '        status = "READY" if pressure.get("ready") else f"OFF:{pressure.get(\'reason\', \'unknown\')}"\n        noise = row.get("market_noise") or {}\n        print(f"║ ── {pair} │ PRESSURE {status}")\n        if noise.get("available"):\n            print(f"║    MARKET NOISE {noise.get(\'regime\', \'—\'):<7} SCORE {float(noise.get(\'noise_score\', 0.0)):.2f} [analytics only]")\n        else:\n            print("║    MARKET NOISE unavailable [analytics only]")\n',
        "scanner market-noise display",
    )
    helper = '''\n\ndef _attach_market_noise(signal: Dict[str, Any], noise: Dict[str, Any]) -> Dict[str, Any]:\n    \"\"\"Attach analytics after all routing/KNN decisions; never alter signal fields.\"\"\"\n    signal["market_noise"] = dict(noise or market_noise.unavailable("market_noise_missing"))\n    return signal\n\n'''
    text = replace_once(text, "\ndef _evaluate_raw(", helper + "\ndef _evaluate_raw(", "market-noise attachment helper")

    old = '''        _ohlcv_arrays = _fetch_ohlc_arrays(kraken_pair, interval=15, limit=60)
        _ref_ts = volume_flow.get("bar_start")
        if _ohlcv_arrays is not None:
            _o, _h, _l, _c, _v, _last_ts = _ohlcv_arrays
'''
    new = '''        _ohlcv_arrays = _fetch_ohlc_arrays(kraken_pair, interval=15, limit=60)
        _ref_ts = volume_flow.get("bar_start")
        shared_market_noise = market_noise.unavailable(
            "market_noise_fetch_failed", reference_bar_start=_ref_ts,
        )
        if _ohlcv_arrays is not None:
            _o, _h, _l, _c, _v, _last_ts = _ohlcv_arrays
            # This local scanner helper already excludes Kraken's unfinished candle.
            shared_market_noise = market_noise.observe(
                _o, _h, _l, _c, _v, reference_bar_start=_last_ts,
            )
'''
    text = replace_once(text, old, new, "shared market-noise computation")

    marker = "        # 7. Log one observation per bot per completed pressure candle.\n"
    attach = '''        # Analytics attachment occurs after structure/KNN work and cannot affect decisions.
        for signal in (gv, gr, rts, trd, drv, pulse, shd_vol, shd_trd):
            _attach_market_noise(signal, shared_market_noise)

'''
    text = replace_once(text, marker, attach + marker, "post-decision market-noise attachment")
    text = replace_once(
        text,
        '                "volume_flow": volume_flow,\n                "market_state": market_state,\n',
        '                "volume_flow": volume_flow,\n                "market_noise": dict(shared_market_noise),\n                "market_state": market_state,\n',
        "published row market-noise field",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if not SRC.is_dir() or not DST.is_dir():
        raise SystemExit(f"Missing source or destination folder:\n{SRC}\n{DST}")
    for name in COPY_FILES:
        if not (SRC / name).exists():
            raise SystemExit(f"Source file not found: {SRC / name}\nRun git switch main; git pull origin main in the source repository first.")
    scanner = DST / "scanner.py"
    if not scanner.exists():
        raise SystemExit(f"Live scanner not found: {scanner}")

    backup(scanner)
    for name in ("shadow_scoreboard.py", "test_shadow_candidates.py", "JHL-Market-Edge-Shell.html"):
        destination = DST / name
        if destination.exists():
            backup(destination)
    for name in COPY_FILES:
        shutil.copy2(SRC / name, DST / name)
    patch_scanner(scanner)

    print("Installed market-noise analytics and the final shadow dashboard from main.")
    print("Backups were created beside every replaced/modified live file.")
    print("Next: run the two focused test files before restarting the scanner.")


if __name__ == "__main__":
    main()
