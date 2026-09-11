# GDA AI Network / JHL Gimba – Handoff v2

This markdown captures where the build stands right now, including:

- JHL Gimba stack and context (structure, specialists, APRIL12).
- JHL Live Shell (local website) with scanner, signal reader, and market-state panels.
- Structure tuning philosophy (STRUCTURE_UNCLEAR vs mixed vs clear) and BOS.
- Funding/pitch direction for GDA AI Network.

Use this as a reset point: if things get scrambled, this tells you how the system is wired and what the shell and context are supposed to do.

---

## 1. System overview

### 1.1 Core identity

**Project name:** GDA AI Network

**Trading engine:** JHL Gimba (multi-specialist decision-support stack)

Purpose:

- Turn you from a retail chart-clicker into a small liquidator with full market context.
- Provide a structured view of trend, structure, tempo, volatility, traps, and alignment.
- Use APRIL12 to surface the best 12 markets to focus on per cycle.

### 1.2 Specialists

JHL Gimba consists of:

- **Structure_bias** — HTF market context:
  - Reads D1, 4H, and 1H tempo.
  - Outputs `market_condition`, `market_tempo`, `trend`, `zone`, `eq_pct`, `alignment`, `bos`, `ema_bias`, and a detailed `why` string.
- **Gimba Trend (TRD)** — trend specialist.
- **Gimba Volatile (VOL)** — volatile environment specialist.
- **Gimba Range (RNG)** — range specialist.
- **RTS Liquidation (RTS)** — liquidation/trap specialist, can veto direction and exposes trap scores.

These specialists are designed as **mainframes**:

- They can train in any environment.
- Initially tuned for crypto pairs.
- Conceptually drop-in for other markets with additional training.

### 1.3 Context vs signals

Structure_bias and specialists:

- Do **not** generate direct trade signals in this file.
- Generate **context** that amplifies or discounts the specialists and the signals you choose to follow.

Your scanner and bots use this context to:

- Boost conviction when trend, zone, and tempo align.
- Discount or veto trades when traps, structure, or alignment are bad.

---

## 2. Structure_bias.py – HTF market context

### 2.1 Inputs and outputs

**Inputs:**

- Kraken OHLC for each pair:
  - D1: 1440-minute interval, last 30 candles.
  - 4H: 240-minute interval, last 40 candles.
  - 1H: 60-minute interval, last 60 candles.

**Outputs (context dict):

- `pair`
- `market_condition` — HTF structure state (TRENDING_*/RANGING_NEUTRAL or STRUCTURE_UNCLEAR).
- `market_tempo` — tempo (LIVE/BUILDING/EARLY/LATE/DEAD).
- `trend` — combined D1/H4 trend (`up`, `down`, `ranging`).
- `zone` — `premium`, `discount`, `neutral` within the D1 range.
- `eq_pct` — normalized position of price within the D1 swing range.
- `d1_trend`, `h4_trend`, `h1_tempo`.
- `amplifier` and `counter_amplifier` — multiplier for conviction adjustments.
- `bos` — 4H break of structure flag.
- `ema21_d1` and `ema_bias` (up/down).
- `swing_high`, `swing_low` — D1 swing extremums.
- `alignment` — `aligned_up`, `aligned_down`, `pullback_or_countermove`, or `range` based on HTF trend vs 1H velocity.
- `tempo_context` — speed/velocity/acceleration details from the 1H tempo module.
- `why` — a compact string summarizing all of the above, e.g.:

  ```
  d1=down | h4=ranging | zone=premium | eq_pct=1.10 | ema_bias=up | tempo=LIVE | v_dir=up | alignment=pullback_or_countermove | bos_detected_4h
  ```

### 2.2 Trend logic

Trend detection (`_swing_structure`):

- Uses pivot highs/lows to classify trend as `up`, `down`, or `ranging`.
- Compares last two pivot highs and lows:
  - HH + HL → `up`.
  - LH + LL → `down`.
  - Otherwise → `ranging`.

Higher-timeframe trend resolution (`_resolve_market_condition`):

- **Aligned trends:**
  - D1 `up` + H4 `up`:
    - `TRENDING_UP_DISCOUNT` (zone discount) → longs amplified.
    - `TRENDING_UP_PREMIUM` (zone premium) → longs discounted.
    - `TRENDING_UP_NEUTRAL` (zone neutral) → normal confidence.
  - D1 `down` + H4 `down` similarly produce `TRENDING_DOWN_*` states.

- **Pullback states:**
  - D1 `up` + H4 `down`/`ranging` → `TRENDING_UP_PULLBACK`.
  - D1 `down` + H4 `up`/`ranging` → `TRENDING_DOWN_PULLBACK`.

- **Ranging:**
  - Non-aligned trends → `RANGING_NEUTRAL`.

Each condition emits a numeric amplifier that scanner can use to adjust conviction.

### 2.3 BOS (Break of Structure)

BOS detection (`_bos_detected`):

- Uses 4H candles only.
- For `trend == "up"`:
  - Checks if the latest close breaks the prior high across a lookback window.
- For `trend == "down"`:
  - Checks if the latest close breaks the prior low.
- BOS is stored as a boolean and added as a marker in the `why` string (`bos_detected_4h`).

Design intent:

- BOS is a **context flag** for structure/trend.
- BOS does **not** gate whether structure exists; TRENDING_* states come from trend and zone.

---

## 3. JHL Live Shell – local website

### 3.1 Purpose

The shell is a static HTML/JS file that:

- Runs in the same folder as `signals.json`.
- Reads `signals.json` over HTTP on a loop.
- Renders three panels:
  - **Scanner overview** — APRIL top 12 with structure and alignment.
  - **Signal reader** — WATCH-only specialist view.
  - **Market state** — narrative structure/tempo/trap summary.

### 3.2 Data it reads

The shell expects `signals.json` to contain:

- `ts`, `cycle`, `signals`.
- For each row:
  - `pair`.
  - `structure` object mirroring `structure_bias.py` outputs (including `state`, `zone`, `eq_pct`, `bos`, `ema_bias`, `tempo`, `alignment`, `why`).
  - Specialist objects: `gimba_volatile`, `gimba_range`, `rts_liq`, `gimba_trend`.
  - Each specialist has `action_state`, `bias`, `conviction`, `tempo`, `knn_samples`, `knn_adj`, optional entry/SL/TP, and for RTS a trap metric (`trap_score` or `trap_risk`) plus veto fields.

### 3.3 APRIL-style scoring inside the shell

The shell computes a roster in-browser using:

- Structure score from `structure.state`.
- Count and alignment of WATCH signals across specialists.
- Tempo and conviction per bot.
- Volatility scores.
- Trap scores from RTS.

Scores are signed:

- **Positive** → structurally favorable contexts.
- **Near zero** → neutral / meh.
- **Negative** → context-poor or risky environments.

APRIL roster is the top 12 pairs by score. All panels focus on this roster.

### 3.4 Compact structure tag (Scanner overview)

For each pair the shell renders a compact tag:

```text
TRENDING_DOWN_PULLBACK [premium | eq 0.73 | ema↓ | LATE]
```

Implementation (`compactStructureTag(row)`):

- Pulls `state`, `zone`, `eq_pct`, `ema_bias`, and `tempo` from `structure`.
- Uses `STRUCTURE_UNCLEAR [...]` for unclear states.
- Uses `STATE [...]` for TRENDING/RANGING states.

This tag is short enough to fit on the scanner cards while still conveying:

- HTF structure state.
- Premium/discount/neutral.
- eq_pct as a quick coordinate.
- EMA bias.
- Tempo.

### 3.5 Market state sentences

The Market state panel uses a structured sentence per pair.

For clear structure (`state != STRUCTURE_UNCLEAR`):

- Builds a summary:

  ```text
  TRENDING_DOWN_PULLBACK (LATE | premium | pullback_or_countermove) · eq 0.73; tempo mix VOL:LIVE · RNG:LATE, liquidation context sweep, trap risk 0.15.
  ```

- Uses `structureSummary(row)` to combine:
  - `state`, `zone`, `eq_pct`, `tempo`, `alignment`.
- Appends tempo mix, liquidation context, and trap risk.

For STRUCTURE_UNCLEAR:

- The shell distinguishes between **data issues** and **mixed but usable** contexts using `structure.why`.

Logic:

```js
if (state === 'STRUCTURE_UNCLEAR') {
  const why = s.why || '';
  const isDataIssue =
    why.includes('d1_data_unavailable') ||
    why.includes('h4_data_unavailable') ||
    why.includes('h1_data_unavailable') ||
    why.includes('insufficient_data');

  if (isDataIssue) {
    // true blind spot – no HTF data
    return `Higher-timeframe structure is unclear (${why}); treat this pair as context-poor until D1/4H data stabilizes.`;
  }

  // mixed, but not blind – you still have trend, zone, eq_pct, and alignment
  return `Higher-timeframe structure is mixed (${why}); treat this pair as lower-confidence and lean on specialists and tempo until structure cleans up.`;
}
```

Examples:

- **Data failure:**

  ```text
  Higher-timeframe structure is unclear (d1_data_unavailable); treat this pair as context-poor until D1/4H data stabilizes.
  ```

- **Mixed but usable:**

  ```text
  Higher-timeframe structure is mixed (d1=down | h4=ranging | zone=premium | eq_pct=1.10 | ema_bias=up | tempo=LIVE | v_dir=up | alignment=pullback_or_countermove); treat this pair as lower-confidence and lean on specialists and tempo until structure cleans up.
  ```

This prevents STRUCTURE_UNCLEAR from sounding like “we have no idea” in cases where you actually have rich context and simply prefer to lean on specialists.

### 3.6 Trap score wiring

Trap scores in the shell are read as:

```js
const trap = Number(row?.rts_liq?.trap_score || row?.rts_liq?.trap_risk || 0);
```

This ensures:

- If RTS outputs `trap_score`, it’s used everywhere:
  - In APRIL scoring.
  - In Market state trap tag.
- If RTS uses `trap_risk` instead, the shell still picks it up.

In the Market panel cards:

```text
trap 0.15
```

matches the live RTS trap values (once the correct key is in the payload).

---

## 4. Structure tuning philosophy (shell side)

### 4.1 Goal

- Keep higher-timeframe structure as your **defensive shield**.
- Avoid making structure so strict that it takes 25 days to show anything useful.
- Use clear TRENDING/RANGING states as soon as they are “good enough,” not only when they are perfect.

### 4.2 How the shell supports this

Shell changes are designed to:

- Make **STRUCTURE_UNCLEAR** mean “we truly lack HTF data” (data_unavailable/insufficient), not “trend is messy.”
- Mark cases like GOLD (D1 down, H4 ranging, zone premium, eq_pct 1.10, EMA up, tempo LIVE, v_dir up, alignment pullback) as **mixed**, not blind.
- Encourage you to lean on specialists and tempo in mixed environments rather than treat them as zero information.

You plan to adjust `structure_bias.py` gradually so:

- `_swing_structure` and `_resolve_market_condition` produce TRENDING_* and RANGING_NEUTRAL states more often.
- STRUCTURE_UNCLEAR is reserved for genuine data gaps.
- BOS remains a 4H break-of-structure detail, not a gate.

---

## 5. Funding / pitch context (GDA AI Network)

### 5.1 Personal story

- Trading for ~3 years.
- Built JHL/Gimba tools for ~3 months with hundreds of hours of intense programming and trial-and-error.
- Stuck driving Uber with limited capital and time; not enough to trade out quickly.
- Instead of giving up, you built a full end-to-end system.

### 5.2 What you’re proud of

- A fully functional system that has an answer whether the market goes up, down, or sideways.
- Specialists that:
  - Map HTF structure, trend, tempo, volatility, traps.
  - Act as both offensive tools and defensive shields.
- A live shell and APRIL roster that give you honest, real-time context across a broad universe.

### 5.3 Funding plan (10k / 5k minimum)

You framed a clear ask:

- **Hardware:**
  - Laptop with at least **32 GB RAM** (~$600–$1,000) to run serious quant backtesting and forward-testing simultaneously.

- **Trading capital:**
  - ~$1,500 on Kraken.
  - Bots train 7 days across ~690 pairs.
  - Live run starts day 8.

- **Runway:**
  - 2 months in a modest Airbnb/room to focus.
  - ~$500 car rental so you can still drive Uber to cover food/car while devoting the rest of time to testing and refinement.

- **Time horizon:**
  - 3 months: fully up, tested, and running at full force; Uber becomes optional.
  - 6 months: clean monthly PnL, strict SL/TP rules that you can explain to a 5th grader; productization into alerts/bots/services.

### 5.4 Prop firm angle

Part of the funding plan includes:

- Purchasing higher-value prop firm challenges.
- Using your system, which is built around strict rules and small error margins, to pass those challenges.
- Goal within roughly 2 months of focused time:
  - Be trading with at least **$500k** in prop capital from one or more firms.
  - Trade very conservatively to extract roughly **$15k/day** when conditions are right.
  - Use that to clear debt and provide a strong base for family (sister and niece).

---

## 6. Reset checklist

If you ever need to rebuild this wiring from scratch:

1. Ensure `scanner.py` is writing `signals.json` with `ts`, `cycle`, and a `signals` list.
2. Keep `structure_bias.py` as the HTF context engine, emitting `structure` fields as described above.
3. Ensure specialists (`gimba_volatile`, `gimba_range`, `rts_liq`, `gimba_trend`) produce:
   - `action_state`, `bias`, `conviction`, `tempo`, `knn_samples`, `knn_adj`, optional entry/SL/TP.
   - RTS includes `trap_score` or `trap_risk` plus veto fields.
4. Place `jhl-live-shell.html` in the same folder as `signals.json` and serve with:

   ```bash
   python -m http.server 8000
   ```

5. Open the shell (e.g., `http://localhost:8000/jhl-live-shell.html`) and verify:
   - Status strip shows timestamp, cycle, pairs scanned, active watch rows, APRIL roster size.
   - Scanner overview shows APRIL top 12 with compact structure tags and scores.
   - Signal reader shows watch-only specialist cards when signals are active.
   - Market state panel shows structured sentences reflecting HTF structure, tempo, and traps.

With those in place, you have:

- GDA AI Network running locally.
- JHL Gimba specialists and context feeding `signals.json`.
- A shell and APRIL roster giving you the field view you need to trade instead of code.
