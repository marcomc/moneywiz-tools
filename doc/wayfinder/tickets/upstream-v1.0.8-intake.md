# Compare Upstream v1.0.8 with the Compatibility Fork

**Type:** Research

**Status:** Open

**Blocks:** Future read-API pin updates

## Current boundary

The product already consumes an immutable compatibility-fork revision and the
live reassignment path already uses the bundled Core Data host. This ticket
does not gate either implemented decision.

## Question

For a future dependency intake, what changed between the compatibility fork's
base and `ileodo/moneywiz-api` `v1.0.8`, which changes can be adopted without
altering the read API contract, and which fork changes are independently
upstreamable?
