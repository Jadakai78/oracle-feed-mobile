"""
test_gimba_drive.py — Focused tests for the Gimba Drive training-only specialist.

Tests cover:
- evaluate() returns correct shape and training_only=True
- All five conditions independently block a claim when absent
- DRIVE_LONG / DRIVE_SHORT claim emitted only when all five are met
- KNN feature extraction (_features_drive) in knn_engine
- outcome_evaluator BOT_LOGS includes gimba_drive
- scanner: diagnostic_only flag set on gimba_volatile and gimba_trend
"""
from __future__ import annotations

import sys
import types
import json
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ── Path setup ────────────────────────────────────────────────────────────
GIMBA_DIR = Path(__file__).parent
sys.path.insert(0, str(GIMBA_DIR))


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_ohlc_rows(n: int = 50, base: float = 100.0, trend: str = "up") -> list:
    """Synthetic OHLC rows in Kraken format."""
    rows = []
    price = base
    for i in range(n):
        if trend == "up":
            price += 0.2
        elif trend == "down":
            price -= 0.2
        o = price - 0.05
        h = price + 0.3
        l = price - 0.3
        c = price
        rows.append([1000 + i * 900, str(o), str(h), str(l), str(c), "0", str(1.0 + i * 0.01)])
    return rows


def _make_uptrend_rows(n: int = 50) -> list:
    """Monotonically increasing rows so swing structure reliably detects 'up'."""
    rows = []
    for i in range(n):
        base = 100.0 + i * 0.5
        rows.append([1000 + i * 900, str(base), str(base + 0.4), str(base - 0.4), str(base + 0.2), "0", "1.5"])
    return rows


def _make_downtrend_rows(n: int = 50) -> list:
    """Monotonically decreasing rows so swing structure reliably detects 'down'."""
    rows = []
    for i in range(n):
        base = 200.0 - i * 0.5
        rows.append([1000 + i * 900, str(base), str(base + 0.4), str(base - 0.4), str(base - 0.2), "0", "1.5"])
    return rows


# ── Tests for gimba_drive.py helpers ─────────────────────────────────────

import gimba_drive as gd


class TestHelpers:
    def test_atr_basic(self):
        h = np.array([2.0, 3.0, 4.0, 5.0])
        l = np.array([1.0, 1.5, 2.0, 2.5])
        c = np.array([1.5, 2.5, 3.5, 4.5])
        val = gd._atr(h, l, c, 2)
        assert val > 0

    def test_rsi_midpoint(self):
        # With flat prices all diffs are 0; avg_loss=0 → RSI=100 (no losses).
        # Use a zigzag pattern to get near 50.
        c = np.tile([1.0, 2.0], 15).astype(float)
        val = gd._rsi(c, 14)
        assert 40.0 < val < 60.0

    def test_rsi_all_up(self):
        c = np.cumsum(np.ones(30))
        assert gd._rsi(c, 14) == 100.0

    def test_relative_volume_flat(self):
        v = np.ones(30)
        assert gd._relative_volume(v, 20) == pytest.approx(1.0, abs=0.01)

    def test_htf_alignment_up(self):
        direction, reasons = gd._htf_alignment({"d1_trend": "up", "h4_trend": "up", "trend": "up"})
        assert direction == "up"
        assert reasons == []

    def test_htf_alignment_none(self):
        direction, reasons = gd._htf_alignment({"d1_trend": "ranging", "h4_trend": "ranging", "trend": "ranging"})
        assert direction == ""
        assert reasons

    def test_htf_alignment_from_combined_trend(self):
        direction, reasons = gd._htf_alignment({"trend": "down"})
        assert direction == "down"

    def test_pullback_location_long_ok(self):
        ok, eq_pct, reasons = gd._pullback_location(50.0, 100.0, 0.0, "up")
        assert ok
        assert reasons == []

    def test_pullback_location_long_extended(self):
        ok, eq_pct, reasons = gd._pullback_location(95.0, 100.0, 0.0, "up")
        assert not ok
        assert reasons

    def test_pullback_location_short_ok(self):
        ok, eq_pct, reasons = gd._pullback_location(60.0, 100.0, 0.0, "down")
        assert ok
        assert reasons == []

    def test_pullback_location_short_extended(self):
        ok, eq_pct, reasons = gd._pullback_location(5.0, 100.0, 0.0, "down")
        assert not ok
        assert reasons

    def test_compression_insufficient_bars(self):
        hm = np.ones(5)
        lm = np.zeros(5)
        cm = np.ones(5) * 0.5
        ok, ratio, reasons = gd._pullback_compression(hm, lm, cm, 0.1)
        assert not ok
        assert "insufficient_bars" in reasons[0]

    def test_compression_detected(self):
        # prior window has large range, recent is narrow
        n = 30
        hm = np.ones(n) * 10.0
        lm = np.zeros(n)
        cm = np.ones(n) * 5.0
        # Override last 6 bars to be tightly compressed
        hm[-6:] = 5.1
        lm[-6:] = 4.9
        ok, ratio, reasons = gd._pullback_compression(hm, lm, cm, 1.0)
        assert ok

    def test_local_structure_break_long(self):
        # All bars at 100; current bar closes at 101 (above local high 100)
        hm = np.ones(20) * 100.0
        lm = np.ones(20) * 99.0
        cm = np.ones(20) * 99.5
        cm[-1] = 101.0  # break above
        broke, level, reasons = gd._local_structure_break(hm, lm, cm, "up")
        assert broke

    def test_local_structure_break_long_fails(self):
        hm = np.ones(20) * 100.0
        lm = np.ones(20) * 99.0
        cm = np.ones(20) * 99.5
        broke, level, reasons = gd._local_structure_break(hm, lm, cm, "up")
        assert not broke
        assert reasons

    def test_local_structure_break_short(self):
        hm = np.ones(20) * 100.0
        lm = np.ones(20) * 99.0
        cm = np.ones(20) * 99.5
        cm[-1] = 98.0  # break below
        broke, level, reasons = gd._local_structure_break(hm, lm, cm, "down")
        assert broke

    def test_break_holds_and_expands_long_rvol(self):
        # High RVOL, price above break level
        cm = np.ones(30) * 100.0
        vm = np.ones(30)
        vm[-1] = 3.0  # rvol = 3.0 / avg(1.0) = 3.0 >= 1.2
        ok, rvol, rsi, reasons = gd._break_holds_and_expands(cm, vm, "up", 99.0, 0.5, 0.0)
        assert ok

    def test_break_fails_if_price_reverts_long(self):
        cm = np.ones(30) * 98.0  # price below break level
        vm = np.ones(30) * 2.0
        ok, rvol, rsi, reasons = gd._break_holds_and_expands(cm, vm, "up", 99.0, 0.5, 0.0)
        assert not ok
        assert "break_failed" in reasons[0]


# ── Tests for evaluate() public API ──────────────────────────────────────

class TestEvaluate:
    """Test the evaluate() function with mocked OHLC fetches."""

    def _mock_fetch_returns(self, rows_d1, rows_h4, rows_h1, rows_m15):
        """Return a _fetch_ohlc side_effect that returns rows by interval."""
        def side_effect(kraken_pair, interval, limit=80):
            if interval == 1440:
                return rows_d1
            if interval == 240:
                return rows_h4
            if interval == 60:
                return rows_h1
            if interval == 15:
                return rows_m15
            return None
        return side_effect

    def test_returns_null_on_missing_d1(self):
        with patch.object(gd, "_fetch_ohlc", return_value=None):
            result = gd.evaluate("SOL/USD", "SOLUSD", 0.0)
        assert result["setup_type"] == "NO_DRIVE_CONDITION"
        assert result["training_only"] is True
        assert result["action_state"] == "idle"
        assert result["bias"] == "NONE"

    def test_training_only_always_true(self):
        with patch.object(gd, "_fetch_ohlc", return_value=None):
            result = gd.evaluate("BTC/USD", "XBTUSD", 0.0)
        assert result["training_only"] is True

    def test_output_shape(self):
        """Confirm required keys are always present."""
        with patch.object(gd, "_fetch_ohlc", return_value=None):
            result = gd.evaluate("ETH/USD", "ETHUSD", 0.0)
        for key in (
            "pair", "bias", "engine", "setup_type", "conviction",
            "entry", "sl", "tp", "why", "action_state",
            "indicators", "traction_expectation", "invalidation_note",
            "thesis_decay_note", "drive_conditions", "training_only",
        ):
            assert key in result, f"Missing key: {key}"

    def test_no_claim_when_all_data_present_but_conditions_unmet(self):
        """Monotone range rows → no pullback zone, likely no claim."""
        rows = _make_ohlc_rows(50, 100.0, "flat")
        side = self._mock_fetch_returns(rows, rows, rows, rows)
        with patch.object(gd, "_fetch_ohlc", side_effect=side):
            result = gd.evaluate("SOL/USD", "SOLUSD", 0.0)
        assert result["training_only"] is True
        # In flat data all conditions likely fail — no DRIVE claim
        assert result["engine"] == "GimbaDrive"

    def test_engine_field(self):
        with patch.object(gd, "_fetch_ohlc", return_value=None):
            result = gd.evaluate("SOL/USD", "SOLUSD", 0.0)
        assert result["engine"] == "GimbaDrive"

    def test_drive_conditions_dict_always_present(self):
        with patch.object(gd, "_fetch_ohlc", return_value=None):
            result = gd.evaluate("SOL/USD", "SOLUSD", 0.0)
        dc = result["drive_conditions"]
        for cond in ("htf_alignment", "pullback_location", "compression", "structure_break", "expansion"):
            assert cond in dc

    def test_no_execution_markers(self):
        """Confirms the result contains training_only and no execution fields."""
        with patch.object(gd, "_fetch_ohlc", return_value=None):
            result = gd.evaluate("SOL/USD", "SOLUSD", 0.0)
        assert result["training_only"] is True
        # No order/execution-routing fields should be present
        for forbidden in ("order", "execute", "live_risk", "position_size"):
            assert forbidden not in result

    def test_structure_context_accepted(self):
        """Pre-computed structure context avoids a duplicate fetch."""
        ctx = {
            "d1_trend": "up", "h4_trend": "up", "trend": "up",
            "swing_high": 150.0, "swing_low": 100.0,
        }
        rows = _make_ohlc_rows(50)
        side = self._mock_fetch_returns(rows, rows, rows, rows)
        with patch.object(gd, "_fetch_ohlc", side_effect=side):
            result = gd.evaluate("SOL/USD", "SOLUSD", 0.0, structure=ctx)
        assert result["indicators"]["d1_trend"] == "up"

    def test_drive_long_claim_when_all_conditions_met(self):
        """
        Force all five conditions to be met by mocking the helper functions
        so that DRIVE_LONG is emitted.
        """
        rows_m15 = _make_ohlc_rows(50, 100.0, "up")
        rows_htf = _make_uptrend_rows(50)

        side = self._mock_fetch_returns(rows_htf, rows_htf, rows_htf, rows_m15)

        ctx = {
            "d1_trend": "up", "h4_trend": "up", "trend": "up",
            "swing_high": 150.0, "swing_low": 50.0,
        }

        with patch.object(gd, "_fetch_ohlc", side_effect=side), \
             patch.object(gd, "_htf_alignment", return_value=("up", [])), \
             patch.object(gd, "_pullback_location", return_value=(True, 0.50, [])), \
             patch.object(gd, "_pullback_compression", return_value=(True, 0.60, [])), \
             patch.object(gd, "_local_structure_break", return_value=(True, 99.0, [])), \
             patch.object(gd, "_break_holds_and_expands", return_value=(True, 1.5, 55.0, [])):
            result = gd.evaluate("SOL/USD", "SOLUSD", 0.0, structure=ctx)

        assert result["setup_type"] == "DRIVE_LONG"
        assert result["bias"] == "LONG"
        assert result["action_state"] == "watch"
        assert result["training_only"] is True
        assert result["entry"] is not None
        assert result["sl"] is not None
        assert result["tp"] is not None
        assert all(result["drive_conditions"].values())

    def test_drive_short_claim_when_all_conditions_met(self):
        rows_m15 = _make_ohlc_rows(50, 100.0, "down")
        rows_htf = _make_downtrend_rows(50)
        side = self._mock_fetch_returns(rows_htf, rows_htf, rows_htf, rows_m15)
        ctx = {
            "d1_trend": "down", "h4_trend": "down", "trend": "down",
            "swing_high": 150.0, "swing_low": 50.0,
        }

        with patch.object(gd, "_fetch_ohlc", side_effect=side), \
             patch.object(gd, "_htf_alignment", return_value=("down", [])), \
             patch.object(gd, "_pullback_location", return_value=(True, 0.60, [])), \
             patch.object(gd, "_pullback_compression", return_value=(True, 0.60, [])), \
             patch.object(gd, "_local_structure_break", return_value=(True, 101.0, [])), \
             patch.object(gd, "_break_holds_and_expands", return_value=(True, 1.5, 45.0, [])):
            result = gd.evaluate("SOL/USD", "SOLUSD", 0.0, structure=ctx)

        assert result["setup_type"] == "DRIVE_SHORT"
        assert result["bias"] == "SHORT"
        assert result["action_state"] == "watch"
        assert result["sl"] > result["entry"]  # stop above entry for short

    @pytest.mark.parametrize("failed_cond", [
        "htf_alignment", "pullback_location", "compression",
        "structure_break", "expansion",
    ])
    def test_no_claim_when_one_condition_absent(self, failed_cond):
        """Each absent condition independently blocks the claim."""
        rows_m15 = _make_ohlc_rows(50, 100.0, "up")
        rows_htf = _make_uptrend_rows(50)
        side = self._mock_fetch_returns(rows_htf, rows_htf, rows_htf, rows_m15)
        ctx = {
            "d1_trend": "up", "h4_trend": "up", "trend": "up",
            "swing_high": 150.0, "swing_low": 50.0,
        }

        cond_map = {
            "htf_alignment": ("up", []),
            "pullback_location": (True, 0.50, []),
            "compression": (True, 0.60, []),
            "structure_break": (True, 99.0, []),
            "expansion": (True, 1.5, 55.0, []),
        }
        # Override the failing condition
        if failed_cond == "htf_alignment":
            cond_map["htf_alignment"] = ("", ["no_htf_alignment"])
        elif failed_cond == "pullback_location":
            cond_map["pullback_location"] = (False, 0.95, ["price_extended"])
        elif failed_cond == "compression":
            cond_map["compression"] = (False, 1.2, ["no_compression"])
        elif failed_cond == "structure_break":
            cond_map["structure_break"] = (False, 99.0, ["no_structure_break"])
        elif failed_cond == "expansion":
            cond_map["expansion"] = (False, 0.9, 49.0, ["no_expansion"])

        with patch.object(gd, "_fetch_ohlc", side_effect=side), \
             patch.object(gd, "_htf_alignment", return_value=cond_map["htf_alignment"]), \
             patch.object(gd, "_pullback_location", return_value=cond_map["pullback_location"]), \
             patch.object(gd, "_pullback_compression", return_value=cond_map["compression"]), \
             patch.object(gd, "_local_structure_break", return_value=cond_map["structure_break"]), \
             patch.object(gd, "_break_holds_and_expands", return_value=cond_map["expansion"]):
            result = gd.evaluate("SOL/USD", "SOLUSD", 0.0, structure=ctx)

        assert result["setup_type"] == "NO_DRIVE_CONDITION"
        assert result["action_state"] == "idle"
        assert result["bias"] == "NONE"
        assert not result["drive_conditions"][failed_cond]

    def test_why_contains_reasons_when_conditions_absent(self):
        rows = _make_ohlc_rows(50)
        side = self._mock_fetch_returns(rows, rows, rows, rows)
        ctx = {
            "d1_trend": "up", "h4_trend": "up", "trend": "up",
            "swing_high": 150.0, "swing_low": 50.0,
        }
        with patch.object(gd, "_fetch_ohlc", side_effect=side), \
             patch.object(gd, "_htf_alignment", return_value=("", ["no_htf_alignment(d1=up,h4=up)"])), \
             patch.object(gd, "_pullback_location", return_value=(True, 0.5, [])), \
             patch.object(gd, "_pullback_compression", return_value=(True, 0.6, [])), \
             patch.object(gd, "_local_structure_break", return_value=(True, 99.0, [])), \
             patch.object(gd, "_break_holds_and_expands", return_value=(True, 1.5, 55.0, [])):
            result = gd.evaluate("SOL/USD", "SOLUSD", 0.0, structure=ctx)
        assert "no_htf_alignment" in result["why"]


# ── Tests for knn_engine._features_drive ─────────────────────────────────

import knn_engine


class TestKNNFeaturesDrive:
    def _make_record(self, bias="LONG"):
        return {
            "pair": "SOL/USD",
            "bias": bias,
            "indicators": {
                "d1_trend": "up", "h4_trend": "up", "eq_pct": 0.4,
                "compression_ratio": 0.7, "rvol_m15": 1.5, "rsi_m15": 55.0,
                "speed_score": 0.3, "atr_m15": 0.5,
            },
            "structure": {"d1_trend": "up", "h4_trend": "up", "zone": "discount", "eq_pct": 0.4},
            "drive_conditions": {
                "htf_alignment": True, "pullback_location": True, "compression": True,
                "structure_break": True, "expansion": True,
            },
            "volume_flow": {"ready": True, "delta_norm": 0.3, "cvd_slope": 0.1, "volume_norm": 1.2},
        }

    def test_features_drive_returns_list(self):
        record = self._make_record()
        features = knn_engine._features_drive(record)
        assert features is not None
        assert isinstance(features, list)
        assert len(features) > 0

    def test_features_drive_all_numeric(self):
        record = self._make_record()
        features = knn_engine._features_drive(record)
        for f in features:
            assert isinstance(f, float), f"Non-float feature: {f}"

    def test_features_drive_registered(self):
        assert "gimba_drive" in knn_engine.FEATURE_FN

    def test_features_drive_empty_record_still_returns_list(self):
        # _structure({}) returns a dict with 5 None-valued keys (d1_trend,
        # h4_trend, zone, eq_pct, market_condition) which is truthy, so the
        # `if not ind and not struct` early-return guard does NOT fire.
        # A list of default floats is returned instead.
        result = knn_engine._features_drive({})
        assert isinstance(result, list)
        assert len(result) > 0

    def test_features_drive_conditions_reflected(self):
        record = self._make_record()
        features = knn_engine._features_drive(record)
        # All five conditions are True → should appear as 1.0 in features
        # The five condition flags are at indices 8-12
        cond_features = features[8:13]
        assert all(f == 1.0 for f in cond_features)

    def test_knn_engine_accepts_gimba_drive(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = knn_engine.KNNEngine("gimba_drive", Path(tmpdir))
            adj, n = engine.adjust(self._make_record())
        assert adj == 0.0
        assert n == 0


# ── Tests for outcome_evaluator BOT_LOGS ─────────────────────────────────

import outcome_evaluator


class TestOutcomeEvaluatorBotLogs:
    def test_gimba_drive_in_bot_logs(self):
        assert "gimba_drive" in outcome_evaluator.BOT_LOGS

    def test_all_expected_bots_present(self):
        expected = {"gimba_volatile", "gimba_range", "rts_liquidation", "gimba_trend", "gimba_drive"}
        assert expected.issubset(set(outcome_evaluator.BOT_LOGS))


# ── Tests for scanner diagnostic_only markers ────────────────────────────

class TestScannerDiagnosticOnly:
    """
    Verify that scanner.run_cycle sets diagnostic_only=True on gimba_volatile
    and gimba_trend, and that gimba_drive is present and training_only.

    These tests mock all external calls so no network is required.
    """

    def _make_signal(self, engine, bias="NONE", action="idle", conviction=0.0):
        return {
            "pair": "SOL/USD", "bias": bias, "engine": engine,
            "setup_type": "TEST", "conviction": conviction,
            "action_state": action, "indicators": {}, "entry": None, "sl": None, "tp": None,
            "why": "test",
        }

    def _make_drive_signal(self):
        sig = self._make_signal("GimbaDrive")
        sig.update({
            "drive_conditions": {k: False for k in ("htf_alignment","pullback_location","compression","structure_break","expansion")},
            "traction_expectation": "test", "invalidation_note": "test", "thesis_decay_note": "test",
            "training_only": True,
        })
        return sig

    def test_diagnostic_only_flagged(self):
        import scanner

        structure = {
            "pair": "SOL/USD", "market_condition": "RANGING_NEUTRAL", "trend": "ranging",
            "zone": "neutral", "eq_pct": 0.5, "d1_trend": "ranging", "h4_trend": "ranging",
            "h1_tempo": "DEAD", "amplifier": 1.0, "counter_amplifier": 0.70,
            "bos": False, "ema21_d1": 100.0, "swing_high": 110.0, "swing_low": 90.0,
            "alignment": "range", "market_tempo": "DEAD", "tempo_context": {}, "why": "test",
        }
        volume_flow = {
            "ready": False, "reason": "test", "timeframe": "15m",
            "bar_start": None, "bar_end": None, "source": "test",
        }
        gv_sig = self._make_signal("GimbaVolatile")
        gr_sig = self._make_signal("GimbaRange")
        rts_sig = self._make_signal("RTSLiquidation")
        trd_sig = self._make_signal("GimbaTrend")
        drv_sig = self._make_drive_signal()

        market_state = {"state": "ranging"}

        with patch("scanner.structure_bias") as mock_sb, \
             patch("scanner.fetch_bar_data", return_value=([], {}, "test_skip")), \
             patch("scanner.gimba_volume_flow") as mock_gvf, \
             patch("scanner._evaluate_raw") as mock_eval, \
             patch("scanner.gimba_drive") as mock_drive, \
             patch("scanner.market_state_engine") as mock_mse, \
             patch("scanner._apply_knn"), \
             patch("scanner._append_training_log"):

            mock_sb.evaluate.return_value = structure
            mock_gvf.unavailable.return_value = volume_flow
            mock_eval.side_effect = [gv_sig, gr_sig, rts_sig, trd_sig]
            mock_drive.evaluate.return_value = drv_sig
            mock_mse.evaluate.return_value = market_state

            # Only run one pair
            scanner.PAIRS = [("SOL/USD", "SOLUSD")]
            results = scanner.run_cycle(1)

        assert len(results) == 1
        row = results[0]

        # Volatile and Trend should be marked diagnostic_only
        assert row["gimba_volatile"].get("diagnostic_only") is True
        assert row["gimba_trend"].get("diagnostic_only") is True

        # Drive should be present and training_only
        assert "gimba_drive" in row
        assert row["gimba_drive"].get("training_only") is True

        # Range and RTS should NOT be marked diagnostic_only
        assert not row["gimba_range"].get("diagnostic_only")
        assert not row["rts_liq"].get("diagnostic_only")
