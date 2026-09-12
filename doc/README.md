# Documentation Index

Use the documents below by task rather than reading the design history first.
The README and command reference are the quickest path to a working CLI;
design documents explain implementation constraints after the task is clear.

## Operator guides

| Task | Document |
| --- | --- |
| Install, relocate, update, or remove the app bundle | [Bundle Installation](BUNDLE-INSTALLATION.md) |
| Configure the store and run everyday commands | [Project README](../README.md) |
| Run and revalidate a live payee reassignment | [Live Write Compatibility](LIVE-WRITE-COMPATIBILITY.md) |
| Find commands and their intended scope | [Functions Reference](../FUNCTIONS.md) |

## Live writer and schema evidence

| Topic | Document |
| --- | --- |
| Core Data host, identity, and live-write protocol | [Core Data Writer](CORE-DATA-WRITER.md) |
| Exact duplicate consolidation and fuzzy-map review | [Payee Consolidation](PAYEE-CONSOLIDATION.md) |
| Verified MoneyWiz 2026 payee and transaction mapping | [Live Payee Structure](LIVE-PAYEE-STRUCTURE.md) |
| Logical object relationships | [Entity Relationship Diagram](ER-DIAGRAM.md) |
| Core Data sync-object lifecycle | [Sync Object Model](SYNCOBJECT.md) |
| Broader field mappings and test-store recipes | [Field Mappings](FIELD-MAPPINGS.md) |
| Generated test-store schema snapshot | [Database Schema](DB-SCHEMA.md) |
| Profile x capability compatibility policy | [Schema Compatibility](SCHEMA-COMPATIBILITY.md) |

`DB-SCHEMA.md` is generated from a test-store snapshot. Do not use its entity
numbers as a live-store contract and do not hand-edit generated sections.

## Design and maintenance

| Topic | Document |
| --- | --- |
| Domain concepts and terminology | [Concepts](CONCEPTS.md) |
| Functional scope | [Functional Specification](FSD.md) |
| Runtime and non-functional requirements | [Software Requirements Specification](SRS.md) |
| Technical design and validation strategy | [Technical Design Document](TDD.md) |
| Extension boundaries and roadmap | [Extensions](EXTENSIONS.md) |
| P0–P3 delivery, phase preparation and acceptance | [Transaction Write Implementation Plan](proposals/TRANSACTION-WRITE-IMPLEMENTATION-PLAN.md) |
| Proposed transaction contracts and technical evidence | [Transaction Write API Proposal](proposals/TRANSACTION-WRITE-API.md) |
| Build-time repository relationship | [Repository Integration](REPO-INTEGRATION.md) |
| Product/API/writer architecture decisions | [Wayfinder Map](wayfinder/MAP.md) |

## Developer documentation workflow

| Developer task | Start here | Success check |
| --- | --- | --- |
| Change a command or option | [Functions Reference](../FUNCTIONS.md), then [Technical Design](TDD.md) | `moneywiz --help` and command-specific help match the docs |
| Change installation or bundle contents | [Bundle Installation](BUNDLE-INSTALLATION.md), then [Repository Integration](REPO-INTEGRATION.md) | `make check-deps`, bundle tests, and installed `moneywiz --version` pass |
| Change live-write behavior | [Live Write Compatibility](LIVE-WRITE-COMPATIBILITY.md), then [Core Data Writer](CORE-DATA-WRITER.md) | Compatibility and writer tests pass; live evidence is recorded separately |
| Prepare a release | [CHANGELOG](../CHANGELOG.md), [Technical Design](TDD.md), and [Functional Specification](FSD.md) | Version metadata, help output, docs, tests, and `git diff --check` agree |

Documentation maintenance follows four checks: technical accuracy against the
implementation, task completeness from setup through success verification,
skimmable structure with one clear reader goal per section, and release
alignment. Examples should be copied from executable help or exercised in the
CLI regression suite; do not document retired entry points as alternatives.
