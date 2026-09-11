# 2026-08-05 — Boot Notes (Market Edge + KNN + Shell)

## Intent

Not building “setup AI”, but **market AI** — an architecture that learns how the tape actually moves:

- Where and when liquidation events happen.
- Which regimes (trend, pullback, range, chop, thin/explosive) pay and which leak.
- How prop risk and execution biases interact with those regimes.

The goal is to make money off **market behaviour**, not just prettier individual setups.

---

## KNN Engine: From Setup Bias to Market Regime Bias

**File:** `knn_engine.py`  

### Previous state

- Each bot had a small feature vector:
  - Volatile: RSI, rvol, ATR, speed_pct, maturity, st_direction, st_flipped.
  - Range: RSI, bb_pct, ATR, expansion_active.
  - RTS: trap_score, rvol, ATR, sweep/reclaim flags, strong_wick.
- Outcome labeling:
  - Good: `action == "watch"` and conviction ≥ 0.65.
  - Bad: `action == "idle"` or conviction < 0.40.
  - Neutral: ignored.
- KNN adjustment returned a bias in [-0.15, +0.15] per bot.[153]

### New direction

Add **market context** into KNN feature vectors so neighbours cluster by **regime**, not just indicators.

#### Volatile (`_features_volatile`)

Now includes:

- Local signal:
  - RSI, rvol, ATR, speed_pct, maturity, st_direction, st_flipped.
- Structure context:
  - `d1_trend` and `h4_trend` encoded as –1/0/+1.
  - `zone` encoded as discount/neutral/premium → –1/0/+1.
  - `eq_pct` as 0–1.
- Regime context:
  - `volatility_state` → normal vs explosive.
  - `volume_state_15m` → thin/normal/high.[153]

Result: KNN can learn “late premium, D1 down, thin/explosive” as a specific context that historically leaks for continuation longs.

#### Range (`_features_range`)

Now includes:

- Local signal:
  - RSI, bb_pct, ATR, expansion_active.
- Structure context:
  - `d1_trend`, `h4_trend`, `zone`, `eq_pct`.

Result: KNN can distinguish range fades in discount vs premium zones, and in aligned vs misaligned HTF trends.

#### RTS (`_features_rts`)

Now includes:

- Local trap geometry:
  - trap_score, rvol, ATR, sweep_size, sweep/reclaim flags, strong_wick.
- Structure context:
  - `zone` encoded, `eq_pct`.
  - `market_condition` → simple regime code: TRENDING vs RANGING vs other.[145]

Result: KNN can learn which **trap contexts** (trend vs range, discount vs premium) actually paid vs faked out.

#### Trend (`_features_trend`)

Already used HTF context:

- `d1_trend`, `h4_trend`, `zone`, `eq_pct`.
- `pullback_depth`, `rsi_h1`, `rvol_m15`, speed scores.[153]

This stays; now all four bots have a similar regime‑aware KNN view.

---

## Live Shell: Left / Middle / Right Speaking “Market Edge”

**File:** `JHL-Live-Shell.html`[193]

### Layout

- **Left panel — Scanner overview**
  - Shows:
    - Pair, score.
    - Consensus tag (ALL/3/2/SPLIT/SOLO/----).
    - Structure tag (state, zone, eq, ema bias, tempo).
    - Shadow pill (CLAIM / WATCH / VETO + score).
    - Offense mode (TREND / RANGE / TRAP / MIXED / DEAD).
    - Watcher count.
    - New:
      - TF mix: `D1`, `H4`, `H1`, `M15` tempos.
      - “Market edge” sentence (via `marketSentence(row)`).

- **Middle panel — Signal reader (WATCH only)**
  - For each APRIL pair with watch signals:
    - Pair header.
    - Consensus + veto.
    - Shadow pill + MODE.
    - **New edge line**: `VOL▲★, RNG—, RTS—, TRD▲·` style:
      - `▲★` = strong edge (bias + conviction ≥ 0.6 + non‑DEAD tempo).
      - `▲·` = weak edge (conviction 0.2–0.6 + non‑DEAD tempo).
      - `—` = no entry edge.
    - Sub‑cards per bot:
      - Bias (LONG/SHORT), conviction, tempo, KNN adj/samples, geometry (E/SL/TP).

- **Right panel — Actionable edge**
  - Filters APRIL rows to **actionable** only:
    - At least one bot with strong edge (`hasStrongEdge(row)`).
    - Shadow verdict ≠ `shadow_veto`.
    - Consensus ≥ `2 of 4` in one direction (ALL/3/2 of 4).
  - Shows:
    - Pair, structure state.
    - Zone, eq_pct, trap score.
    - Shadow pill, MODE.
    - Edge line (`VOL▲★, RNG—, RTS—, TRD▲·`).
    - TF mix (D1/H4/H1/M15 tempos).
    - Market edge sentence.

Result:  
- Left = **who & where is making money** (field read + regime sentence).  
- Middle = **no edge vs edge + shield** (per pair, per bot).  
- Right = **only go lanes** where your system believes there is real, prop‑aware edge.

---

## Boot, not Reboot

This session is more “boot” than “reboot”:

- You did **not** throw out the system.
- You clarified the mission:
  - From “find better setups” → to “understand and monetise market regimes.”
- You:

  - Gave KNN a richer picture of context.
  - Made the shell show your money‑lane language.
  - Tightened how Shadow, offense modes, consensus, and edge are seen in one wall.

The “boot” concept is:

> Start from the architecture you have, align it with your true intent (market edge), and let it learn live regimes and liquidation behaviour over the next 1–2 days while you keep risk light.

If you keep this MD as a checkpoint, you’ll be able to look back Friday and see exactly what changed and whether the system is now answering the question you really care about: **“Where is the market making money, and am I standing in that lane or in front of it?”**