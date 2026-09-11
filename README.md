# Gimba

Active JHL Gimba Market Edge system.

Includes the scanner, Market State Engine, pressure/volume-flow logic,
specialist bots, KNN learning, outcome evaluator, and live HTML wall.

---

## Specialist Roster

### Active Execution Specialists
These specialists generate execution-eligible claims and contribute to the
OFFENSE/PERMISSION panel.  Range and RTS are unchanged.

| Module | Label | Identity |
|---|---|---|
| `gimba_range.py` | RNG | Rotational / mean-reversion. Hunts edge-to-center fades. |
| `rts_liquidation.py` | RTS | Liquidity sweep and trap specialist. |

### Training-Only Specialist
This specialist is **observation and training only**. It produces DRIVE_LONG /
DRIVE_SHORT claims and is logged to `training_logs/gimba_drive.jsonl`, but it
**does not enable execution, order placement, live risk changes, or any external
execution pathway.**

| Module | Label | Identity |
|---|---|---|
| `gimba_drive.py` | DRIVE | Event-driven continuation. Requires all five conditions: HTF alignment, valid pullback location, pullback compression, local structure break in the aligned direction, and break holds with speed/efficiency expansion. |

**Drive claim schema** (each JSONL record contains):
- `setup_type`: `DRIVE_LONG`, `DRIVE_SHORT`, or `NO_DRIVE_CONDITION`
- `entry`, `sl`, `tp`: proposed levels (or `null` if no claim)
- `sl` is placed below/above the local structure break level with an ATR buffer (hard invalidation)
- `tp` is set at the prior D1 swing extreme
- `traction_expectation`: configurable time/traction window label
- `invalidation_note`: human-readable hard invalidation description
- `thesis_decay_note`: human-readable thesis decay description
- `drive_conditions`: dict of which of the five conditions were met/failed
- `training_only: true` — always present; confirms no execution pathway

**Drive exit framework (diagnostic/evaluation use only):**
- Hard invalidation: close back through the local structure break / pullback zone
- Thesis decay: speed_score → 0, RVOL drops below 1.0, or price returns inside trigger range without follow-through within the traction window
- Time horizon: evaluated by `outcome_evaluator.py` over 16 completed 15m bars

**Limitations:**
- Structure break detection uses close-based pivot logic only; wick-based breaks are not detected
- Speed/efficiency expansion uses RVOL, RSI momentum, and tempo module as proxies
- Traction expectation is a fixed configurable default, not adaptive per-pair

### Training-Only Micro-Regime Observer
Pulse is a **non-executing observer**. It classifies each pair into exactly one
of `PULSE_DEAD`, `PULSE_CHOPPY`, `PULSE_IMPULSIVE`, or `PULSE_EXHAUSTED` and
logs to `training_logs/gimba_pulse.jsonl`. Pulse is visible in the scanner and
HTML wall with a **TRAINING ONLY** badge, but it **must not**:
- generate trade claims or execution eligibility
- place orders or size positions
- change live risk
- receive KNN conviction adjustments in v1
- count toward OFFENSE / PERMISSION

Pulse records include an explainable `pulse_score`, component metrics
(realized range, range expansion, directional efficiency, candle alternation,
directional run length, wick/body rejection noise, breakout retention/failure),
human-readable rationale, and forward observer outcomes for 15m / 30m / 60m /
16-bar horizons.

### Shared Market-Noise Analytics

Scanner observations also carry a shared read-only `market_noise` object derived
from completed 15m OHLCV bars only. It is attached for `gimba_volatile`,
`gimba_range`, `rts_liquidation`, `gimba_trend`, `gimba_drive`, `gimba_pulse`,
`shadow_volatile`, and `shadow_trend_recovery`.

Fields:
- `wick_body_noise` — mean `(upper_wick + lower_wick) / real_body`, capped per bar
- `alternation_ratio` — fraction of body-direction flips across non-doji candles
- `directional_efficiency` — net close travel divided by total close-to-close path
- `directional_run_length` — longest consecutive body-direction run
- `noise_score` — normalized 0.00–1.00 blend of wick noise, alternation,
  inefficiency, and run fragmentation
- `regime` — `CLEAN` when score `< 0.34`, `MIXED` when `< 0.67`, else `CHOPPY`

This layer is analytical evidence only. It does **not** change OFFENSE,
PERMISSION, routing, orders, sizing, risk, conviction, KNN inputs, or outcome
labels.

**OHLCV limitations:**
- Public completed OHLCV bars only; no order-book or proprietary liquidity data
- Breakout hold/fail is approximated from candle closes and wick behavior
- Intrabar event ordering cannot be recovered from OHLC alone

### Diagnostic Context Providers
These modules are evaluated and logged every cycle but **must not generate
execution eligibility**. Their outputs appear in the Specialist Reads panel
with a DIAGNOSTIC badge and are excluded from the OFFENSE/PERMISSION
calculation.

| Module | Label | Role |
|---|---|---|
| `gimba_volatile.py` | VOL·CTX | Volatility/expansion context: supertrend direction, RVOL, maturity, tempo state |
| `gimba_trend.py` | TRD·CTX | HTF continuation context: D1/H4 trend alignment, pullback depth, speed scores |

---

## Canonical Specialist Contract (`specialist_contracts.py`)

`specialist_contracts.py` is a **contract-only** module.  It defines the
canonical data shapes, enums, ownership policy, and named score constants for
the full specialist architecture.  It **does not** place orders, touch live
risk, modify KNN, or provide any execution pathway.  It is not imported by
`scanner.py`.

### Specialist Family Matrix

| Family constant (`SpecialistFamily`) | Module | Label | Role | Execution eligible? |
|---|---|---|---|---|
| `RTS_LIQUIDITY` | `rts_liquidation.py` | RTS | PROPOSAL | ✅ Yes |
| `GIMBA_VOLATILE` | `gimba_volatile.py` | VOL·CTX | SHADOW (recovered) | ❌ Shadow-logged only |
| `GIMBA_RANGE` | `gimba_range.py` | RNG | PROPOSAL | ✅ Yes (yields to expansion) |
| `TREND_RECOVERY` | `gimba_trend.py` | TRD·CTX | SHADOW (recovered) | ❌ Shadow-logged only |
| `STRUCTURE` | `structure_bias.py` | ORC | ORACLE\_STRUCTURE | ✅ Final router only |
| `GIMBA_PULSE` | `gimba_pulse.py` | PULSE | TRAINING\_ONLY | ❌ Never |

### Ownership Precedence (highest → lowest)

1. **STRUCTURE** — final router, always overrides
2. **RTS** — confirmed trap vetoes every non-RTS directional claim regardless of direction; RTS's own claim is exempt
3. **VOLATILE** — owns active expansion until mature or invalidated
4. **RANGE** — rotation-only; yields when expansion is accepted
5. **TREND\_RECOVERY** — reclaim/pullback-continuation only; currently shadow-mode
6. **NONE**

### Veto Rules (deterministic, in precedence order)

| # | Condition | Veto reason |
|---|---|---|
| 1 | Challenger family is SHADOW or TRAINING\_ONLY | `SHADOW_MODE` |
| 2 | RTS trap confirmed (any non-RTS directional claim; RTS's own claim exempt) | `RTS_TRAP_CONFIRMED` |
| 3 | Volatile expansion active, not mature, not invalidated | `EXPANSION_ACTIVE_VOLATILE` |
| 4 | Range challenger while expansion active, not mature, not invalidated | `RANGE_YIELDING_EXPANSION` |
| 5 | Structure router blocks (applied externally) | `STRUCTURE_ROUTER_BLOCK` |

### Shadow-Mode (recovered specialists)

`GIMBA_VOLATILE` and `TREND_RECOVERY` are currently in **shadow mode**:
claims are produced, annotated `shadow_mode=True`, logged with
`ClaimState.SHADOW_LOGGED`, and **never forwarded to the execution router**.
Shadow mode is lifted by explicit system-owner promotion — no code change is
required in this module.

- `TREND_RECOVERY` is reclaim/pullback-continuation only.  Emitted names carry
  the `SHADOW_TRD_` namespace prefix; the semantic portion must start with
  `RECLAIM_`, `PULLBACK_CONTINUATION_`, or `PULLBACK_HOLD_`.
  Expansion or breakout setups are contract violations.

### Score Band Constants (`ScoreBand`)

Named anchors for the normalized confidence score (0.0 – 1.0).
**No existing runtime thresholds are changed.**

| Constant | Value | Meaning |
|---|---|---|
| `STRONG_CONVICTION` | 0.80 | High-confidence claim |
| `MODERATE_CONVICTION` | 0.60 | Moderate-confidence claim |
| `WEAK_SIGNAL` | 0.40 | Weak / borderline signal |
| `NO_SIGNAL` | 0.00 | Below meaningful threshold |

---

## Shadow Candidate Specialists

Two recovered designs are implemented as **shadow-only candidate specialists**.
Neither changes live execution, OFFENSE/PERMISSION, Range/RTS routing, order
placement, sizing, risk, or KNN conviction.

### Shadow Volatile (`shadow_gimba_volatile.py`)

| Property | Value |
|---|---|
| Log bot name | `shadow_volatile` |
| JSONL file | `training_logs/shadow_volatile.jsonl` |
| Scanner display | `SHD-VOL` with `[SHADOW]` tag |
| Mandate | Expansion/continuation versus maturity/exhaustion |
| Inputs | 15m OHLCV only (ATR, RSI, RVOL, supertrend, maturity, speed) |

Setup families: `SHADOW_VOL_EXPANSION_LONG/SHORT`, `SHADOW_VOL_CONTINUATION_LONG/SHORT`,
`SHADOW_VOL_MATURITY_LONG/SHORT`, `SHADOW_VOL_EXHAUSTION`, `SHADOW_VOL_NO_SIGNAL`.

**All records always have**: `shadow_mode=True`, `diagnostic_only=True`,
`training_only=True`, `action_state='observe'`, `entry/sl/tp=None`.

### Shadow Trend Recovery (`shadow_trend_recovery.py`)

| Property | Value |
|---|---|
| Log bot name | `shadow_trend_recovery` |
| JSONL file | `training_logs/shadow_trend_recovery.jsonl` |
| Scanner display | `SHD-TRD` with `[SHADOW]` tag |
| Mandate | Continuation after pullback, liquidation, or reclaim |
| Inputs | 15m OHLCV + structure context (HTF trend) |

Valid setup-family naming convention (contract restriction):
All non-`NO_SIGNAL` names carry the `SHADOW_TRD_` namespace prefix followed by
a semantic portion that must start with exactly one of `RECLAIM_`,
`PULLBACK_CONTINUATION_`, or `PULLBACK_HOLD_`.  The validator
`_is_valid_trend_recovery_family()` enforces this rule at output construction
time and raises `AssertionError` on any violation.

Generic trend-direction families (e.g. `SHADOW_TRD_BULLISH`) that lack a
recognised semantic prefix are **contract violations** and are never emitted.

Setup families: `SHADOW_TRD_RECLAIM_LONG/SHORT`, `SHADOW_TRD_PULLBACK_CONTINUATION_LONG/SHORT`,
`SHADOW_TRD_PULLBACK_HOLD_LONG/SHORT`, `SHADOW_TRD_NO_SIGNAL`.

---

## Observer/Candidate Outcome Evaluation

`outcome_evaluator.py` resolves shadow candidate records at four forward horizons:

| Horizon | Bars | Duration |
|---|---|---|
| `15m` | 1 bar | 15 minutes |
| `30m` | 2 bars | 30 minutes |
| `60m` | 4 bars | 1 hour |
| `16bar` | 16 bars | 4 hours |

Fields per horizon: `net_directional_return`, `realized_range`,
`directional_efficiency`, `mfe`, `mae`, `hold_fail` (HELD/FAILED when an
invalidation level is present).

**Labels are analytical only** — they are never trade win/loss or KNN inputs.

---

## Shadow Scoreboard (`shadow_scoreboard.py`)

Deterministic summary of shadow Volatile, shadow Trend Recovery, and Drive
records.  **No winner is declared automatically.**

```
python shadow_scoreboard.py           # print human-readable summary
python shadow_scoreboard.py --json    # JSON output
python shadow_scoreboard.py --bot shadow_volatile  # one bot only
```

Per-bot statistics:
- Sample count and resolved count
- Coverage (fraction resolved)
- Directional hit rate
- Mean aligned return (16-bar horizon)
- Mean and median MFE / MAE
- Setup family counts
- Per-noise-regime (`CLEAN` / `MIXED` / `CHOPPY`, with `UNKNOWN` fallback for
  legacy rows) breakdowns of the same statistics

---

## Promotion Criteria (Shadow → Active)

Shadow candidates are promoted by **explicit system-owner decision only**.
The following analytical criteria are used to inform (not automate) that
decision:

| Criterion | Minimum threshold (indicative) |
|---|---|
| Sample count | ≥ 200 resolved records per family |
| Directional hit rate | > 52% across all setups, > 55% for primary setup family |
| Mean aligned return (16-bar) | Positive; > 0.002 on non-trivial sample |
| Mean MFE | Consistent across market regimes |
| Coverage | ≥ 80% (enough records are being resolved) |
| Mandate adherence | No generic trend-direction claims emitted |
| Shadow flag integrity | All records have `shadow_mode=True`, `entry/sl/tp=None` |

A candidate that meets all criteria **may** be promoted by system-owner
review.  Meeting the criteria is necessary but not sufficient — the owner
retains final authority.  The scoreboard report is the evidence base; it
does not produce a verdict.
