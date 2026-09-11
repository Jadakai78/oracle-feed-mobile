# PRISM Clean-Room v1

**Price-Regime Intelligence Structure Mainframe — research-only, non-authorizing.**

This project is a standalone, clean-room implementation. It does not import,
read, or depend on any existing scanner, evaluator, signal, alert, execution,
or live-adapter code. It uses only the Python standard library, deterministic
synthetic fixtures stored inside this directory, and `unittest`.

## Non-authorizing declaration

Every public output record in this project carries:

```json
{
  "manual_review_only": true,
  "does_not_authorize_trade": true,
  "does_not_simulate_order": true
}
```

PRISM **maps structure; it does not decide or execute**. No module in this
project ever emits `side`, `entry`, `stop`, `target`, `score`, `rank`,
`route`, `signal`, `execution_eligible`, `trade_authority`, `entry_authority`,
`order`, `position`, `alert`, `webhook`, or any disguised equivalent
(`buy`/`sell`/`long`/`short`/`recommended_action`/`confidence_score`/
`trade_setup`). `prism_common_v1.scan_forbidden_keys()` recursively checks
for these on every record produced by the observer and outcome resolver, and
the read-only validator re-checks this on every ledger row.

**Width expansion describes dispersion/volatility context only — it is never
a directional (bullish/bearish) statement.** A widening band means price is
moving through a larger range; it says nothing about which way price will go
next, and no module here claims otherwise.

## Component diagram

```
                     canonical 15m OHLCV bars
                                |
                +---------------+---------------+
                |                               |
        prism_terrain_v1.py             prism_width_v1.py
        build_terrain()                 build_width_observation()
        (mean/stddev/z/zone/            (rolling 365-bar dispersion,
         middle_slope)                   25-window history, slope,
                |                         percentile; cross-checks
                |                         terrain.bandwidth)
                |                               |
                +---------------+---------------+
                                |
                    prism_width_regime_v1.py
                    classify_width_regime()
                    (percentile + slope -> descriptive regime label)
                                |
                    prism_observer_v1.py
                    build_prism_observation()
                    (freezes terrain + width + regime into one
                     immutable, descriptive OPEN observation)
                                |
              +-----------------+------------------+
              |                                     |
  prism_outcome_resolver_v1.py              prism_ledger_v1.py
  resolve_prism_outcome()                   append_observation()
  (future-bars-only realized                append_closed_outcome()
   return/range/excursion samples           load_state()
   at 1/4/16/64-bar horizons;               (append-only, idempotent,
   produces a CLOSED outcome)                atomic-write JSONL ledger)
                                                     |
                                     prism_ledger_validator_v1.py
                                     validate_ledger() / CLI
                                     (read-only; never writes or
                                      repairs the ledger)
```

## Components

- **`prism_terrain_v1.py`** — `build_terrain(bars, timeframe="15m")`. Rolling
  365-close mean/population-stddev band, z-score, 7-zone displacement
  classification, and a middle-slope (UP/DOWN/FLAT/UNAVAILABLE) comparison
  against the immediately preceding 365-close window. Fails closed
  (`state="UNAVAILABLE"`) with a specific reason code on any malformed,
  insufficient, gapped, or zero-stddev input.
- **`prism_width_v1.py`** — `build_width_observation(bars, timeframe, terrain=None)`.
  Same `6 x population-stddev` width definition as terrain's bandwidth, plus
  up to 25 prior rolling-window widths (current window always excluded),
  a width slope vs. the immediately preceding window, and a midpoint
  empirical percentile once 25 prior windows exist. `PARTIAL` between 365
  and 389 bars, `AVAILABLE` at 390+ bars, fails closed otherwise. If a
  terrain payload is supplied, its `bandwidth` must agree with the freshly
  computed current width within a strict tolerance or the result fails
  closed.
- **`prism_width_regime_v1.py`** — `classify_width_regime(width_observation)`.
  Pure function mapping (percentile, slope) to one of `WIDTH_CONTRACTING`,
  `WIDTH_COMPRESSED`, `WIDTH_EXPANDING`, `WIDTH_ELEVATED`, `WIDTH_NEUTRAL`, or
  `WIDTH_UNAVAILABLE`. Never mutates its input.
- **`prism_observer_v1.py`** — `build_prism_observation(pair, bars, timeframe="15m")`.
  Pure, in-memory composition of the three components above into one frozen,
  deterministic, descriptive-only `status="OPEN"` record with a canonical
  `PAIR|TIMEFRAME|CLOSE_UTC|PRISM_WIDTH_REGIME_V1` observation ID. Returns
  `None` if any required component is unavailable. `pair` is normalized by
  stripping whitespace from both sides of the single `/` separator (e.g.
  `"  SOL / USD  "` becomes `"SOL/USD"`); whitespace-only components (e.g.
  `" /USD"`) are rejected as invalid. The normalized pair is used in both
  the output `pair` field and the deterministic `observation_id`.
- **`prism_outcome_resolver_v1.py`** — `resolve_prism_outcome(observation, future_bars)`.
  Pure function that measures realized close-return, range, and up/down
  excursion percentages at the 1/4/16/64-bar horizons using only future bars
  starting exactly one interval after the observation's reference timestamp.
  Requires 64 valid, contiguous future bars; returns `None` otherwise. Emits
  no direction, side, or win/loss label — only magnitude-based descriptive
  statistics. Produces a frozen `status="CLOSED"` outcome record that copies
  (not references) the observation's terrain/width snapshots. `reference_price`
  must be a finite, strictly positive number (`is_finite_number` +
  `> 0`); zero, negative, `NaN`, and infinite values all return `None`.
- **`prism_ledger_v1.py`** — `load_state`, `append_observation`,
  `append_closed_outcome`. Append-only, idempotent (`DUPLICATE` on replay),
  dry-run-capable (`DRY_RUN`, no file changes), fail-closed on invalid
  records (`INVALID_RECORD`), atomic state writes (temp file + `os.replace`).
  Every path is explicitly passed by the caller; there is no default
  production path and no background loop. **Recovery-safe idempotency**:
  duplicate detection checks both `state.observation_ids`/`state.outcome_ids`
  *and* a direct read-only scan of the target JSONL file for the
  `observation_id`. This means that if a process crashes or fails between
  the JSONL append and the atomic state replace (leaving a JSONL row with no
  matching state entry), a retry of the same append is still recognized as
  `DUPLICATE` and does not create a second row.
- **`prism_ledger_validator_v1.py`** — read-only CLI:
  `python prism_ledger_validator_v1.py OBSERVATIONS_JSONL STATE_JSON`.
  Validates JSON syntax, schema, canonical IDs, timestamp alignment and
  strict ordering, required terrain keys (`state`, `zone`, `middle_slope`,
  `bandwidth`) and width keys (`state`, `current_width`, `prior_width_count`,
  `width_slope`, `width_percentile`, `regime`), known-label enums for zone/
  middle-slope/width-slope/regime, finite-number checks (via
  `is_finite_number`) on `reference_price`, `terrain.bandwidth`, and
  `width.current_width`/`width_percentile`, safety flags, and recursively
  scans for forbidden keys anywhere in each record. Rejects the internal
  contradiction of an `OPEN` record with `width.state == "AVAILABLE"` but
  `regime == "WIDTH_UNAVAILABLE"`. Cross-checks the JSONL observation-ID set
  against `state.observation_ids` exactly, and checks that `state.outcome_ids`
  only references known observation IDs — using a **strict** state load
  (distinct from the ledger's own recovery-safe `load_state`): a missing or
  corrupt state file is itself an explicit validation failure here, not a
  silent normalization to empty. Reports skipped 15-minute intervals as
  informational notes, not failures. Exit code `0` for PASS, `1` for FAIL.
  Never writes or repairs any file.

## Running the tests

From the `prism_cleanroom_v1/` directory:

```
python -m unittest discover -v -s tests -p "test_*.py"
```

This runs all 100 tests across all seven modules with no network access and
no writes outside the explicit `tempfile.TemporaryDirectory()` paths used by
the ledger and validator test suites.

## Running the read-only validator with explicit paths

```
python prism_ledger_validator_v1.py path/to/prism_width_regime_observations_v1.jsonl path/to/prism_width_regime_state_v1.json
```

Both paths must be passed explicitly — the tool has no default/production
path and will not create, modify, or repair either file.

## Fixtures

`fixtures/` contains six deterministic synthetic bar series (see
`scripts_gen_fixtures.py` for exact generation logic):

- `prism_001_valid.json`, `prism_007_valid.json`, `prism_008_valid.json`,
  `prism_009_valid.json` — 390-bar valid series. Across this set,
  `WIDTH_ELEVATED`, `WIDTH_EXPANDING`, and `WIDTH_CONTRACTING` are all
  produced (verified in the observer test suite and reproducible by running
  the modules directly against these files).
- `prism_043_insufficient_history.json` — 364 valid bars (one short of the
  365-bar minimum).
- `prism_044_missing_bar.json` — 390 bars with one 15-minute timestamp gap.

These fixtures exist purely for deterministic functional test coverage. They
are synthetic sine-wave constructions with no relationship to real market
data and **carry no predictive or evidentiary value about any actual market**.

## Non-authorizing scope reminder

This project is a structural research tool. It is not ready for, and must
not be wired into, live trading, a live scanner, an alerting system, or any
production execution path.
