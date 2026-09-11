# GDA AI Network / JHL Gimba – Change Map

This document captures the current system state and maps out all changes discussed so far, with a focus on sharpening offense while preserving a strong defense.

It is meant to be a living blueprint for:
- Context (what exists today).
- Problems observed.
- Design decisions.
- Concrete change steps (structure, RTS, scoring, shell).

---

## 1. Current system state

### 1.1 Stack overview

Active components:

- **Structure_bias (structure_bias.py)** – HTF market context (D1/4H + 1H tempo)
  - Outputs:
    - `market_condition` – TRENDING_UP/DOWN_* or RANGING_NEUTRAL or STRUCTURE_UNCLEAR.
    - `market_tempo` – LIVE / BUILDING / EARLY / LATE / DEAD.
    - `trend` – combined D1/H4 trend (`up`, `down`, `ranging`).
    - `zone` – premium / discount / neutral (D1 range).
    - `eq_pct` – normalized price position in D1 swing.
    - `alignment` – aligned_up, aligned_down, pullback_or_countermove, range.
    - `bos` – 4H break of structure flag.
    - `ema21_d1` + `ema_bias` (up/down).
    - `tempo_context` – speed, velocity, acceleration, v_direction, a_direction.
    - `why` – compact summary of D1/H4/zone/eq_pct/ema/tempo/v_dir/alignment (+ bos).

- **RTS Liquidation (rts_liquidation.py)** – trap / liquidation specialist
  - Identity:
    - Find retail bag holders, take their stop money, ride the reclaim.
  - Event families:
    - LIQUIDITYSWEEPRECLAIM (LONG/SHORT).
    - FAILEDBREAKOUT / FAILEDBREAKDOWN.
    - EXTENSIONRISKNOSHORT / EXTENSIONRISKNOLONG.
    - LIQUIDATIONTOCONTINUATION (LONG/SHORT).
  - Outputs:
    - `trapscore` – trap risk remaining (0 clean entry, 1 stay out).
    - `setuptype`, `bias`, `conviction`, `actionstate`.
    - `veto` + `vetodirection`.
    - Geometry (entry/SL/TP) for certain setups.

- **Specialists:**
  - **Gimba Volatile (VOL)** – expansion specialist.
  - **Gimba Range (RNG)** – mean reversion specialist.
  - **Gimba Trend (TRD)** – trend specialist.

- **Tempo (tempo.py)** – speed/velocity layer on 15m.

- **KNN (knn_engine.py)** – per-bot KNN adjustment.
  - Each bot gets its own KNN instance and training log.
  - Activates at 30 samples.

- **Scanner (scanner-3.py)** – writes `signals.json`.

- **Reader (read-2.py)** – terminal reader for signals.

- **JHL Live Shell (jhl-live-shell.html)** – local web shell
  - Panels:
    - Scanner overview (APRIL roster top 12).
    - Signal reader (WATCH-only).
    - Market state (structure / tempo / traps narrative).
  - Uses Cloudflare Tunnel to reach phone.

- **Blueprint & Handoff markdowns** – high-level context and state.

### 1.2 What’s proven so far

- Defense works:
  - Tempo gates (DEAD = no signals, LATE = no chase).
  - RTS veto outranks specialists when trap exposure is active.
  - Structure identifies TRENDING_* vs PULLBACK vs RANGING.
  - On a rough trading day, only a few stops were hit; PnL ended slightly positive.

- Offense exists but is not sharply separated from defense:
  - Signals are taken knowing some aren’t strong, to get a feel.
  - Scoring is present but not fully driving “attack vs ghost vs suppressed” lanes.

---

## 2. Problems & observations

### 2.1 Balance of offense vs defense

Legacy shade/ghost builds:

- When shade and ghost were active, defense and shield **overweighted** offense.
- Too many setups were killed or shielded; not enough clear attack setups.

Current day:

- Defense still strong; offense under-defined.
- System protects you but does not yet call out **few, clear, high-quality attacks**.

### 2.2 STRUCTURE_UNCLEAR messaging

Shell behavior before tuning:

- STRUCTURE_UNCLEAR used heavily, even when D1/H4/zone/eq_pct/ema/tempo/v_dir were known.
- Market state wording implied “we have no useful higher-timeframe information,” even for mixed but meaningful contexts.

After tuning:

- STRUCTURE_UNCLEAR now split into:
  - **Data issues:** `d1_data_unavailable`, `h4_data_unavailable`, `h1_data_unavailable`, `insufficient_data` → strong “context-poor” warning.
  - **Mixed but usable contexts:** full `why` string used with softer “mixed” language.
- Example for GOLD:

  ```text
  Higher-timeframe structure is mixed (d1=down | h4=ranging | zone=premium | eq_pct=1.10 | ema_bias=up | tempo=LIVE | v_dir=up | alignment=pullback_or_countermove); treat this pair as lower-confidence and lean on specialists and tempo until structure cleans up.
  ```

### 2.3 BOS and generic structure

Structure_bias:

- BOS is defined as 4H break of prior high/low in the direction of trend.
- BOS is stored as a simple boolean.

Concern:

- BOS, treated generically, is not equally useful for all lanes (VOL, RNG, RTS, TRD).
- BOS should enrich **trend/structure**, not be a universal gate for offense.

### 2.4 Trapscore visibility

- Shell initially read `trap_risk`; now reads `trap_score` or `trap_risk` from RTS.
- Trapscore is meant to be **trap risk remaining** (0 clean, 1 high risk).

Concern:

- Trapscore should be used explicitly in scoring and lane routing, not just displayed.

### 2.5 Offense knife

- You’ve framed offense as “the knife that needs sharpening.”
- System currently excels at telling you when to **avoid**; less clear on when to **attack**.

Desired behavior:

- Trap, trend, structure, and tempo **working together**, not separately.
- Structure to identify key areas where **order blocks / liquidity pools / smart money zones** sit.
- RTS to act as micro-execution layer inside those zones, confirming real kill setups.

---

## 3. Design decisions (what we want)

### 3.1 Clear lane separation

Use Oracle spec A–Z as doctrine:

- **Attack lane (Oracle Attack)**
  - Owns live sniper setups.
  - Outputs: `attackscore`, `oracleconfidence`, `readertier`, `attackgrade`, `scorecomplete`, geometry (entry/SL/TP), and reasons.

- **Ghost lane (Oracle Ghost)**
  - Owns non-attack but meaningful setups.
  - States: `kill`, `shield`, `scout`.
  - Outputs: `ghostscore`, `ghostconfidence`, `ghostreasonprimary`, `ghostreasons`.
  - Focuses on defense / scouting / trap / volatility / tempo / liquidity warnings.

- **Suppressed lane**
  - Rows that are neither attackable nor informative.

Goal:

- One upstream router decides attack vs ghost vs suppressed.
- Attack handled as offense; Ghost handled as defense.

### 3.2 Sentinel-aware penalties (Oracle Shade)

From Oracle spec: [trap, volatility, tempo, liquidity, execution] are separate penalty families.

Doctrine:

- **Trap penalty**:
  - Hurts structure-focused lanes more heavily.
  - Trap-oriented lanes (RTS, trap-thriving) are penalized less or differently.

- **Volatility penalty**:
  - High volatility penalizes certain attack styles; may be neutral or positive for volatility lanes.

- **Tempo penalty**:
  - DEAD or LATE states reduce attackscore.

- **Liquidity / volume penalty**:
  - Thin volume / poor liquidity reduce attackscore.

- **Execution penalty**:
  - Failed RR, poor fills, policy rules can push attackscore down.

Negative scores allowed:

- `attackscore` can drop below zero to distinguish:
  - Weak but still viable setups.
  - Neutral, no-edge setups.
  - Actively hostile setups.

### 3.3 Shared "kill" doctrine

A **real kill** should exist when:

1. **Trend & structure**:
   - D1/H4 give a clear TRENDING_UP/DOWN_* or TRENDING_*_PULLBACK state.
   - Price is at a key structural area: discount zone for longs, premium zone for shorts, pullback zone for continuation.

2. **Order block / liquidity context**:
   - Structure and RTS agree on a meaningful pool:
     - D1 swing highs/lows reflect key order blocks.
     - RTS finds sweeps/reclaims around those levels.

3. **Reclaim / trap resolution**:
   - RTS signals LIQUIDITYSWEEPRECLAIM or LIQUIDATIONTOCONTINUATION.
   - Trapscore indicates reduced trap risk (low values).

4. **Tempo & volatility**:
   - Tempo is LIVE / BUILDING / EARLY.
   - Volatility is healthy, not chaotic.

5. **Geometry**:
   - Entry/SL/TP can be defined cleanly around the pool / reclaim.

Kill setup:

- Combine these into a high `attackscore`, strong `oracleconfidence`, and a clear `actionstate` (stalk/engage).
- Ghost setup: if any hard defense triggers (dead tempo, high trapscore, thin volume, extension risk), route to Ghost with appropriate kill/shield/scout.

### 3.4 Structure-as-ICT/SMC context

Structure_bias should become more explicitly:

- A map of **HTF ranges and order blocks**:
  - D1 swing highs/lows as key structure.
  - Zone (premium/discount) as “order block” territory.
  - eq_pct as numeric coordinate within that territory.

- HTF trend state plus:
  - TRENDING_UP/DOWN_DISCOUNT – value zones for trend trades.
  - TRENDING_UP/DOWN_PREMIUM – stretched zones where trap risk may be higher.
  - PULLBACK states – ideal for RTS-style entries when retail is trapped.

RTS sits on top of this map to pinpoint actual trap events in those zones.

---

## 4. Concrete change steps

### 4.1 Shell (jhl-live-shell.html)

Already implemented:

- **Compact structure tag** for Scanner overview:

  ```text
  TRENDING_DOWN_PULLBACK [premium | eq 0.73 | ema↓ | LATE]
  ```

- **Market state sentences**:
  - Clear structure → `TRENDING_*` or `RANGING_NEUTRAL` summary.
  - STRUCTURE_UNCLEAR:
    - Data issues → "context-poor" warning.
    - Mixed contexts → "mixed" language with full `why` detail.

- **Trapscore wiring**:
  - Reads `trap_score` or `trap_risk` from `rts_liq`.
  - Displays trap values and uses them in APRIL-style scoring.

Next shell step (later):

- Display **attack vs ghost lanes** once router logic exists.
- Style ghost rows with Ghost print flag (shade) for quick visual defense.

### 4.2 Structure_bias tuning

Short-term shell-side tuning (already done):

- Reduce misuse of STRUCTURE_UNCLEAR.
- Use `market_condition` and `alignment` more for narrative.

Next back-end steps (future):

1. **Relax trend lookbacks slightly** (optional):
   - D1: lookback 20 → ~15.
   - H4: lookback 15 → ~10.
   - This makes trend resolution more responsive.

2. **Add explicit order block hints**:
   - Tag D1 swing high/low zones as potential order blocks.
   - Mark eq_pct extremes (e.g., > 1.0) as extension risk.

3. **Expose `structure_alignment` for offense**:
   - Use `aligned_up/down` vs `pullback_or_countermove` vs `range` as part of attack vs ghost router.

### 4.3 RTS / trap scoring & ICT/SMC integration

Current RTS capabilities:

- Liquidity pools: last 25 candles before the last.
- Sweeps and reclaims around pool boundaries.
- Trapscore defined as risk remaining.

Next RTS steps:

1. **Formalize trapscore bands** for offense/defense:
   - `trapscore <= 0.30` → clean reclaim / lower trap risk (better for attack lanes).
   - `trapscore ~ 0.50` → neutral trap risk.
   - `trapscore >= 0.70` → high trap risk (strong Ghost triggers for structure-focused lanes).

2. **Integrate trapscore into attack scoring**:
   - For trend/structure lanes, high trapscore → strong negative penalty.
   - For RTS lane, trapscore influences capture vs stand-aside, but may not kill offense entirely.

3. **Align RTS `setuptype` with structure zones**:
   - Prioritize LIQUIDITYSWEEPRECLAIM and LIQUIDATIONTOCONTINUATION when price is in discount/premium zones consistent with HTF trend.

### 4.4 Attack vs Ghost router (future build)

Router steps:

1. Build **Oracle context** from structure + RTS + specialists + tempo.
2. Evaluate attackability:
   - Clear TRENDING_* state.
   - Favorable zone (discount for longs, premium for shorts).
   - Low to moderate trapscore for structure-focused lane.
   - Tempo LIVE/BUILDING/EARLY.
3. Evaluate ghost conditions:
   - Dead or late tempo.
   - High trapscore.
   - Extension risk.
   - Liquidity/volume problems.
4. Route:
   - **Attack** when context says “kill.”
   - **Ghost** when context says “important but not attackable.”
   - **Suppressed** when neither.

Attack rows:

- Have high `attackscore`, real `oracleconfidence`, geometry, and reasons.

Ghost rows:

- Have `ghoststate` (kill/shield/scout), `ghostscore`, `ghostconfidence`, and ghost reasons.

### 4.5 Scoring discipline

From Oracle spec and current practice:

- No fake defaults:
  - Don’t invent `oracleconfidence` or `attackscore` when not scored.
  - Preserve null or explicit "unscored" states.

- All scoring stays on internal 0–100 scale.

Panel side (shell):

- Display final `attackscore` or APRIL score.
- Use shade/Ghost flags for visual defense.

---

## 5. Trading implications

With these changes and philosophy:

- **Defense remains strong**:
  - Structure/TRENDING_*/PULLBACK states keep you aware of HTF context.
  - Tempo gates and RTS veto continue to block bad aggression.
  - Ghost/shield lanes preserve trap/vol/tempo warnings.

- **Offense gets sharper**:
  - Real kill setups are defined where structure zones, RTS traps, trend, and tempo align.
  - Attack vs ghost routing clarifies which lanes are tradeable vs watch-only.
  - Trapscore and penalty families act as continuous weights, not blunt on/off switches.

- Trading days like the one you just had become:
  - Fewer signals taken.
  - More focus on the few attack lanes with true context alignment.
  - Same defensive protection, better offensive concentration.

---

## 6. Next actions

Immediate:

- Keep trading with current shell + context to feel live behavior.
- Observe which setups feel like real kills based on combined structure + RTS + tempo.

Near-term code work:

- Tuning structure_bias lookbacks and possibly adding order block hints.
- Formalizing trapscore bands and integrating them into APRIL scoring.
- Designing the initial Attack vs Ghost router for one lane (e.g., RTS or TRD) and testing it.

Later:

- Full Oracle Attack/Ghost implementation with Shade penalties.
- Shell updates to show lanes, ghost print, and clean attack scoring.

This change map is your guide: defense stays, offense gets doctrine, and the system as a whole begins to call out “this is the kill” instead of just “this is safe/not safe.”
