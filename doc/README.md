# Documentation Index

Use the documents below by task rather than reading the design history first.

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
| Supported physical-schema profiles | [Schema Compatibility](SCHEMA-COMPATIBILITY.md) |

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
| Build-time repository relationship | [Repository Integration](REPO-INTEGRATION.md) |
| Product/API/writer architecture decisions | [Wayfinder Map](wayfinder/MAP.md) |
