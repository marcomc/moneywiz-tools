# Define the Python-to-Core-Data Writer Contract

**Type:** Grilling

**Status:** Open

**Blocks:** Future writer operations and the GUI boundary

## Implemented baseline

Reassignment uses `contract_version` 1. Python verifies the write capability,
adds the exact profile ID, model checksum, capability, schema version 1, and
reassignment operations to the JSON plan, then invokes the bundled host with
the store, managed-object model, and plan paths.

Before opening the store, the host independently requires that exact version,
profile, checksum, capability, schema, and a non-empty reassignment-only
operation list. It preflights all referenced objects before mutation, saves the
accepted plan through Core Data, and returns JSON counts for created payees,
reassigned transactions, merged payees, and migrated relationships. Python
treats a nonzero host status as an error and relays a successful JSON result.

## Question

How should the implemented reassignment-only version 1 exchange evolve before
another writer operation or a future GUI adds new preview, apply,
cancellation, or result semantics?
