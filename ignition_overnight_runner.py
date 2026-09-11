# ignition_overnight_runner.py
# Read-only overnight runner for the JHL ignition dry run.
# Runs local scripts only. No order placement or BTCC execution calls.

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "training_logs" / "ignition_arena"
RUN_LOG = LOG_DIR / "overnight_runner.jsonl"

QUEUE = ROOT / "kraken_btcc_top3_queue.py"
MAP = ROOT / "kraken_btcc_top3_map.py"
OBSERVER = ROOT / "ignition_observer.py"
RESOLVER = ROOT / "ignition_outcome_resolver.py"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_log(record: dict) -> None:
    import json

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


def run_script(path: Path) -> bool:
    if not path.exists():
        append_log(
            {
                "timestamp_utc": utc_now_iso(),
                "script": str(path),
                "status": "MISSING",
                "orders_enabled": False,
            }
        )
        print(f"[MISSING] {path.name}")
        return False

    started = time.time()

    try:
        result = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        elapsed = round(time.time() - started, 3)

        record = {
            "timestamp_utc": utc_now_iso(),
            "script": path.name,
            "return_code": result.returncode,
            "elapsed_seconds": elapsed,
            "stdout": result.stdout[-6000:],
            "stderr": result.stderr[-3000:],
            "orders_enabled": False,
        }
        append_log(record)

        status = "PASS" if result.returncode == 0 else "FAIL"
        print(f"[{status}] {path.name} | {elapsed}s")

        if result.stdout.strip():
            print(result.stdout.rstrip())

        if result.stderr.strip():
            print(f"[STDERR] {result.stderr.rstrip()}")

        return result.returncode == 0

    except subprocess.TimeoutExpired:
        append_log(
            {
                "timestamp_utc": utc_now_iso(),
                "script": path.name,
                "status": "TIMEOUT",
                "timeout_seconds": 90,
                "orders_enabled": False,
            }
        )
        print(f"[TIMEOUT] {path.name}")
        return False

    except Exception as exc:
        append_log(
            {
                "timestamp_utc": utc_now_iso(),
                "script": path.name,
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "orders_enabled": False,
            }
        )
        print(f"[ERROR] {path.name}: {exc}")
        return False


def cycle(run_map_and_resolver: bool) -> None:
    cycle_started = utc_now_iso()

    print(f"\n{'=' * 70}")
    print(f"IGNITION DRY-RUN CYCLE — {cycle_started}")
    print("Orders: disabled | Execution: manual only")
    print(f"{'=' * 70}")

    queue_ok = run_script(QUEUE)
    observer_ok = run_script(OBSERVER)

    map_ok = None
    resolver_ok = None

    if run_map_and_resolver:
        map_ok = run_script(MAP)
        resolver_ok = run_script(RESOLVER)

    append_log(
        {
            "timestamp_utc": utc_now_iso(),
            "record_type": "OVERNIGHT_CYCLE",
            "queue_ok": queue_ok,
            "observer_ok": observer_ok,
            "map_ok": map_ok,
            "resolver_ok": resolver_ok,
            "orders_enabled": False,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JHL read-only overnight ignition dry-run runner."
    )
    parser.add_argument(
        "--every-seconds",
        type=int,
        default=60,
        help="Queue and observer cycle interval. Default: 60 seconds.",
    )
    parser.add_argument(
        "--map-resolver-every-cycles",
        type=int,
        default=5,
        help="Run map and resolver every N cycles. Default: 5.",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run the first cycle immediately.",
    )
    args = parser.parse_args()

    if args.every_seconds < 30:
        print("FAIL: --every-seconds must be at least 30.")
        return 1

    if args.map_resolver_every_cycles < 1:
        print("FAIL: --map-resolver-every-cycles must be at least 1.")
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("JHL IGNITION OVERNIGHT RUNNER")
    print(f"Project root: {ROOT}")
    print(f"Queue / observer interval: {args.every_seconds} seconds")
    print(
        "Map / resolver interval: "
        f"every {args.map_resolver_every_cycles} queue cycles"
    )
    print("Orders: disabled")
    print("Press Ctrl+C to stop the runner.")

    cycle_number = 0

    try:
        if not args.run_now:
            time.sleep(args.every_seconds)

        while True:
            cycle_number += 1
            run_map_and_resolver = (
                cycle_number % args.map_resolver_every_cycles == 0
            )
            cycle(run_map_and_resolver)
            time.sleep(args.every_seconds)

    except KeyboardInterrupt:
        append_log(
            {
                "timestamp_utc": utc_now_iso(),
                "record_type": "OVERNIGHT_RUNNER_STOPPED",
                "cycles_completed": cycle_number,
                "orders_enabled": False,
            }
        )
        print("\nRunner stopped by user. No orders were sent.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
