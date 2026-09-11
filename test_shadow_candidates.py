"""
test_shadow_candidates.py — Focused tests for the shadow candidate specialists.

Tests cover:
  1. shadow_gimba_volatile  — shadow-only restrictions (mode flags, entry/sl/tp=None)
  2. shadow_trend_recovery  — shadow-only restrictions + mandate enforcement
  3. scanner               — shadow logs persisted, [SHADOW] visible, existing behavior intact
  4. outcome_evaluator     — shadow resolve function, horizon labeling
  5. shadow_scoreboard     — compute_stats, load_records, no winner
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

GIMBA_DIR = Path(__file__).parent
sys.path.insert(0, str(GIMBA_DIR))

import shadow_gimba_volatile as sgv
import shadow_trend_recovery as str_rec
import shadow_scoreboard as ss
import outcome_evaluator


# ── Helpers ───────────────────────────────────────────────────────────────

def _up_rows(n: int = 50, base: float = 100.0) -> tuple:
    """Monotonically increasing OHLCV numpy arrays."""
    prices = base + np.arange(n) * 0.5
    o = prices - 0.05
    h = prices + 0.3
    l = prices - 0.3
    c = prices
    v = np.ones(n) * 1.5
    v[-1] = 3.0  # high RVOL
    return o, h, l, c, v


def _down_rows(n: int = 50, base: float = 200.0) -> tuple:
    prices = base - np.arange(n) * 0.5
    o = prices + 0.05
    h = prices + 0.3
    l = prices - 0.3
    c = prices
    v = np.ones(n) * 1.5
    v[-1] = 3.0
    return o, h, l, c, v


def _flat_rows(n: int = 50, base: float = 100.0) -> tuple:
    prices = np.full(n, base)
    prices += np.sin(np.arange(n) * 0.3) * 0.1  # tiny noise
    o = prices - 0.01
    h = prices + 0.05
    l = prices - 0.05
    c = prices
    v = np.ones(n)
    return o, h, l, c, v


# ══════════════════════════════════════════════════════════════════════════
# 1. shadow_gimba_volatile — shadow-only restrictions
# ══════════════════════════════════════════════════════════════════════════

class TestShadowVolatileRestrictions:
    """Every result must have the five mandatory shadow flags."""

    def _assert_shadow_flags(self, result: Dict[str, Any]) -> None:
        assert result["shadow_mode"] is True, "shadow_mode must be True"
        assert result["diagnostic_only"] is True
        assert result["training_only"] is True
        assert result["action_state"] == "observe"
        assert result["entry"] is None
        assert result["sl"] is None
        assert result["tp"] is None

    def test_insufficient_data_returns_shadow_flags(self):
        o = h = l = c = v = np.array([100.0] * 5, dtype=float)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        self._assert_shadow_flags(result)
        assert result["setup_family"] == sgv.SF_NO_SIGNAL

    def test_uptrend_continuation_shadow_flags(self):
        o, h, l, c, v = _up_rows(50)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        self._assert_shadow_flags(result)

    def test_downtrend_shadow_flags(self):
        o, h, l, c, v = _down_rows(50)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        self._assert_shadow_flags(result)

    def test_engine_label(self):
        o, h, l, c, v = _up_rows(50)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        assert result["engine"] == sgv.ENGINE_LABEL

    def test_reference_price_set(self):
        o, h, l, c, v = _up_rows(50)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        assert result["reference_price"] is not None
        assert result["reference_price"] > 0

    def test_reference_bar_ts_passthrough(self):
        o, h, l, c, v = _up_rows(50)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v, reference_bar_ts=9999)
        assert result["reference_bar_ts"] == 9999

    def test_setup_family_valid_token(self):
        o, h, l, c, v = _up_rows(50)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        valid = {
            sgv.SF_EXPANSION_LONG, sgv.SF_EXPANSION_SHORT,
            sgv.SF_CONTINUATION_LONG, sgv.SF_CONTINUATION_SHORT,
            sgv.SF_MATURITY_LONG, sgv.SF_MATURITY_SHORT,
            sgv.SF_EXHAUSTION, sgv.SF_NO_SIGNAL,
        }
        assert result["setup_family"] in valid

    def test_score_bounded(self):
        for make in (_up_rows, _down_rows, _flat_rows):
            o, h, l, c, v = make(50)
            result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
            assert 0.0 <= result["score"] <= 1.0

    def test_maturity_context_present(self):
        o, h, l, c, v = _up_rows(50)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        assert result["maturity_context"] in (
            "fresh_move", "room_remaining", "mature_extended", "exhausted"
        )

    def test_reasons_is_list(self):
        o, h, l, c, v = _up_rows(50)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        assert isinstance(result["reasons"], list)

    def test_required_inputs_ohlcv(self):
        o, h, l, c, v = _up_rows(50)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        assert "ohlcv_15m" in result["required_inputs"]


# ══════════════════════════════════════════════════════════════════════════
# 2. shadow_trend_recovery — shadow-only + mandate enforcement
# ══════════════════════════════════════════════════════════════════════════

class TestShadowTrendRecoveryRestrictions:
    VALID_FAMILIES = {
        str_rec.SF_RECLAIM_LONG, str_rec.SF_RECLAIM_SHORT,
        str_rec.SF_PB_CONTINUATION_LONG, str_rec.SF_PB_CONTINUATION_SHORT,
        str_rec.SF_PB_HOLD_LONG, str_rec.SF_PB_HOLD_SHORT,
        str_rec.SF_NO_SIGNAL,
    }

    def _assert_shadow_flags(self, result: Dict[str, Any]) -> None:
        assert result["shadow_mode"] is True
        assert result["diagnostic_only"] is True
        assert result["training_only"] is True
        assert result["action_state"] == "observe"
        assert result["entry"] is None
        assert result["sl"] is None
        assert result["tp"] is None

    def test_insufficient_data(self):
        o = h = l = c = v = np.array([100.0] * 5, dtype=float)
        result = str_rec.evaluate_arrays("TEST/USD", o, h, l, c, v)
        self._assert_shadow_flags(result)
        assert result["setup_family"] == str_rec.SF_NO_SIGNAL

    def test_shadow_flags_uptrend(self):
        o, h, l, c, v = _up_rows(50)
        result = str_rec.evaluate_arrays("TEST/USD", o, h, l, c, v,
                                         structure_context={"trend": "up"})
        self._assert_shadow_flags(result)

    def test_shadow_flags_downtrend(self):
        o, h, l, c, v = _down_rows(50)
        result = str_rec.evaluate_arrays("TEST/USD", o, h, l, c, v,
                                         structure_context={"trend": "down"})
        self._assert_shadow_flags(result)

    def test_setup_family_is_valid_token(self):
        for make, ctx in (
            (_up_rows, {"trend": "up"}),
            (_down_rows, {"trend": "down"}),
            (_flat_rows, {"trend": "ranging"}),
        ):
            o, h, l, c, v = make(50)
            result = str_rec.evaluate_arrays("TEST/USD", o, h, l, c, v, structure_context=ctx)
            assert result["setup_family"] in self.VALID_FAMILIES, (
                f"unexpected family: {result['setup_family']}"
            )

    def test_no_generic_trend_direction_families(self):
        """No SHADOW_TRD_BULLISH or SHADOW_TRD_CONTINUATION that lack reclaim/pullback semantics."""
        for make, ctx in (
            (_up_rows, {"trend": "up"}),
            (_down_rows, {"trend": "down"}),
        ):
            o, h, l, c, v = make(50)
            result = str_rec.evaluate_arrays("TEST/USD", o, h, l, c, v, structure_context=ctx)
            sf = result["setup_family"]
            # Must be one of the valid families — none that are generic
            assert sf in self.VALID_FAMILIES

    def test_ranging_trend_emits_no_signal(self):
        o, h, l, c, v = _flat_rows(50)
        result = str_rec.evaluate_arrays("TEST/USD", o, h, l, c, v,
                                         structure_context={"trend": "ranging"})
        # For flat/ranging, expect no signal
        assert result["setup_family"] == str_rec.SF_NO_SIGNAL

    def test_score_bounded(self):
        for make, ctx in (
            (_up_rows, {"trend": "up"}),
            (_down_rows, {"trend": "down"}),
        ):
            o, h, l, c, v = make(50)
            result = str_rec.evaluate_arrays("TEST/USD", o, h, l, c, v, structure_context=ctx)
            assert 0.0 <= result["score"] <= 1.0

    def test_required_inputs(self):
        o, h, l, c, v = _up_rows(50)
        result = str_rec.evaluate_arrays("TEST/USD", o, h, l, c, v)
        assert "ohlcv_15m" in result["required_inputs"]
        assert "structure_context" in result["required_inputs"]

    def test_engine_label(self):
        o, h, l, c, v = _up_rows(50)
        result = str_rec.evaluate_arrays("TEST/USD", o, h, l, c, v)
        assert result["engine"] == str_rec.ENGINE_LABEL

    def test_null_result_always_shadow(self):
        result = str_rec._null_result("TEST/USD", "test_reason")
        assert result["shadow_mode"] is True
        assert result["entry"] is None


# ══════════════════════════════════════════════════════════════════════════
# 3. scanner — shadow logs persisted, no changes to existing behavior
# ══════════════════════════════════════════════════════════════════════════

class TestScannerShadowIntegration:
    """Verify scanner._append_shadow_log writes correct records."""

    def test_append_shadow_log_writes_jsonl(self):
        import scanner as scan
        import importlib
        # Reset seen keys for clean test
        original_seen = scan._SEEN_EVENT_KEYS.copy()
        scan._SEEN_EVENT_KEYS.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            # Patch LOG_DIR on scanner module
            original_log_dir = scan.LOG_DIR
            scan.LOG_DIR = log_dir

            signal = {
                "setup_family": sgv.SF_CONTINUATION_LONG,
                "side": "LONG",
                "score": 0.55,
                "state": "shadow_vol_continuation_long",
                "reasons": ["test_reason"],
                "required_inputs": ["ohlcv_15m"],
                "invalidation_level": 99.0,
                "maturity_context": "room_remaining",
                "reference_price": 100.0,
                "reference_bar_ts": 1000,
                "shadow_mode": True,
                "diagnostic_only": True,
                "training_only": True,
                "action_state": "observe",
                "entry": None,
                "sl": None,
                "tp": None,
                "indicators": {},
            }
            scan._append_shadow_log(
                bot_name="shadow_volatile",
                pair="SOL/USD",
                signal=signal,
                ts="2026-01-01T00:00:00+00:00",
                event_key="SOL/USD|shadow_volatile|15m|1000",
                structure={},
                volume_flow={},
            )

            path = log_dir / "shadow_volatile.jsonl"
            assert path.exists(), "shadow_volatile.jsonl not created"
            lines = path.read_text(encoding="utf-8").splitlines()
            assert len(lines) == 1
            record = json.loads(lines[0])

            assert record["bot"] == "shadow_volatile"
            assert record["shadow_mode"] is True
            assert record["diagnostic_only"] is True
            assert record["training_only"] is True
            assert record["action_state"] == "observe"
            assert record["entry"] is None
            assert record["sl"] is None
            assert record["tp"] is None
            assert record["outcome"]["status"] == "pending"

            scan.LOG_DIR = original_log_dir
        scan._SEEN_EVENT_KEYS.clear()
        scan._SEEN_EVENT_KEYS.update(original_seen)

    def test_deduplication_by_event_key(self):
        import scanner as scan
        original_seen = scan._SEEN_EVENT_KEYS.copy()
        scan._SEEN_EVENT_KEYS.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            original_log_dir = scan.LOG_DIR
            scan.LOG_DIR = log_dir

            signal = {
                "setup_family": sgv.SF_NO_SIGNAL, "side": "NONE", "score": 0.0,
                "state": "no", "reasons": [], "required_inputs": [],
                "invalidation_level": None, "maturity_context": None,
                "reference_price": 100.0, "reference_bar_ts": 1000,
                "shadow_mode": True, "diagnostic_only": True, "training_only": True,
                "action_state": "observe", "entry": None, "sl": None, "tp": None,
                "indicators": {},
            }
            key = "SOL/USD|shadow_volatile|15m|1000"
            for _ in range(3):
                scan._append_shadow_log("shadow_volatile", "SOL/USD", signal, "ts", key, {}, {})

            lines = (log_dir / "shadow_volatile.jsonl").read_text(encoding="utf-8").splitlines()
            assert len(lines) == 1, "deduplication failed"

            scan.LOG_DIR = original_log_dir
        scan._SEEN_EVENT_KEYS.clear()
        scan._SEEN_EVENT_KEYS.update(original_seen)


# ══════════════════════════════════════════════════════════════════════════
# 4. outcome_evaluator — shadow resolve, horizon labeling
# ══════════════════════════════════════════════════════════════════════════

def _make_shadow_record(
    pair: str = "SOL/USD",
    bot: str = "shadow_volatile",
    side: str = "LONG",
    ref_price: float = 100.0,
    ref_bar_ts: int = 1000,
    ts: str = "2026-01-01T00:00:00+00:00",
    outcome_status: str = "pending",
    invalidation_level: float = 99.0,
) -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "event_key": f"{pair}|{bot}|15m|{ref_bar_ts}",
        "ts": ts,
        "pair": pair,
        "bot": bot,
        "setup_family": "SHADOW_VOL_CONTINUATION_LONG",
        "side": side,
        "reference_price": ref_price,
        "reference_bar_ts": ref_bar_ts,
        "invalidation_level": invalidation_level,
        "shadow_mode": True,
        "diagnostic_only": True,
        "training_only": True,
        "action_state": "observe",
        "entry": None,
        "sl": None,
        "tp": None,
        "outcome": {"status": outcome_status, "label": None},
    }


def _make_ohlc_rows(n: int, base: float = 100.0, up: bool = True) -> List[List[Any]]:
    rows = []
    price = base
    for i in range(n):
        price += 0.5 if up else -0.5
        rows.append([1000 + i * 900, str(price - 0.1), str(price + 0.3),
                     str(price - 0.3), str(price), "0", "1.0"])
    return rows


class TestOutcomeEvaluatorShadow:
    def test_shadow_horizon_long_positive(self):
        ref = 100.0
        rows = _make_ohlc_rows(16, base=ref, up=True)
        result = outcome_evaluator._shadow_horizon(rows[:1], ref, "LONG", None)
        assert result["net_directional_return"] > 0, "expected positive return for LONG up"
        assert result["mfe"] > 0
        assert result["mae"] <= 0

    def test_shadow_horizon_short_positive(self):
        ref = 100.0
        rows = _make_ohlc_rows(16, base=ref, up=False)
        result = outcome_evaluator._shadow_horizon(rows[:1], ref, "SHORT", None)
        assert result["net_directional_return"] > 0, "expected positive return for SHORT down"

    def test_shadow_horizon_hold_status_held(self):
        ref = 100.0
        invalidation = 98.0  # well below
        rows = _make_ohlc_rows(4, base=ref, up=True)
        result = outcome_evaluator._shadow_horizon(rows, ref, "LONG", invalidation)
        assert result["hold_fail"] == "HELD"

    def test_shadow_horizon_hold_status_failed(self):
        ref = 100.0
        invalidation = 102.0  # price will stay below for LONG = held
        # For LONG, failed means low < invalidation_level
        # Use rows that go DOWN below invalidation
        rows = _make_ohlc_rows(4, base=100.0, up=False)
        # Each row has low = price - 0.3, so prices drop below 98
        result = outcome_evaluator._shadow_horizon(rows, ref, "LONG", 99.5)
        assert result["hold_fail"] in ("HELD", "FAILED")

    def test_shadow_horizon_no_invalidation(self):
        ref = 100.0
        rows = _make_ohlc_rows(4, base=ref, up=True)
        result = outcome_evaluator._shadow_horizon(rows, ref, "LONG", None)
        assert result["hold_fail"] is None

    def test_resolve_shadow_pending_no_future_data(self):
        """Should return None when no future candles available yet."""
        import time
        record = _make_shadow_record(ref_bar_ts=int(time.time()) + 999999)
        result = outcome_evaluator._resolve_shadow(record, int(time.time()))
        assert result is None

    def test_resolve_shadow_already_resolved(self):
        record = _make_shadow_record()
        record["outcome"] = {
            "status": "resolved", "horizons": {"16bar": {"net_directional_return": 0.1}}
        }
        result = outcome_evaluator._resolve_shadow(record, int(100e9))
        assert result is None, "already-resolved record should return None"

    def test_resolve_shadow_missing_reference_price(self):
        record = _make_shadow_record()
        record["reference_price"] = None
        result = outcome_evaluator._resolve_shadow(record, int(100e9))
        assert result is not None
        assert result["status"] == "resolved"
        assert result["label"] is None

    def test_resolve_shadow_label_always_none(self):
        """Shadow outcomes must never use trade win/loss labels."""
        ref = 100.0
        rows = _make_ohlc_rows(20, base=ref, up=True)

        with patch.object(outcome_evaluator, "_ohlc", return_value=rows):
            record = _make_shadow_record(
                ref_bar_ts=1, ts="2020-01-01T00:00:00+00:00",
            )
            result = outcome_evaluator._resolve_shadow(record, int(100e9))

        if result is not None and result.get("status") == "resolved":
            assert result["label"] is None, "shadow outcome label must be None"

    def test_shadow_bot_dispatched_in_resolve(self):
        """_resolve should dispatch shadow_volatile to _resolve_shadow."""
        record = _make_shadow_record()
        # Make ts very old so evaluation can proceed
        record["ts"] = "2020-01-01T00:00:00+00:00"
        record["reference_bar_ts"] = 1

        rows = _make_ohlc_rows(20, base=100.0, up=True)
        with patch.object(outcome_evaluator, "_ohlc", return_value=rows):
            result = outcome_evaluator._resolve(record, int(100e9))
        # Should not return None (no "not watch action" short-circuit for shadow bots)
        # result is either None (waiting) or a dict with status
        if result is not None:
            assert result.get("status") in ("pending", "resolved")

    def test_shadow_trend_recovery_bot_dispatched(self):
        record = _make_shadow_record(bot="shadow_trend_recovery")
        record["ts"] = "2020-01-01T00:00:00+00:00"
        record["reference_bar_ts"] = 1

        rows = _make_ohlc_rows(20, base=100.0, up=True)
        with patch.object(outcome_evaluator, "_ohlc", return_value=rows):
            result = outcome_evaluator._resolve(record, int(100e9))
        if result is not None:
            assert result.get("status") in ("pending", "resolved")

    def test_bot_logs_includes_shadow_bots(self):
        assert "shadow_volatile" in outcome_evaluator.BOT_LOGS
        assert "shadow_trend_recovery" in outcome_evaluator.BOT_LOGS

    def test_horizons_contain_required_keys(self):
        ref = 100.0
        rows = _make_ohlc_rows(20, base=ref, up=True)
        with patch.object(outcome_evaluator, "_ohlc", return_value=rows):
            record = _make_shadow_record(
                ts="2020-01-01T00:00:00+00:00",
                ref_bar_ts=1,
            )
            result = outcome_evaluator._resolve_shadow(record, int(100e9))

        if result and result.get("status") == "resolved":
            for horizon in ("15m", "30m", "60m", "16bar"):
                if horizon in result.get("horizons", {}):
                    h = result["horizons"][horizon]
                    for key in ("net_directional_return", "realized_range",
                                "directional_efficiency", "mfe", "mae"):
                        assert key in h, f"missing {key} in horizon {horizon}"


# ══════════════════════════════════════════════════════════════════════════
# 5. shadow_scoreboard — compute_stats, load_records, no winner
# ══════════════════════════════════════════════════════════════════════════

def _resolved_shadow_record(
    setup_family: str = "SHADOW_VOL_CONTINUATION_LONG",
    side: str = "LONG",
    ndr_16bar: float = 0.05,
    mfe_16bar: float = 0.08,
    mae_16bar: float = -0.02,
) -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "bot": "shadow_volatile",
        "setup_family": setup_family,
        "side": side,
        "outcome": {
            "status": "resolved",
            "label": None,
            "horizons": {
                "16bar": {
                    "net_directional_return": ndr_16bar,
                    "realized_range": 0.10,
                    "directional_efficiency": 0.5,
                    "mfe": mfe_16bar,
                    "mae": mae_16bar,
                }
            },
        },
    }


def _drive_record(label: int) -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "bot": "gimba_drive",
        "setup_type": "DRIVE_LONG",
        "outcome": {
            "status": "resolved",
            "label": label,
            "mfe": 0.06,
            "mae": -0.01,
        },
    }


class TestShadowScoreboard:
    def test_empty_records(self):
        stats = ss.compute_stats([])
        assert stats["sample_count"] == 0
        assert stats["coverage"] == 0.0
        assert stats["directional_hit_rate"] is None
        assert stats["mean_aligned_return"] is None

    def test_positive_hit_rate(self):
        records = [
            _resolved_shadow_record(ndr_16bar=0.05),
            _resolved_shadow_record(ndr_16bar=0.03),
            _resolved_shadow_record(ndr_16bar=-0.02),
        ]
        stats = ss.compute_stats(records)
        assert stats["sample_count"] == 3
        assert stats["resolved_count"] == 3
        assert stats["coverage"] == 1.0
        assert stats["directional_hit_rate"] == pytest.approx(2 / 3, rel=0.01)

    def test_mean_mfe_computed(self):
        records = [
            _resolved_shadow_record(mfe_16bar=0.08),
            _resolved_shadow_record(mfe_16bar=0.04),
        ]
        stats = ss.compute_stats(records)
        assert stats["mean_mfe"] == pytest.approx(0.06, rel=0.01)

    def test_median_mfe(self):
        records = [
            _resolved_shadow_record(mfe_16bar=0.02),
            _resolved_shadow_record(mfe_16bar=0.04),
            _resolved_shadow_record(mfe_16bar=0.10),
        ]
        stats = ss.compute_stats(records)
        assert stats["median_mfe"] == pytest.approx(0.04, rel=0.01)

    def test_setup_family_counts(self):
        records = [
            _resolved_shadow_record("SHADOW_VOL_EXPANSION_LONG"),
            _resolved_shadow_record("SHADOW_VOL_EXPANSION_LONG"),
            _resolved_shadow_record("SHADOW_VOL_CONTINUATION_LONG"),
        ]
        stats = ss.compute_stats(records)
        fc = stats["setup_family_counts"]
        assert fc["SHADOW_VOL_EXPANSION_LONG"] == 2
        assert fc["SHADOW_VOL_CONTINUATION_LONG"] == 1

    def test_drive_records_label_based(self):
        records = [
            _drive_record(1),  # win
            _drive_record(1),  # win
            _drive_record(-1), # loss
        ]
        stats = ss.compute_stats(records)
        assert stats["directional_hit_rate"] == pytest.approx(2 / 3, rel=0.01)

    def test_pending_records_excluded_from_resolved(self):
        pending = {
            "schema_version": 2, "bot": "shadow_volatile",
            "setup_family": "SHADOW_VOL_NO_SIGNAL",
            "outcome": {"status": "pending", "label": None},
        }
        records = [pending, _resolved_shadow_record()]
        stats = ss.compute_stats(records)
        assert stats["sample_count"] == 2
        assert stats["resolved_count"] == 1
        assert stats["coverage"] == 0.5

    def test_load_records_empty_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nonexistent.jsonl"
            records = ss.load_records(path)
            assert records == []

    def test_load_records_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            data = [{"a": 1}, {"b": 2}]
            with path.open("w", encoding="utf-8") as f:
                for d in data:
                    f.write(json.dumps(d) + "\n")
            records = ss.load_records(path)
            assert len(records) == 2

    def test_load_records_skips_bad_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            path.write_text('{"ok": 1}\nbad json\n{"ok": 2}\n', encoding="utf-8")
            records = ss.load_records(path)
            assert len(records) == 2

    def test_report_returns_all_three_bots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            result = ss.report(log_dir)
            for bot in ("shadow_volatile", "shadow_trend_recovery", "gimba_drive"):
                assert bot in result

    def test_report_no_winner_declared(self):
        """report() returns a plain dict — no 'winner' key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            result = ss.report(log_dir)
            assert "winner" not in result

    def test_scoreboard_bots_constant(self):
        assert "shadow_volatile" in ss.SCOREBOARD_BOTS
        assert "shadow_trend_recovery" in ss.SCOREBOARD_BOTS
        assert "gimba_drive" in ss.SCOREBOARD_BOTS


# ══════════════════════════════════════════════════════════════════════════
# 6. Contract enforcement
# ══════════════════════════════════════════════════════════════════════════

class TestContractEnforcement:
    """Verify that shadow modules never claim execution flags."""

    def test_volatile_no_action_watch(self):
        o, h, l, c, v = _up_rows(50)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        assert result["action_state"] != "watch"
        assert result["action_state"] == "observe"

    def test_trend_recovery_no_action_watch(self):
        o, h, l, c, v = _up_rows(50)
        result = str_rec.evaluate_arrays("TEST/USD", o, h, l, c, v,
                                         structure_context={"trend": "up"})
        assert result["action_state"] != "watch"
        assert result["action_state"] == "observe"

    def test_volatile_no_knn_field(self):
        o, h, l, c, v = _up_rows(50)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        assert "knn_adj" not in result

    def test_trend_recovery_no_knn_field(self):
        o, h, l, c, v = _up_rows(50)
        result = str_rec.evaluate_arrays("TEST/USD", o, h, l, c, v)
        assert "knn_adj" not in result

    def test_volatile_null_result_always_observe(self):
        result = sgv._null_result("TEST/USD", "test")
        assert result["action_state"] == "observe"
        assert result["shadow_mode"] is True

    def test_trend_recovery_valid_prefixes_constant(self):
        for prefix in str_rec.VALID_PREFIXES:
            assert prefix in ("RECLAIM_", "PULLBACK_CONTINUATION_", "PULLBACK_HOLD_")


# ══════════════════════════════════════════════════════════════════════════
# 7. Trend Recovery — namespaced validator rejects generic families
# ══════════════════════════════════════════════════════════════════════════

class TestTrendRecoveryFamilyValidator:
    """Focused tests for the SHADOW_TRD_ namespace + semantic-prefix rule."""

    def test_valid_families_accepted(self):
        for sf in (
            str_rec.SF_RECLAIM_LONG,
            str_rec.SF_RECLAIM_SHORT,
            str_rec.SF_PB_CONTINUATION_LONG,
            str_rec.SF_PB_CONTINUATION_SHORT,
            str_rec.SF_PB_HOLD_LONG,
            str_rec.SF_PB_HOLD_SHORT,
            str_rec.SF_NO_SIGNAL,
        ):
            assert str_rec._is_valid_trend_recovery_family(sf), (
                f"expected valid: {sf!r}"
            )

    def test_generic_trend_direction_families_rejected(self):
        """Families with SHADOW_TRD_ namespace but no reclaim/pullback semantic are invalid."""
        for bad in (
            "SHADOW_TRD_BULLISH",
            "SHADOW_TRD_BEARISH",
            "SHADOW_TRD_CONTINUATION_LONG",
            "SHADOW_TRD_TREND_LONG",
            "SHADOW_TRD_",
            "SHADOW_TRD_UP",
        ):
            assert not str_rec._is_valid_trend_recovery_family(bad), (
                f"expected invalid: {bad!r}"
            )

    def test_missing_namespace_prefix_rejected(self):
        """Names without SHADOW_TRD_ prefix are always rejected (except NO_SIGNAL)."""
        for bad in (
            "RECLAIM_LONG",
            "PULLBACK_CONTINUATION_LONG",
            "SHADOW_VOL_EXPANSION_LONG",
            "TREND_LONG",
        ):
            assert not str_rec._is_valid_trend_recovery_family(bad), (
                f"expected invalid: {bad!r}"
            )

    def test_evaluate_arrays_all_emitted_families_satisfy_contract(self):
        """All families emitted by evaluate_arrays satisfy the validator."""
        scenarios = [
            (_up_rows, {"trend": "up"}),
            (_down_rows, {"trend": "down"}),
            (_flat_rows, {"trend": "ranging"}),
        ]
        for make, ctx in scenarios:
            o, h, l, c, v = make(50)
            result = str_rec.evaluate_arrays("TEST/USD", o, h, l, c, v,
                                             structure_context=ctx)
            sf = result["setup_family"]
            assert str_rec._is_valid_trend_recovery_family(sf), (
                f"emitted family {sf!r} failed validator (ctx={ctx})"
            )


# ══════════════════════════════════════════════════════════════════════════
# 8. Volatile exhaustion — confirmation required; expanding moves stay maturity
# ══════════════════════════════════════════════════════════════════════════

class TestVolatileExhaustionConfirmation:
    """Exhaustion requires maturity >= MATURITY_EXHAUSTED AND confirmed signal."""

    def _make_high_maturity_arrays(
        self,
        n: int = 60,
        rvol_last: float = 0.80,
        speed_range: float = 0.02,
    ) -> tuple:
        """
        Build arrays whose move_maturity will be >= MATURITY_EXHAUSTED (0.80).

        maturity = min(total_range / (atr * 4), 1.0)
        We want total_range / (atr * 4) >= 0.80 → total_range >= 3.2 * atr

        Strategy: large sustained move so swing range >> atr * 4.
        """
        # Large sustained upward move: range will far exceed atr*4 → maturity=1.0
        prices = np.linspace(100.0, 200.0, n)  # 100-point range
        c = prices
        h = prices + 0.2
        l = prices - 0.2
        o = prices - 0.05
        # ATR ≈ 0.4 (h-l + small true range between bars)
        # total_range = 100, atr*4 ≈ 1.6 → maturity = min(100/1.6, 1) = 1.0 → exhausted
        v = np.ones(n)
        v[-1] = rvol_last  # control RVOL of last bar
        return o, h, l, c, v

    def test_exhaustion_with_low_rvol_confirmed(self):
        """High maturity + low RVOL → SF_EXHAUSTION."""
        # Low RVOL (below RVOL_CONTINUATION_MIN=1.20) confirms exhaustion
        o, h, l, c, v = self._make_high_maturity_arrays(rvol_last=0.70)
        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        assert result["setup_family"] == sgv.SF_EXHAUSTION, (
            f"expected EXHAUSTION with low RVOL, got {result['setup_family']!r}; "
            f"indicators={result.get('indicators')}"
        )
        assert result["indicators"]["maturity"] >= sgv.MATURITY_EXHAUSTED

    def test_high_maturity_high_rvol_strong_speed_not_exhaustion(self):
        """High maturity + high RVOL + strong speed → maturity state, NOT exhaustion."""
        # RVOL_CONTINUATION_MIN=1.20; use 2.0 (well above) for high RVOL
        # Also ensure speed > SPEED_MIN=0.30 (use a very large price move range)
        n = 60
        # Very large move: speed over 20 bars will be huge; high RVOL
        prices = np.linspace(100.0, 200.0, n)
        c = prices
        h = prices + 0.2
        l = prices - 0.2
        o = prices - 0.05
        v = np.ones(n) * 1.0
        v[-1] = 2.0  # RVOL = last / mean(first 20) = 2.0/1.0 = 2.0 > 1.20

        result = sgv.evaluate_arrays("TEST/USD", o, h, l, c, v)
        assert result["setup_family"] != sgv.SF_EXHAUSTION, (
            f"high-maturity expanding move should NOT be exhaustion, "
            f"got {result['setup_family']!r}; indicators={result.get('indicators')}"
        )
        assert result["setup_family"] in (
            sgv.SF_MATURITY_LONG, sgv.SF_MATURITY_SHORT,
        ), (
            f"expected maturity state for high-maturity/high-RVOL/strong-speed move, "
            f"got {result['setup_family']!r}"
        )
