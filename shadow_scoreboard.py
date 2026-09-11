"""shadow_scoreboard.py — Deterministic Shadow Candidate Scoreboard

Summarises shadow Volatile, shadow Trend Recovery, and Drive records
separately by:
  - sample count
  - directional hit rate  (for resolved records with a non-None label)
  - mean aligned return   (outcome.horizons.16bar.net_directional_return)
  - median / mean MFE     (outcome.horizons.16bar.mfe)
  - median / mean MAE     (outcome.horizons.16bar.mae)
  - coverage              (fraction of records with a resolved outcome)

NO winner is declared automatically.
NO execution signals, KNN inputs, or live risk parameters are touched.

Usage:
    python shadow_scoreboard.py                         # print summary
    python shadow_scoreboard.py --json                  # JSON output
    python shadow_scoreboard.py --bot shadow_volatile   # one bot only

Public API (for testing):
    compute_stats(records) -> dict
    load_records(path) -> list[dict]
    report(log_dir) -> dict
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG_DIR = Path(__file__).parent / "training_logs"

# The three bots covered by this scoreboard
SCOREBOARD_BOTS = ("shadow_volatile", "shadow_trend_recovery", "gimba_drive")


# ── helpers ───────────────────────────────────────────────────────────────

def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_records(path: Path) -> List[Dict[str, Any]]:
    """Load all valid JSON lines from a JSONL log file."""
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _horizon_metrics(record: Dict[str, Any], horizon: str = "16bar") -> Optional[Dict[str, float]]:
    """
    Extract numeric outcome metrics at the requested horizon.
    Returns None if the outcome is not resolved or metrics are absent.
    """
    outcome = record.get("outcome") or {}
    if str(outcome.get("status") or "").lower() != "resolved":
        return None
    horizons = outcome.get("horizons") or {}
    h = horizons.get(horizon) or {}
    if not h:
        # Fallback: Drive records use legacy flat outcome fields
        mfe = _number(outcome.get("mfe"))
        mae = _number(outcome.get("mae"))
        label = outcome.get("label")
        if mfe is None:
            return None
        net_ret: Optional[float] = None
        if label == 1:
            net_ret = mfe
        elif label == -1:
            net_ret = mae
        return {"net_directional_return": net_ret, "mfe": mfe, "mae": mae}
    return {
        "net_directional_return": _number(h.get("net_directional_return")),
        "mfe": _number(h.get("mfe")),
        "mae": _number(h.get("mae")),
    }


def _direction_label(record: Dict[str, Any]) -> Optional[int]:
    """
    Return +1 if the resolved outcome was directionally aligned, -1 if not, None if unclear.
    Uses the existing label field for Drive records (1 = TP hit, -1 = SL hit).
    For shadow records, uses net_directional_return sign.
    """
    outcome = record.get("outcome") or {}
    if str(outcome.get("status") or "").lower() != "resolved":
        return None

    # Drive records have a direct label
    label = outcome.get("label")
    if label in (1, -1):
        return int(label)

    # Shadow records: use net_directional_return from 16bar horizon
    metrics = _horizon_metrics(record, "16bar")
    if metrics is None:
        return None
    ndr = _number(metrics.get("net_directional_return"))
    if ndr is None:
        return None
    if ndr > 0:
        return 1
    if ndr < 0:
        return -1
    return None


def _noise_regime(record: Dict[str, Any]) -> str:
    regime = ((record.get("market_noise") or {}).get("regime") or "").upper()
    return regime if regime in {"CLEAN", "MIXED", "CHOPPY"} else "UNKNOWN"


def _compute_core_stats(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute scoreboard statistics for a list of records.

    Returns a dict with keys:
        sample_count, resolved_count, coverage,
        directional_hit_rate,
        mean_aligned_return,
        mean_mfe, median_mfe,
        mean_mae, median_mae,
        setup_family_counts  (dict)
    """
    n = len(records)
    if n == 0:
        return {
            "sample_count": 0,
            "resolved_count": 0,
            "coverage": 0.0,
            "directional_hit_rate": None,
            "mean_aligned_return": None,
            "mean_mfe": None,
            "median_mfe": None,
            "mean_mae": None,
            "median_mae": None,
            "setup_family_counts": {},
        }

    # Setup family counts
    family_counts: Dict[str, int] = {}
    for rec in records:
        sf = str(rec.get("setup_family") or rec.get("setup_type") or "unknown")
        family_counts[sf] = family_counts.get(sf, 0) + 1

    # Resolved metrics
    resolved_count = 0
    direction_labels: List[int] = []
    aligned_returns: List[float] = []
    mfe_vals: List[float] = []
    mae_vals: List[float] = []

    for rec in records:
        outcome = rec.get("outcome") or {}
        if str(outcome.get("status") or "").lower() != "resolved":
            continue
        resolved_count += 1

        metrics = _horizon_metrics(rec, "16bar")
        if metrics:
            ndr = _number(metrics.get("net_directional_return"))
            mfe = _number(metrics.get("mfe"))
            mae = _number(metrics.get("mae"))
            if ndr is not None:
                aligned_returns.append(ndr)
            if mfe is not None:
                mfe_vals.append(mfe)
            if mae is not None:
                mae_vals.append(mae)

        lbl = _direction_label(rec)
        if lbl is not None:
            direction_labels.append(lbl)

    coverage = resolved_count / n if n > 0 else 0.0

    directional_hit_rate: Optional[float] = None
    if direction_labels:
        hits = sum(1 for x in direction_labels if x == 1)
        directional_hit_rate = round(hits / len(direction_labels), 4)

    def _safe_mean(vals: List[float]) -> Optional[float]:
        return round(statistics.mean(vals), 6) if vals else None

    def _safe_median(vals: List[float]) -> Optional[float]:
        return round(statistics.median(vals), 6) if vals else None

    return {
        "sample_count": n,
        "resolved_count": resolved_count,
        "coverage": round(coverage, 4),
        "directional_hit_rate": directional_hit_rate,
        "mean_aligned_return": _safe_mean(aligned_returns),
        "mean_mfe": _safe_mean(mfe_vals),
        "median_mfe": _safe_median(mfe_vals),
        "mean_mae": _safe_mean(mae_vals),
        "median_mae": _safe_median(mae_vals),
        "setup_family_counts": family_counts,
    }


def compute_stats(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    stats = _compute_core_stats(records)
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        buckets.setdefault(_noise_regime(record), []).append(record)
    stats["noise_regimes"] = {
        regime: _compute_core_stats(bucket_records)
        for regime, bucket_records in sorted(buckets.items())
    }
    return stats


def report(log_dir: Path = LOG_DIR) -> Dict[str, Any]:
    """
    Load all three bot logs and compute per-bot stats.
    Returns dict keyed by bot name.  Does NOT declare a winner.
    """
    result: Dict[str, Any] = {}
    for bot in SCOREBOARD_BOTS:
        path = log_dir / f"{bot}.jsonl"
        records = load_records(path)
        result[bot] = compute_stats(records)
    return result


def _print_report(stats: Dict[str, Any], as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return

    print("\n══ JHL SHADOW SCOREBOARD ══════════════════════════════════════════")
    print("  Evidence collection — analytical only — no winner declared")
    print("═══════════════════════════════════════════════════════════════════\n")

    for bot_name, s in stats.items():
        print(f"  ── {bot_name} ──")
        print(f"     Samples      : {s['sample_count']}")
        print(f"     Resolved     : {s['resolved_count']}")
        print(f"     Coverage     : {s['coverage']:.1%}")
        dhr = s.get("directional_hit_rate")
        print(f"     Dir hit rate : {dhr:.1%}" if dhr is not None else "     Dir hit rate : n/a")
        mar = s.get("mean_aligned_return")
        print(f"     Mean aligned return : {mar:.6f}" if mar is not None else "     Mean aligned return : n/a")
        mmfe = s.get("mean_mfe")
        med_mfe = s.get("median_mfe")
        print(f"     MFE mean/med : {mmfe:.6f} / {med_mfe:.6f}" if mmfe is not None else "     MFE mean/med : n/a")
        mmae = s.get("mean_mae")
        med_mae = s.get("median_mae")
        print(f"     MAE mean/med : {mmae:.6f} / {med_mae:.6f}" if mmae is not None else "     MAE mean/med : n/a")
        fc = s.get("setup_family_counts", {})
        if fc:
            print(f"     Setup families:")
            for sf, cnt in sorted(fc.items(), key=lambda x: -x[1]):
                print(f"       {sf:<45} {cnt:>5}")
        regimes = s.get("noise_regimes", {})
        if regimes:
            print("     Noise regimes:")
            for regime, regime_stats in regimes.items():
                dhr_regime = regime_stats.get("directional_hit_rate")
                dhr_text = f"{dhr_regime:.1%}" if dhr_regime is not None else "n/a"
                mar_regime = regime_stats.get("mean_aligned_return")
                mar_text = f"{mar_regime:.6f}" if mar_regime is not None else "n/a"
                mmfe_regime = regime_stats.get("mean_mfe")
                med_mfe_regime = regime_stats.get("median_mfe")
                mfe_text = (
                    f"{mmfe_regime:.6f} / {med_mfe_regime:.6f}"
                    if mmfe_regime is not None and med_mfe_regime is not None
                    else "n/a"
                )
                mmae_regime = regime_stats.get("mean_mae")
                med_mae_regime = regime_stats.get("median_mae")
                mae_text = (
                    f"{mmae_regime:.6f} / {med_mae_regime:.6f}"
                    if mmae_regime is not None and med_mae_regime is not None
                    else "n/a"
                )
                print(
                    f"       {regime:<7} samples={regime_stats['sample_count']:>3} "
                    f"resolved={regime_stats['resolved_count']:>3} "
                    f"coverage={regime_stats['coverage']:.1%} "
                    f"hit={dhr_text} aligned={mar_text} "
                    f"MFE={mfe_text} MAE={mae_text}"
                )
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="JHL Shadow Scoreboard — analytical summary, no winner declared."
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--bot", metavar="BOT", help="Show only one bot")
    parser.add_argument(
        "--log-dir", metavar="DIR", default=str(LOG_DIR),
        help=f"Training log directory (default: {LOG_DIR})",
    )
    args = parser.parse_args()

    chosen_log_dir = Path(args.log_dir)
    stats = report(chosen_log_dir)

    if args.bot:
        if args.bot not in stats:
            print(f"Unknown bot '{args.bot}'. Available: {', '.join(stats.keys())}")
            return
        stats = {args.bot: stats[args.bot]}

    _print_report(stats, as_json=args.json)


if __name__ == "__main__":
    main()
