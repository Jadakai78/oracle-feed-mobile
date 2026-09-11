"""
Focused tests for the Gimba Pulse training-only observer.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

GIMBA_DIR = Path(__file__).parent
sys.path.insert(0, str(GIMBA_DIR))

import gimba_pulse as gp
import outcome_evaluator


def _row(ts: int, open_: float, high: float, low: float, close: float, volume: float = 1.0) -> list:
    return [ts, str(open_), str(high), str(low), str(close), "0", str(volume)]


def _dead_rows() -> list:
    rows = []
    price = 100.0
    for i in range(12):
        close = price + (0.02 if i % 2 else -0.01)
        rows.append(_row(1000 + i * 900, price, price + 0.08, price - 0.08, close, 1.0))
        price = close
    return rows


def _impulsive_rows() -> list:
    rows = []
    price = 100.0
    for i in range(6):
        close = price + 0.15
        rows.append(_row(1000 + i * 900, price, close + 0.12, price - 0.08, close, 1.0))
        price = close
    for i in range(6, 12):
        close = price + 0.9
        rows.append(_row(1000 + i * 900, price, close + 0.25, price - 0.05, close, 2.0))
        price = close
    return rows


def _choppy_rows() -> list:
    rows = []
    price = 100.0
    for i in range(12):
        close = price + (0.35 if i % 2 == 0 else -0.32)
        high = max(price, close) + 0.45
        low = min(price, close) - 0.45
        rows.append(_row(1000 + i * 900, price, high, low, close, 1.2))
        price = close
    return rows


def _exhausted_rows() -> list:
    rows = []
    price = 100.0
    for i in range(8):
        close = price + 0.7
        rows.append(_row(1000 + i * 900, price, close + 0.15, price - 0.05, close, 1.5))
        price = close
    prev_high = max(float(row[2]) for row in rows[-5:])
    open_ = price + 0.1
    high = prev_high + 0.8
    close = prev_high - 0.2
    low = min(open_, close) - 0.6
    rows.extend([
        _row(1000 + 8 * 900, open_, high, low, close, 1.8),
        _row(1000 + 9 * 900, close, close + 0.2, close - 0.7, close - 0.3, 1.6),
        _row(1000 + 10 * 900, close - 0.3, close, close - 0.9, close - 0.6, 1.5),
        _row(1000 + 11 * 900, close - 0.6, close - 0.2, close - 1.0, close - 0.8, 1.4),
    ])
    return rows


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (_dead_rows(), gp.STATE_DEAD),
        (_choppy_rows(), gp.STATE_CHOPPY),
        (_impulsive_rows(), gp.STATE_IMPULSIVE),
        (_exhausted_rows(), gp.STATE_EXHAUSTED),
    ],
)
def test_pulse_classification(rows, expected):
    with patch.object(gp, "_fetch_ohlc", return_value=rows):
        result = gp.evaluate("SOL/USD", "SOLUSD", 0.0)
    assert result["pulse_state"] == expected
    assert result["setup_type"] == expected
    assert result["training_only"] is True
    assert result["diagnostic_only"] is True
    assert result["entry"] is None and result["sl"] is None and result["tp"] is None


def test_pulse_output_contains_required_metrics_and_limitations():
    with patch.object(gp, "_fetch_ohlc", return_value=_impulsive_rows()):
        result = gp.evaluate("SOL/USD", "SOLUSD", 0.0)
    assert result["action_state"] == "observe"
    for key in (
        "realized_range",
        "range_expansion",
        "directional_efficiency",
        "alternation_ratio",
        "directional_run_length",
        "wick_body_noise",
        "breakout_status",
    ):
        assert key in result["indicators"]
    assert result["diagnostics"]["ohlcv_limitations"]


def test_scanner_integrates_pulse_without_knn_or_execution_scope():
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

    def _sig(engine):
        return {
            "pair": "SOL/USD", "bias": "NONE", "engine": engine,
            "setup_type": "TEST", "conviction": 0.0, "action_state": "idle",
            "indicators": {}, "entry": None, "sl": None, "tp": None, "why": "test",
        }

    drive = _sig("GimbaDrive")
    drive.update({
        "drive_conditions": {k: False for k in ("htf_alignment", "pullback_location", "compression", "structure_break", "expansion")},
        "traction_expectation": "test", "invalidation_note": "test", "thesis_decay_note": "test",
        "training_only": True,
    })
    pulse = {
        "pair": "SOL/USD",
        "bias": "NONE",
        "engine": "GimbaPulse",
        "setup_type": gp.STATE_CHOPPY,
        "pulse_state": gp.STATE_CHOPPY,
        "pulse_score": 0.42,
        "conviction": 0.42,
        "entry": None,
        "sl": None,
        "tp": None,
        "why": "test pulse",
        "action_state": "observe",
        "indicators": {"realized_range": 0.01},
        "diagnostics": {"reference_bar_start": 12345},
        "training_only": True,
        "diagnostic_only": True,
    }

    with patch("scanner.structure_bias") as mock_sb, \
         patch("scanner.fetch_bar_data", return_value=([], {}, "test_skip")), \
         patch("scanner.gimba_volume_flow") as mock_gvf, \
         patch("scanner._evaluate_raw") as mock_eval, \
         patch("scanner.gimba_drive") as mock_drive, \
         patch("scanner.gimba_pulse") as mock_pulse, \
         patch("scanner.market_state_engine") as mock_mse, \
         patch("scanner._apply_knn") as mock_knn, \
         patch("scanner._append_training_log") as mock_log:
        mock_sb.evaluate.return_value = structure
        mock_gvf.unavailable.return_value = volume_flow
        mock_eval.side_effect = [_sig("GimbaVolatile"), _sig("GimbaRange"), _sig("RTSLiquidation"), _sig("GimbaTrend")]
        mock_drive.evaluate.return_value = drive
        mock_pulse.evaluate.return_value = pulse
        mock_mse.evaluate.return_value = {"state": "ranging"}
        scanner.PAIRS = [("SOL/USD", "SOLUSD")]
        results = scanner.run_cycle(1)

    row = results[0]
    assert row["gimba_pulse"]["training_only"] is True
    assert row["gimba_pulse"]["diagnostic_only"] is True
    assert mock_knn.call_count == 3
    assert "gimba_pulse" in [call.kwargs["bot_name"] for call in mock_log.call_args_list]


def test_pulse_in_outcome_bot_logs():
    assert "gimba_pulse" in outcome_evaluator.BOT_LOGS


def test_pulse_outcome_labels_forward_metrics_without_trade_result():
    start_epoch = 1_700_000_000
    record = {
        "schema_version": 2,
        "bot": "gimba_pulse",
        "pair": "SOL/USD",
        "ts": datetime.fromtimestamp(start_epoch, tz=timezone.utc).isoformat(),
        "state": gp.STATE_IMPULSIVE,
        "setup_type": gp.STATE_IMPULSIVE,
        "diagnostics": {
            "observer_direction": "UP",
            "breakout_side": "UP",
            "breakout_level": 100.5,
            "reference_close": 101.0,
            "reference_bar_start": start_epoch,
        },
        "outcome": {"status": "pending", "label": None},
    }
    rows = [_row(start_epoch, 100.0, 101.2, 99.8, 101.0)]
    price = 101.0
    for i in range(1, 17):
        close = price + 0.4
        rows.append(_row(start_epoch + i * 900, price, close + 0.2, price - 0.1, close))
        price = close
    now_epoch = start_epoch + outcome_evaluator.HORIZON_BARS * 900
    with patch.object(outcome_evaluator, "_ohlc", return_value=rows):
        outcome = outcome_evaluator._resolve(record, now_epoch)
    assert outcome["status"] == "resolved"
    assert outcome["label"] is None
    assert set(("15m", "30m", "60m", "16bar")).issubset(outcome["horizons"])
    assert outcome["horizons"]["15m"]["local_break_status"] == "HELD"


def test_append_training_log_persists_pulse_diagnostics_for_forward_resolution(tmp_path):
    import scanner

    scanner.LOG_DIR = tmp_path
    scanner.LOG_DIR.mkdir(exist_ok=True)
    scanner._SEEN_EVENT_KEYS.clear()

    start_epoch = 1_700_000_000
    signal = {
        "setup_type": gp.STATE_IMPULSIVE,
        "pulse_state": gp.STATE_IMPULSIVE,
        "conviction": 0.91,
        "pulse_score": 0.91,
        "action_state": "observe",
        "why": "test pulse",
        "training_only": True,
        "diagnostic_only": True,
        "indicators": {"realized_range": 0.02},
        "diagnostics": {
            "observer_direction": "UP",
            "breakout_side": "UP",
            "breakout_level": 100.5,
            "reference_close": 101.0,
            "reference_bar_start": start_epoch,
        },
    }
    scanner._append_training_log(
        bot_name="gimba_pulse",
        pair="SOL/USD",
        signal=signal,
        ts=datetime.fromtimestamp(start_epoch, tz=timezone.utc).isoformat(),
        event_key="SOL/USD|gimba_pulse|15m|12345",
        structure={},
        diagnostics={"reference_close": 999.0, "observer_direction": "DOWN"},
        volume_flow={},
    )

    record = json.loads((tmp_path / "gimba_pulse.jsonl").read_text(encoding="utf-8").strip())
    assert record["diagnostics"]["reference_close"] == 101.0
    assert record["diagnostics"]["reference_bar_start"] == start_epoch
    assert record["diagnostics"]["observer_direction"] == "UP"
    assert record["diagnostics"]["breakout_side"] == "UP"
    assert record["diagnostics"]["breakout_level"] == 100.5

    rows = [_row(start_epoch, 100.0, 101.2, 99.8, 101.0)]
    price = 101.0
    for i in range(1, 17):
        close = price + 0.4
        rows.append(_row(start_epoch + i * 900, price, close + 0.2, price - 0.1, close))
        price = close

    with patch.object(outcome_evaluator, "_ohlc", return_value=rows):
        outcome = outcome_evaluator._resolve_pulse(
            record,
            start_epoch + outcome_evaluator.HORIZON_BARS * 900,
        )

    assert outcome is not None
    assert outcome["status"] == "resolved"
    assert set(("15m", "30m", "60m", "16bar")).issubset(outcome["horizons"])
