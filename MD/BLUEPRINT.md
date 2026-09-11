# JHL HOLDINGS — BATTLEFIELD BLUEPRINT
**Last Updated:** 2026-08-03  
**Owner:** Jason Warr | JHL Holdings LLC | Chicago, IL  
**Emails:** blazing0478@gmail.com + jasonrwarr@outlook.com (ALWAYS BOTH)  
**Boot this file first** — paste into any new admin to rehydrate context in under 5 minutes.

---

## WHO WE ARE

Proprietary trader building a self-learning signal system for crypto.  
Current capital: 1 prop account ($5K). Kraken API trading is the destination once capital arrives.  
Scientific method framing: **we prove ourselves wrong, not right.**  
Guiding principle: **we are always chasing the dragon.**

---

## WHERE WE ARE RIGHT NOW

**Active system:** `C:\Users\jason\OneDrive\Desktop\jhl_v2\gimba\`  
**Status:** TRAINING DAY. Running all day 2026-08-03. Live tomorrow.  
**Infrastructure:** Local only. Railway dead. GitHub stale. Everything runs from the gimba folder.

### Current File Stack
```
gimba\
  scanner.py          — main loop, 12 pairs, 5min cycle, writes signals.json
  gimba_volatile.py   — volatility/expansion specialist
  gimba_range.py      — mean-reversion/range specialist
  rts_liquidation.py  — trap/liquidation specialist
  structure_bias.py   — D1/4H trend context, amplifies other bots
  tempo.py            — velocity (vt=Pt-Pt-1) + acceleration (at=vt-vt-1) + tempo state
  knn_engine.py       — shared KNN brain, one instance per bot
  read.py             — clean signal reader, run in separate terminal
  signals.json        — live output (auto-written each cycle)
  training_logs\      — JSONL per bot, KNN trains from these
    gimba_volatile.jsonl
    gimba_range.jsonl
    rts_liquidation.jsonl
```

### Run Commands
```powershell
cd C:\Users\jason\OneDrive\Desktop\jhl_v2\gimba
python scanner.py        # terminal 1 — keeps running
python read.py           # terminal 2 — read anytime
```

---

## THE MATRIX (4 bots + 1 context layer)

| Bot | Identity | Timeframe | Key Signal |
|-----|----------|-----------|------------|
| GimbaVolatile | Expansion specialist | 15m | SURGE_CONTINUATION, CASCADE_RECOVERY |
| GimbaRange | Mean-reversion specialist | 1H | LOWER_BAND_BOUNCE, UPPER_BAND_FADE |
| RTSLiquidation | Trap/liquidation specialist | 15m | LIQUIDITY_SWEEP_RECLAIM, FAILED_BREAKOUT |
| StructureBias | D1/4H context layer | D1+4H | Amplifies/discounts other bots |
| Tempo | Speed/velocity layer | 15m | LIVE/BUILDING/EARLY/LATE/DEAD |

### Alignment Rules (read.py output)
- `ALL 3 ▲` — highest conviction. All three specialists agree.
- `2 of 3 ▲` — high conviction. Act with normal sizing.
- `SOLO(RNG)` — lower confidence. Manage tight. ETH this morning was this.
- `SPLIT ⚠` — bots disagree. Stand aside.

### Structure Amplifier
- `TRENDING_UP_DISCOUNT` + LONG = conviction ×1.20 (green)
- `TRENDING_UP_PREMIUM` + LONG = conviction ×0.85 (yellow — caution)
- `TRENDING_DOWN_PREMIUM` + SHORT = conviction ×1.20 (green)
- Counter-trend signal = conviction ×0.70

### Tempo Gates
- `LIVE` / `BUILDING` / `EARLY` = signals fire normally
- `LATE` = SURGE conditions downgraded to NO_CHASE automatically
- `DEAD` = nothing fires regardless of other indicators

### RTS Precedence Rule
Confirmed RTS veto (conviction ≥ 0.65) outranks ALL other specialists.  
`VETO:LONG` = block all long signals. `VETO:SHORT` = block all shorts.

---

## KNN — HOW IT LEARNS

Each bot has its own KNN instance. **KNN separate — that's what makes them special.**  
- Reads its own JSONL training log
- Needs 30 samples minimum before activating
- Returns conviction adjustment in [-0.15, +0.15]
- Terminal shows `KNN(n/30)` until ready, then `KNN(144)+0.023` when live
- Today's training → tomorrow's edge

---

## ACTIVE PAIRS (12)

SOL/USD, BTC/USD, ETH/USD, XRP/USD, ADA/USD, DOGE/USD,  
LINK/USD, AVAX/USD, DOT/USD, MATIC/USD, AAVE/USD, LTC/USD

---

## TRADING RULES (NON-NEGOTIABLE)

- Casino model: first loser = done. No exceptions.
- No mid-drive trading decisions. Ever.
- Missed signal = skip, never chase.
- CAUTION: Neg C1 → CUT IMMEDIATELY. Flat C2 → CUT. 2 candles max.
- Pull profits daily up to $325. No compounding — cash flow priority.
- Waterfall: $167 overhead + $25 credits = $192 floor → Jason capped at $200 → JHL $100 → max $325/day.
- Two trading windows: Session 1 = 2:33AM CDT. Session 2 = 12PM CDT.
- Prop = frontend income. Kraken/Forex = 401K. 10% of every payout feeds 401Ks.
- Shorts ENABLED on Breakout and Kraken.
- $25K seat = DRAGON MODE — full aggression, $150+ risk/trade.

---

## WHAT WE PROVED TODAY (2026-08-03)

1. Matrix works live. ETH fired SOLO(RNG) LOWER_BAND_BOUNCE. Structure said TRENDING_DOWN_DISCOUNT — caution. Closed at +3.42 instead of holding to full TP. Correct read.
2. Tempo gates are live. DEAD market = nothing fires. LATE = no chase.
3. Velocity formula wired: vt = Pt - Pt-1, at = vt - vt-1. Feeds SURGE conviction bonus and Range expansion kill.
4. KNN collecting data all day. Activates at 30 samples per bot.

---

## NEXT SESSION AGENDA

- [ ] Review KNN sample counts (check `training_logs\` JSONL line counts)
- [ ] Check if any pairs generated consistent signals during training day
- [ ] Live session: read.py only. Trade ALL 3 ▲ or 2 of 3 ▲ signals.
- [ ] After capital: wire Kraken API for autonomous execution loop.

---

## FUTURE BUILDS (DO NOT BUILD YET)

- Autonomous trend bot (Kraken API execution) — after capital arrives
- Full Oracle scoring engine (battlefield\ folder) — after Tuesday live session proves matrix
- KNN outcome labeling from real trade results — after first live week

---

## BOOT RITUAL FOR NEW ADMIN

Paste this file. Then say:  
*"Summarize the current system state and tell me what we're doing today."*  
If the admin gets it right without asking clarifying questions — you have a good session.  
If it asks "what project is this?" — paste again and add the run commands.

---

*Build don't buy. Cheaper is always better. We are always chasing the dragon.*
