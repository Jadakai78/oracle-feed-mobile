# JHL Gimba Build Handoff

This document summarizes the system changes, design decisions, and paste-ready direction established so far for the JHL Gimba scanner, reader, market reader, and APRIL roster workflow.

## Objective

The goal is to stop relying on a static 12-pair universe and instead evaluate the full market universe, then surface the **best 12 pairs** everywhere: scanner, reader, and market reader. The shared concept is that the full universe is scanned underneath, while the visible terminal panels stay focused on the top-ranked APRIL roster for the current cycle.

## Core architecture decided

The architecture settled on four layers:

1. **Scanner** runs the full universe and writes `signals.json`.
2. **APRIL roster selector** reads that payload and ranks all pairs.
3. **Reader** displays only the APRIL top 12 in clean signal format.
4. **Market reader** displays only the APRIL top 12 in market-state format.

This keeps one common source of truth across all terminal panels.

## APRIL roster concept

A shared helper module named `april_roster.py` was chosen as the easiest and cleanest design. The reason is that all three scripts need the same pair selection logic, and putting the ranking into one module avoids duplicated logic and drift.

### Purpose of `april_roster.py`

`april_roster.py` is intended to:

- Read `signals.json`
- Score every pair in the payload
- Return the top 12 pair names in ranked order
- Provide reusable helper functions for scanner, reader, and market reader

### Scoring philosophy

The roster score is meant to reward:

- Clean structure, especially `TRENDING_*` and usable `RANGING_NEUTRAL`
- Active tempo such as `LIVE`, `BUILDING`, and `EARLY`
- Real watch-state activity and aligned directional agreement
- Tradable volatility and expansion

The roster score is meant to penalize:

- `STRUCTURE_UNCLEAR`
- `DEAD` conditions
- RTS veto and elevated trap pressure
- Split or weak environments

## `april_roster.py` status

A paste-ready `april_roster.py` was outlined with the following public shape:

- `load_signals()`
- `score_pair(row)`
- `ranked_rows(data=None)`
- `top_12_pairs(data=None)`
- `filter_rows_to_top12(rows, data=None)`
- `debug_print(data=None)`

### Included scoring buckets

The draft roster module included these score components:

- Structure score
- Tempo score
- Watch-state score
- Volatility score
- Trap penalty
- Freshness bonus

It was also designed to recognize these bot keys where present:

- `gimba_volatile`
- `gimba_range`
- `rts_liq`
- `gimba_trend`

## Reader evolution

The reader started as a one-shot script that simply read `signals.json` once and printed current watch signals. It was then upgraded conceptually into a live terminal panel.

### Reader goals

The upgraded `read.py` should:

- Import `top_12_pairs` from `april_roster.py`
- Filter the payload to the APRIL roster only
- Loop like the scanner instead of exiting after one print
- Clear the screen each refresh for a clean terminal wall
- Include `gimba_trend` in alignment logic when present
- Surface structure failure reasons when structure is unclear

### Alignment upgrade

The old reader was built for three specialists. The tuned version was expanded to support four specialists:

- `VOL`
- `RNG`
- `RTS`
- `TRD`

Alignment labels were upgraded from `ALL 3 / 2 of 3` to:

- `ALL 4 ▲` or `ALL 4 ▼`
- `3 of 4 ▲` or `3 of 4 ▼`
- `2 of 4 ▲` or `2 of 4 ▼`
- `SPLIT ⚠`
- `SOLO(...)`
- `----`

### Reader loop behavior

A looping version of `read.py` was specified with a `REFRESH_INTERVAL`, intended to:

- Load `signals.json`
- Recompute APRIL top 12
- Filter and sort rows by roster order
- Clear the screen
- Print the updated panel
- Sleep and repeat until Ctrl+C

This was confirmed to be the correct behavior for a terminal monitor. The clear-screen behavior is intentional so the panel behaves like scanner and market reader rather than appending stale rows forever.

### Structure failure tuning in reader

A key tuning pass was added so the reader does not just print `STRUCTURE_UNCLEAR`. The improved behavior is to append the `why` field from structure context when available, producing lines like:

- `STRUCTURE_UNCLEAR [d1_data_unavailable]`
- `STRUCTURE_UNCLEAR [h4_data_unavailable]`
- `STRUCTURE_UNCLEAR [insufficient_data]`

This makes the terminal much easier to debug when the matrix is blank.

### Additional reader context

A small enhancement was also added to print `eq_pct` when available, so idle rows can still show where price sits in the structure range.

## Market reader evolution

The market reader was redesigned as a separate panel focused on **market state**, not direct bot entries. It is intended to show the APRIL top 12 in battlefield language.

### Market reader goals

The upgraded `market_reader.py` should:

- Import `top_12_pairs` from `april_roster.py`
- Filter to APRIL top 12 only
- Loop on a timer like the other panels
- Clear the screen each refresh
- Read structure, tempo, volatility, and liquidation state per pair
- Use trend and structure context to describe the environment

### Panel purpose

Panel 3 is meant to answer:

- What is the structure environment?
- Is tempo live, building, early, late, or dead?
- Is volatility quiet, normal, active, or expanding?
- Is liquidity calm, sweeping, trap-risk, or full trap?

### Market reader classification buckets

The designed market reader included these major functions:

- Structure classification
- Tempo summary
- Volatility regime classification
- Liquidation and trap regime classification
- A natural-language summary sentence per pair

### Loop behavior

The looped market reader was specified to:

- Reread `signals.json`
- Refresh the APRIL roster every cycle
- Clear the terminal
- Reprint the full market-state board
- Sleep and repeat until Ctrl+C

## Structure context interpretation

A major insight during debugging was that repeated `STRUCTURE_UNCLEAR` values are not necessarily a reader bug. They come from `structure_bias.py` when D1 or 4H OHLC fetches fail or return insufficient data.

### Meaning of `STRUCTURE_UNCLEAR`

The structure module is designed to return a null structure object when higher-timeframe data is unavailable. That null object includes:

- `state = STRUCTURE_UNCLEAR`
- `trend = unknown`
- `zone = neutral`
- `bos = False`
- `why = insufficient_data` or a more specific failure reason

### Failure reasons already present in structure context

The `why` field can carry values such as:

- `d1_data_unavailable`
- `h4_data_unavailable`
- `insufficient_data`

This is why the reader and market reader were tuned to display the reason inline.

## Trend integration

`gimba_trend` was confirmed to be producing payload fields such as:

- `bias`
- `engine = GimbaTrend`
- `setup_type`
- `conviction`
- `why`
- `action_state`
- indicator fields like `d1_trend`, `h4_trend`, `htf_trend`, `h1_tempo`, `m15_tempo`, `zone`, `eq_pct`, `rsi_h1`, `rvol_m15`, `pullback_depth`, `ema20_h1`, `ema50_h1`, and speed scores

This means the reader and market reader were both designed to account for trend as a fourth specialist where available.

## Scanner direction

The scanner remained the foundational producer of `signals.json`, and the plan going forward is:

- Expand scanner coverage to the full pair universe
- Keep writing full-payload `signals.json`
- Keep appending training logs
- Eventually print only the APRIL top 12 to the terminal, even though the full universe is scanned underneath

This preserves learning and context while keeping the visible wall focused.

## Intended workflow after all patches

The desired steady-state workflow is:

1. Run scanner in one terminal
2. Run reader in a second terminal
3. Run market reader in a third terminal
4. Let all three refresh continuously

### Expected responsibilities

- **Scanner**: detects setups, writes payload, maintains logs
- **Reader**: shows active bot signals for the APRIL top 12
- **Market reader**: shows the state of the battlefield for the APRIL top 12

## Known implementation notes

### Reader

The final tuned reader should include:

- APRIL roster filtering
- looping behavior
- terminal clear on refresh
- structure `why` display
- `eq_pct` display
- four-bot alignment logic

### Market reader

The final tuned market reader should include:

- APRIL roster filtering
- looping behavior
- terminal clear on refresh
- structure / tempo / volatility / liquidation summaries
- readiness to show structure failure reason inline as the next tuning pass

### APRIL roster

The roster module should remain the single shared selector. Any future tuning of weights should happen there so scanner, reader, and market reader all update together.

## Suggested next steps

The next logical build steps are:

1. Finalize `april_roster.py` in the project directory
2. Install the tuned looping `read.py`
3. Install the tuned looping `market_reader.py`
4. Patch scanner to scan the full universe but print only the APRIL top 12
5. Add structure failure reason display to market reader as well
6. Verify that all three panels show the same roster order each cycle

## Paste-ready files already drafted in chat

The conversation produced full or near-full drafts for:

- `april_roster.py`
- `read.py`
- `market_reader.py`

Those drafts are meant to be copied into the working directory and adjusted as needed to fit the current live scanner payload.

## Summary of decisions

The key decisions made so far are:

- Use a dynamic APRIL roster instead of a static 12-pair list
- Centralize selection logic in `april_roster.py`
- Keep scanner scanning broadly, but keep terminals focused narrowly
- Make reader and market reader loop like live dashboards
- Show structure failure reasons inline for fast debugging
- Treat trend as a fourth specialist in terminal alignment views

## Closing note

The direction is coherent now: one universe underneath, one APRIL roster above, and three synchronized panels showing different layers of the same market truth.
