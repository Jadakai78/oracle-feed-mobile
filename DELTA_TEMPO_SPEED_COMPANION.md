# Delta Tempo Speed Companion

## Purpose

Read-only Delta/Tempo price-speed episode watcher. The first aligned flow and price impulse opens a watch only. It never places orders, sends alerts, modifies queues, replaces Delta stops/targets, or grants entry authority.

## Lifecycle

`WATCH_INITIAL_IMPULSE` records the first meaningful aligned price response. A later valid confirmation can promote only to `CONFIRMED_PULLBACK_REACCELERATION`, `CONFIRMED_BREAKOUT_ACCEPTANCE`, or `CONFIRMED_RECLAIM_ACCELERATION`. Valid promotion is evaluated before generic velocity decay. `DROPPED` removes active visibility while retaining the state and reason. `INVALIDATED` records direction reversal or reference-level failure.

## Measurements

Flow speed and flow acceleration remain Delta/Tempo fields. Price velocity is two completed-close displacement divided by completed-bar ATR. Price velocity acceleration compares current velocity to the prior companion observation.

## Safety

Manual review only. Entry authority is always false. Existing Delta/Tempo stop, target, geometry, alerts, queues, and order behavior are unchanged.
