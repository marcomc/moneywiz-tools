# MoneyWiz Tools Context

MoneyWiz Tools is the user-facing product for inspecting and safely changing a
MoneyWiz database where the native application is insufficient. It separates
read access, write intent, and persistence ownership.

## Product Boundaries

**MoneyWiz Tools**:
The distributed product: its command-line interface today and any future
graphical interface. It is the only component presented to users as a product.
_Avoid_: MoneyWiz API, writer app

**Product CLI**:
The `moneywiz` command, which is the sole supported command-line interface for
MoneyWiz Tools users and automations.
_Avoid_: moneywiz-cli, Python module invocation

**Read API**:
A reusable Python library that discovers and represents MoneyWiz database data
without owning changes to the live database.
_Avoid_: MoneyWiz Tools, live writer

**Core Data writer**:
The product component that persists a validated write intent to the live
MoneyWiz database through the persistence contract the application expects.
_Avoid_: raw SQL writer, Python writer

**Live MoneyWiz database**:
The persistent store currently managed by MoneyWiz and its synchronization
system. Its integrity includes application-managed history and metadata.
_Avoid_: fixture database, copied database

**Write intent**:
A validated business-level request to change MoneyWiz data, independent of how
the change is persisted.
_Avoid_: SQL statement, database mutation

**Schema profile**:
A named description of a MoneyWiz database schema variant used to interpret
its stored data correctly.
_Avoid_: database version

**Verified write capability**:
Authorization for one Core Data writer operation on one recognized schema
profile after it passes the defined persistence and application evidence.
_Avoid_: verified write profile

**Compatibility register**:
The versioned declaration of the schema profiles and read or write capabilities
that a MoneyWiz Tools release supports.
_Avoid_: MoneyWiz app version list

## Source Relationships

**Upstream API**:
The original `ileodo/moneywiz-api` project from which the read API derives.
_Avoid_: product dependency contract

**Compatibility fork**:
The `marcomc/moneywiz-api` repository that carries selected read-compatible
changes and supports synchronization with the upstream API.
_Avoid_: separate end-user product

**Upstreamable read patch**:
A read API change that addresses a general MoneyWiz schema or library concern
without depending on MoneyWiz Tools product behavior.
_Avoid_: product-specific fork patch
