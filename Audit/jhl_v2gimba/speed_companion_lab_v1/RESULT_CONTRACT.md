# Speed Phase Result Contract

## Entry point

```python
from speed_phase import analyze_completed_candles

result = analyze_completed_candles(candles)
```

`candles` is an ordered list of completed OHLCV candle dictionaries. The
function returns one dictionary with exactly these nine keys:

```text
direction
phase
decay_reason
impulse_age_bars
impulse_size_atr
pullback_bars
pullback_depth_fraction
pullback_volume_vs_impulse
reclaim_confirmed
```

## Fields

| Field | Type | Meaning |
|---|---|---|
| `direction` | `"LONG"` or `"SHORT"` | Direction of the qualifying impulse |
| `phase` | See phase values below | Current state of the impulse |
| `decay_reason` | string or `null` | Reason only when `phase` is `"DECAY"` |
| `impulse_age_bars` | integer | Completed bars since the qualifying impulse |
| `impulse_size_atr` | number or `null` | Impulse size measured in ATR units, when available |
| `pullback_bars` | integer or `null` | Count of recognized pullback bars, when evaluated |
| `pullback_depth_fraction` | number or `null` | Pullback depth as a fraction of the impulse move, when evaluated |
| `pullback_volume_vs_impulse` | number or `null` | Average pullback volume divided by impulse volume, when evaluated |
| `reclaim_confirmed` | boolean | `true` only for confirmed reacceleration |

## Phase values

| Phase | Meaning | `decay_reason` | `reclaim_confirmed` |
|---|---|---|---|
| `WATCH` | Valid impulse remains under observation | `null` | `false` |
| `CONTROLLED_PULLBACK` | Valid pullback remains within depth and volume limits | `null` | `false` |
| `REACCELERATION` | Valid reclaim confirms renewed momentum | `null` | `true` |
| `DECAY` | The impulse is no longer valid | One of the decay reasons below | `false` |

## Decay reasons

| Value | Meaning |
|---|---|
| `pullback_depth_breached` | Pullback depth exceeded the permitted maximum |
| `pullback_volume_excessive` | Pullback participation exceeded the permitted maximum |
| `structure_invalidated` | Price closed through the impulse structural boundary |
| `watch_window_expired` | The impulse exceeded the observation window |

## Boundary behavior

- Pullback depth at exactly `0.500000` remains valid; `0.500001` decays.
- Pullback volume ratio at exactly `0.800000` remains valid; `0.800001` decays.
- A long close exactly at the impulse low remains valid.
- A short close exactly at the impulse high remains valid.
- Impulse age `12` remains valid; expiry begins after the watch window.
- Fields with unavailable or inapplicable measurements are returned as `null`;
  they are never omitted from the result dictionary.

## Consumer guidance

- Branch on `phase` first.
- Read `decay_reason` only when `phase == "DECAY"`.
- Treat nullable numeric fields as unavailable measurements, not as zero.
- Use `reclaim_confirmed` only as confirmation metadata; it is `true` only in
  `REACCELERATION`.

## Verification

`test_result_contract.py` validates this exact key set, valid enums, nullable
field types, and the phase/reason/reclaim consistency rules across every
fixture.
