from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

GIMBA_DIR = Path(__file__).parent
sys.path.insert(0, str(GIMBA_DIR))

import market_noise
import scanner
import shadow_scoreboard as ss


def test_market_noise_metrics_are_deterministic():
    opens = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    highs = [101.4, 102.1, 103.2, 104.3, 105.4, 106.5]
    lows = [99.8, 100.6, 101.8, 102.8, 103.8, 104.8]
    closes = [101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
    first = market_noise.observe(opens, highs, lows, closes, reference_bar_start=1_700_000_000)
    second = market_noise.observe(opens, highs, lows, closes, reference_bar_start=1_700_000_000)
    assert first == second
    assert first["regime"] == "CLEAN"
    assert first["available"] is True


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.339, "CLEAN"),
        (0.340, "MIXED"),
        (0.669, "MIXED"),
        (0.670, "CHOPPY"),
    ],
)
def test_market_noise_regime_boundaries(score, expected):
    assert market_noise.classify_noise_score(score) == expected


def test_market_noise_unavailable_shape_is_dashboard_safe():
    noise = market_noise.unavailable("missing_bars", reference_bar_start=1_700_000_000)
    assert noise["available"] is False
    assert noise["regime"] is None
    assert noise["noise_score"] is None
    assert noise["reference_bar_end"] == 1_700_000_900


def test_market_noise_rejects_subminimum_window():
    noise = market_noise.observe(
        [100.0] * 6,
        [101.0] * 6,
        [99.0] * 6,
        [100.5] * 6,
        window_bars=4,
    )
    assert noise["available"] is False
    assert noise["reason"] == "window_bars_below_minimum"


@pytest.mark.parametrize(
    "bot_name",
    [
        "gimba_volatile",
        "gimba_range",
        "rts_liquidation",
        "gimba_trend",
        "gimba_drive",
        "gimba_pulse",
    ],
)
def test_training_logs_persist_market_noise(bot_name, tmp_path):
    original_log_dir = scanner.LOG_DIR
    original_seen = scanner._SEEN_EVENT_KEYS.copy()
    scanner.LOG_DIR = tmp_path
    scanner._SEEN_EVENT_KEYS.clear()
    signal = {
        "setup_type": "TEST",
        "bias": "LONG",
        "conviction": 0.6,
        "action_state": "watch",
        "why": "test",
        "indicators": {},
        "diagnostics": {},
        "market_noise": {"available": True, "regime": "MIXED", "noise_score": 0.51},
    }
    try:
        scanner._append_training_log(
            bot_name=bot_name,
            pair="SOL/USD",
            signal=signal,
            ts="2026-01-01T00:00:00+00:00",
            event_key=f"SOL/USD|{bot_name}|15m|1",
            structure={},
            diagnostics={},
            volume_flow={},
        )
        record = json.loads((tmp_path / f"{bot_name}.jsonl").read_text(encoding="utf-8").strip())
        assert record["market_noise"]["regime"] == "MIXED"
        assert record["market_noise"]["noise_score"] == 0.51
    finally:
        scanner.LOG_DIR = original_log_dir
        scanner._SEEN_EVENT_KEYS.clear()
        scanner._SEEN_EVENT_KEYS.update(original_seen)


@pytest.mark.parametrize("bot_name", ["shadow_volatile", "shadow_trend_recovery"])
def test_shadow_logs_persist_market_noise(bot_name, tmp_path):
    original_log_dir = scanner.LOG_DIR
    original_seen = scanner._SEEN_EVENT_KEYS.copy()
    scanner.LOG_DIR = tmp_path
    scanner._SEEN_EVENT_KEYS.clear()
    signal = {
        "setup_family": "SHADOW_TEST",
        "side": "LONG",
        "score": 0.55,
        "state": "observe",
        "reasons": [],
        "required_inputs": [],
        "invalidation_level": None,
        "maturity_context": None,
        "reference_price": 100.0,
        "reference_bar_ts": 1000,
        "shadow_mode": True,
        "diagnostic_only": True,
        "training_only": True,
        "action_state": "observe",
        "indicators": {},
        "market_noise": {"available": True, "regime": "CHOPPY", "noise_score": 0.83},
    }
    try:
        scanner._append_shadow_log(
            bot_name=bot_name,
            pair="SOL/USD",
            signal=signal,
            ts="2026-01-01T00:00:00+00:00",
            event_key=f"SOL/USD|{bot_name}|15m|1",
            structure={},
            volume_flow={},
        )
        record = json.loads((tmp_path / f"{bot_name}.jsonl").read_text(encoding="utf-8").strip())
        assert record["market_noise"]["regime"] == "CHOPPY"
        assert record["market_noise"]["noise_score"] == 0.83
    finally:
        scanner.LOG_DIR = original_log_dir
        scanner._SEEN_EVENT_KEYS.clear()
        scanner._SEEN_EVENT_KEYS.update(original_seen)


def test_attach_market_noise_is_read_only_to_existing_signal_fields():
    signal = {"bias": "LONG", "conviction": 0.7, "action_state": "watch"}
    baseline = copy.deepcopy(signal)
    attached = scanner._attach_market_noise(signal, {"available": True, "regime": "CLEAN", "noise_score": 0.2})
    assert attached["market_noise"]["regime"] == "CLEAN"
    without_noise = dict(attached)
    without_noise.pop("market_noise")
    assert without_noise == baseline


def test_run_cycle_adds_only_market_noise_analytics_to_signals():
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
    market_state = {"state": "ranging"}
    base_gv = {"bias": "NONE", "setup_type": "GV", "why": "gv", "conviction": 0.1, "action_state": "idle"}
    base_gr = {"bias": "LONG", "setup_type": "GR", "why": "gr", "conviction": 0.6, "action_state": "watch"}
    base_rts = {"bias": "SHORT", "setup_type": "RTS", "why": "rts", "conviction": 0.6, "action_state": "watch"}
    base_trd = {"bias": "LONG", "setup_type": "TRD", "why": "trd", "conviction": 0.2, "action_state": "idle"}
    base_drv = {"bias": "LONG", "setup_type": "DRV", "why": "drv", "conviction": 0.5, "action_state": "observe", "training_only": True}
    base_pulse = {"pulse_state": "PULSE_CHOPPY", "setup_type": "PULSE_CHOPPY", "why": "pulse", "pulse_score": 0.4, "action_state": "observe", "indicators": {}}
    shadow_vol = {"setup_family": "SHADOW_VOL_NO_SIGNAL", "side": "NONE", "score": 0.0, "state": "observe"}
    shadow_trd = {"setup_family": "SHADOW_TRD_NO_SIGNAL", "side": "NONE", "score": 0.0, "state": "observe"}
    expected = {
        "gimba_volatile": {"bias": "NONE", "setup_type": "GV", "why": "gv", "conviction": 0.1, "action_state": "idle", "diagnostic_only": True},
        "gimba_range": base_gr,
        "rts_liq": base_rts,
        "gimba_trend": {"bias": "LONG", "setup_type": "TRD", "why": "trd", "conviction": 0.2, "action_state": "idle", "diagnostic_only": True},
        "gimba_drive": base_drv,
        "gimba_pulse": {"pulse_state": "PULSE_CHOPPY", "setup_type": "PULSE_CHOPPY", "why": "pulse", "pulse_score": 0.4, "action_state": "observe", "indicators": {}, "training_only": True, "diagnostic_only": True},
        "shadow_volatile": shadow_vol,
        "shadow_trend_recovery": shadow_trd,
    }

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

    assert row["market_noise"]["available"] is True
    for key, expected_signal in expected.items():
        actual = dict(row[key])
        assert "market_noise" in actual
        assert "market_timing" in actual
        actual.pop("market_noise")
        actual.pop("market_timing")
        assert actual == expected_signal


def test_scoreboard_groups_stats_by_noise_regime():
    records = [
        {
            "bot": "shadow_volatile",
            "setup_family": "A",
            "market_noise": {"regime": "CLEAN"},
            "outcome": {"status": "resolved", "label": None, "horizons": {"16bar": {"net_directional_return": 0.04, "mfe": 0.05, "mae": -0.01}}},
        },
        {
            "bot": "shadow_volatile",
            "setup_family": "B",
            "market_noise": {"regime": "CHOPPY"},
            "outcome": {"status": "resolved", "label": None, "horizons": {"16bar": {"net_directional_return": -0.03, "mfe": 0.02, "mae": -0.04}}},
        },
        {
            "bot": "shadow_volatile",
            "setup_family": "B",
            "market_noise": {"regime": "CHOPPY"},
            "outcome": {"status": "pending", "label": None},
        },
    ]
    stats = ss.compute_stats(records)
    assert stats["noise_regimes"]["CLEAN"]["sample_count"] == 1
    assert stats["noise_regimes"]["CLEAN"]["directional_hit_rate"] == 1.0
    assert stats["noise_regimes"]["CHOPPY"]["sample_count"] == 2
    assert stats["noise_regimes"]["CHOPPY"]["resolved_count"] == 1
    assert stats["noise_regimes"]["CHOPPY"]["coverage"] == 0.5
