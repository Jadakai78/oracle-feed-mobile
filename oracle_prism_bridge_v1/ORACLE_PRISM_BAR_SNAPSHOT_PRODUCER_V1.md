# Oracle PRISM Bar Snapshot Producer v1

## What this is
A standalone, finite, run-once bridge script. It fetches Kraken's **public**
15-minute OHLC data for a canonical pair universe and writes an explicit
`ORACLE_PRISM_BAR_SNAPSHOT` JSON file.

It is the **only network-facing component** in this chain. Every other
module in this project family (the PRISM clean room, the Oracle Prop
Context Builder) is offline/deterministic and touches no network.

## What this is NOT
- Not part of `prism_cleanroom_v1`. It is a separate, standalone project
  with zero import coupling in either direction: it does not import PRISM
  clean-room code, and PRISM clean-room code does not import it.
- Not a scanner loop. It runs once and exits — there is no `while True`,
  no scheduler, no polling interval.
- Does no publishing, no GitHub/Pages/Cloudflare/Railway interaction, no
  feed writing, no alerting, no broker/exchange-account action, no order
  routing, and no execution of any kind.
- Does not modify the existing Oracle scanner, adapter, or publisher.

## Network scope
The only network call this script makes is a public, unauthenticated GET
to Kraken's public OHLC endpoint (`https://api.kraken.com/0/public/OHLC`).
No API key, account, or authenticated endpoint is used anywhere.

## Kraken timestamp conversion (exact formula)
Kraken's OHLC `time` field (`row[0]`) is the **interval-start** epoch
second, not the close. This bridge converts every retained bar's timestamp
to the PRISM-required bar-**close** time using exactly:

```
datetime.fromtimestamp(row[0] + 900, timezone.utc)
```

formatted as ISO-8601 UTC with a trailing `Z`. This is the same convention
already used elsewhere in this codebase's Delta/Tempo pipeline (bar end =
bar start + 15 minutes) and is applied consistently here.

## Field mapping
`row[1] -> open`, `row[2] -> high`, `row[3] -> low`, `row[4] -> close`,
`row[6] -> volume`. `row[5]` (vwap) and `row[7]` (trade count) are not
carried into the snapshot.

## Alias handling
Only two verified Kraken symbol aliases are applied: `BTC -> XBT` and
`DOGE -> XDG`. No other pair is guessed or aliased — every other pair is
passed through as plain `BASE+QUOTE` concatenation. If a pair's plain
concatenation does not resolve on Kraken (for example, a since-renamed or
delisted symbol), that pair's fetch will fail and — per the failure
convention below — it resolves to an empty-bars record rather than a
guessed symbol.

## The empty-bars failure convention (and its inherent ambiguity)
Any of the following causes a pair's output to be exactly
`{"pair": "<pair>", "bars": []}`, and nothing else:
- the network/API call itself fails or times out;
- Kraken returns a malformed or error response for that pair;
- fewer than 390 valid completed bars are available;
- any bar fails OHLCV shape validation (non-finite, zero, or negative
  value; `low > min(open, close)`; `high < max(open, close)`; `high < low`);
- the retained bar sequence is not strictly ascending in exactly
  15-minute steps.

This bridge **never retries, interpolates, pads, merges, or fabricates**
bars to compensate for a short or broken series.

**Important limitation:** from the snapshot alone, a downstream consumer
cannot distinguish "this pair genuinely has less than 390 bars of real
trading history" from "the fetch/parse failed for an unrelated reason" —
both produce the identical `bars: []` shape. This is a deliberate,
disclosed trade-off: the alternative (adding a reason/status field) would
require changing the already-frozen `ORACLE_PRISM_BAR_SNAPSHOT` input
contract that the PRISM Oracle Context Builder already consumes, which is
out of scope for this bridge.

## Snapshot contract
Top-level keys are exactly: `recordtype`, `schema_version`,
`generated_at_utc`, `timeframe`, `pairs`.
Pair-entry keys are exactly: `pair`, `bars`.
Bar keys are exactly: `timestamp`, `open`, `high`, `low`, `close`, `volume`.
No status, reason, source, action, score, direction, tier, watchlist, or
execution field is ever present. This module intentionally does not import
or duplicate PRISM's forbidden-key list; its tests verify the exact key
sets directly instead.

## CLI
```
python oracle_prism_bar_snapshot_producer_v1.py --output <path> [--pairs PAIR [PAIR ...]]
```
- `--output` is required; there is no default output path.
- `--pairs` is optional and must be already-canonical `BASE/QUOTE` strings
  (no normalization or repair is performed — a malformed entry fails the
  whole run before any network call). Defaults to the fixed 49-pair Oracle
  universe (duplicated locally in this module, not imported from the
  Oracle scanner).
- Exit 0 only after one valid snapshot is atomically written.
- Exit nonzero **only** for whole-run/config/output failures (bad
  `--pairs`, cannot write `--output`). An individual pair's fetch failure
  never causes a nonzero exit — it always resolves to that pair's
  empty-bars record while the run still succeeds.

## What consumes this output
The next and only consumer is the already-approved, offline
`prism_oracle_context_builder_v1.py` (inside `prism_cleanroom_v1/`), which
reads an `ORACLE_PRISM_BAR_SNAPSHOT` file and produces a
`PRISMORACLECONTEXT` artifact. **No feed integration exists yet** — this
bridge does not write to, or get read by, the Oracle Prop Feed
scanner/adapter/publisher chain in any way.
