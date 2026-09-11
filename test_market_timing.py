from __future__ import annotations

import copy
import re
import sys
from pathlib import Path
from unittest.mock import patch

GIMBA_DIR = Path(__file__).parent
sys.path.insert(0, str(GIMBA_DIR))

import market_timing
import scanner


def test_market_timing_classifies_post_sweep_confirmed():
    timing = market_timing.observe(
        structure={},
        volume_flow={"ready": True, "delta_state": "buy", "cvd_slope": 0.2},
        market_noise={"available": True, "regime": "MIXED"},
        market_state={"state": "FAILED_DOWN_AUCTION_RECLAIM"},
        rts_signal={
            "setup_type": "LIQUIDITY_SWEEP_RECLAIM_LONG",
            "indicators": {"swept_low": True, "reclaim_low": True},
        },
        range_signal={},
    )
    assert timing["base_status"] == "swept_reclaimed"
    assert timing["delta_state"] == "buy"
    assert timing["cvd_state"] == "rising"
    assert timing["noise_relation"] == "post_sweep"
    assert timing["timing_state"] == "CONFIRMED"
    assert isinstance(timing["reasons"], list) and timing["reasons"]


def test_market_timing_unavailable_fallback_shape():
    timing = market_timing.observe(
        structure={},
        volume_flow={"ready": False, "reason": "no_flow"},
        market_noise={"available": False, "reason": "missing"},
        market_state={},
        rts_signal={},
        range_signal={},
    )
    assert timing["base_status"] == "no_base"
    assert timing["delta_state"] == "unavailable"
    assert timing["cvd_state"] == "unavailable"
    assert timing["noise_relation"] == "unavailable"
    assert timing["timing_state"] == "OBSERVE"
    assert timing["gap"] == "no_actionable_base"


def test_market_timing_accepting_through_base_is_destructive():
    timing = market_timing.observe(
        structure={},
        volume_flow={"ready": True, "delta_state": "balanced", "cvd_slope": -0.1},
        market_noise={"available": True, "regime": "CHOPPY"},
        market_state={"state": "BALANCE"},
        rts_signal={"indicators": {"swept_high": True, "reclaim_high": False}},
        range_signal={},
    )
    assert timing["base_status"] == "accepting_through_base"
    assert timing["noise_relation"] == "destructive_at_base"
    assert timing["gap"] == "base_failing"
    assert timing["timing_state"] == "OBSERVE"


def test_market_timing_choppy_at_base_is_contested_stalk():
    timing = market_timing.observe(
        structure={},
        volume_flow={"ready": True, "delta_state": "balanced", "cvd_slope": 0.0},
        market_noise={"available": True, "regime": "CHOPPY"},
        market_state={"state": "BALANCE"},
        rts_signal={"indicators": {}},
        range_signal={"action_state": "watch"},
    )
    assert timing["base_status"] == "at_base"
    assert timing["noise_relation"] == "contested_at_base"
    assert timing["gap"] == "awaiting_pressure_alignment"
    assert timing["timing_state"] == "STALK"


def test_market_timing_aligned_at_base_requires_reclaim_hold():
    timing = market_timing.observe(
        structure={},
        volume_flow={"ready": True, "delta_state": "buy", "cvd_slope": 0.2},
        market_noise={"available": True, "regime": "MIXED"},
        market_state={"state": "BALANCE"},
        rts_signal={"indicators": {}},
        range_signal={"action_state": "watch"},
    )
    assert timing["base_status"] == "at_base"
    assert timing["noise_relation"] == "contested_at_base"
    assert timing["gap"] == "awaiting_reclaim_close_and_hold"
    assert timing["timing_state"] == "STALK"


def test_market_timing_aligned_holding_base_choppy_is_contested_with_gap():
    timing = market_timing.observe(
        structure={},
        volume_flow={"ready": True, "delta_state": "buy", "cvd_slope": 0.2},
        market_noise={"available": True, "regime": "CHOPPY"},
        market_state={"state": "FAILED_DOWN_AUCTION_RECLAIM"},
        rts_signal={"setup_type": "LIQUIDATION_TO_CONTINUATION_LONG", "indicators": {}},
        range_signal={},
    )
    assert timing["base_status"] == "holding_base"
    assert timing["noise_relation"] == "contested_at_base"
    assert timing["gap"] == "awaiting_noise_resolution"
    assert timing["timing_state"] == "STALK"


def test_attach_market_timing_is_read_only_to_existing_signal_fields():
    signal = {"bias": "LONG", "conviction": 0.7, "action_state": "watch"}
    baseline = copy.deepcopy(signal)
    attached = scanner._attach_market_timing(signal, market_timing.unavailable("test"))
    assert attached["market_timing"]["timing_state"] == "OBSERVE"
    without_timing = dict(attached)
    without_timing.pop("market_timing")
    assert without_timing == baseline


def test_run_cycle_adds_market_timing_with_dashboard_safe_shape():
    structure = {
        "pair": "SOL/USD", "market_condition": "RANGING_NEUTRAL", "trend": "ranging",
        "zone": "neutral", "eq_pct": 0.5, "d1_trend": "ranging", "h4_trend": "ranging",
        "h1_tempo": "DEAD", "amplifier": 1.0, "counter_amplifier": 0.70,
        "bos": False, "ema21_d1": 100.0, "swing_high": 110.0, "swing_low": 90.0,
        "alignment": "range", "market_tempo": "DEAD", "tempo_context": {}, "why": "test",
    }
    volume_flow = {
        "ready": False, "reason": "test", "timeframe": "15m",
        "bar_start": 1_700_000_000, "bar_end": 1_700_000_900, "source": "test",
    }
    market_state = {"state": "BALANCE"}
    base_gv = {"bias": "NONE", "setup_type": "GV", "why": "gv", "conviction": 0.1, "action_state": "idle"}
    base_gr = {"bias": "LONG", "setup_type": "GR", "why": "gr", "conviction": 0.6, "action_state": "watch"}
    base_rts = {"bias": "SHORT", "setup_type": "RTS", "why": "rts", "conviction": 0.6, "action_state": "watch", "indicators": {}}
    base_trd = {"bias": "LONG", "setup_type": "TRD", "why": "trd", "conviction": 0.2, "action_state": "idle"}
    base_drv = {"bias": "LONG", "setup_type": "DRV", "why": "drv", "conviction": 0.5, "action_state": "observe", "training_only": True}
    base_pulse = {"pulse_state": "PULSE_CHOPPY", "setup_type": "PULSE_CHOPPY", "why": "pulse", "pulse_score": 0.4, "action_state": "observe", "indicators": {}}
    shadow_vol = {"setup_family": "SHADOW_VOL_NO_SIGNAL", "side": "NONE", "score": 0.0, "state": "observe"}
    shadow_trd = {"setup_family": "SHADOW_TRD_NO_SIGNAL", "side": "NONE", "score": 0.0, "state": "observe"}

    with patch("scanner.structure_bias") as mock_sb, \
         patch("scanner.fetch_bar_data", return_value=([], {}, "test_skip")), \
         patch("scanner.gimba_volume_flow") as mock_gvf, \
         patch("scanner._evaluate_raw") as mock_eval, \
         patch("scanner.gimba_drive") as mock_drive, \
         patch("scanner.gimba_pulse") as mock_pulse, \
         patch("scanner.shadow_gimba_volatile") as mock_shd_vol, \
         patch("scanner.shadow_trend_recovery") as mock_shd_trd, \
         patch("scanner.market_state_engine") as mock_mse, \
         patch("scanner._apply_structure_amplifier"), \
         patch("scanner._apply_knn"), \
         patch("scanner._append_training_log"), \
         patch("scanner._append_shadow_log"), \
         patch("scanner._fetch_ohlc_arrays", return_value=(
             [100.0] * 8,
             [100.8, 101.0, 101.2, 101.4, 101.6, 101.8, 102.0, 102.2],
             [99.6, 99.8, 100.0, 100.2, 100.4, 100.6, 100.8, 101.0],
             [100.3, 100.6, 100.9, 101.2, 101.5, 101.8, 102.1, 102.4],
             [1.0] * 8,
             1_700_000_900,
         )):
        mock_sb.evaluate.return_value = structure
        mock_gvf.unavailable.return_value = volume_flow
        mock_eval.side_effect = [copy.deepcopy(base_gv), copy.deepcopy(base_gr), copy.deepcopy(base_rts), copy.deepcopy(base_trd)]
        mock_drive.evaluate.return_value = copy.deepcopy(base_drv)
        mock_pulse.evaluate.return_value = copy.deepcopy(base_pulse)
        mock_shd_vol.evaluate_arrays.return_value = copy.deepcopy(shadow_vol)
        mock_shd_trd.evaluate_arrays.return_value = copy.deepcopy(shadow_trd)
        mock_mse.evaluate.return_value = market_state
        original_pairs = scanner.PAIRS
        scanner.PAIRS = [("SOL/USD", "SOLUSD")]
        try:
            row = scanner.run_cycle(1)[0]
        finally:
            scanner.PAIRS = original_pairs

    required = {"base_status", "delta_state", "cvd_state", "noise_relation", "gap", "timing_state", "reasons", "rationale"}
    assert required.issubset(set(row["market_timing"]))
    for key in ("gimba_volatile", "gimba_range", "rts_liq", "gimba_trend", "gimba_drive", "gimba_pulse", "shadow_volatile", "shadow_trend_recovery"):
        assert required.issubset(set(row[key]["market_timing"]))


def test_timing_not_in_offense_permission_or_execution_sets():
    html = (GIMBA_DIR / "JHL-Market-Edge-Shell.html").read_text(encoding="utf-8")
    exec_block = re.search(r"const EXEC_BOTS\s*=\s*\[(.+?)\];", html)
    train_block = re.search(r"const TRAIN_BOTS\s*=\s*\[(.+?)\];", html)
    offense_fn = re.search(r"function offense\(row\)\s*\{(.+?)\n\}", html, re.DOTALL)
    permission_fn = re.search(r"function permissionCard\(row\)\s*\{(.+?)\n\}", html, re.DOTALL)
    assert exec_block and train_block and offense_fn and permission_fn
    assert "market_timing" not in exec_block.group(1)
    assert "market_timing" not in train_block.group(1)
    assert "market_timing" not in offense_fn.group(1)
    assert "market_timing" not in permission_fn.group(1)
