# JHL Market Edge — Current State

**Checkpoint:** 2026-08-07

## Mission

JHL is not being rebuilt as a prettier setup scanner. It is being tightened into **market AI**:

> Identify how price is behaving, identify the regime and specialist opportunity, then participate only when the observed movement has a real, payable path.

The operating aim is to learn which trend, pullback, range, chop, thin, explosive, and liquidation conditions actually pay versus leak.

---

## Architecture That Stays

```text
Kraken market data
→ specialist bots: Volatile / Range / RTS / Trend
→ shared structure + tempo + pressure context
→ structure amplifier
→ specialist-specific KNN memory
→ Shadow / veto / execution protection
→ APRIL roster + Live Shell
```

### Specialist roles

| Specialist | Job |
|---|---|
| Gimba Volatile | Expansion, impulse, cascade recovery, no-chase behavior |
| Gimba Range | Range rotation and failed breaks; yields during real expansion |
| RTS Liquidation | Sweep/reclaim, failed acceptance, trap protection, veto authority |
| Gimba Trend | Higher-timeframe continuation and pullback resumption |

### Existing indicator roles

| Tool | Official role |
|---|---|
| EMA 25 / 50 / 100 / 200 | Official ribbon: trend order, compression, pullback/loss-of-control reference |
| BB500 2σ / 3σ | Broad location and extension vocabulary; not an autonomous reversal trigger |
| ATR / volatility state | Movement/noise expectations and expansion classification |
| Relative volume | Participation quality |
| Impulse / velocity / acceleration / tempo | Movement, follow-through, chop, exhaustion behavior |
| Local highs/lows, sweeps, reclaims | Trigger, acceptance/rejection, invalidation, trap geometry |
| Spread/freshness/execution checks | Whether a valid idea is executable |

No indicator is being added or removed merely for novelty. The requirement is effectiveness: one clear job per tool, no duplicated voting, and no invisible/missing data contributing to a score.

---

## Offense Doctrine

Defense is already strong. Offense is now explicitly defined using existing tools; no new indicator is required.

```text
OFFENSE = the market has shown it can move,
hold the movement, and has room to continue.
```

A tactic is not permitted merely because it has a plan or a high score. It needs four proofs:

1. **Displacement** — directional impulse/tempo/ATR behavior, not dead or choppy movement.
2. **Participation** — adequate relative volume and, when available, pressure confirmation.
3. **Acceptance** — price holds/reclaims the gained ground rather than instantly returning through it.
4. **Path** — a realistic destination exists after spread/risk, before invalidation.

### Offense states

```text
NONE      No demonstrated directional behavior.
FORMING   Possible move; observation only.
PROVEN    Displacement + participation + acceptance + payable path.
DECAYING  A move existed but is losing acceptance/force.
```

Defense explains why participation is unsafe. Offense must independently prove why participation is justified.

---

## Delta / CVD Status

`gimba_volume_flow.py` is a real calculation module, not an imagined indicator.

It computes from trade executions:

```text
buy volume
sell volume
delta = buy volume − sell volume
CVD = prior CVD + current delta
CVD slope
normalized volume / delta states
```

### Previous problem

The prior scanner’s `fetch_bar_data()` was a placeholder returning:

```python
[], {"open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0.0}
```

That caused all pressure values to be fake zeros:

```text
volume = 0
volume_state = normal
delta = 0
delta_state = balanced
cvd = 0
cvd_slope = 0
```

Those values meant **unavailable data**, not balanced order flow.

### Correct policy

```text
No pressure data ≠ balanced pressure.
No pressure data ≠ normal volume.
No pressure data gets no vote.
```

The corrected `gimba_volume_flow.py` returns:

```json
{
  "ready": false,
  "reason": "no_trade_executions",
  "volume_state": "unknown",
  "delta_state": "unknown",
  "delta": null,
  "cvd": null
}
```

when it cannot calculate pressure honestly.

---

## KNN Status

Each specialist retains its own KNN and its own log:

```text
gimba_volatile.jsonl
gimba_range.jsonl
rts_liquidation.jsonl
gimba_trend.jsonl
```

This separation is correct: each bot learns its own terrain.

### KNN feature context

The current KNN direction is regime-aware rather than setup-only:

```text
Local specialist indicators
+ D1/H4 trend
+ zone / eq_pct
+ market condition
+ Shadow regime when present
+ volume-flow readiness
+ normalized volume
+ side-aligned delta/CVD pressure
```

### Critical KNN correction

Old labels were circular:

```text
high-conviction WATCH → positive
idle / low conviction → negative
```

That taught KNN the system’s prior opinion, not whether the market actually paid.

The corrected KNN accepts only explicit evaluated outcomes:

```json
"outcome": {
  "status": "resolved",
  "label": 1,
  "reason": "target_before_invalidation"
}
```

or:

```json
"outcome": {
  "status": "resolved",
  "label": -1,
  "reason": "invalidation_before_target"
}
```

Until at least 30 valid outcome-labeled rows exist for a bot, its KNN should safely return:

```text
KNN(0/30) +0.000
```

That is intentional and safer than self-reinforcing historical conviction.

---

## Current File Replacements

### 1. `gimba_volume_flow.py`

Replacement created.

It:

- Requires actual classified trade executions.
- Requires nonzero OHLCV volume and a valid volume baseline.
- Requires valid prior CVD state.
- Emits explicit `ready`, `reason`, and `source` fields.
- Normalizes CVD slope by volume baseline.
- Does not claim balanced/normal pressure when data is missing.

### 2. `knn_engine.py`

Replacement created.

It:

- Keeps one KNN per bot/log.
- Supports canonical `structure` blocks and legacy locations for structure values.
- Adds a pressure-ready feature.
- Aligns delta/CVD with the proposed side.
- Deduplicates training events by `event_key`.
- Uses outcome labels only.
- Does not let unavailable pressure masquerade as zero/balanced pressure.

### 3. `scanner.py`

Replacement created, then repaired with a raw-evaluator compatibility helper.

It:

- Fetches Kraken public completed OHLC bars and recent public trades.
- Uses the penultimate OHLC row because the final row is incomplete.
- Rejects trade data if the response reaches the 1000-trade cap rather than computing partial delta/CVD.
- Builds volume flow before central KNN adjustment.
- Applies KNN after structure and pressure context are attached.
- Writes canonical schema-version-2 training records.
- Writes one observation per bot per completed 15-minute pressure candle, not every 5-minute refresh.
- Prevents duplicate in-process training events.

### Scanner raw-evaluator repair

The installed modules did not expose `evaluate_pair`, producing:

```text
module 'gimba_volatile' has no attribute 'evaluate_pair'
```

The scanner must use `_evaluate_raw()` and try these raw evaluator names:

```python
("evaluate_pair", "evaluatepair", "evaluate")
```

It must **not** fall back to `evaluate_with_knn()`, because that would apply internal KNN before the scanner attaches shared structure and `volume_flow` context.

---

## Canonical Training Record

New records should follow this shape:

```json
{
  "schema_version": 2,
  "event_key": "SOL/USD|gimba_volatile|15m|completed-bar-start",
  "ts": "...",
  "pair": "SOL/USD",
  "bot": "gimba_volatile",
  "setup_type": "...",
  "bias": "LONG",
  "conviction": 0.0,
  "action": "watch",
  "indicators": {},
  "structure": {},
  "diagnostics": {},
  "volume_flow": {
    "ready": true
  },
  "outcome": {
    "status": "pending",
    "label": null
  }
}
```

### Old records

Older JSONL records may be retained for audit, but should not be treated as full pressure-aware KNN history when their fields are absent or their labels are circular.

---

## Immediate Deployment Order

1. Back up the existing versions of `scanner.py`, `knn_engine.py`, and `gimba_volume_flow.py`.
2. Replace `gimba_volume_flow.py`.
3. Replace `knn_engine.py`.
4. Replace `scanner.py` and include the `_evaluate_raw()` compatibility helper.
5. Run the scanner.
6. Confirm the terminal shows either:

```text
PRESSURE READY
```

or an honest unavailable reason such as:

```text
PRESSURE OFF:no_trade_executions
PRESSURE OFF:trade_response_at_limit
PRESSURE OFF:kraken_fetch_error:...
```

7. Inspect one new JSONL line per bot and confirm:

```text
schema_version = 2
structure is populated
volume_flow is present
volume_flow.ready is truthful
event_key exists
outcome.status = pending
```

---

## Remaining Required Component

One component remains before KNN can learn from actual market behavior:

> **Outcome evaluator / post-entry observer**

It must evaluate a pending event after a defined horizon or after stop/target/invalidation behavior and write an explicit outcome label.

Do not invent labels from conviction, WATCH state, or manual preference.

The next required source artifact is the current trade-management, position-monitoring, or audit/outcome file—if one exists. If none exists, create the smallest dedicated evaluator that updates resolved outcomes without changing scanner or specialist logic.

---

## What Is Not Being Changed

- No indicator is being removed merely because it is a favorite or familiar tool.
- No indicator is being added for novelty.
- EMA 25/50/100/200 remains the official ribbon.
- BB500 2σ/3σ remains location/extension context, not an autonomous reversal command.
- The four specialist identities remain intact.
- The project remains a boot/tightening effort, not a rebuild.

---

## Pinned Rules

```text
No imagined weapon gets a vote.
No duplicated weapon gets multiple votes.
No missing pressure becomes neutral pressure.
No setup becomes a position without demonstrated offense.
No KNN learns from its own old conviction.
```
