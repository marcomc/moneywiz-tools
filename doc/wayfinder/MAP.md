# Wayfinder: MoneyWiz Tools Architecture

## Destination

Define an implementable architecture where MoneyWiz Tools is the sole
distributed product, a separately maintained read API fork can absorb and
contribute upstream improvements, and the Core Data writer is the sole
supported path for live MoneyWiz database writes.

## Notes

- This local Markdown directory is the issue tracker for this map.
- Use the vocabulary in [CONTEXT.md](../../CONTEXT.md).
- Each ticket resolves one decision or investigation. Do not perform the
  migration while charting the map.
- The product CLI is `moneywiz`; MCP support and a public PyPI distribution
  are out of scope.
- No subagent orchestration is available in this runtime. Research tickets are
  therefore resolved explicitly in later sessions.

## Decisions so far

- [MoneyWiz Tools is the sole distributed product](#moneywiz-tools-is-the-sole-distributed-product) — CLI now and a future GUI belong to one product boundary.
- [The Core Data writer owns live persistence](#the-core-data-writer-owns-live-persistence) — Python can plan and validate a write but cannot persist it through raw SQL.
- [The read API is a separate compatibility fork](#the-read-api-is-a-separate-compatibility-fork) — `marcomc/moneywiz-api` remains a technical repository, not a second product.
- [Read patches must be upstreamable](#read-patches-must-be-upstreamable) — fork changes cannot depend on MoneyWiz Tools behavior.
- [The product consumes a pinned Git dependency](#the-product-consumes-a-pinned-git-dependency) — no local checkout is required, consumed, or bundled.
- [The product CLI is `moneywiz`](#the-product-cli-is-moneywiz) — `moneywiz-cli` is not part of the supported user interface.
- [Upstream updates are explicit and verified](#upstream-updates-are-explicit-and-verified) — each intake is reviewed before the product pin changes.
- [Define the schema-profile support policy](tickets/schema-profile-support-policy.md) — recognized profiles are readable; live persistence requires a verified write capability.
- [Define evidence for a verified write profile](tickets/verified-write-profile-evidence.md) — capability evidence combines automated profile tests with a controlled MoneyWiz acceptance run.
- [Define the compatibility register and retention policy](tickets/compatibility-register-retention-policy.md) — every release supports its declared entries; removal requires explicit deprecation.

## Frontier

| Ticket | Type | Status | Blocks |
| --- | --- | --- | --- |
| [Compare upstream `v1.0.8` with the compatibility fork](tickets/upstream-v1.0.8-intake.md) | Research | Open | Fork baseline and migration |
| [Choose the pinned dependency and bundle mechanism](tickets/pinned-dependency-bundle-mechanism.md) | Research | Open | Reproducible build migration |
| [Define the Python-to-Core-Data writer contract](tickets/python-coredata-writer-contract.md) | Grilling | Open | Writer migration and future GUI boundary |

## Not yet specified

- The exact migration sequence for extracting the existing raw-SQL write code
  once the upstream baseline and writer contract are known.
- The future GUI interaction model; this map only reserves its product and
  writer boundaries.

## Out of scope

- MCP integration: explicitly not required for the destination.
- A public PyPI distribution for the read API.
- Raw SQL as a supported writer for a live MoneyWiz database.

## MoneyWiz Tools is the sole distributed product

MoneyWiz Tools owns the user experience, installation bundle, CLI, and future
GUI. The read API fork and Core Data writer are implementation components, not
separate end-user applications.

## The Core Data writer owns live persistence

Only the Core Data writer persists changes to a live MoneyWiz database. Python
creates and validates write intent but does not offer raw-SQL persistence as a
live operation.

## The read API is a separate compatibility fork

`marcomc/moneywiz-api` remains a separate technical fork of
`ileodo/moneywiz-api`, allowing the product to use a versioned dependency and
to exchange changes with upstream without presenting a second product.

## Read patches must be upstreamable

Read API changes address general library or MoneyWiz-schema behavior. A change
that depends on MoneyWiz Tools belongs in the product repository instead.

## The product consumes a pinned Git dependency

MoneyWiz Tools acquires the read API from an immutable Git reference recorded
in the lockfile. The installed app bundle remains self-contained. An optional
ignored local checkout may exist for separate development, but the product does
not require, consume, or bundle it.

## The product CLI is `moneywiz`

The supported command-line interface is `moneywiz`. Direct Python module
invocation and `moneywiz-cli` are not the user-facing integration contract.

## Upstream updates are explicit and verified

Upstream releases are compared, tested, and accepted deliberately. A product
release changes its pinned API revision only after that intake succeeds.
