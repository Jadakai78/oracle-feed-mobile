$ErrorActionPreference = 'Stop'
$root = 'C:\Users\jason\OneDrive\Desktop\jhl_v2\jhl_v2gimba'
Set-Location $root
$router = Join-Path $root 'delta_tempo_prop_router.py'
$expected = 'B5522981B0B648FEA03F5531ECDE38605224EC5CE9912CA92D39550352D5FDFC'
$actual = (Get-FileHash $router -Algorithm SHA256).Hash
if ($actual -ne $expected) { throw "Router hash mismatch. Expected $expected but found $actual. Nothing changed." }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backup = "$router.speed_companion_$stamp.bak"
Copy-Item $router $backup -Force

$companion = @'
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict

import numpy as np

_STATE: Dict[str, Dict[str, Any]] = defaultdict(dict)
MIN_PRICE_VELOCITY = 0.35
MIN_PRICE_ACCEL = 1.15
DECAY_RATIO = 0.70
PULLBACK_MAX_ATR = 1.50


def _n(value: Any):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _completed(ohlcv_arrays: tuple | None):
    if not ohlcv_arrays or len(ohlcv_arrays) < 5:
        return None
    try:
        _, highs, lows, closes, _, _ = ohlcv_arrays
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)
        closes = np.asarray(closes, dtype=float)
    except (TypeError, ValueError):
        return None
    if min(len(highs), len(lows), len(closes)) < 6:
        return None
    return highs[:-1], lows[:-1], closes[:-1]


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float | None:
    if len(closes) < 4:
        return None
    tr = np.maximum(highs[1:] - lows[1:], np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])))
    value = float(np.mean(tr[-10:])) if len(tr) else 0.0
    return value if value > 0 and math.isfinite(value) else None


def _price_metrics(side: str, ohlcv_arrays: tuple | None):
    completed = _completed(ohlcv_arrays)
    if completed is None:
        return None, None, None, None, None, None
    highs, lows, closes = completed
    atr = _atr(highs, lows, closes)
    if atr is None or len(closes) < 4:
        return None, None, atr, None, None, None
    signed_move = closes[-1] - closes[-3]
    velocity = abs(signed_move) / atr
    aligned = signed_move > 0 if side == 'LONG' else signed_move < 0 if side == 'SHORT' else False
    price = float(closes[-1])
    local_high = float(np.max(highs[-5:]))
    local_low = float(np.min(lows[-5:]))
    return velocity, aligned, atr, price, local_high, local_low


def _base(state: str, side: str, velocity, prior_velocity, accel, active: bool, reasons: list[str], price, atr, level):
    return {
        'schema_version': 'delta_tempo_speed_companion_v1',
        'episode_state': state,
        'episode_direction': side,
        'initial_impulse_detected': state not in {'IDLE', 'NO_DATA'},
        'watch_reference_price': state and price if state == 'WATCH_INITIAL_IMPULSE' else None,
        'watch_reference_level': level if state == 'WATCH_INITIAL_IMPULSE' else None,
        'price_velocity': round(velocity, 6) if velocity is not None else None,
        'prior_price_velocity': round(prior_velocity, 6) if prior_velocity is not None else None,
        'price_velocity_acceleration_ratio': round(accel, 6) if accel is not None else None,
        'impulse_quality': 'HIGH' if velocity is not None and velocity >= 1.0 else 'MEANINGFUL' if velocity is not None and velocity >= MIN_PRICE_VELOCITY else 'LOW',
        'persistence_state': 'ACTIVE' if active else 'INACTIVE',
        'promotion_pattern': None,
        'active_feed_visibility': active,
        'manual_review_only': True,
        'entry_authority': False,
        'reason_codes': reasons,
        'atr': round(atr, 8) if atr is not None else None,
    }


def evaluate(pair: str, side: str, ready: bool, flow_speed, flow_acceleration_ratio, reclaim_confirmed: bool, structure: Dict[str, Any] | None, market_state: Dict[str, Any] | None, ohlcv_arrays: tuple | None) -> Dict[str, Any]:
    state = _STATE[pair]
    structure = structure or {}
    market_state = market_state or {}
    velocity, aligned_price, atr, price, local_high, local_low = _price_metrics(side, ohlcv_arrays)
    prior_velocity = state.get('price_velocity')
    accel = velocity / prior_velocity if velocity is not None and prior_velocity and prior_velocity > 0 else None
    flow_ok = bool(ready and side in {'LONG', 'SHORT'} and flow_speed is not None and flow_speed >= 0.50)
    price_ok = bool(velocity is not None and velocity >= MIN_PRICE_VELOCITY and aligned_price)
    condition = str(structure.get('market_condition') or '').upper()
    mechanism = str(market_state.get('mechanism') or '').upper()
    bos = bool(structure.get('bos'))

    if not flow_ok or velocity is None:
        result = _base('NO_DATA' if velocity is None else 'IDLE', side, velocity, prior_velocity, accel, False, ['price_or_flow_unavailable'], price, atr, None)
        state['price_velocity'] = velocity
        return result

    episode = state.get('episode_state', 'IDLE')
    prior_side = state.get('side')
    if prior_side in {'LONG', 'SHORT'} and side != prior_side:
        state.clear()
        state.update({'side': side, 'episode_state': 'INVALIDATED', 'price_velocity': velocity})
        return _base('INVALIDATED', side, velocity, prior_velocity, accel, False, ['delta_direction_reversal'], price, atr, None)

    if episode in {'IDLE', 'NO_DATA', 'DROPPED', 'INVALIDATED'}:
        if price_ok:
            level = local_low if side == 'LONG' else local_high
            state.update({'side': side, 'episode_state': 'WATCH_INITIAL_IMPULSE', 'initial_price': price, 'reference_level': level, 'peak_velocity': velocity, 'price_velocity': velocity})
            return _base('WATCH_INITIAL_IMPULSE', side, velocity, prior_velocity, accel, True, ['initial_aligned_flow_price_impulse_watch_only'], price, atr, level)
        state.update({'side': side, 'episode_state': 'IDLE', 'price_velocity': velocity})
        return _base('IDLE', side, velocity, prior_velocity, accel, False, ['no_meaningful_aligned_price_impulse'], price, atr, None)

    peak = max(float(state.get('peak_velocity') or 0.0), float(velocity or 0.0))
    state['peak_velocity'] = peak
    retention = velocity / peak if peak > 0 and velocity is not None else None
    initial_price = _n(state.get('initial_price'))
    pullback = False
    if initial_price is not None and atr is not None and price is not None:
        pullback_distance = (initial_price - price) if side == 'LONG' else (price - initial_price)
        pullback = 0 < pullback_distance <= atr * PULLBACK_MAX_ATR

    structural_failure = (side == 'LONG' and state.get('reference_level') is not None and price is not None and price < state['reference_level'] - (atr or 0.0) * 0.25) or (side == 'SHORT' and state.get('reference_level') is not None and price is not None and price > state['reference_level'] + (atr or 0.0) * 0.25)
    if structural_failure:
        state.update({'episode_state': 'INVALIDATED', 'price_velocity': velocity})
        return _base('INVALIDATED', side, velocity, prior_velocity, accel, False, ['watch_reference_level_failed'], price, atr, state.get('reference_level'))

    if retention is not None and retention < DECAY_RATIO:
        state.update({'episode_state': 'DROPPED', 'price_velocity': velocity})
        return _base('DROPPED', side, velocity, prior_velocity, accel, False, ['price_velocity_decay_below_retention_threshold'], price, atr, state.get('reference_level'))

    reaccelerating = bool(price_ok and accel is not None and accel >= MIN_PRICE_ACCEL and flow_acceleration_ratio is not None and flow_acceleration_ratio >= 1.0)
    pattern = None
    reasons = []
    if reaccelerating and reclaim_confirmed:
        pattern = 'CONFIRMED_RECLAIM_ACCELERATION'
        reasons = ['reclaim_confirmed', 'price_velocity_reaccelerated', 'delta_flow_aligned']
    elif reaccelerating and (bos or 'BREAK' in condition):
        pattern = 'CONFIRMED_BREAKOUT_ACCEPTANCE'
        reasons = ['breakout_or_bos_context', 'price_velocity_reaccelerated', 'delta_flow_aligned']
    elif reaccelerating and (pullback or 'PULLBACK' in condition or mechanism == 'PULLBACK_RECLAIM'):
        pattern = 'CONFIRMED_PULLBACK_REACCELERATION'
        reasons = ['controlled_pullback_or_reclaim_context', 'price_velocity_reaccelerated', 'delta_flow_aligned']

    if pattern:
        state.update({'episode_state': pattern, 'price_velocity': velocity})
        result = _base(pattern, side, velocity, prior_velocity, accel, True, reasons, price, atr, state.get('reference_level'))
        result['promotion_pattern'] = pattern.replace('CONFIRMED_', '')
        return result

    next_state = 'WATCH_PULLBACK' if pullback else 'WATCH_PERSISTING'
    state.update({'episode_state': next_state, 'price_velocity': velocity})
    return _base(next_state, side, velocity, prior_velocity, accel, True, ['initial_impulse_remains_under_observation'], price, atr, state.get('reference_level'))
'@
Set-Content -Path (Join-Path $root 'delta_tempo_speed_companion.py') -Value $companion -Encoding UTF8

$test = @'
import unittest
import numpy as np
import delta_tempo_speed_companion as companion


def bars(values):
    values = np.asarray(values, dtype=float)
    highs = values + 0.5
    lows = values - 0.5
    opens = values - 0.1
    volumes = np.ones(len(values))
    times = np.arange(len(values))
    return times, highs, lows, values, volumes, volumes


class SpeedCompanionTests(unittest.TestCase):
    def setUp(self):
        companion._STATE.clear()

    def call(self, pair, closes, speed=0.8, ratio=1.3, reclaim=False, structure=None, state=None):
        return companion.evaluate(pair, 'LONG', True, speed, ratio, reclaim, structure or {'market_condition': 'TRENDING_UP'}, state or {}, bars(closes))

    def test_initial_impulse_is_watch_only(self):
        result = self.call('A', [100, 100.2, 100.5, 101.0, 102.0, 103.0, 104.0])
        self.assertEqual(result['episode_state'], 'WATCH_INITIAL_IMPULSE')
        self.assertTrue(result['active_feed_visibility'])
        self.assertFalse(result['entry_authority'])

    def test_pullback_reacceleration_promotes_after_watch(self):
        self.call('B', [100, 100.2, 100.5, 101.0, 102.0, 103.0, 104.0])
        self.call('B', [100, 100.2, 100.5, 101.0, 102.0, 103.0, 102.6], ratio=1.0)
        result = self.call('B', [100, 100.2, 100.5, 101.0, 102.0, 102.6, 104.4], ratio=1.3, structure={'market_condition': 'PULLBACK_UP'})
        self.assertEqual(result['episode_state'], 'CONFIRMED_PULLBACK_REACCELERATION')

    def test_reclaim_promotes(self):
        self.call('C', [100, 100.2, 100.5, 101.0, 102.0, 103.0, 104.0])
        result = self.call('C', [100, 100.2, 100.5, 101.0, 102.0, 101.8, 104.8], reclaim=True)
        self.assertEqual(result['episode_state'], 'CONFIRMED_RECLAIM_ACCELERATION')

    def test_breakout_acceptance_promotes(self):
        self.call('D', [100, 100.2, 100.5, 101.0, 102.0, 103.0, 104.0])
        result = self.call('D', [100, 100.2, 100.5, 101.0, 102.0, 103.0, 105.0], structure={'market_condition': 'BREAKOUT_UP', 'bos': True})
        self.assertEqual(result['episode_state'], 'CONFIRMED_BREAKOUT_ACCEPTANCE')

    def test_decay_drops_visibility(self):
        self.call('E', [100, 100.2, 100.5, 101.0, 102.0, 103.0, 106.0])
        result = self.call('E', [100, 100.2, 100.5, 101.0, 102.0, 105.8, 106.0], ratio=1.0)
        self.assertEqual(result['episode_state'], 'DROPPED')
        self.assertFalse(result['active_feed_visibility'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
'@
Set-Content -Path (Join-Path $root 'test_delta_tempo_speed_companion.py') -Value $test -Encoding UTF8

$doc = @'
# Delta Tempo Speed Companion

## Purpose

This local, read-only companion adds a price-speed episode lifecycle to Delta/Tempo. It does not place orders, send alerts, modify queues, replace Delta stops or targets, or grant entry authority.

## Rule

The first aligned Delta plus price-speed movement is `WATCH_INITIAL_IMPULSE`, not an entry. It records a reference price and structural level. Only later confirmation can promote the episode for manual review.

## States

- `WATCH_INITIAL_IMPULSE`: first meaningful aligned price response; watch only.
- `WATCH_PERSISTING`: impulse remains under observation.
- `WATCH_PULLBACK`: controlled reset/pullback remains inside the watched thesis.
- `CONFIRMED_PULLBACK_REACCELERATION`: controlled pullback then renewed aligned price velocity.
- `CONFIRMED_BREAKOUT_ACCEPTANCE`: breakout/BOS context then renewed aligned price velocity.
- `CONFIRMED_RECLAIM_ACCELERATION`: reclaim confirmed then renewed aligned price velocity.
- `DROPPED`: price velocity retention falls below the configured threshold; active visibility ends but the state remains auditable.
- `INVALIDATED`: direction reverses or the watched reference level fails.

## Measurements

- Flow speed and flow acceleration remain owned by Delta/Tempo.
- Price velocity is the absolute two-bar completed-close displacement divided by a completed-bar ATR estimate.
- Price velocity acceleration compares current price velocity to the prior companion observation.
- The module never conflates flow speed with price speed.

## Router integration

The router imports `evaluate` from this module, calls it after reclaim/radar/geometry computation, and emits the result in the backward-compatible `speed_companion` field.

## Run tests

`python -m unittest -v test_delta_tempo_speed_companion.py`
'@
Set-Content -Path (Join-Path $root 'DELTA_TEMPO_SPEED_COMPANION.md') -Value $doc -Encoding UTF8

$source = Get-Content $router -Raw
$importAnchor = 'from knn_engine import KNNEngine'
$importReplacement = "from knn_engine import KNNEngine`r`nfrom delta_tempo_speed_companion import evaluate as evaluate_speed_companion"
if ($source.IndexOf($importAnchor) -lt 0) { throw 'Import anchor not found. Router restored.' }
if ($source.Contains('evaluate_speed_companion')) { throw 'Router already appears integrated. Router restored.' }
$source = $source.Replace($importAnchor, $importReplacement)

$callAnchor = '    geometry = _local_geometry(side, ohlcv_arrays)'
$callReplacement = @'
    geometry = _local_geometry(side, ohlcv_arrays)

    speed_companion = evaluate_speed_companion(
        pair=pair,
        side=side,
        ready=ready,
        flow_speed=speed,
        flow_acceleration_ratio=ratio,
        reclaim_confirmed=reclaim_conf,
        structure=structure,
        market_state=market_state,
        ohlcv_arrays=ohlcv_arrays,
    )
'@
if ($source.IndexOf($callAnchor) -lt 0) { Copy-Item $backup $router -Force; throw 'Companion call anchor not found. Router restored.' }
$source = $source.Replace($callAnchor, $callReplacement.TrimEnd())

$returnAnchor = '        "risk_source":         "LOCAL_15M_ATR_BUFFERED",'
$returnReplacement = "        `"risk_source`":         `"LOCAL_15M_ATR_BUFFERED`",`r`n        `"speed_companion`":     speed_companion,"
if ($source.IndexOf($returnAnchor) -lt 0) { Copy-Item $backup $router -Force; throw 'Return payload anchor not found. Router restored.' }
$source = $source.Replace($returnAnchor, $returnReplacement)
Set-Content -Path $router -Value $source -Encoding UTF8

try {
    python -m unittest -v test_delta_tempo_speed_companion.py
    if ($LASTEXITCODE -ne 0) { throw "Unit tests failed with exit code $LASTEXITCODE" }
    python -m py_compile delta_tempo_prop_router.py delta_tempo_speed_companion.py
    if ($LASTEXITCODE -ne 0) { throw "Compile check failed with exit code $LASTEXITCODE" }
    Write-Host "SUCCESS: Speed Companion installed. Router backup: $backup" -ForegroundColor Green
} catch {
    Copy-Item $backup $router -Force
    throw "Installation failed and router was restored from $backup. $($_.Exception.Message)"
}
