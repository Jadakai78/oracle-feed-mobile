# Assumptions

Only assumptions actually required to resolve ambiguity in the specification
are listed. Where the specification was ambiguous, the fail-closed,
descriptive-only interpretation was preserved.

## Floating-point tolerance

A single tolerance constant, `TOLERANCE = 1e-9` (`prism_common_v1.TOLERANCE`),
is used everywhere a strict equality/closeness check is required:
`math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)`. This governs:
- middle-slope UP/DOWN/FLAT comparisons in `prism_terrain_v1.py`,
- width-slope UP/DOWN/FLAT comparisons and the percentile "equal" bucket in
  `prism_width_v1.py`,
- the terrain-bandwidth vs. current-width agreement check in
  `prism_width_v1.py` (a mismatch beyond this tolerance fails closed with
  `PRISM.RUNTIME.TERRAIN_WIDTH_MISMATCH`).

## Bar-close timestamp semantics

`timestamp` on a canonical bar is assumed to be the bar's **close**
timestamp, consistent with the worked example in the specification
(`"2026-01-01T00:00:00Z"` paired with `last_completed_candle_utc` of the same
value for the last bar in the series). Consequently, in
`prism_outcome_resolver_v1.py`, the first valid future bar must have a
`timestamp` exactly one 15-minute interval **after**
`observation["reference_bar_close_utc"]`. This intentionally mirrors a real
naming pitfall discovered in prior (non-clean-room) PRISM work, where a field
named "close" actually held an interval-start value — this clean-room build
treats the field name as authoritative and does not reintroduce that
ambiguity; if the underlying live-adapter feeding this clean-room pipeline
ever labels bars by interval-start instead, that adapter must convert to a
true close timestamp before calling any function in this project.

## Ordering

All bar lists (`bars`, `future_bars`) are assumed and required to be ordered
oldest-to-newest. `validate_bars_series()` enforces this implicitly by
requiring each consecutive pair of bars to be exactly 15 minutes apart in
list order; a reversed or shuffled series will fail closed as
`PRISM.DATA.MISSING_BARS` (non-monotonic gaps) rather than being silently
re-sorted. Inputs are never mutated or re-ordered by any module.

## Why 390 bars yields 25 prior windows plus one current window

A 365-bar rolling window requires 365 bars. Each additional bar beyond 365
allows exactly one more complete rolling window ending one bar earlier. At
390 bars (365 + 25), there are exactly 25 complete prior windows (ending at
bar indices 364 through 388) plus the current window (ending at bar index
389) — 26 total windows, 25 of which are "prior." Bar counts beyond 390 are
capped to the most recent 25 prior windows (`MAX_PRIOR_WINDOWS = 25` in
`prism_width_v1.py`) so `prior_width_count` never exceeds 25, matching the
width-regime classifier's strict requirement of exactly 25.

## Why observation-ledger timestamp gaps are informational but in-calculation bar gaps are invalid

A single terrain/width calculation requires an unbroken, contiguous 15-minute
bar series — any gap inside that series would silently corrupt the rolling
mean/stddev math, so `validate_bars_series()` fails closed
(`PRISM.DATA.MISSING_BARS`) on any internal gap. The **ledger**, by contrast,
is filled by discrete, independent observation calls (potentially manual,
potentially scheduled) — each call independently validates its own
contiguous bar window before ever reaching the ledger. A gap *between two
ledger rows* simply means no observation call happened during that interval;
it says nothing about the validity of either individual observation. The
validator therefore reports inter-row gaps as informational notes, never as
failures, matching the specification's explicit instruction in section 11.

## Canonical pair format

`build_prism_observation` requires `pair` to be a non-empty string containing
exactly one `/` with non-empty text on both sides (e.g. `SOL/USD`), matching
every example in the specification. Strings without a `/` (e.g. `SOLUSD`) or
with empty segments (e.g. `/USD`) are treated as invalid and return `None`.

## Fixture file shape

Each fixture JSON file wraps the canonical bar list in a small object:
`{"pair": "...", "timeframe": "15m", "bars": [...]}`. The specification does
not prescribe an exact fixture-file schema beyond "deterministic synthetic
fixtures," so this wrapper was chosen to keep `pair`/`timeframe` alongside
the bars for direct use by `build_prism_observation` in tests.

## Pair normalization

`build_prism_observation` strips leading/trailing whitespace from each side
of the pair's single `/` separator before validating and using it (e.g.
`"  SOL / USD  "` -> `"SOL/USD"`). A component that is empty after stripping
(e.g. `" /USD"`) is treated as whitespace-only and rejected as invalid,
returning `None`. This normalization is applied consistently to the output
`pair` field and the deterministic `observation_id`, so two callers passing
differently-whitespaced but semantically identical pair strings for the same
bars produce byte-identical observation records.

## Validator state-load strictness vs. ledger state-load leniency

`prism_ledger_v1.load_state()` is intentionally forgiving — a missing or
corrupt state file safely normalizes to the empty state, because the ledger
module's job is to keep accepting valid appends even after partial failures
(see "Ledger recovery-safe idempotency" below). `prism_ledger_validator_v1.py`
has the opposite job: it is an audit tool, so a missing or corrupt state file
is treated as an explicit validation failure (`_load_state_strict`) rather
than silently treated as "zero observations recorded." A validator that
silently normalized a corrupt/missing state file to empty could mask real
data loss.

## Ledger recovery-safe idempotency

`append_observation`/`append_closed_outcome` append the JSONL row before
performing the atomic state replace. If the process crashes or the state
write fails between those two steps, a retried call with the same record
must not produce a second JSONL row. Duplicate detection therefore checks
both `state.observation_ids`/`state.outcome_ids` **and** a direct read-only
scan of the target JSONL file for the `observation_id`
(`_id_exists_in_jsonl`). This intentionally does not attempt to "heal" the
state file by backfilling the missing ID — it only guarantees no duplicate
row is written; reconciling state with the JSONL file after a partial
failure is an operational/validator concern (surfaced by
`prism_ledger_validator_v1.py`'s explicit set-mismatch failure), not
something the append functions silently repair.

## Width mismatch reason code

The specification names four terrain-facing reason codes explicitly but does
not name one for the width/terrain bandwidth-mismatch case in section 6. A
fifth, analogously-named code, `PRISM.RUNTIME.TERRAIN_WIDTH_MISMATCH`, was
added for this one case; it is documented here and in `prism_common_v1.py`.
