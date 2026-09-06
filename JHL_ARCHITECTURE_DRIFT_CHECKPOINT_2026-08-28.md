# JHL Architecture Drift Checkpoint — PRISM / Delta-Tempo / Speed / Oracle Feed

**Checkpoint date:** 2026-08-28  
**Status:** Architecture locked for integration planning. No live integration, alerting, execution, or publisher change authorized by this document.  
**Primary objective:** Preserve the existing live phone feed while defining the correct promotion path for PRISM market context, Delta/Tempo niche evidence, and Speed Companion timing.

---

## 1. Core hierarchy

```text
PRISM
  = Price-Regime Intelligence & Structure Mainframe
  = shared market-context base
  = maps state, construction, fair price, band travel, risk, routes, and uncertainty
  = does not create trade authority

Delta/Tempo
  = independent niche / technique
  = detects and describes strong movement, participation, delta/CVD alignment,
    velocity, speed change, promotion, persistence, decay, and directional episodes
  = consumes PRISM context; does not own or redefine PRISM

Speed Companion
  = Delta/Tempo timing and lifecycle enhancement
  = evaluates completed M5 bars
  = supports first-candle awareness, second-candle confirmation,
    decay, invalidation, expiry, and reacceleration
  = separate computation; not a separate strategy or competing feed authority

Oracle feed / GitHub phone feed
  = existing presentation and delivery surface
  = displays validated source-owned facts
  = manual review only
  = does not calculate source logic, blend scores, authorize trades, or execute
```

---

## 2. Non-negotiable source ownership

| Source | Owns | Must not do |
|---|---|---|
| PRISM | Market context, construction, fair-price relationship, band-travel state, route hypotheses, risk map, data health | Issue an order, send alerts, become an entry signal, redefine technique rules |
| Delta/Tempo | Directional episode, Delta/CVD/participation evidence, velocity/tempo state, promotion/decay, source-owned reasons and any separately defined shadow score | Redefine PRISM context, silently bypass risk, create composite authority |
| Speed Companion | Completed M5 lifecycle and timing state for a Delta/Tempo episode | Become an independent trade system, replace Delta/Tempo, own PRISM context |
| Oracle context/feed | Existing fixed-universe context, ranking, feed packaging, and current phone-compatible JSON | Invent PRISM or Delta/Tempo facts |
| PRISM Adapter | Schema validation, source-health handling, source-preserving display payload | Recompute sources, blend scores, infer missing values, grant authority |
| GitHub phone UI | Display current validated payload | Make decisions, infer confirmations, store secrets, send alerts |
| Pushover | Future backup notification consumer only | Become primary signal source or infer a new trading event |

---

## 3. Existing live components

### 3.1 TERRYPC runtime

The currently active local runtime processes are:

```text
python .\oracle_prop_context_scanner.py
python .\oracle_micro_trigger_scanner_v1.py
```

Observed logical process chains:

```text
oracle_prop_context_scanner.py
  WindowsApps python launcher
    -> PythonCore child runtime

oracle_micro_trigger_scanner_v1.py
  WindowsApps python launcher
    -> PythonCore child runtime
```

The paper outcome recorder was not observed in the active process list at the last check:

```text
py .\oracle_paper_outcome_recorder_v1.py
```

No action is authorized by this document to start, stop, duplicate, or modify these processes.

### 3.2 Oracle context

```text
File: oracle_prop_context_scanner.py
Output: oracle_prop_context_v1.json
Cadence: 300 seconds
Universe: APRIL_12_FIXED, exactly 49 pairs
Data basis: completed Kraken 15-minute OHLC bars
Authority: read-only context only
```

The context scanner classifies source-owned fields including:

```text
directional_context
market_type
structure
tempo
flow
shield
location
review_state
reason_codes
context_score
```

Its `ARMED` state is an Oracle-context condition. It is not equivalent to an M5 first-candle confirmation and must not be relabeled as such.

### 3.3 Oracle feed adapter

```text
File: oracle_prop_feed_adapter_v1.py
Input: oracle_prop_context_v1.json
Output: oracle_prop_feed_v1.json
```

Current source-owned feed tiers:

```text
BEST_NOW
WATCH_NEEDS_TRIGGER
SHIELDED
REJECTED_CONTEXT
```

The adapter also creates a limited micro watchlist.

This is the current primary phone-feed payload path. It must remain operational while any replacement or adapter work is validated separately.

### 3.4 Micro trigger scanner

```text
File: oracle_micro_trigger_scanner_v1.py
Input: oracle_prop_feed_v1.json
Role: read-only local micro-speed/momentum observer
```

Explicitly out of scope for this component:

```text
No GitHub publishing
No alerts
No notifications
No order routing
No feed mutation
No trade authority
```

It must not become the integration point for PRISM, hosted-feed publication, Pushover, or execution logic.

### 3.5 Existing hosted feed

```text
Repository: Jadakai78/oracle-feed-mobile
Hosted payload: oracle_prop_feed_v1.json
Hosted page: index.html
Refresh behavior: page fetches oracle_prop_feed_v1.json approximately every 60 seconds
```

The GitHub-hosted feed is the current phone-facing delivery surface.

The slow-PC clone is:

```text
C:\Users\jason\OneDrive\Desktop\jhl_v2\oracle-feed-mobile
```

At the last confirmed check, it was clean and synchronized:

```text
Branch: main
HEAD: f131ed2
State: main...origin/main
```

The recurring GitHub feed-update commits continue to originate from the active TERRYPC publishing path.

### 3.6 Slow-PC M5 task

```text
Task: JHL_Kraken_Spot_M5_Review_Refresh_SlowPC
State: Disabled
Lock file: absent at last check
```

The slow-PC task must remain disabled unless separately and explicitly reauthorized. TERRYPC remains the active M5/runtime source.

---

## 4. PRISM mainframe contract

PRISM is the shared **Price-Regime Intelligence & Structure Mainframe**.

Its purpose is to map market state, not create an order:

```text
Market activity
  -> PRISM context and construction map
  -> ranked conditional route hypotheses
  -> independent technique adapter
  -> manual human review
```

PRISM layers:

```text
Context
  direction, speed, regime, location, distance, activity, volatility, data health

Construction
  impulse, flag, compression, breakout acceptance, stair-step,
  grind, exhaustion, failure, mixed/unclassified

Fair Price
  accepted, rejected, reclaiming, magnet, ignored, balance

Band Travel
  365-period distribution position, sigma zone, width, middle slope,
  arrival mode, conditional route state

Route
  conditional path hypotheses, prerequisites, invalidation, expiry

Research / Outcome
  timestamped snapshots, forward labels, MFE/MAE, time-to-resolution
```

PRISM is context and risk map. It does not add score points to a technique and does not silently turn context into entry permission.

---

## 5. Delta/Tempo niche contract

Delta/Tempo is an independent technique adapter operating inside PRISM context.

It owns:

```text
Directional episode state
Delta / CVD / participation alignment
Velocity and rate-of-change behavior
Tempo / acceleration / deceleration
Promotion, persistence, decay, invalidation
Source-owned reasons
Any separately contracted Delta/Tempo shadow score
```

PRISM maps the battlefield.

Delta/Tempo determines whether its niche sees a meaningful event in that battlefield.

No adapter may:

```text
Combine PRISM and Delta/Tempo into a new total score
Convert PRISM context into synthetic Delta/Tempo confluence
Change Delta/Tempo thresholds or episode meaning
Carry forward old Delta/Tempo values when the source is stale or unavailable
```

---

## 6. Speed Companion contract

Speed Companion is a **Delta/Tempo timing enhancement**, not a separate specialist or feed authority.

It must operate on completed M5 bars and expose source-owned lifecycle facts such as:

```text
DETECTED
PERSISTING
ARMED_1_OF_2
CONFIRMED_2_OF_2
DECAY
INVALIDATED
EXPIRED
REACCELERATION
UNAVAILABLE
```

The intended interpretation is:

```text
Delta/Tempo event + PRISM map
  -> Speed Companion identifies a completed M5 first qualifying candle
  -> phone feed displays early awareness
  -> second completed candle confirms or invalidates
```

The two-candle rule belongs to the Delta/Tempo technique lifecycle. It is not a PRISM route rule and it must not redefine Oracle-context `review_state: ARMED`.

---

## 7. Future unified phone card

The phone feed should eventually display one source-preserving packet per pair:

```text
Pair: EGLD/USD

PRISM
  Context: trend / regime / location / construction
  Fair price: relationship and acceptance state
  Band travel: 365-period map and conditional route
  Risk: available distance, opposing structure, invalidation condition
  Data health: valid / stale / partial / unavailable

Delta/Tempo
  Direction: LONG / SHORT / NONE
  Episode: detected / persisting / armed / decay / invalidated
  Delta/CVD / participation: source-owned evidence
  Reasons: source-owned

Speed Companion
  M5 status: armed 1 of 2 / confirmed 2 of 2 / invalidated / unavailable
  First completed candle close
  Second-candle due/close
  Lifecycle reason

Display
  Attention: observe / review map / constrained / unavailable
  Manual review only
  No trade authority
```

The display must not manufacture:

```text
A composite score
A combined pass/fail
An order instruction
A stop-loss instruction
A target instruction
An alerting instruction
```

---

## 8. Alerting policy

The primary field interface is the hosted phone feed.

Pushover is a secondary backup only.

Future alert behavior, if separately approved and implemented, is:

```text
New source-owned Delta/Tempo + Speed Companion ARMED_1_OF_2 episode
  -> one normal-priority Pushover heads-up
  -> episode-key dedupe prevents repeat alerts

Same episode on later refreshes
  -> no duplicate Pushover

CONFIRMED_2_OF_2
  -> phone feed promotes same episode
  -> no second Pushover by default

INVALIDATED / EXPIRED / UNAVAILABLE
  -> phone feed updates state
  -> no default Pushover
```

The alert sender must be a separate notification consumer with its own state/dedupe ledger. It must not be the PRISM Adapter, PRISM mainframe, hosted UI, or micro-trigger scanner.

No new Pushover behavior is authorized by this document.

---

## 9. Required adapter rules

Any future PRISM Adapter or replacement feed adapter must enforce:

1. Sources retain ownership of their fields, thresholds, ordering, and scores.
2. Context is descriptive, constraining, tempering, vetoing, or unavailable; it is not score-additive.
3. Delta/Tempo and any other source scores remain independent.
4. Missing, stale, invalid, malformed, untrusted, or pair-mismatched data is visibly unavailable.
5. Prior values must never be carried forward as current when a source fails.
6. Source timestamps, pair identity, schema identity, freshness, and safety flags must validate before display.
7. A malformed candidate output fails closed: do not replace a prior valid published payload.
8. Risk, uncertainty, opposing structure, available distance, and data coverage are visible.
9. Every payload remains manual-review-only with no trade, entry, alert, queue, or execution authority.

---

## 10. Current integration sequence

No code change is authorized by this checkpoint alone.

The next approved planning sequence is:

```text
1. Contract inventory
   - identify the actual fresh PRISM source artifact and schema
   - identify the actual Delta/Tempo v2 source artifact and schema
   - identify the actual Speed Companion state artifact and schema
   - identify source timestamps, pair keys, freshness rules, and safety flags

2. Adapter decision
   - compare those contracts against PRISM Adapter Contract v1
   - decide whether existing adapter lab can be promoted unchanged,
     requires a versioned v2 contract, or remains lab-only

3. Fixture validation
   - all sources available
   - PRISM unavailable
   - Delta/Tempo unavailable
   - Speed unavailable
   - stale source
   - pair mismatch
   - malformed source
   - independent scores remain uncombined
   - all manual-review/no-authority flags preserved

4. Parallel output
   - write a separate candidate adapter feed
   - do not replace oracle_prop_feed_v1.json
   - do not change the GitHub phone page
   - compare output over multiple cycles

5. Phone UI review
   - present source-separated packet
   - preserve existing live feed as rollback
   - verify timestamps, health, readability, and no false authority

6. Controlled promotion
   - explicit approval required
   - versioned adapter and UI migration
   - rollback path retained
   - no Pushover until source-owned episode and dedupe contracts are validated
```

---

## 11. Explicitly not authorized

This checkpoint does not authorize:

```text
Editing active TERRYPC runtime scanners
Editing oracle_prop_context_scanner.py
Editing oracle_micro_trigger_scanner_v1.py
Editing oracle_prop_feed_adapter_v1.py
Replacing oracle_prop_feed_v1.json
Changing the GitHub hosted page
Publishing a new feed payload
Creating or sending Pushover notifications
Re-enabling the GIMBAP M5 scheduled task
Stopping active TERRYPC processes
Adding order, queue, routing, stop, target, or execution behavior
```

---

## 12. Drift guard

Before any future command or change, identify its layer:

```text
[PRISM]       Shared mainframe market context
[DELTA]       Delta/Tempo technique/niche
[SPEED]       Delta/Tempo completed-M5 lifecycle enhancement
[ORACLE]      Existing feed/context packaging
[ADAPTER]     Source-preserving display translation and validation
[PUBLISHER]   Existing TERRYPC -> GitHub publication path
[HOSTED UI]   GitHub phone display only
[ALERTING]    Separate Pushover backup consumer
[RESEARCH]    Fixtures, audits, outcomes, lab-only work
```

No source, lab, process, artifact, or responsibility may be moved across layers without explicit review.

---

## 13. Locked summary

```text
PRISM is the mainframe.
Delta/Tempo is the niche.
Speed Companion sharpens Delta/Tempo timing.
Oracle/GitHub is the current phone delivery path.
The phone feed is primary.
Pushover is future backup only.
All current work remains manual review only.
No source scores are blended.
No source is allowed to silently impersonate another source.
```

---

## 14. Verified Speed Companion runtime contract

Verified on: 2026-08-28  
Runtime machine: TERRYPC  
Runtime workspace:

C:\Users\OneDrive\Desktop\jhl_v2\jhl_v2gimba

Source artifact:

speed_companion_kraken_spot_state_v1.json

Related runtime artifacts:

oracle_prop_context_kraken_spot_speed_v1.json
oracle_prop_feed_kraken_spot_speed_review_v1.json

The source artifact is fresh, versioned, and contains:

recordtype
schema_version
generated_at_utc
manual_review_only
entry_authority
does_not_authorize_trade
does_not_change_queue
source
health
states

Each source-owned state record includes:

pair
state
reason
input_timeframe
last_completed_candle_utc
bar_count
analysis_window_bars
active_horizon_bars
lifecycle_scope
source
Kraken pair identity fields
speed_phase
raw_speed_phase
manual_review_only
entry_authority

The verified source record semantics are:

state
  = source/data availability state, such as AVAILABLE
  = not a market confirmation state

speed_phase
  = source-owned M5 lifecycle state

speed_phase.direction
  = source-owned direction

speed_phase.phase
  = source-owned lifecycle phase

speed_phase.impulse_age_bars
  = current impulse age measured in completed M5 bars

speed_phase.impulse_size_atr
  = source-owned impulse magnitude

speed_phase.reclaim_confirmed
  = source-owned reclaim fact

speed_phase.decay_reason
  = source-owned reason when decay applies

Observed example:

Pair: AAVE/USD
Source state: AVAILABLE
Input timeframe: 5m
Last completed candle: 2026-08-28T21:20:00+00:00
Lifecycle scope: CURRENT_IMPULSE
Direction: LONG
Speed phase: WATCH
Impulse age: 8 completed M5 bars
Impulse size: 1.710611 ATR
Reclaim confirmed: False
Manual review only: True
Entry authority: False

### Speed ownership boundary

Speed Companion owns completed-M5 lifecycle facts. It does not own:

PRISM context or route logic
Delta/Tempo episode policy
Two-candle confirmation labels
Pushover notification decisions
Trade authority

The future two-candle confirmation must be a versioned, source-preserving Delta/Tempo policy that consumes validated Speed facts. It must not overwrite or relabel raw speed_phase.phase.

The adapter must show both independently:

Speed:
  source availability
  raw M5 phase
  direction
  impulse age
  reclaim/decay facts

Delta/Tempo:
  technique-owned first-candle / second-candle episode state

---

## 15. Verified Delta/Tempo Speed Companion contract

Verified on: 2026-08-28  
Runtime machine: TERRYPC  
Runtime workspace:

C:\Users\OneDrive\Desktop\jhl_v2\jhl_v2gimba

Implementation:

delta_tempo_speed_companion.py
test_delta_tempo_speed_companion.py
delta_tempo_prop_router.py
test_delta_tempo_v2_contract.py

### Ownership

Delta/Tempo Speed Companion is the per-pair, technique-owned timing and episode-lifecycle enhancement for Delta/Tempo.

It is distinct from the generic Kraken Spot Speed Companion:

Generic Kraken Spot Speed Companion
  = market-wide completed-M5 lifecycle observer

Delta/Tempo Speed Companion
  = Delta/Tempo-specific timing state machine that combines:
    directional Delta flow,
    price velocity normalized by ATR,
    price-velocity acceleration,
    reclaim confirmation,
    structural market condition,
    breakout/BOS facts,
    controlled-pullback state,
    decay retention,
    and per-pair episode memory

### Input discipline

The implementation evaluates completed OHLCV observations by excluding the final array element before calculating its price metrics.

### Source-owned output fields

schema_version = delta_tempo_speed_companion_v1
episode_state
episode_direction
initial_impulse_detected
watch_reference_price
watch_reference_level
price_velocity
prior_price_velocity
price_velocity_acceleration_ratio
impulse_quality
persistence_state
promotion_pattern
active_feed_visibility
manual_review_only
entry_authority
reason_codes
atr

### Source-owned lifecycle

NO_DATA
IDLE
WATCH_INITIAL_IMPULSE
WATCH_PERSISTING
WATCH_PULLBACK
CONFIRMED_RECLAIM_ACCELERATION
CONFIRMED_BREAKOUT_ACCEPTANCE
CONFIRMED_PULLBACK_REACCELERATION
DROPPED
INVALIDATED

### Source-owned thresholds

MIN_PRICE_VELOCITY = 0.35 ATR
MIN_PRICE_ACCEL = 1.15
DECAY_RATIO = 0.70
PULLBACK_MAX_ATR = 1.50

These thresholds remain owned by the Delta/Tempo source. No adapter or UI may alter their meaning.

### Field-feed interpretation

WATCH_INITIAL_IMPULSE
  = first qualifying completed Delta/Tempo timing observation
  = feed-visible
  = manual review only
  = entry authority remains false
  = future one-time Pushover backup eligibility, subject to separate
    alert-dedupe implementation and explicit approval

WATCH_PERSISTING / WATCH_PULLBACK
  = same episode remains active
  = feed updates
  = no duplicate Pushover

CONFIRMED_RECLAIM_ACCELERATION
CONFIRMED_BREAKOUT_ACCEPTANCE
CONFIRMED_PULLBACK_REACCELERATION
  = source-owned promotion of the existing episode
  = phone card promotes
  = no second Pushover by default

DROPPED / INVALIDATED
  = episode no longer active
  = feed deactivates or archives it
  = no default Pushover

### Safety boundary

The source contract and tests verify:

manual_review_only = true
entry_authority = false

The presence of source terms such as EXECUTION_READY elsewhere in the Delta/Tempo router does not grant execution authority to the adapter, hosted phone feed, Pushover, or any runtime process.

### Test coverage verified

Initial qualifying impulse:
  WATCH_INITIAL_IMPULSE
  active_feed_visibility = true
  entry_authority = false

Controlled pullback then reacceleration:
  CONFIRMED_PULLBACK_REACCELERATION

Reclaim confirmation:
  CONFIRMED_RECLAIM_ACCELERATION

Breakout/BOS acceptance:
  CONFIRMED_BREAKOUT_ACCEPTANCE

Velocity decay:
  DROPPED
  active_feed_visibility = false

### Promotion status

The code and tests establish the Delta/Tempo timing contract.

They do not yet prove that a standalone, timestamped, 49-pair live Delta/Tempo v2 artifact is being produced, validated, joined into the PRISM Adapter, or published to the current GitHub phone feed.

That runtime-output and adapter-wiring work remains a separate controlled integration phase.

---

## 15. Verified Delta/Tempo Speed Companion contract

Verified on: 2026-08-28  
Runtime machine: TERRYPC  
Runtime workspace:

C:\Users\OneDrive\Desktop\jhl_v2\jhl_v2gimba

Implementation:

delta_tempo_speed_companion.py
test_delta_tempo_speed_companion.py
delta_tempo_prop_router.py
test_delta_tempo_v2_contract.py

### Ownership

Delta/Tempo Speed Companion is the per-pair, technique-owned timing and episode-lifecycle enhancement for Delta/Tempo.

It is distinct from the generic Kraken Spot Speed Companion:

Generic Kraken Spot Speed Companion
  = market-wide completed-M5 lifecycle observer

Delta/Tempo Speed Companion
  = Delta/Tempo-specific timing state machine that combines:
    directional Delta flow,
    price velocity normalized by ATR,
    price-velocity acceleration,
    reclaim confirmation,
    structural market condition,
    breakout/BOS facts,
    controlled-pullback state,
    decay retention,
    and per-pair episode memory

### Input discipline

The implementation evaluates completed OHLCV observations by excluding the final array element before calculating its price metrics.

### Source-owned output fields

schema_version = delta_tempo_speed_companion_v1
episode_state
episode_direction
initial_impulse_detected
watch_reference_price
watch_reference_level
price_velocity
prior_price_velocity
price_velocity_acceleration_ratio
impulse_quality
persistence_state
promotion_pattern
active_feed_visibility
manual_review_only
entry_authority
reason_codes
atr

### Source-owned lifecycle

NO_DATA
IDLE
WATCH_INITIAL_IMPULSE
WATCH_PERSISTING
WATCH_PULLBACK
CONFIRMED_RECLAIM_ACCELERATION
CONFIRMED_BREAKOUT_ACCEPTANCE
CONFIRMED_PULLBACK_REACCELERATION
DROPPED
INVALIDATED

### Source-owned thresholds

MIN_PRICE_VELOCITY = 0.35 ATR
MIN_PRICE_ACCEL = 1.15
DECAY_RATIO = 0.70
PULLBACK_MAX_ATR = 1.50

These thresholds remain owned by the Delta/Tempo source. No adapter or UI may alter their meaning.

### Field-feed interpretation

WATCH_INITIAL_IMPULSE
  = first qualifying completed Delta/Tempo timing observation
  = feed-visible
  = manual review only
  = entry authority remains false
  = future one-time Pushover backup eligibility, subject to separate
    alert-dedupe implementation and explicit approval

WATCH_PERSISTING / WATCH_PULLBACK
  = same episode remains active
  = feed updates
  = no duplicate Pushover

CONFIRMED_RECLAIM_ACCELERATION
CONFIRMED_BREAKOUT_ACCEPTANCE
CONFIRMED_PULLBACK_REACCELERATION
  = source-owned promotion of the existing episode
  = phone card promotes
  = no second Pushover by default

DROPPED / INVALIDATED
  = episode no longer active
  = feed deactivates or archives it
  = no default Pushover

### Safety boundary

The source contract and tests verify:

manual_review_only = true
entry_authority = false

The presence of source terms such as EXECUTION_READY elsewhere in the Delta/Tempo router does not grant execution authority to the adapter, hosted phone feed, Pushover, or any runtime process.

### Test coverage verified

Initial qualifying impulse:
  WATCH_INITIAL_IMPULSE
  active_feed_visibility = true
  entry_authority = false

Controlled pullback then reacceleration:
  CONFIRMED_PULLBACK_REACCELERATION

Reclaim confirmation:
  CONFIRMED_RECLAIM_ACCELERATION

Breakout/BOS acceptance:
  CONFIRMED_BREAKOUT_ACCEPTANCE

Velocity decay:
  DROPPED
  active_feed_visibility = false

### Promotion status

The code and tests establish the Delta/Tempo timing contract.

They do not yet prove that a standalone, timestamped, 49-pair live Delta/Tempo v2 artifact is being produced, validated, joined into the PRISM Adapter, or published to the current GitHub phone feed.

That runtime-output and adapter-wiring work remains a separate controlled integration phase.

---

## 16. Verified PRISM Feed Adapter contract

**Verified on:** 2026-08-28  
**Shared lab path:**

```text
C:\Users\OneDrive\Desktop\jhl_v2\jhl-market-edge-drive\
Audit\jhl_v2gimba\prism_adapter_lab_v1
```

**Implementation and tests:**

```text
prism_feed_adapter_v1.py
test_prism_feed_adapter_v1.py
prism_adapter.py
test_prism_adapter.py
sample_prism_adapter_feed.json
```

### Adapter role

The PRISM Feed Adapter is a read-only report projector and schema/safety validator. It is not a PRISM scanner, decision engine, alert sender, publisher, execution engine, or order authority.

It translates validated source reports into:

```text
recordtype = PRISMFEEDCONTEXT
schema_version = prism.feed-context.v1
```

### Required top-level safety fields

```text
manual_review_only = true
trade_authority = false
entry_authority = false
does_not_send_alerts = true
does_not_change_queue = true
publish_eligible
publish_block_reason
cards
```

### Card shape

```text
pair
source_health
context
prism_map
confluence
risk
display
```

The card separates source-owned facts:

```text
Context:
  higher-timeframe environment, lane, regime, location, constraints

PRISM map:
  construction, fair-price relationship, band-travel state,
  ranked conditional routes, map quality

Confluence:
  independent Eight Gates and Delta/Tempo v2 sections
  score_relationship = INDEPENDENT_NOT_COMBINED

Risk:
  structural invalidation, opposing structure, available distance,
  room, liquidation coverage, risk reasons

Display:
  attention state and manual-review/no-entry-authority flags
```

### Verified safety behavior

The test suite verifies:

```text
Fixture reports:
  may project to feed context
  must not be publish eligible
  publish_block_reason = fixture_market_source

Missing-bar report:
  map_status = unavailable
  data_health.state = missing_bars
  PRISM.DATA.MISSING_BARS remains visible
  construction state remains unavailable
  no substitute PRISM map is invented

Trade authority:
  report_has_trade_authority is rejected

Forbidden execution-like field:
  report_contains_forbidden_field is rejected

Non-fixture Kraken market source:
  may be publish eligible only after the report passes validation
```

### Promotion status

The PRISM adapter contract and fixture tests are complete.

They do not yet prove a live, non-fixture, timestamped PRISM mainframe report is being produced from runtime market data or connected to the live Oracle/GitHub phone feed.

### Final contract-inventory result

Verified:

```text
1. Generic Kraken Spot Speed Companion runtime source contract
2. Delta/Tempo-specific Speed Companion source and lifecycle contract
3. PRISM Feed Adapter projection and safety contract
```

Not yet live-wired:

```text
1. Timestamped, 49-pair Delta/Tempo v2 runtime snapshot
2. Non-fixture live PRISM mainframe source report
3. Candidate source-preserving unified adapter feed
4. Hosted phone UI migration
5. New first-episode Pushover backup consumer and dedupe ledger
```

### Next controlled implementation target

Create a separate, read-only, versioned Delta/Tempo v2 runtime snapshot.

It must:

```text
- Preserve source-owned Delta/Tempo and Delta/Tempo Speed Companion fields
- Carry timestamps, pair identity, source/configuration identity, health,
  manual-review-only, and no-authority flags
- Validate the required 49-pair universe
- Write a new candidate artifact only
- Not modify existing Oracle, PRISM, GitHub, queue, alert, or execution paths
```
