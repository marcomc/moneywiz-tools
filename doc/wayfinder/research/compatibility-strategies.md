# Compatibility Strategies for an Externally Owned MoneyWiz Store

## Question

How should one MoneyWiz Tools release support multiple MoneyWiz database
schemas and writer operations without bundling multiple versions of the same
Python library?

## Findings

### The store owner migrates its schema; MoneyWiz Tools does not

Core Data applications that own their stores can bundle multiple model versions
and mappings, then migrate an old store to their current model. Apple describes
that process as requiring source and destination models, and sometimes an
explicit mapping model. [Core Data Model Versioning and Data Migration](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/CoreDataVersioning/Articles/Introduction.html)

That is not the MoneyWiz Tools situation. MoneyWiz owns the model and its iCloud
history. Apple notes that iCloud-backed Core Data migration has additional
constraints and model-version-dependent synchronization behavior. [Migration and iCloud](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/CoreDataVersioning/vmCloud/vmCloud.html)

MoneyWiz Tools must therefore adapt to the store it finds. It must never attempt
to migrate the MoneyWiz schema or infer that a database is writable merely
because it can be opened.

### Version numbers are evidence, not the compatibility key

SQLite provides `user_version` for applications to use, but SQLite itself does
not interpret it. `application_id` similarly identifies an application file
format, not a compatibility contract. [SQLite PRAGMA documentation](https://www.sqlite.org/pragma.html#pragma_user_version)

The compatibility selector must consequently use a MoneyWiz-specific schema
fingerprint: the required tables, columns, entity identifiers, and other
semantics needed by an operation. Record the observed MoneyWiz application and
model versions beside that fingerprint as evidence and diagnostics, but do not
gate behavior on the application version alone.

### Schema resolution belongs in adapters, not duplicate libraries

Schema-evolution systems distinguish the schema that wrote data from the schema
the reader expects and resolve explicit compatible differences. Apache Avro,
for example, resolves matching fields recursively, ignores writer-only fields,
and requires defaults for reader-only fields. [Apache Avro schema resolution](https://avro.apache.org/docs/1.12.0/specification/#schema-resolution)

The analogous MoneyWiz Tools design is one current read API with a profile
registry and narrowly scoped adapters. Each adapter maps a recognized physical
schema to the product's stable read model. It is not a second copy of
`moneywiz-api` in the app bundle.

### Compatibility is an explicit, version-controlled contract

Django keeps schema history in version control, uses historical model state for
old migrations, and retains required compatibility code until that history can
be retired. [Django migrations](https://docs.djangoproject.com/en/3.1/topics/migrations/)

MoneyWiz Tools should use the same discipline without applying migrations:

1. Ship a version-controlled compatibility register with each product release.
2. Declare read and write capabilities separately for every recognized profile.
3. Run the regression corpus for every declared supported profile before a
   release.
4. Deprecate a profile only through an explicit release-note and register
   change, not incidentally when new code is added.

## Recommended Design

### Bundle composition

Bundle one current revision of the read API plus all profile adapters and the
compatibility register. Do not bundle several historical API packages or choose
a package version at runtime.

This avoids divergent object models, duplicated dependency fixes, and the risk
that an old package path silently uses a pre-fix writer behavior. The selected
adapter is data-driven by the observed profile.

### Capability matrix

The register should be a version-controlled data file. Every entry names:

| Field | Purpose |
| --- | --- |
| Product release | The MoneyWiz Tools release declaring the contract. |
| Schema profile ID and fingerprint | The store structure selected at runtime. |
| MoneyWiz evidence | Observed application version, model version, and test date. |
| Capability | A read feature or one named writer operation. |
| State | Supported, blocked, experimental, deprecated, or removed. |
| Evidence | Fixture test and controlled application-run identifiers. |

A feature is independent of a profile until its adapter or writer contract
needs a profile-specific behavior. At runtime `moneywiz` asks the register
whether the requested capability is supported for the detected profile and
either dispatches to the adapter or refuses clearly.

### Verification lifecycle for a new MoneyWiz profile

1. Capture a sanitized schema fixture and fingerprint from a database created
   or migrated by the target MoneyWiz application.
2. Add read tests that prove the stable read model for that fixture.
3. Use an app-created disposable MoneyWiz database for a controlled write
   round trip for each writer operation: apply, inspect postconditions, reopen
   MoneyWiz, create a new transaction, synchronize, revert, and recheck.
4. Record the resulting evidence in the compatibility register and enable only
   the demonstrated `profile x operation` capability.
5. Run all declared profile fixtures for every subsequent MoneyWiz Tools
   release. A new product feature is enabled on an older profile when its
   adapter and capability test pass; otherwise it is explicitly blocked only
   for that profile.

## Recommended Support Policy

Do not promise support for a moving number of MoneyWiz application versions or
only the newest database. Instead, each release supports every profile and
capability present in its compatibility register. Start with all captured
profiles that remain inexpensive to test; remove one only through an explicit
deprecation decision.

This preserves useful new functions on an old database whenever the
`profile x operation` capability passes. It also makes the test cost visible:
every retained profile is part of the release regression corpus.

## Non-goals

- MoneyWiz Tools does not migrate a MoneyWiz database to a newer schema.
- MoneyWiz Tools does not promise that an older MoneyWiz application can open a
  store after a newer MoneyWiz application has migrated it.
- Recognizing a profile never authorizes an untested writer operation.
