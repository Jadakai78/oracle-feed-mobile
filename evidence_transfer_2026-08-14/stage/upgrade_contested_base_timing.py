from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

SRC = Path(r"C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl-market-edge-drive\gimba")
DST = Path(r"C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba")
COPY_FILES = ("market_noise.py", "market_timing.py", "shadow_scoreboard.py", "test_market_noise.py", "test_market_timing.py", "test_shadow_candidates.py", "JHL-Market-Edge-Shell.html")


def backup(path: Path) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, path.with_name(f"{path.name}.{stamp}.bak"))


def replace_all(text: str, old: str, new: str, expected: int, label: str) -> str:
    found = text.count(old)
    if found != expected:
        raise RuntimeError(f"{label}: expected {expected} anchors, found {found}. No scanner changes written.")
    return text.replace(old, new)


def upgrade_scanner(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "import market_timing" in text or '"market_timing":' in text:
        raise RuntimeError("scanner.py already appears to include market_timing; no changes made.")
    if "import market_noise" not in text or "_attach_market_noise" not in text:
        raise RuntimeError("This upgrade expects the prior market-noise installation in scanner.py.")

    text = text.replace("import market_noise\n", "import market_noise\nimport market_timing\n", 1)
    noise_log = '        "market_noise": signal.get("market_noise") or market_noise.unavailable("market_noise_missing"),\n'
    timing_log = noise_log + '        "market_timing": signal.get("market_timing") or market_timing.unavailable("market_timing_missing"),\n'
    text = replace_all(text, noise_log, timing_log, 2, "training/shadow log fields")

    marker = "\ndef _evaluate_raw("
    helper = '''\n\ndef _attach_market_timing(signal: Dict[str, Any], timing: Dict[str, Any]) -> Dict[str, Any]:
    signal["market_timing"] = dict(timing or market_timing.unavailable("market_timing_missing"))
    return signal
'''
    if marker not in text:
        raise RuntimeError("market-timing helper anchor missing.")
    text = text.replace(marker, helper + marker, 1)

    noise_attach = '''        for signal in (gv, gr, rts, trd, drv, pulse, shd_vol, shd_trd):
            _attach_market_noise(signal, shared_market_noise)
'''
    timing_attach = noise_attach + '''
        shared_market_timing = market_timing.observe(
            structure=structure,
            volume_flow=volume_flow,
            market_noise=shared_market_noise,
            market_state=market_state,
            rts_signal=rts,
            range_signal=gr,
        )
        for signal in (gv, gr, rts, trd, drv, pulse, shd_vol, shd_trd):
            _attach_market_timing(signal, shared_market_timing)
'''
    text = replace_all(text, noise_attach, timing_attach, 1, "post-decision timing attachment")

    published_noise = '                "market_noise": dict(shared_market_noise),\n'
    published_timing = published_noise + '                "market_timing": dict(shared_market_timing),\n'
    text = replace_all(text, published_noise, published_timing, 1, "published-row timing field")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if not SRC.is_dir() or not DST.is_dir():
        raise SystemExit(f"Missing source or destination folder:\n{SRC}\n{DST}")
    missing = [str(SRC / name) for name in COPY_FILES if not (SRC / name).is_file()]
    if missing:
        raise SystemExit("Source files missing. Run git switch main; git pull origin main in the source repository first:\n" + "\n".join(missing))
    scanner = DST / "scanner.py"
    if not scanner.is_file():
        raise SystemExit(f"Live scanner not found: {scanner}")

    backup(scanner)
    for name in COPY_FILES:
        target = DST / name
        if target.exists():
            backup(target)
        shutil.copy2(SRC / name, target)
    try:
        upgrade_scanner(scanner)
    except Exception:
        shutil.copy2(scanner.with_name(sorted(scanner.parent.glob("scanner.py.*.bak"), key=lambda p: p.stat().st_mtime)[-1].name), scanner)
        raise

    print("Installed merged PR #15 contested-base timing diagnostics.")
    print("Backups were created beside each live file. Run the focused tests before restarting services.")


if __name__ == "__main__":
    main()
