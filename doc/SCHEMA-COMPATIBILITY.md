# Schema Compatibility

MoneyWiz SQLite stores are Core Data stores, not a single stable public SQL
schema. The same logical property can use different physical columns across
model generations.

## Supported read profiles

The API detects capabilities from `PRAGMA table_info(ZSYNCOBJECT)`:

| Profile | Shares column | Price column | Evidence |
| --- | --- | --- | --- |
| `suffixed-investment-columns-fixture` | `ZNUMBEROFSHARES1` | `ZPRICEPERSHARE1` | Existing test fixture |
| `moneywiz-2026-model-48` | `ZNUMBEROFSHARES` | `ZPRICEPERSHARE` | MoneyWiz 2026 live store, model 48 |

The profile is a structural capability label. It is not a substitute for the
MoneyWiz application version, managed-object model, or Core Data metadata
fingerprint.

## Compatibility policy

- Read paths use explicit aliases for known physical-column variants.
- Read paths normalize known zero-valued transfer FX fields from the populated
  counterparty amount when the current profile stores that value on the other
  side of the transfer.
- The inverse case is also normalized when the transfer amount is populated but
  the counterparty amount is stored as zero.
- Transfer currency metadata may be `NULL` in the live profile; the read model
  preserves that absence as an empty value and continues validating numeric
  transfer consistency.
- Optional columns are omitted from filtered output instead of raising
  `KeyError`.
- Optional relationship tables, such as tag and refund joins, produce an empty
  relationship map when absent from a store profile.
- Unknown profiles must be reported before a feature relies on an unsupported
  field.
- Best-effort read loading skips an individual record that violates model
  invariants and records the entity, ID, and parse error; it does not abort
  unrelated commands for the whole store.
- Live writes remain stricter than reads and require a separately verified
  `profile x capability` entry in `scripts/compatibility_matrix.json`.
- An unknown profile is diagnostic-only. A known profile is not enough to
  authorize a write: the requested capability must be `verified`.
- Keep fixtures for each supported profile and run the same read tests against
  every fixture.

## Version evidence

Record these values for each compatibility profile:

1. MoneyWiz app version and build.
2. Selected `.mom` model version.
3. `Z_METADATA.Z_PLIST` fingerprint.
4. `Z_PRIMARYKEY` entity mapping.
5. Relevant table columns and relationship names.

`Z_METADATA.Z_VERSION` is Core Data metadata and must not be treated as the
MoneyWiz model version by itself. See [Live Payee Structure](LIVE-PAYEE-STRUCTURE.md)
and [Live Write Compatibility](LIVE-WRITE-COMPATIBILITY.md).
