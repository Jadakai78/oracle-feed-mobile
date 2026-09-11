# JHL APRIL12 + Live Shell

This document captures the current design for two pieces that sit on top of the existing Gimba stack:

- **APRIL12 roster selector** — a shared module that ranks the full universe and returns the best 12 pairs for the current cycle.
- **JHL Live Shell (local website)** — a static dashboard that reads `signals.json` over HTTP and renders three synchronized panels.

It is meant as a compact reset point: if anything gets lost, this file tells you how to wire APRIL12 and the shell back into the system.

---

## 1. APRIL12 roster selector

### 1.1 Purpose

APRIL12 is the selector that decides which pairs matter most right now. It replaces a static 12-pair list with a dynamic roster drawn from the full universe your scanner is already running.

From the rest of the system’s perspective it does exactly one thing:

> Given the current `signals.json` payload, return the top 12 pairs in ranked order.

Everything else — scoring details, weighting, penalties — lives inside the selector and can be tuned without touching scanner, reader, or market panels.

### 1.2 Data it reads

APRIL12 reads the same payload you’re already writing from `scanner-3.py`:

- Top-level: `ts`, `cycle`, `signals` list
- Per-row keys (examples):
  - `pair`
  - `structure` (state, zone, bos, eq_pct, why)
  - `gimba_volatile`, `gimba_range`, `rts_liq`, `gimba_trend` (bias, conviction, tempo, knn fields, entry/sl/tp, veto, trap_risk, etc.)

It does **not** invent new data; it scores what is already there.

### 1.3 Scoring philosophy

The selector’s scoring logic is built around a few simple rules of thumb:

- **Reward clean structure** — TRENDING_* states and usable RANGING_NEUTRAL get positive weight; STRUCTURE_UNCLEAR gets a penalty.
- **Reward real activity** — rows with watch-state signals and aligned directional agreement get more weight than idle or split rows.
- **Reward good tempo** — LIVE, BUILDING, and EARLY tempos are favored; LATE and DEAD are discounted.
- **Reward tradable volatility** — expansion and healthy volatility regimes get a modest boost.
- **Penalize traps and veto** — elevated trap risk and RTS veto apply negative weight.

Net result: in each cycle the selector surfaces the 12 pairs most worth paying attention to, without forcing you to curate a list by hand.

### 1.4 Public API shape

The APRIL12 module is designed to expose a small, reusable public surface:

- `load_signals()` — read `signals.json` from disk and return the parsed dict.
- `score_pair(row)` — compute a numeric score for a single pair row.
- `ranked_rows(data=None)` — return all rows sorted by score, highest first.
- `top_12_pairs(data=None)` — return a list of the top 12 `pair` names.
- `filter_rows_to_top12(rows, data=None)` — given a list of rows, return only those whose pair is in the current top 12.

Scanner, reader, and market panels do **not** need to know how scoring works; they just call `top_12_pairs` or `filter_rows_to_top12` and render.

### 1.5 Where it lives

The selector is intended as a standalone module in the same directory as your other bots:

```text
project-root/
  scanner.py
  read.py
  market_reader.py
  tempo.py
  gimba_volatile.py
  gimba_range.py
  rts_liquidation.py
  gimba_trend.py
  structure_bias.py
  knn_engine.py
  april_roster.py   # APRIL12 selector module
  signals.json
```

All three primary scripts import from it:

- `scanner.py` can use it if you want to print only APRIL12 rows to the terminal.
- `read.py` uses it to filter to APRIL12 when printing watch signals.
- `market_reader.py` uses it to filter to APRIL12 when printing market state.

---

## 2. JHL Live Shell (local website)

### 2.1 Purpose

The live shell is a **static local website** that sits on top of the same `signals.json` feed and gives you three coordinated views in the browser:

1. **Scanner overview** — a panel that shows APRIL12 rows with structure, zone, BOS, eq_pct, alignment, and veto.
2. **Signal reader** — a WATCH-only panel that mirrors the terminal reader, per bot, with bias, conviction, tempo, KNN, and geometry.
3. **Market state** — a panel that reads structure, tempo mix, liquidation context, and trap risk into natural-language sentences per pair.

It does not replace your terminals. It’s a visual shell that uses the same truth and makes it easier to see how everything synchronizes.

### 2.2 How it gets data

The shell is a single HTML file that expects to live in the same folder as `signals.json`. In the browser, it fetches that file over HTTP:

- URL used: `./signals.json`
- Method: `fetch` with `cache: "no-store"`
- Refresh behavior: auto every few seconds, plus a manual refresh button

Because modern browsers restrict `fetch` from `file://` URLs, you run it behind a tiny local HTTP server, for example:

```bash
python -m http.server 8000
```

Then you hit `http://localhost:8000/jhl-live-shell.html` and the page starts reading and re-reading `signals.json` as scanner writes it.

### 2.3 What it renders

The shell computes an APRIL-style top 12 roster in-browser and uses that same selection across all panels.

#### Status strip

At the top it shows a status grid:

- Feed timestamp (`ts`)
- Cycle number
- Total rows in `signals.json`
- Count of rows with at least one WATCH signal
- APRIL12 roster size (usually 12)

#### Panel 1 — Scanner overview

For each roster row it shows:

- Pair name
- APRIL score
- Alignment tag (ALL 4 / 3 of 4 / 2 of 4 / SPLIT / SOLO / ----)
- Structure state, zone, BOS, eq_pct
- Veto information when RTS is vetoing direction

This is the browser version of “wall of truth” from scanner, narrowed to the current roster.

#### Panel 2 — Signal reader

This panel only cares about WATCH signals.

For each pair with at least one watch signal it shows:

- Header with pair and alignment tag
- A sub-card per active bot (VOL, RNG, RTS, TRD):
  - Bias (LONG/SHORT)
  - Conviction value
  - Tempo string
  - KNN sample/adjn (either `samples/30` or an adjusted value)
  - Geometry line when entry/sl/tp are defined

It behaves like the terminal reader, but lets you see all bots for a pair at once in a more relaxed layout.

#### Panel 3 — Market state

This panel reads structure and liquidation context into narrative text.

For each roster row it shows:

- Pair name
- Structure state (TRENDING_UP_DISCOUNT, RANGING_NEUTRAL, etc.)
- Zone and eq_pct
- Trap risk and liquidation setup type
- A sentence such as:

> TRENDING_UP_DISCOUNT with discount pricing; tempo mix VOL:LIVE · RNG:EARLY, liquidation context sweep, trap risk 0.35.

If structure is unclear, it calls that out explicitly, including the `why` reason when the structure module provides it.

### 2.4 Controls and behavior

The shell includes a few simple controls at the top:

- **Theme toggle** — switches the page between light and dark while keeping the same layout.
- **Refresh now** — forces an immediate fetch of `signals.json`.
- **Auto ON/OFF** — turns the periodic refresh loop on or off.

Auto-refresh is on by default, so as you leave scanner running the shell quietly chases the feed.

### 2.5 How it fits with APRIL12

The in-browser roster logic and the APRIL12 selector module are intentionally similar:

- The APRIL12 module does scoring on the Python side and can be used by scanner, reader, and market_reader scripts.
- The shell mirrors that logic in JavaScript so that even if you don’t run the Python APRIL module, the browser can still produce a sensible top 12.

If you prefer a single source of scoring truth, a natural next step is to have scanner write a `april_roster.json` file (already scored and ordered) and let the shell read that instead of recomputing scores in JS.

---

## 3. Running everything together

With APRIL12 and the shell in place, the full picture looks like this:

1. **Scanner** keeps writing `signals.json` for the full universe.
2. **APRIL12 module** scores and ranks those rows, giving you a top 12 roster.
3. **Terminal reader** filters to the APRIL12 roster and prints watch signals.
4. **Terminal market reader** filters to the APRIL12 roster and prints battlefield state.
5. **JHL Live Shell** sits in the same folder, reading `signals.json` and presenting the same roster and state in a browser.

The important part: every surface you look at is backed by the **same feed**. If something feels off, you debug `signals.json` and APRIL12 logic once, and all panels benefit.

---

## 4. Reset checklist

If you ever need to rebuild this wiring from scratch:

1. Make sure `scanner.py` is writing `signals.json` with `ts`, `cycle`, and a `signals` list.
2. Add `april_roster.py` with the public API described above.
3. Update `read.py` and `market_reader.py` to import APRIL12 and filter to the top 12.
4. Put `jhl-live-shell.html` in the same folder as `signals.json`.
5. Run a local HTTP server (`python -m http.server 8000`) and open the shell.

Once those five are in place, you have APRIL12 selection and a local website shell on top of your existing engines.
